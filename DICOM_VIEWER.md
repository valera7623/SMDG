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
4. Multi-frame → берётся первый кадр
5. Windowing: заданный WL/WW или автоматический min-max
6. `PIL.Image.fromarray()` → PNG в память
7. Сохранение PNG в Redis (TTL 1 час)
8. StreamingResponse (без записи на диск)

**Аудит:** `dicom.streamed` / `dicom.stream_failed`

**Примеры запросов:**

```bash
# Автоматическая нормализация (min-max)
curl -o auto.png "http://localhost:8000/api/dicom/render/7?token=TOKEN"

# Bone preset (WL=500, WW=2000)
curl -o bone.png "http://localhost:8000/api/dicom/render/7?token=TOKEN&center=500&width=2000"

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

`static/html/dicom-viewer.html` — автономная страница без внешних зависимостей (~540 строк).

**Загрузка:**
1. `GET /api/dicom/metadata/{id}?token=...` → метаданные для sidebar (с автозагрузкой WL/WW)
2. `GET /api/dicom/render/{id}?token=...&center=...&width=...` → PNG с WL/WW параметрами

**Инструменты:**

| Кнопка | Действие |
|-------------------|-------------------------------------------------------------------|
| 🪟 Окно (WL/WW)    | Drag мышью: горизонталь = WW, вертикаль = WC. Курсор: `ew-resize` |
| 🔍 Зум           | Drag вверх/вниз или колёсико мыши. Курсор: `crosshair`             |
| ✋ Пан            | Drag для перемещения. Курсор: `grab` → `grabbing`                 |
| ↺ Сброс          | Сброс масштаба, позиции и инверсии                                 |
| ◐ Инверт         | Инверсия цветов (CSS `filter: invert(1)`)                          |
| 💾 Скачать       | Скачать оригинальный DICOM-файл (осмысленное имя файла)            |
| ℹ️               | Панель метаданных (6 групп, сокращённые UID)                       |
| ✕                | Закрыть viewer                                                     |                          

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
4. **Изображение** — Rows, Columns, BitsAllocated, BitsStored, HighBit, PixelRepresentation, SamplesPerPixel, PhotometricInterpretation, NumberOfFrames
5. **Окно/Уровень** — WindowCenter, WindowWidth, RescaleIntercept, RescaleSlope
6. **Оборудование** — Manufacturer, ManufacturerModelName, InstitutionName, StationName, SoftwareVersions

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
| Сжатый DICOM (JPEG2000, RLE) | 500  | pydicom может не распаковать без codecs |
| Зависимости не установлены   | 500  | «Зависимость не установлена: numpy»     |

### Сжатые DICOM

Форматы JPEG2000, JPEG-LS, RLE требуют дополнительных кодеков:

```bash
# Для pydicom с поддержкой сжатия
pip install pydicom[gdcm]
```

Без кодеков pydicom может извлечь pixel_array только для:
- Implicit VR Little Endian (`1.2.840.10008.1.2`)
- Explicit VR Little Endian (`1.2.840.10008.1.2.1`)
- Explicit VR Big Endian (`1.2.840.10008.1.2.2`)

---

## 7. Производительность

| Операция                  | Время     | Примечание                                       |
|---------------------------|-----------|--------------------------------------------------|
| Первый запрос metadata    | 1-5 сек   | Расшифровка + pydicom парсинг                    |
| Повторный запрос metadata | <10 мс    | Redis-кэш (`smdg:dicom_meta:{file_id}`)          |
| Render PNG (первый)       | 0.5-3 сек | Расшифровка + pydicom + numpy + PIL              |
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

| Функция                    | Статус | Описание                                |
|----------------------------|--------|-----------------------------------------|
| Single-frame DICOM         | ✅     | PNG рендер через pydicom                |
| Redis-кэш метаданных       | ✅     | 30+ тегов, TTL 2.25ч                    |
| Redis-кэш PNG              | ✅     | `smdg:dicom_png:{id}:{wc}:{ww}`, TTL 1ч |
| QIDO-RS + WADO-RS          | ✅     | DICOMweb стандарт                       |
| WL/WW drag мышью           | ✅     | Горизонталь=WW, вертикаль=WC            |
| 5 пресетов тканей          | ✅     | Bone, Lung, Brain, Abdomen, Liver       |
| Авто-WL/WW из DICOM        | ✅     | Из WindowCenter/WindowWidth тегов       |
| 6 групп метаданных         | ✅     | С сокращением UID                       |
| Удаление файлов S3         | ✅     | encrypted_storage API, cascade delete   |
| Multi-frame (CT/MRI серии) | 🔜     | Загрузка всех кадров, scroll между ними |
| Сжатые DICOM (JPEG2000)    | 🔜     | pydicom[gdcm]                           |
| Measurements               | 🔜     | Линейка, угол, ROI через Canvas         |
| OHIF Viewer интеграция     | 🔜     | Полноценный PACS viewer в iframe        |
| Экспорт PNG/Screenshot     | 🔜     | Сохранение текущего вида                |
| Cine playback              | 🔜      | Анимация multi-frame (cine loop)       |
