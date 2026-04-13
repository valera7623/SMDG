# DICOM Viewer — Документация

## Обзор

DICOM Viewer — подсистема SMDG для просмотра медицинских изображений DICOM прямо в браузере.
Расшифровка происходит **на сервере** (через pydicom + numpy), результат отдаётся как **PNG** —
браузер не парсит DICOM самостоятельно.

### Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                       БРАУЗЕР                                │
│                                                              │
│  index.html ──[👁️ Просмотр]──▶ dicom-viewer.html            │
│                      POST /api/dicom/view-url                │
│                      ← { view_url, token, study_uid, ... }   │
│                                                              │
│  dicom-viewer.html (Vanilla JS)                              │
│    ├── GET /api/dicom/metadata/{id}?token=... → JSON         │
│    ├── GET /api/dicom/render/{id}?token=...  → PNG           │
│    └── Инструменты: 🪟 Окно  🔍 Зум  ✋ Пан  ◐ Инверт  💾   │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│                  BACKEND (FastAPI)                            │
│                                                              │
│  POST /api/dicom/view-url          JWT auth → view_token     │
│  GET  /api/dicom/render/{id}       view_token → PNG (pydicom)│
│  GET  /api/dicom/wado/{id}         view_token → DICOM bytes  │
│  GET  /api/dicom/metadata/{id}     view_token → JSON теги    │
│                                                              │
│  QIDO-RS (DICOMweb Query):                                   │
│  GET  /api/dicom/qido/studies       → Study-level JSON       │
│  GET  /api/dicom/qido/studies/{uid}/series → Series JSON     │
│  GET  /api/dicom/qido/.../instances → Instance JSON          │
│                                                              │
│  WADO-RS (DICOMweb Retrieve):                                │
│  GET  /api/dicom/wado/studies/{s}/series/{se}/instances/{i}  │
│                                                              │
│  Redis Cache: smdg:dicom_meta:{file_id} (TTL 2.25h)          │
│  Аудит: dicom.view_initiated, dicom.metadata_accessed,       │
│         dicom.streamed, dicom.stream_failed                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Конфигурация

### Переменные окружения

| Переменная                     | По умолчанию | Описание                         |
|--------------------------------|--------------|----------------------------------|
| `DICOM_VIEWER_ENABLED`         | `false`      | Включить/выключить DICOM Viewer  |
| `DICOM_VIEW_TOKEN_TTL_SECONDS` | `900`        | Время жизни view-токена (сек)    |
| `DICOM_MAX_STREAM_SIZE_MB`     | `500`        | Макс. размер DICOM для streaming |

### Пример `.env`

```env
DICOM_VIEWER_ENABLED=true
DICOM_VIEW_TOKEN_TTL_SECONDS=900
DICOM_MAX_STREAM_SIZE_MB=500
```

### Health check

```bash
curl http://localhost:8000/health | jq .features.dicom_viewer
# → true (включён) или false (отключён)
```

При `DICOM_VIEWER_ENABLED=false` все DICOM-эндпоинты возвращают **HTTP 501**.

---

## 2. API Reference

### 2.1. POST /api/dicom/view-url

Генерирует view-токен и URL для DICOM Viewer.

**Auth:** JWT cookie (любая авторизованная роль)

**Параметры:**

| Param     | Type | Required | Описание      |
|-----------|------|----------|---------------|
| `file_id` | int  | Да       | ID файла в БД |

**Ответ 200:**

```json
{
  "view_url": "/dicom-viewer?v=123&token=uuid&file_id=7&StudyInstanceUID=...&SeriesInstanceUID=...&SOPInstanceUID=...",
  "token": "ab717c3c-077e-4740-b5fc-32001cde3833",
  "expires_at": "2026-04-12T02:15:00+00:00",
  "file_name": "chest_ct.dcm",
  "file_id": 7,
  "study_uid": "2.25.607865462823299765952766741860798",
  "series_uid": "2.25.2482503788353432257188259916283494"
}
```

**Ответы:**

| Код | Условие               |
|-----|-----------------------|
| 200 | Успех                 |
| 400 | Файл не DICOM         |
| 404 | Файл не найден        |
| 501 | DICOM Viewer отключён |

**Аудит:** `dicom.view_initiated`

---

### 2.2. GET /api/dicom/render/{file_id}

Рендерит DICOM в PNG через pydicom + numpy + PIL.

**Auth:** view_token (query param)

**Параметры:**

| Param     | Type    | Required | Описание           |
|-----------|---------|----------|--------------------|
| `file_id` | int     | Да       | ID файла           |
| `token`   | string  | Да       | View-токен         |
| `center`  | float   | Нет      | Window Center (WL) |
| `width`   | float   | Нет      | Window Width (WW)  |
| `frame`   | int     | Нет      | Номер кадра (0-indexed, по умолчанию 0) |

**Ответ 200:** PNG изображение (`image/png`)

**Заголовки ответа:**

| Header         | Описание              |
|----------------|-----------------------|
| `X-Cache: HIT` | PNG из Redis-кэша     |
| `X-Cache: MISS`| PNG отрендерен заново |

**Windowing:**

- Если указаны `center` и `width` — применяется DICOM WL/WW формула
- Если не указаны — автоматическая нормализация (min-max)
- Результат кэшируется в Redis (`smdg:dicom_png:{file_id}:{wc}:{ww}`, TTL 1 час)

**Процесс:**
1. Проверка Redis-кэша PNG (HIT → мгновенный ответ)
2. Расшифровка `.age` файла в память
3. `pydicom.dcmread()` → `ds.pixel_array` (numpy)
4. Multi-frame → выбор кадра по параметру `frame` (по умолчанию 0)
5. Windowing: заданный WL/WW или автоматический min-max
6. `PIL.Image.fromarray()` → PNG в память
7. Сохранение PNG в Redis (TTL 1 час, ключ включает frame number)
8. StreamingResponse (без записи на диск)

**Multi-frame обработка:**
- Если `pixel_array.ndim == 3`, извлекается кадр `pixel_array[frame]`
- Валидация: `frame` должен быть в диапазоне `0..total_frames-1`
- Ошибка 400 при выходе за пределы диапазона
- Redis ключ: `smdg:dicom_png:{file_id}:frame{frame}:{wc}:{ww}`

**Аудит:** `dicom.streamed` / `dicom.stream_failed`

**Примеры запросов:**

```bash
# Автоматическая нормализация (min-max), frame 0
curl -o auto.png "http://localhost:8000/api/dicom/render/7?token=TOKEN"

# Конкретный кадр multi-frame (frame 5)
curl -o frame5.png "http://localhost:8000/api/dicom/render/7?token=TOKEN&frame=5"

# Bone preset (WL=500, WW=2000), frame 10
curl -o bone.png "http://localhost:8000/api/dicom/render/7?token=TOKEN&frame=10&center=500&width=2000"

# Lung preset (WL=-500, WW=1500)
curl -o lung.png "http://localhost:8000/api/dicom/render/7?token=TOKEN&center=-500&width=1500"

# Brain preset (WL=40, WW=80)
curl -o brain.png "http://localhost:8000/api/dicom/render/7?token=TOKEN&center=40&width=80"
```

---

### 2.3. GET /api/dicom/metadata/{file_id}

Возвращает DICOM-теги в JSON. Использует Redis-кэш.

**Auth:** view_token (query param)

**Ответ 200:**

```json
{
  "StudyInstanceUID": "2.25.607865462823299765952766741860798",
  "SeriesInstanceUID": "2.25.2482503788353432257188259916283494",
  "SOPInstanceUID": "2.25.469066027164914000277527661653546",
  "TransferSyntaxUID": "1.2.840.10008.1.2.1",
  "PatientName": "Иванов^Иван^Иванович",
  "PatientID": "123456",
  "PatientSex": "M",
  "PatientBirthDate": "19700101",
  "PatientAge": "55Y",
  "StudyDate": "20260412",
  "StudyTime": "143022",
  "StudyDescription": "Chest CT with contrast",
  "StudyID": "CT001",
  "AccessionNumber": "ACC-2026-001",
  "ReferringPhysicianName": "Петров^Пётр",
  "Modality": "CT",
  "SeriesDescription": "Chest CT with contrast",
  "SeriesNumber": "3",
  "ProtocolName": "Chest_Abdomen",
  "Rows": "512",
  "Columns": "512",
  "BitsAllocated": "16",
  "BitsStored": "16",
  "HighBit": "15",
  "PixelRepresentation": "0",
  "SamplesPerPixel": "1",
  "PhotometricInterpretation": "MONOCHROME2",
  "NumberOfFrames": "126",
  "PixelSpacing": "0.7\\0.7",
  "SliceThickness": "1.5",
  "Manufacturer": "SIEMENS",
  "InstitutionName": "Больница №1",
  "StationName": "CT01",
  "SoftwareVersions": "syngo CT 2020A",
  "WindowCenter": "40",
  "WindowWidth": "400",
  "RescaleIntercept": "-1000",
  "RescaleSlope": "1"
}
```

**Кэширование:**

- Первый запрос: расшифровка DICOM → pydicom парсинг → сохранение в Redis (`smdg:dicom_meta:{file_id}`, TTL = 2.25 часа)
- Повторные запросы: мгновенно из Redis без расшифровки

---

### 2.4. QIDO-RS (DICOMweb Query)

Стандарт DICOMweb для поиска исследований/серий/экземпляров.

#### GET /api/dicom/qido/studies

Возвращает список исследований (в SMDG — один DICOM-файл = одно исследование).

**Параметры:**

| Param            | Type       | Описание                                    |
|------------------|------------|---------------------------------------------|
| `token`          | string     | View-токен                                  |
| `fuzzymatching`  | string     | Нечёткий поиск (заглушка)                   |
| `includefield`   | string     | `all` (по умолчанию) или список тегов       |
| `limit`          | int        | Макс. кол-во результатов (по умолчанию 100) |

**Ответ:** DICOM JSON массив Study объектов

#### GET /api/dicom/qido/studies/{studyUID}/series

Серии для конкретного исследования.

#### GET /api/dicom/qido/studies/{studyUID}/series/{seriesUID}/instances

Экземпляры (images) для конкретной серии.

Все QIDO-RS ответы используют **реальные DICOM UIDs** из файла (через pydicom).

---

### 2.5. WADO-RS (DICOMweb Retrieve)

Стандарт DICOMweb для получения DICOM-объектов.

#### GET /api/dicom/wado/studies/{studyUID}/series/{seriesUID}/instances/{instanceUID}

**Auth:** view_token (query param)

Возвращает DICOM-файл как `application/dicom` streaming.

**Legacy endpoint:**

#### GET /api/dicom/wado/{file_id}?token=...

Прямой доступ к DICOM-файлу по file_id (для обратной совместимости).

---

## 3. Frontend

### 3.1. Кнопка «Просмотр»

В списке файлов (`static/js/modules/files.js`):

- DICOM-файлы определяются по `mime_type === "application/dicom"` или расширению `.dcm`/`.dicom`
- Иконка меняется с 📄 на 🔬
- Кнопка «👁️ Просмотр» появляется **только если** `window.__DICOM_VIEWER_ENABLED__ === true`

### 3.2. DICOM Viewer UI

`static/html/dicom-viewer.html` — автономная страница без внешних зависимостей (~850 строк).

**Загрузка:**
1. `GET /api/dicom/metadata/{id}?token=...` → метаданные для sidebar (с автозагрузкой WL/WW, определение multi-frame)
2. `GET /api/dicom/render/{id}?token=...&center=...&width=...&frame=N` → PNG с WL/WW параметрами и выбором кадра

**Инструменты:**

| Кнопка | Действие |
|-------------------|-------------------------------------------------------------------|
| 🪟 Окно (WL/WW)    | Drag мышью: горизонталь = WW, вертикаль = WC. Курсор: `ew-resize` |
| 🔍 Зум           | Drag вверх/вниз или колёсико мыши. Курсор: `crosshair`             |
| ✋ Пан            | Drag для перемещения. Курсор: `grab` → `grabbing`                 |
| ▶️ Cine           | Multi-frame навигация: scroll переключает кадры (появляется только для CT/MRI) |
| 📐 Измерения      | Инструменты измерений: линейка, угол, ROI (открывает measurement toolbar) |
| ↺ Сброс          | Сброс масштаба, позиции, инверсии, остановка Cine, очистка измерений|
| ◐ Инверт         | Инверсия цветов (CSS `filter: invert(1)`)                          |
| 💾 Скачать       | Скачать оригинальный DICOM-файл (осмысленное имя файла)            |
| ℹ️               | Панель метаданных (7 групп, сокращённые UID)                       |
| ✕                | Закрыть viewer                                                     |

**Инструменты измерений (Measurement Tools):**

При нажатии **📐 Измерения** появляется toolbar с инструментами:

| Инструмент | Клики | Результат |
|------------|-------|-----------|
| 📏 **Линейка** | 2 точки | Расстояние (мм) |
| 📐 **Угол** | 3 точки (вершина посередине) | Угол (градусы) |
| ⬜ **ROI Rectangle** | 2 угла (диагональ) | Ширина, высота, площадь (мм²) |
| ⭕ **ROI Ellipse** | Центр + край | Rx, Ry, площадь (мм²) |

**Управление измерениями:**
- **↩️ Отменить** — удалить последнее измерение
- **🗑️ Очистить** — удалить все измерения
- **✕ Закрыть** — скрыть measurement toolbar

**Pixel Spacing:**
- Автоматически извлекается из DICOM тега `PixelSpacing` (0028,0030)
- Если тег отсутствует — используется 1 мм/пиксель
- Все измерения в миллиметрах (мм) и квадратных миллиметрах (мм²)

**Multi-frame (CT/MRI серии):**

При загрузке multi-frame DICOM (`NumberOfFrames > 1`) автоматически:
- Появляется кнопка **▶️ Cine** в toolbar
- Появляется **Frame Slider** внизу экрана
- Отображается индикатор `1 / 126` (текущий кадр / всего кадров)

**Навигация по кадрам:**
- **Frame Slider**: перетаскивание для выбора любого кадра
- **Кнопки**: ⏮ Первый | ◀ Предыдущий | ▶ Следующий | ⏭ Последний
- **Scroll мыши**: в режиме Cine переключает кадры (вперёд/назад)
- **Cine Loop**: кнопка ▶️ Play/⏸ Pause для автопроигрывания
- **Скорость**: слайдер 1-30 fps (по умолчанию 10 fps)

**Оптимизации Multi-frame:**
- **Клиентский кэш**: загруженные фреймы кэшируются в браузере (макс 50 кадров)
- **Предзагрузка**: автоматически предзагружаются ±3 соседних кадра
- **Deduplication**: одновременные запросы одного кадра объединяются
- **Redis кэш сервера**: каждый фрейм кэшируется отдельно (`smdg:dicom_png:{id}:frame{N}:{wc}:{ww}`)
**Пресеты Window/Level (для разных тканей):**

| Пресет     | WL    | WW    | Описание               |
|------------|-------|-------|------------------------|
| 🦴 Кость   | 500  | 2000   | Костная ткань         |
| 🫁 Легкие    | -500 | 1500  | Лёгочная ткань        |
| 🧠 Мозг    | 40   | 80     | Мягкие ткани мозга    |
| 🫀 Живот    | 50    | 350    | Абдоминальные органы |
| 🍖 Печень | 60    | 150    | Паренхима печени      |

**WL/WW логика:**

- При загрузке автоматически берутся `WindowCenter`/`WindowWidth` из DICOM-метаданных
- Drag мышью в режиме «Окно» изменяет WL/WW с debounce 80ms
- Колёсико мыши изменяет WW (±5) в режиме «Окно», или масштаб в остальных режимах
- Трансформации (zoom/pan) сохраняются при перезагрузке изображения
- Заголовок `X-Cache: HIT/MISS` показывает, отрендерен ли PNG заново или из кэша

**Группы метаданных (6 категорий):**

1. **Пациент** — PatientName, PatientID, PatientBirthDate, PatientSex
2. **Исследование** — StudyDate, StudyTime, StudyDescription, StudyInstanceUID, AccessionNumber, ReferringPhysicianName
3. **Серия** — Modality, SeriesDescription, SeriesNumber, SeriesInstanceUID, SeriesDate
4. **Изображение** — Rows, Columns, BitsAllocated, BitsStored, HighBit, PixelRepresentation, SamplesPerPixel, PhotometricInterpretation, NumberOfFrames, PixelSpacing, SliceThickness
5. **Сжатие** — TransferSyntaxName, TransferSyntaxUID
6. **Окно/Уровень** — WindowCenter, WindowWidth, RescaleIntercept, RescaleSlope
7. **Оборудование** — Manufacturer, ManufacturerModelName, InstitutionName, StationName, SoftwareVersions
8. **Анатомия** — AnatomicalOrientation, PatientPosition

Длинные UID автоматически сокращаются (35 символов + `…`) с показом полного значения при наведении.

**Cleanup:**

- При закрытии страницы очищаются Blob URLs
- Сообщение `dicom-close` отправляется родительскому окну через `postMessage`

---

## 4. Безопасность

### 4.1. Расшифрованные данные НЕ попадают на диск

```
encrypted/.age → _decrypt_dicom_to_memory() → bytes (в памяти)
                                              → pydicom → pixel_array
                                              → numpy windowing → PIL PNG
                                              → Redis кэш (smdg:dicom_png:...)
                                              → StreamingResponse
                                              → ВРЕМЕННЫЕ ФАЙЛЫ УДАЛЕНЫ в finally
```

Никакие расшифрованные данные **не записываются на диск** сервера.

### 4.2. View-токен

- UUID v4, привязан к `file_id`
- TTL настраивается (по умолчанию 15 минут)
- Multi-use (не одноразовый — нужен для загрузки PNG + metadata)
- Автоматическое удаление при истечении срока

### 4.3. Feature Flag

При `DICOM_VIEWER_ENABLED=false`:
- Все DICOM-эндпоинты → HTTP 501
- `/health` → `"dicom_viewer": false`
- Фронтенд скрывает кнопку «Просмотр»

### 4.4. Аудит

| Событие                   | Когда логируется           |
|---------------------------|----------------------------|
| `dicom.view_initiated`    | Генерация view-токена      |
| `dicom.metadata_accessed` | Запрос DICOM-тегов         |
| `dicom.streamed`          | Успешный рендер PNG        |
| `dicom.stream_failed`     | Ошибка расшифровки/рендера |

Логи: `audit_logs/dicom_YYYY-MM-DD.log`

### 4.5. Удаление файлов (S3-aware)

Эндпоинт `POST /api/delete-user-file` использует `encrypted_storage` API вместо прямой работы с файловой системой:

- Проверка существования: `encrypted_storage.exists(storage_key)` (работает и с S3, и с локальной ФС)
- Удаление: `encrypted_storage.delete(storage_key)`
- Связанные `DicomViewToken` удаляются автоматически (cascade `all, delete-orphan` на `File.view_tokens`)
- Аудит операции удаления сохраняется

---

## 5. Развёртывание

### 5.1. Зависимости

```toml
# pyproject.toml
pydicom = "^3.0.1"   # Парсинг DICOM
numpy   = "^2.0"     # Обработка пикселей
pillow  = "^11.0"    # Конвертация в PNG
```

### 5.2. Установка

```bash
# В Docker-контейнере
docker exec smdg-smdg-1 pip install --break-system-packages pydicom numpy pillow
docker restart smdg-smdg-1

# Или пересобрать образ (pyproject.toml уже обновлён)
docker compose build smdg
docker compose up -d smdg
```

### 5.3. Миграция БД

```bash
alembic upgrade head
# Создаёт таблицу dicom_view_tokens
# Добавляет relationship File.view_tokens (cascade delete)
```

### 5.4. Включение

```env
# .env.prod
DICOM_VIEWER_ENABLED=true
```

### 5.5. Проверка

```bash
# Health check
curl http://localhost:8000/health | jq .features.dicom_viewer
# → true

# QIDO-RS
curl "http://localhost:8000/api/dicom/qido/studies?token=<token>" | jq

# Metadata (из кэша)
curl "http://localhost:8000/api/dicom/metadata/7?token=<token>" | jq

# Render PNG (auto min-max)
curl -o test_auto.png "http://localhost:8000/api/dicom/render/7?token=<token>"
file test_auto.png
# → PNG image data, 512 x 512, 8-bit grayscale

# Render PNG с WL/WW
curl -o test_bone.png "http://localhost:8000/api/dicom/render/7?token=<token>&center=500&width=2000"
# Заголовок X-Cache: MISS (первый рендер)

# Повторный запрос — из кэша
curl -I "http://localhost:8000/api/dicom/render/7?token=<token>&center=500&width=2000"
# Заголовок X-Cache: HIT

# Удаление файла (S3-aware)
curl -X POST "http://localhost:8000/api/delete-user-file" \
  -d "filename=ct_scan.dcm.age&confirm=true" \
  --cookie "access_token=<JWT>"
```

---

## 6. Обработка ошибок

| Сценарий                     | HTTP | Действие                                |
|------------------------------|------|-----------------------------------------|
| Файл не DICOM                | 400  | Кнопка «Просмотр» не отображается       |
| View-токен истёк             | 410  | «Сессия истекла, откройте заново»       |
| Токен недействителен         | 401  | «Недействительный токен»                |
| DICOM Viewer отключён        | 501  | Кнопка скрыта                           |
| Файл слишком большой         | 413  | «Файл слишком большой для просмотра»    |
| Ошибка pydicom               | 500  | «Ошибка рендера: ...»                   |
| Сжатый DICOM (JPEG2000, RLE) | 500  | «Не удалось распаковать сжатый DICOM...»|
| Зависимости не установлены   | 500  | «Зависимость не установлена: numpy»     |

### Поддерживаемые Transfer Syntax

**Uncompressed (всегда работают):**
- Implicit VR Little Endian (`1.2.840.10008.1.2`)
- Explicit VR Little Endian (`1.2.840.10008.1.2.1`)
- Explicit VR Big Endian (`1.2.840.10008.1.2.2`)

**Compressed (требуют pydicom[gdcm]):**
- JPEG Baseline (`1.2.840.10008.1.2.4.50`)
- JPEG Extended (`1.2.840.10008.1.2.4.51`)
- JPEG Lossless (`1.2.840.10008.1.2.4.57`)
- JPEG Lossless SV1 (`1.2.840.10008.1.2.4.70`)
- JPEG-LS Lossy (`1.2.840.10008.1.2.4.80`)
- JPEG-LS Lossless (`1.2.840.10008.1.2.4.81`)
- **JPEG 2000 Lossless** (`1.2.840.10008.1.2.4.90`)
- **JPEG 2000 Lossy** (`1.2.840.10008.1.2.4.91`)
- **RLE Lossless** (`1.2.840.10008.1.2.5`)

### Установка GDCM

```bash
# В Docker-контейнере (pyproject.toml уже обновлён)
docker exec smdg-smdg-1 pip install --break-system-packages "pydicom[gdcm]"
docker restart smdg-smdg-1

# Или пересобрать образ
docker compose build smdg
docker compose up -d smdg
```

**Проверка установки:**
```python
import pydicom
from pydicom import data_manager
print(data_manager.get_charset())
# Если GDCM установлен — распаковка JPEG2000 работает автоматически
```

---

## 7. Производительность

| Операция                  | Время     | Примечание                                       |
|---------------------------|-----------|--------------------------------------------------|
| Первый запрос metadata    | 1-5 сек   | Расшифровка + pydicom парсинг                    |
| Повторный запрос metadata | <10 мс    | Redis-кэш (`smdg:dicom_meta:{file_id}`)          |
| Render PNG (первый, uncompressed) | 0.5-3 сек | Расшифровка + pydicom + numpy + PIL      |
| Render PNG (первый, JPEG2000)     | 1-8 сек   + GDCM распаковка                          |
| Render PNG (кэш HIT)      | <5 мс     | Redis-кэш (`smdg:dicom_png:{file_id}:{wc}:{ww}`) |
| QIDO-RS (из кэша)         | <10 мс    | Redis-кэш метаданных                             |
| WADO-RS streaming         | 0.5-3 сек | Расшифровка + streaming                          |
| Удаление файла            | 0.1-1 сек | S3 delete / local unlink + cascade DB delete     |

### Redis-кэш

**Метаданные:**
- Ключ: `smdg:dicom_meta:{file_id}`
- TTL: `dicom_view_token_ttl_seconds + 3600` (по умолчанию 2.25 часа)
- Содержимое: JSON-сериализованный dict с 30+ DICOM-тегами

**PNG изображения:**
- Ключ: `smdg:dicom_png:{file_id}:{wc}:{ww}`
- TTL: 1 час
- Содержимое: бинарные данные PNG
- Пример: `smdg:dicom_png:7:500:2000` (file 7, bone preset)

При каждом WL/WW изменении фронтенд делает новый запрос — если PNG уже в кэше, ответ мгновенный (<5 мс).

### Оптимизации

- **Debounce 80ms** при drag WL/WW — снижает нагрузку на сервер
- **Сохранение трансформаций** (zoom/pan) при перезагрузке PNG — UX не страдает
- **`X-Cache: HIT/MISS`** заголовок — отладка кэширования
- **`optimize=True`** в PIL — уменьшает размер PNG на 30-50%
- **Multi-frame клиентский кэш** — до 50 фреймов в браузере, мгновенное переключение
- **Предзагрузка соседних фреймов** (±3) — плавная навигация в Cine mode
- **Deduplication запросов** — одновременные запросы одного фрейма объединяются
- **Redis кэш на сервере** — каждый фрейм кэшируется отдельно с уникальным ключом

---

## 8. DICOMweb совместимость

| Стандарт          | Поддержка | Описание                                   |
|-------------------|-----------|--------------------------------------------|
| QIDO-RS           | ✅ Полная| Query с fuzzymatching, includefield, limit |
| WADO-RS           | ✅       | Retrieve DICOM objects                     |
| STOW-RS           | ❌       | Store — не требуется для viewer            |
| DICOM JSON        | ✅       | Формат ответа QIDO-RS                      |
| multipart/related | ❌       | Single-frame only                          |

### Формат QIDO-RS ответа

```json
{
  "00080060": { "vr": "CS", "Value": ["CT"] },
  "0020000D": { "vr": "UI", "Value": ["2.25.607865..."] },
  "00100010": { "vr": "PN", "Value": [{"Alphabetic": "Иванов^Иван"}] }
}
```

Стандартный DICOM JSON формат: каждый элемент — объект с `vr` (Value Representation) и `Value`.

---

## 9. Файловая структура

```
app/
  api/
    dicom.py              # Все DICOMweb эндпоинты
  models/
    dicom_view_token.py   # Модель view-токенов
  core/
    config.py             # dicom_viewer_enabled, TTL, max_size

migrations/versions/
  a1b2c3d4e5f7_add_dicom_view_tokens.py

static/
  html/
    dicom-viewer.html     # DICOM Viewer UI
  js/
    modules/
      files.js            # Кнопка «Просмотр»
    main.js               # Feature flag check
  css/
    style.css             # Стили модалки
```

---

## 10. Быстрый старт

```bash
# 1. Установить зависимости
docker exec smdg-smdg-1 pip install --break-system-packages pydicom numpy pillow

# 2. Перезапустить
docker restart smdg-smdg-1

# 3. Включить фичу (если не включена)
echo "DICOM_VIEWER_ENABLED=true" >> .env

# 4. Применить миграцию
docker exec smdg-smdg-1 alembic upgrade head

# 5. Открыть SMDG → загрузить DICOM → нажать «👁️ Просмотр»
```

---

## 11. Roadmap

| Функция                    | Статус | Описание                                                            |
|----------------------------|--------|---------------------------------------------------------------------|
| Single-frame DICOM         | ✅     | PNG рендер через pydicom                                            |
| Redis-кэш метаданных       | ✅     | 30+ тегов, TTL 2.25ч                                                |
| Redis-кэш PNG              | ✅     | `smdg:dicom_png:{id}:{wc}:{ww}`, TTL 1ч                             
| QIDO-RS + WADO-RS          | ✅     | DICOMweb стандарт                                                   |
| WL/WW drag мышью           | ✅     | Горизонталь=WW, вертикаль=WC                                        |
| 5 пресетов тканей          | ✅     | Bone, Lung, Brain, Abdomen, Liver                                   |
| Авто-WL/WW из DICOM        | ✅     | Из WindowCenter/WindowWidth тегов                                   |
| 6 групп метаданных         | ✅     | С сокращением UID                                                   |
| Удаление файлов S3         | ✅     | encrypted_storage API, cascade delete                               |
| Multi-frame (CT/MRI серии) | ✅     | Загрузка всех кадров, scroll, cine loop, предзагрузка               |
| Сжатые DICOM (JPEG2000)    | ✅     | pydicom[gdcm] — JPEG2000, JPEG-LS, RLE, JPEG                        |
| Measurements               | ✅     | Линейка, угол, ROI (Rectangle/Ellipse), Pixel Spacing               |
| OHIF Viewer интеграция     | ✅     | DICOMweb viewer через `/api/dicom/ohif-url`, series panel, metadata |
| Экспорт PNG/Screenshot     | ✅     | Скриншот с измерениями, метаданными и ориентацией                   |

---

## 12. OHIF Viewer Integration

### Обзор

OHIF Viewer — отдельный viewer в стиле OHIF (Open Health Imaging Foundation) с DICOMweb endpoints.
Использует те же QIDO-RS/WADO-RS endpoints что и встроенный DICOM Viewer.

### Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│  OHIF Viewer (standalone page)                               │
│                                                              │
│  /ohif-viewer?token=...&file_id=...                          │
│    ├── GET /api/dicom/metadata/{id}?token=... → JSON         │
│    ├── GET /api/dicom/render/{id}?token=...&frame=N → PNG    │
│    └── Series Panel, Viewport, Metadata                      │
├─────────────────────────────────────────────────────────────┤
│  Backend:                                                    │
│  POST /api/dicom/ohif-url → { ohif_url, token, config }      │
│  (те же QIDO-RS/WADO-RS endpoints)                           │
└─────────────────────────────────────────────────────────────┘
```

### API Endpoint

#### POST /api/dicom/ohif-url

Генерирует URL для OHIF Viewer с DICOMweb configuration.

**Auth:** JWT cookie

**Response 200:**
```json
{
  "ohif_url": "/ohif-viewer?v=...&token=...&file_id=...",
  "token": "uuid",
  "expires_at": "2026-04-12T02:15:00+00:00",
  "file_name": "chest_ct.dcm",
  "viewer_config": {
    "qido_url_root": "/api/dicom/qido?token=...",
    "wado_url_root": "/api/dicom/wado?token=...",
    "study_uid": "2.25.607865..."
  }
}
```

### OHIF Viewer Features

| Feature | Описание |
|---------|----------|
| **Series Panel** | Левая панель с series |
| **Viewport** | Центральный viewport с изображением |
| **Metadata Panel** | Правая панель с DICOM тегами |
| **Window/Level** | Drag мышью, 5 presets |
| **Zoom/Pan** | Mouse drag + wheel |
| **Multi-frame** | Cine controls (slider, play/pause) |
| **Invert** | Инверсия цветов |
| **Reset View** | Сброс трансформаций |

### Frontend Integration

```javascript
// Открыть OHIF Viewer
openOHIFViewer(fileId, fileName);
```

В UI две кнопки для DICOM файлов:
- **👁️ Просмотр** — встроенный DICOM Viewer
- **🏥 OHIF** — OHIF-style Viewer

### Audit

| Событие | Когда логируется |
|---------|------------------|
| `dicom.ohif_initiated` | Генерация OHIF Viewer URL |

---

## 13. Экспорт PNG / Screenshot

### Обзор

Оба viewer (встроенный и OHIF) поддерживают экспорт текущего вида в PNG файл.
Скриншот включает изображение, измерения, метаданные и ориентацию.

### Что включено в скриншот

| Элемент | Описание |
|---------|----------|
| **Изображение** | DICOM с применёнными WL/WW, zoom, pan, invert |
| **Измерения** | Линейки, углы, ROI (если есть) — рисуются поверх |
| **Метаданные** | PatientName, StudyDate, Modality, WL/WW, Frame (для multi-frame) |
| **Ориентация** | A (anterior), P (posterior), R (right), L (left) |

### Формат имени файла

```
{Modality}_{PatientName}_{StudyDate}_fr{Frame}_{Timestamp}.png
```

**Примеры:**
```
CT_Иванов^Иван_20260412_fr5_2026-04-13T14-30-22.png
MRI_Unknown_nodate_2026-04-13T14-30-22.png
```

### Как использовать

1. **Настроить вид**: WL/WW, zoom, pan, измерения
2. **Нажать 📸 Скриншот** в toolbar
3. **Файл автоматически скачивается** с осмысленным именем

### Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│  Screenshot Canvas                                           │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │  [DICOM Image]  ← с применёнными transform           │   │
│  │  + Measurements  ← canvas overlay                    │   │
│  │                                                      │   │
│  │  A                    ← Orientation markers          │   │
│  │ R   L                                                │   │
│  │  P                                                   │   │
│  │                                                      │   │
│  │  Patient | Date | Modality  ← Metadata overlay       │   │
│  │  WL: 500 / WW: 2000 | Frame 5/126                   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  → canvas.toBlob() → download → CT_..._fr5_....png          │
└─────────────────────────────────────────────────────────────┘
```

### Реализация

**Встроенный DICOM Viewer:**
```javascript
takeScreenshot() {
    // 1. Создаём canvas размером с viewport
    // 2. Рисуем изображение с transform (scale, translate, invert)
    // 3. Рисуем measurement canvas поверх
    // 4. Добавляем metadata overlay (patient, date, WL/WW, frame)
    // 5. Добавляем orientation markers (A/P/R/L)
    // 6. Экспорт в PNG с осмысленным именем файла
}
```

**OHIF Viewer:**
```javascript
takeScreenshotOHIF() {
    // Аналогичная логика для OHIF-style viewer
}
```

### Особенности

- **Все трансформации** (zoom, pan, invert) сохраняются в скриншоте
- **Multi-frame** — экспортируется только текущий кадр
- **Измерения** — все активные измерения рисуются поверх
- **Без потерь** — PNG без сжатия, оригинальное качество
- **Ориентация** — стандарт DICOM (A/P/R/L) для медицинских изображений
