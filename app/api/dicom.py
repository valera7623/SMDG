# app/api/dicom.py
"""
DICOMweb API для OHIF Viewer.

Стандарты DICOMweb:
  - QIDO-RS (Query): GET /qido/studies, /qido/studies/{studyUID}/series, ...
  - WADO-RS (Retrieve): GET /wado/studies/{studyUID}/series/{seriesUID}/instances/{instanceUID}

Безопасность:
  - Все эндпоинты авторизуются через view_token (query param)
  - Token multi-use (для multi-frame CT/MRI)
  - Файл расшифровывается ТОЛЬКО в память
  - Каждое действие логируется в аудит
"""

import uuid
import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core import encrypted_storage, PRIVATE_KEY_PATH, audit_logger
from app.core.database import AsyncSessionLocal, get_db
from app.core.auth import get_current_user, TokenData
from app.models.file import File
from app.models.dicom_view_token import DicomViewToken
from app.crypto.crypto import crypto_manager
from app.crypto.crypto import crypto_manager

router = APIRouter(prefix="/dicom", tags=["dicom"])
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Redis Cache для DICOM метаданных
# ─────────────────────────────────────────────────────────────────────

async def _get_dicom_metadata_cache(file_id: int) -> dict | None:
    """Получить кэшированные DICOM-метаданные из Redis."""
    try:
        from redis.asyncio import Redis
        r = Redis.from_url(settings.redis_url, decode_responses=True)
        cached = await r.get(f"smdg:dicom_meta:{file_id}")
        await r.close()
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.debug(f"[DICOM Cache] Redis read error: {e}")
    return None


async def _set_dicom_metadata_cache(file_id: int, metadata: dict):
    """Сохранить DICOM-метаданные в Redis (TTL = TTL view_token + 1 час)."""
    try:
        from redis.asyncio import Redis
        r = Redis.from_url(settings.redis_url, decode_responses=True)
        ttl = settings.dicom_view_token_ttl_seconds + 3600
        await r.set(f"smdg:dicom_meta:{file_id}", json.dumps(metadata), ex=ttl)
        await r.close()
    except Exception as e:
        logger.debug(f"[DICOM Cache] Redis write error: {e}")


async def _parse_and_cache_dicom(file_id: int, encrypted_path: str) -> dict:
    """
    Расшифровать DICOM, распарсить pydicom, извлечь реальные UIDs,
    сохранить в кэш и вернуть метаданные.
    """
    # Расшифровка в память
    decrypted_bytes = await _decrypt_dicom_to_memory(encrypted_path)

    import pydicom
    from io import BytesIO

    ds = pydicom.dcmread(BytesIO(decrypted_bytes), force=True)

    def safe(tag_id, default=""):
        try:
            if tag_id in ds:
                val = ds[tag_id].value
                return str(val) if val is not None else default
            return default
        except Exception:
            return default

    # Реальные DICOM UIDs
    study_uid = safe(0x0020000D)
    series_uid = safe(0x0020000E)
    sop_uid = safe(0x00080018)
    transfer_syntax = safe(0x00020010)

    # Human-readable название Transfer Syntax
    transfer_syntax_name = ""
    if transfer_syntax:
        ts_names = {
            '1.2.840.10008.1.2': 'Implicit VR Little Endian',
            '1.2.840.10008.1.2.1': 'Explicit VR Little Endian',
            '1.2.840.10008.1.2.2': 'Explicit VR Big Endian',
            '1.2.840.10008.1.2.4.50': 'JPEG Baseline',
            '1.2.840.10008.1.2.4.51': 'JPEG Extended',
            '1.2.840.10008.1.2.4.57': 'JPEG Lossless',
            '1.2.840.10008.1.2.4.70': 'JPEG Lossless SV1',
            '1.2.840.10008.1.2.4.80': 'JPEG-LS Lossy',
            '1.2.840.10008.1.2.4.81': 'JPEG-LS Lossless',
            '1.2.840.10008.1.2.4.90': 'JPEG 2000 Lossless',
            '1.2.840.10008.1.2.4.91': 'JPEG 2000 Lossy',
            '1.2.840.10008.1.2.5': 'RLE Lossless',
        }
        transfer_syntax_name = ts_names.get(transfer_syntax, transfer_syntax)

    # Если UIDs отсутствуют — генерируем синтетические
    if not study_uid:
        study_uid = _make_study_uid(file_id)
    if not series_uid:
        series_uid = _make_series_uid(file_id)
    if not sop_uid:
        sop_uid = _make_instance_uid(file_id)

    metadata = {
        # Реальные UIDs
        "StudyInstanceUID": study_uid,
        "SeriesInstanceUID": series_uid,
        "SOPInstanceUID": sop_uid,
        "TransferSyntaxUID": transfer_syntax,
        "TransferSyntaxName": transfer_syntax_name,

        # Пациент
        "PatientName": safe(0x00100010),
        "PatientID": safe(0x00100020),
        "PatientBirthDate": safe(0x00100030),
        "PatientSex": safe(0x00100040),
        "PatientAge": safe(0x00101010),

        # Исследование
        "StudyDate": safe(0x00080020),
        "StudyTime": safe(0x00080030),
        "StudyDescription": safe(0x00081030),
        "StudyID": safe(0x00200010),
        "AccessionNumber": safe(0x00080050),
        "ReferringPhysicianName": safe(0x00080090),

        # Серия
        "Modality": safe(0x00080060),
        "SeriesDescription": safe(0x0008103E),
        "SeriesNumber": safe(0x00200011),
        "ProtocolName": safe(0x00181030),

        # Изображение
        "Rows": safe(0x00280010, "0"),
        "Columns": safe(0x00280011, "0"),
        "BitsAllocated": safe(0x00280100, "0"),
        "SamplesPerPixel": safe(0x00280002, "0"),
        "PhotometricInterpretation": safe(0x00280004),
        "NumberOfFrames": safe(0x00280008, "1"),
        "PixelSpacing": safe(0x00280030),
        "SliceThickness": safe(0x00180050),

        # Оборудование
        "Manufacturer": safe(0x00080070),
        "InstitutionName": safe(0x00080080),
        "StationName": safe(0x00081010),
        "SoftwareVersions": safe(0x00181020),

        # Window
        "WindowCenter": safe(0x00281050, "0"),
        "WindowWidth": safe(0x00281051, "0"),

        # Multi-frame info
        "NumberOfStudyRelatedSeries": safe(0x00201206, "1"),
        "NumberOfStudyRelatedInstances": safe(0x00201208, "1"),
    }

    # Кэшируем
    await _set_dicom_metadata_cache(file_id, metadata)

    logger.info(
        f"[DICOM Parse] file_id={file_id}: Study={study_uid[:20]}..., "
        f"Series={series_uid[:20]}..., Modality={metadata['Modality']}, "
        f"Frames={metadata['NumberOfFrames']}"
    )

    return metadata


# ─────────────────────────────────────────────────────────────────────
# Feature Flag
# ─────────────────────────────────────────────────────────────────────

def _require_dicom_viewer_enabled():
    if not settings.dicom_viewer_enabled:
        raise HTTPException(
            status_code=501,
            detail="DICOM Viewer отключён (DICOM_VIEWER_ENABLED=false)"
        )


# ─────────────────────────────────────────────────────────────────────
# Авторизация через view_token (общая для QIDO-RS и WADO-RS)
# ─────────────────────────────────────────────────────────────────────

async def _validate_view_token(token: str, file_id: int) -> dict:
    """Валидация view-токена. Возвращает dict с данными файла."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DicomViewToken).where(DicomViewToken.token == token)
        )
        vt = result.scalar_one_or_none()
        if not vt:
            raise HTTPException(status_code=401, detail="Недействительный токен")

        now = datetime.now(timezone.utc)
        if vt.expires_at and vt.expires_at < now:
            await db.delete(vt)
            await db.commit()
            raise HTTPException(status_code=410, detail="Токен истёк")

        if vt.file_id != file_id:
            raise HTTPException(status_code=400, detail="file_id не совпадает")

        file_record = await db.get(File, file_id)
        if not file_record or file_record.mime_type != "application/dicom":
            raise HTTPException(status_code=404, detail="DICOM не найден")

        return {
            "file_id": file_record.id,
            "encrypted_path": file_record.encrypted_path,
            "original_name": file_record.original_name,
        }


# ─────────────────────────────────────────────────────────────────────
# Синтетические DICOM UID
# ─────────────────────────────────────────────────────────────────────

def _make_study_uid(file_id: int) -> str:
    """Генерирует синтетический StudyInstanceUID на основе file_id.
    
    DICOM UID: до 64 цифр, формат: root.suffix
    Используем OID корень 2.25 (UUID OID arc) + хеш file_id
    """
    h = hashlib.sha1(f"smdg-study-{file_id}".encode()).hexdigest()
    return f"2.25.{int(h[:28], 16)}"


def _make_series_uid(file_id: int) -> str:
    """Генерирует синтетический SeriesInstanceUID."""
    h = hashlib.sha1(f"smdg-series-{file_id}".encode()).hexdigest()
    return f"2.25.{int(h[:28], 16)}"


def _make_instance_uid(file_id: int) -> str:
    """Генерирует синтетический SOPInstanceUID."""
    h = hashlib.sha1(f"smdg-instance-{file_id}".encode()).hexdigest()
    return f"2.25.{int(h[:28], 16)}"


# ─────────────────────────────────────────────────────────────────────
# POST /api/dicom/view-url — генерация view-токена
# ─────────────────────────────────────────────────────────────────────

@router.post("/view-url")
async def generate_view_url(
    file_id: int = Query(..., description="ID DICOM-файла"),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Генерирует view-токен для OHIF Viewer.

    Требует: JWT аутентификация.
    Возвращает: { view_url, token, expires_at, file_name }
    """
    _require_dicom_viewer_enabled()

    result = await db.execute(select(File).where(File.id == file_id))
    file_record = result.scalar_one_or_none()

    if not file_record:
        raise HTTPException(status_code=404, detail="Файл не найден")

    if file_record.mime_type != "application/dicom":
        raise HTTPException(
            status_code=400,
            detail=f"Файл не является DICOM (MIME: {file_record.mime_type})"
        )

    view_token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.dicom_view_token_ttl_seconds
    )

    dicom_token = DicomViewToken(
        token=view_token,
        file_id=file_record.id,
        expires_at=expires_at,
    )
    db.add(dicom_token)
    await db.commit()
    await db.refresh(dicom_token)

    # Генерируем DICOM UIDs для OHIF
    study_uid = _make_study_uid(file_id)
    series_uid = _make_series_uid(file_id)
    instance_uid = _make_instance_uid(file_id)

    # URL для DICOM Viewer (iframe)
    import time
    cache_buster = int(time.time() // 60)  # меняется каждую минуту
    view_url = (
        f"/dicom-viewer?v={cache_buster}&"
        f"token={view_token}&"
        f"file_id={file_id}&"
        f"StudyInstanceUID={study_uid}&"
        f"SeriesInstanceUID={series_uid}&"
        f"SOPInstanceUID={instance_uid}"
    )

    # АУДИТ
    audit_logger.log_operation(
        action="dicom.view_initiated",
        filename=file_record.original_name,
        user=current_user.sub,
        reason="Открыт DICOM viewer",
        success=True,
        metadata={
            "file_id": file_id,
            "token_id": dicom_token.id,
            "expires_at": expires_at.isoformat(),
            "study_uid": study_uid,
        }
    )

    logger.info(
        f"[DICOM VIEW] Пользователь открыл viewer для "
        f"файла {file_record.original_name} (ID={file_id})"
    )

    return {
        "view_url": view_url,
        "token": view_token,
        "expires_at": expires_at.isoformat(),
        "file_name": file_record.original_name,
        "file_id": file_id,
        "study_uid": study_uid,
        "series_uid": series_uid,
    }


# ─────────────────────────────────────────────────────────────────────
# POST /api/dicom/ohif-url — генерация URL для OHIF Viewer
# ─────────────────────────────────────────────────────────────────────

@router.post("/ohif-url")
async def generate_ohif_url(
    file_id: int = Query(..., description="ID DICOM-файла"),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Генерирует URL для OHIF Viewer с DICOMweb endpoints.

    Требует: JWT аутентификация.
    Возвращает: { ohif_url, token, expires_at, viewer_config }
    """
    _require_dicom_viewer_enabled()

    result = await db.execute(select(File).where(File.id == file_id))
    file_record = result.scalar_one_or_none()

    if not file_record:
        raise HTTPException(status_code=404, detail="Файл не найден")

    if file_record.mime_type != "application/dicom":
        raise HTTPException(
            status_code=400,
            detail=f"Файл не является DICOM (MIME: {file_record.mime_type})"
        )

    view_token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.dicom_view_token_ttl_seconds
    )

    dicom_token = DicomViewToken(
        token=view_token,
        file_id=file_record.id,
        expires_at=expires_at,
    )
    db.add(dicom_token)
    await db.commit()
    await db.refresh(dicom_token)

    # Генерируем DICOM UIDs
    study_uid = _make_study_uid(file_id)
    series_uid = _make_series_uid(file_id)

    # URL для OHIF Viewer (self-hosted или iframe)
    # OHIF Viewer поддерживает viewer route через URL params
    import time
    cache_buster = int(time.time() // 60)
    ohif_url = (
        f"/ohif-viewer?v={cache_buster}&"
        f"token={view_token}&"
        f"file_id={file_id}&"
        f"StudyInstanceUID={study_uid}&"
        f"SeriesInstanceUID={series_uid}"
    )

    # АУДИТ
    audit_logger.log_operation(
        action="dicom.ohif_initiated",
        filename=file_record.original_name,
        user=current_user.sub,
        reason="Открыт OHIF Viewer",
        success=True,
        metadata={
            "file_id": file_id,
            "token_id": dicom_token.id,
            "expires_at": expires_at.isoformat(),
            "study_uid": study_uid,
        }
    )

    logger.info(
        f"[OHIF VIEW] Пользователь открыл OHIF Viewer для "
        f"файла {file_record.original_name} (ID={file_id})"
    )

    return {
        "ohif_url": ohif_url,
        "token": view_token,
        "expires_at": expires_at.isoformat(),
        "file_name": file_record.original_name,
        "file_id": file_id,
        "study_uid": study_uid,
        "series_uid": series_uid,
        "viewer_config": {
            "qido_url_root": f"/api/dicom/qido?token={view_token}",
            "wado_url_root": f"/api/dicom/wado?token={view_token}",
            "study_uid": study_uid,
        }
    }


# ====================================================================
# QIDO-RS (Query based on ID for DICOM Objects)
# ====================================================================

async def _get_or_parse_metadata(file_id: int, encrypted_path: str) -> dict:
    """Получить метаданные из кэша или распарсить DICOM."""
    meta = await _get_dicom_metadata_cache(file_id)
    if meta:
        return meta
    return await _parse_and_cache_dicom(file_id, encrypted_path)


# ── GET /api/dicom/qido/studies ──────────────────────────────────────

@router.get("/qido/studies")
async def qido_studies(
    token: str = Query(..., description="View-токен"),
    fuzzymatching: str = Query(None, alias="fuzzymatching"),
    includefield: str = Query("all", alias="includefield"),
    limit: int = Query(100),
):
    """
    QIDO-RS: Returns list of studies.
    
    Поддерживает: fuzzymatching, includefield, limit.
    Возвращает реальные DICOM UIDs из кэша.
    """
    _require_dicom_viewer_enabled()

    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(DicomViewToken).where(
                DicomViewToken.token == token,
                DicomViewToken.expires_at >= now,
            )
        )
        vt = result.scalar_one_or_none()
        if not vt:
            raise HTTPException(status_code=401, detail="Недействительный токен")

        file_record = await db.get(File, vt.file_id)
        if not file_record or file_record.mime_type != "application/dicom":
            raise HTTPException(status_code=404, detail="DICOM не найден")

        data = {
            "file_id": vt.file_id,
            "original_name": file_record.original_name,
            "patient_id": file_record.patient_id,
            "encrypted_path": file_record.encrypted_path,
        }

    # Получить реальные метаданные (из кэша или парсинг)
    meta = await _get_or_parse_metadata(data["file_id"], data["encrypted_path"])

    study_uid = meta["StudyInstanceUID"]
    modality = meta["Modality"] or "OT"

    return JSONResponse(
        content=[{
            "00080005": {"Value": ["ISO_IR 192"], "vr": "CS"},  # SpecificCharacterSet
            "00080020": {"Value": [meta["StudyDate"]] if meta["StudyDate"] else [], "vr": "DA"},
            "00080030": {"Value": [meta["StudyTime"]] if meta["StudyTime"] else [], "vr": "TM"},
            "00080050": {"Value": [meta["AccessionNumber"]] if meta["AccessionNumber"] else [], "vr": "SH"},
            "00080060": {"Value": [modality], "vr": "CS"},  # Modality
            "00080061": {"Value": [modality], "vr": "CS"},  # ModalitiesInStudy
            "00080090": {"Value": [{"Alphabetic": meta["ReferringPhysicianName"]}] if meta["ReferringPhysicianName"] else [], "vr": "PN"},
            "00081030": {"Value": [meta["StudyDescription"]] if meta["StudyDescription"] else [], "vr": "LO"},
            "00100010": {"Value": [{"Alphabetic": meta["PatientName"] or "Unknown"}], "vr": "PN"},
            "00100020": {"Value": [meta["PatientID"] or f"P{data['file_id']}"], "vr": "LO"},
            "00100030": {"Value": [meta["PatientBirthDate"]] if meta["PatientBirthDate"] else [], "vr": "DA"},
            "00100040": {"Value": [meta["PatientSex"]] if meta["PatientSex"] else [], "vr": "CS"},
            "00101010": {"Value": [meta["PatientAge"]] if meta["PatientAge"] else [], "vr": "AS"},
            "0020000D": {"Value": [study_uid], "vr": "UI"},  # StudyInstanceUID
            "00200010": {"Value": [meta["StudyID"]] if meta["StudyID"] else [], "vr": "SH"},
            "00201206": {"Value": [int(meta.get("NumberOfStudyRelatedSeries", 1))], "vr": "IS"},
            "00201208": {"Value": [int(meta.get("NumberOfStudyRelatedInstances", 1))], "vr": "IS"},
        }],
        headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Type": "application/dicom+json",
        }
    )


# ── GET /api/dicom/qido/studies/{studyUID}/series ────────────────────

@router.get("/qido/studies/{study_uid}/series")
async def qido_series(
    study_uid: str,
    token: str = Query(...),
    includefield: str = Query("all", alias="includefield"),
):
    """QIDO-RS: Series для конкретного Study."""
    _require_dicom_viewer_enabled()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DicomViewToken).where(
                DicomViewToken.token == token,
                DicomViewToken.expires_at >= datetime.now(timezone.utc),
            )
        )
        vt = result.scalar_one_or_none()
        if not vt:
            raise HTTPException(status_code=401, detail="Недействительный токен")

        file_record = await db.get(File, vt.file_id)
        if not file_record:
            raise HTTPException(status_code=404, detail="DICOM не найден")

        data = {
            "file_id": vt.file_id,
            "original_name": file_record.original_name,
            "encrypted_path": file_record.encrypted_path,
        }

    meta = await _get_or_parse_metadata(data["file_id"], data["encrypted_path"])

    if study_uid != meta["StudyInstanceUID"]:
        raise HTTPException(status_code=404, detail="Study не найден")

    series_uid = meta["SeriesInstanceUID"]
    modality = meta["Modality"] or "OT"

    return JSONResponse(
        content=[{
            "00080060": {"Value": [modality], "vr": "CS"},  # Modality
            "0008103E": {"Value": [meta["SeriesDescription"]] if meta["SeriesDescription"] else [], "vr": "LO"},
            "00181030": {"Value": [meta["ProtocolName"]] if meta["ProtocolName"] else [], "vr": "LO"},
            "0020000D": {"Value": [study_uid], "vr": "UI"},  # StudyInstanceUID
            "0020000E": {"Value": [series_uid], "vr": "UI"},  # SeriesInstanceUID
            "00200011": {"Value": [int(meta["SeriesNumber"])] if meta["SeriesNumber"] else [1], "vr": "IS"},
            "00201209": {"Value": [int(meta.get("NumberOfStudyRelatedInstances", 1))], "vr": "IS"},
        }],
        headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Type": "application/dicom+json",
        }
    )


# ── GET /api/dicom/qido/studies/{studyUID}/series/{seriesUID}/instances ──

@router.get("/qido/studies/{study_uid}/series/{series_uid}/instances")
async def qido_instances(
    study_uid: str,
    series_uid: str,
    token: str = Query(...),
    includefield: str = Query("all", alias="includefield"),
):
    """QIDO-RS: Instances для конкретной Series."""
    _require_dicom_viewer_enabled()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DicomViewToken).where(
                DicomViewToken.token == token,
                DicomViewToken.expires_at >= datetime.now(timezone.utc),
            )
        )
        vt = result.scalar_one_or_none()
        if not vt:
            raise HTTPException(status_code=401, detail="Недействительный токен")

        file_record = await db.get(File, vt.file_id)
        if not file_record:
            raise HTTPException(status_code=404, detail="DICOM не найден")

        data = {
            "file_id": vt.file_id,
            "original_name": file_record.original_name,
            "encrypted_path": file_record.encrypted_path,
        }

    meta = await _get_or_parse_metadata(data["file_id"], data["encrypted_path"])

    if study_uid != meta["StudyInstanceUID"]:
        raise HTTPException(status_code=404, detail="Study не найден")
    if series_uid != meta["SeriesInstanceUID"]:
        raise HTTPException(status_code=404, detail="Series не найдена")

    sop_uid = meta["SOPInstanceUID"]
    modality = meta["Modality"] or "OT"

    return JSONResponse(
        content=[{
            "00080016": {"Value": [], "vr": "UI"},  # SOPClassUID
            "00080018": {"Value": [sop_uid], "vr": "UI"},  # SOPInstanceUID
            "00080060": {"Value": [modality], "vr": "CS"},  # Modality
            "0020000D": {"Value": [study_uid], "vr": "UI"},  # StudyInstanceUID
            "0020000E": {"Value": [series_uid], "vr": "UI"},  # SeriesInstanceUID
            "00200013": {"Value": [1], "vr": "IS"},  # InstanceNumber
            "00280010": {"Value": [int(meta["Rows"])] if meta["Rows"] else [], "vr": "US"},
            "00280011": {"Value": [int(meta["Columns"])] if meta["Columns"] else [], "vr": "US"},
            "00280100": {"Value": [int(meta["BitsAllocated"])] if meta["BitsAllocated"] else [], "vr": "US"},
            "00020010": {"Value": [meta["TransferSyntaxUID"]] if meta["TransferSyntaxUID"] else [], "vr": "UI"},
            "00280008": {"Value": [meta["NumberOfFrames"]] if meta["NumberOfFrames"] else [], "vr": "IS"},
        }],
        headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Type": "application/dicom+json",
        }
    )


# ====================================================================
# WADO-RS (Web Access to DICOM Objects - Retrieve)
# ====================================================================

# ── GET /api/dicom/wado/studies/{studyUID}/series/{seriesUID}/instances/{instanceUID} ──

@router.get("/wado/studies/{study_uid}/series/{series_uid}/instances/{instance_uid}")
async def wado_retrieve(
    study_uid: str,
    series_uid: str,
    instance_uid: str,
    token: str = Query(..., description="View-токен"),
):
    """WADO-RS: Возвращает DICOM-файл как streaming response."""
    _require_dicom_viewer_enabled()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DicomViewToken).where(
                DicomViewToken.token == token,
                DicomViewToken.expires_at >= datetime.now(timezone.utc),
            )
        )
        vt = result.scalar_one_or_none()
        if not vt:
            raise HTTPException(status_code=401, detail="Недействительный токен")

        file_record = await db.get(File, vt.file_id)
        if not file_record or file_record.mime_type != "application/dicom":
            raise HTTPException(status_code=404, detail="DICOM не найден")

        # Извлекаем данные внутри session
        data = {
            "file_id": vt.file_id,
            "encrypted_path": file_record.encrypted_path,
            "original_name": file_record.original_name,
            "token_id": vt.id,
        }

    # Проверяем UID
    if study_uid != _make_study_uid(data["file_id"]):
        raise HTTPException(status_code=404, detail="Study не найден")
    if series_uid != _make_series_uid(data["file_id"]):
        raise HTTPException(status_code=404, detail="Series не найдена")
    if instance_uid != _make_instance_uid(data["file_id"]):
        raise HTTPException(status_code=404, detail="Instance не найден")

    # Расшифровка в память
    try:
        decrypted_bytes = await _decrypt_dicom_to_memory(data["encrypted_path"])
    except Exception as e:
        logger.error(f"[DICOM WADO] Ошибка расшифровки: {e}")
        audit_logger.log_operation(
            action="dicom.stream_failed",
            filename=data["original_name"],
            user="anon",
            reason=f"Ошибка расшифровки: {e}",
            success=False,
            metadata={"file_id": data["file_id"]},
        )
        raise HTTPException(status_code=500, detail="Ошибка расшифровки DICOM")

    max_size = settings.dicom_max_stream_size_mb * 1024 * 1024
    if len(decrypted_bytes) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"Файл слишком большой ({len(decrypted_bytes) / 1024 / 1024:.1f} МБ)"
        )

    audit_logger.log_operation(
        action="dicom.streamed",
        filename=data["original_name"],
        user="anon",
        reason="DICOM streaming в OHIF",
        success=True,
        metadata={
            "file_id": data["file_id"],
            "size": len(decrypted_bytes),
            "token_id": data["token_id"],
        }
    )

    return StreamingResponse(
        iter([decrypted_bytes]),
        media_type="application/dicom",
        headers={
            "Content-Disposition": f'inline; filename="{data["original_name"]}"',
            "Content-Length": str(len(decrypted_bytes)),
            "Access-Control-Allow-Origin": "*",
        }
    )


# ── Legacy endpoint: GET /api/dicom/wado/{file_id} (прямая ссылка) ──

@router.get("/wado/{file_id}")
async def wado_legacy(
    file_id: int,
    token: str = Query(..., description="View-токен"),
):
    """Legacy WADO endpoint для обратной совместимости."""
    _require_dicom_viewer_enabled()
    data = await _validate_view_token(token, file_id)

    try:
        decrypted_bytes = await _decrypt_dicom_to_memory(data["encrypted_path"])
    except Exception as e:
        logger.error(f"[DICOM WADO] Ошибка: {e}")
        raise HTTPException(status_code=500, detail="Ошибка расшифровки DICOM")

    max_size = settings.dicom_max_stream_size_mb * 1024 * 1024
    if len(decrypted_bytes) > max_size:
        raise HTTPException(status_code=413, detail="Файл слишком большой")

    return StreamingResponse(
        iter([decrypted_bytes]),
        media_type="application/dicom",
        headers={
            "Content-Disposition": f'inline; filename="{data["original_name"]}"',
            "Content-Length": str(len(decrypted_bytes)),
            "Access-Control-Allow-Origin": "*",
        }
    )


# ─────────────────────────────────────────────────────────────────────
# GET /api/dicom/render/{file_id} — Render DICOM as PNG
# ─────────────────────────────────────────────────────────────────────

@router.get("/render/{file_id}")
async def render_dicom_png(
    file_id: int,
    token: str = Query(..., description="View-токен"),
    center: float = Query(None, description="Window Center (WL)"),
    width: float = Query(None, description="Window Width (WW)"),
    frame: int = Query(0, description="Номер кадра для multi-frame DICOM (0-indexed)"),
):
    """Рендерит DICOM в PNG через pydicom+numpy+PIL.

    Параметры center/width задают Window Center/Width для визуализации.
    Если не указаны — используется полная динамическая нормализация (min-max).
    Параметр frame выбирает конкретный кадр из multi-frame DICOM (CT/MRI серии).
    Результат кэшируется в Redis.
    """
    _require_dicom_viewer_enabled()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DicomViewToken).where(
                DicomViewToken.token == token,
                DicomViewToken.expires_at >= datetime.now(timezone.utc),
            )
        )
        vt = result.scalar_one_or_none()
        if not vt:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        if vt.file_id != file_id:
            raise HTTPException(status_code=400, detail="file_id не совпадает")

        file_record = await db.get(File, file_id)
        if not file_record or file_record.mime_type != "application/dicom":
            raise HTTPException(status_code=404, detail="DICOM не найден")

        data = {
            "encrypted_path": file_record.encrypted_path,
            "original_name": file_record.original_name,
        }

    # Проверяем кэш PNG
    wl_key = f"smdg:dicom_png:{file_id}:frame{frame}:{int(center) if center else 'auto'}:{int(width) if width else 'auto'}"
    try:
        from redis.asyncio import Redis
        r = Redis.from_url(settings.redis_url, decode_responses=False)
        cached_png = await r.get(wl_key)
        await r.close()
        if cached_png:
            return StreamingResponse(
                iter([cached_png]),
                media_type="image/png",
                headers={
                    "Content-Length": str(len(cached_png)),
                    "Access-Control-Allow-Origin": "*",
                    "X-Cache": "HIT",
                }
            )
    except Exception as e:
        logger.debug(f"[DICOM PNG Cache] Redis read error: {e}")

    # Рендерим
    try:
        decrypted_bytes = await _decrypt_dicom_to_memory(data["encrypted_path"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка расшифровки: {e}")

    try:
        import pydicom
        import numpy as np
        from PIL import Image
        from io import BytesIO

        ds = pydicom.dcmread(BytesIO(decrypted_bytes), force=True)

        # Проверяем Transfer Syntax UID для определения сжатия
        transfer_syntax = getattr(ds, 'file_meta', {}).get('TransferSyntaxUID', None)
        if transfer_syntax:
            ts_uid = str(transfer_syntax)
            # Определяем сжатые форматы
            compressed_formats = {
                '1.2.840.10008.1.2.4.50': 'JPEG Baseline',
                '1.2.840.10008.1.2.4.51': 'JPEG Extended',
                '1.2.840.10008.1.2.4.57': 'JPEG Lossless',
                '1.2.840.10008.1.2.4.70': 'JPEG Lossless SV1',
                '1.2.840.10008.1.2.4.80': 'JPEG-LS Lossy',
                '1.2.840.10008.1.2.4.81': 'JPEG-LS Lossless',
                '1.2.840.10008.1.2.4.90': 'JPEG 2000 Lossless',
                '1.2.840.10008.1.2.4.91': 'JPEG 2000 Lossy',
                '1.2.840.10008.1.2.5': 'RLE Lossless',
            }
            if ts_uid in compressed_formats:
                logger.info(f"[DICOM RENDER] Compressed DICOM detected: {compressed_formats[ts_uid]} ({ts_uid})")

        pixel_array = ds.pixel_array  # numpy array (pydicom + GDCM распакует автоматически)

        # Multi-frame обработка
        total_frames = 1
        if pixel_array.ndim == 3:
            total_frames = pixel_array.shape[0]
            if frame < 0 or frame >= total_frames:
                raise HTTPException(
                    status_code=400,
                    detail=f"Frame {frame} out of range (0-{total_frames-1})"
                )
            pixel_array = pixel_array[frame]
        elif frame > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Single-frame DICOM, frame parameter must be 0"
            )

        # Windowing
        if center is not None and width is not None and width > 0:
            # Применяем заданные WL/WW
            wc = float(center)
            ww = float(width)
            lower = wc - ww / 2
            upper = wc + ww / 2
            pixel_array = np.clip((pixel_array.astype(np.float32) - lower) / (upper - lower) * 255, 0, 255).astype(np.uint8)
        elif pixel_array.dtype != np.uint8:
            # Автоматическая нормализация (min-max)
            pmin = int(pixel_array.min())
            pmax = int(pixel_array.max())
            if pmax > pmin:
                pixel_array = ((pixel_array.astype(np.float32) - pmin) / (pmax - pmin) * 255).astype(np.uint8)
            else:
                pixel_array = np.zeros(pixel_array.shape, dtype=np.uint8)

        # Конвертируем в PNG
        img = Image.fromarray(pixel_array, mode='L')
        png_buffer = BytesIO()
        img.save(png_buffer, format='PNG', optimize=True)
        png_bytes = png_buffer.getvalue()

        # Кэшируем PNG в Redis (TTL = 1 час)
        try:
            from redis.asyncio import Redis
            r = Redis.from_url(settings.redis_url, decode_responses=False)
            await r.set(wl_key, png_bytes, ex=3600)
            await r.close()
        except Exception as e:
            logger.debug(f"[DICOM PNG Cache] Redis write error: {e}")

        logger.info(
            f"[DICOM RENDER] {data['original_name']} → {img.width}x{img.height} PNG, "
            f"frame={frame}/{total_frames-1}, "
            f"WL={int(center) if center else 'auto'}/WW={int(width) if width else 'auto'}"
        )

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Зависимость не установлена: {e}")
    except RuntimeError as e:
        # GDCM ошибки распаковки
        error_msg = str(e).lower()
        if 'gdcm' in error_msg or 'jpeg' in error_msg or 'codec' in error_msg:
            logger.error(f"[DICOM RENDER] GDCM decompression error: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Не удалось распаковать сжатый DICOM (JPEG2000/JPEG-LS/RLE). Установите pydicom[gdcm]. Ошибка: {e}"
            )
        raise HTTPException(status_code=500, detail=f"Ошибка рендера: {e}")
    except Exception as e:
        logger.error(f"[DICOM RENDER] Ошибка: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка рендера: {e}")

    return StreamingResponse(
        iter([png_bytes]),
        media_type="image/png",
        headers={
            "Content-Length": str(len(png_bytes)),
            "Access-Control-Allow-Origin": "*",
            "X-Cache": "MISS",
        }
    )


# ─────────────────────────────────────────────────────────────────────
# GET /api/dicom/metadata/{file_id} — DICOM теги как JSON
# ─────────────────────────────────────────────────────────────────────

@router.get("/metadata/{file_id}")
async def get_dicom_metadata(
    file_id: int,
    token: str = Query(...),
):
    """
    Возвращает DICOM-теги файла в формате JSON.
    Использует кэш Redis. Если нет — парсит через pydicom.
    """
    _require_dicom_viewer_enabled()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DicomViewToken).where(
                DicomViewToken.token == token,
                DicomViewToken.expires_at >= datetime.now(timezone.utc),
            )
        )
        vt = result.scalar_one_or_none()
        if not vt:
            raise HTTPException(status_code=401, detail="Недействительный токен")

        if vt.file_id != file_id:
            raise HTTPException(status_code=400, detail="file_id не совпадает")

        file_record = await db.get(File, file_id)
        if not file_record or file_record.mime_type != "application/dicom":
            raise HTTPException(status_code=404, detail="DICOM не найден")

        data = {
            "encrypted_path": file_record.encrypted_path,
            "original_name": file_record.original_name,
        }

    # Получить из кэша или распарсить
    meta = await _get_or_parse_metadata(file_id, data["encrypted_path"])

    audit_logger.log_operation(
        action="dicom.metadata_accessed",
        filename=data["original_name"],
        user="anon",
        reason="Запрошены DICOM-теги",
        success=True,
        metadata={"file_id": file_id},
    )

    return meta


# ─────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────

async def _decrypt_dicom_to_memory(encrypted_path: str) -> bytes:
    """Расшифровка age DICOM БЕЗ сохранения на диск."""
    from app.core import DECRYPTED_DIR

    tmp_enc = DECRYPTED_DIR / f"enc_dicom_{uuid.uuid4()}.age"
    tmp_dec = DECRYPTED_DIR / f"dec_dicom_{uuid.uuid4()}.dcm"

    try:
        await encrypted_storage.download(
            key=encrypted_path,
            destination_path=tmp_enc,
        )
        await crypto_manager.decrypt_file(
            encrypted_path=tmp_enc,
            private_key_path=PRIVATE_KEY_PATH,
            output_path=tmp_dec,
        )
        return tmp_dec.read_bytes()
    finally:
        for path in (tmp_enc, tmp_dec):
            try:
                if path.exists():
                    path.unlink()
            except Exception as e:
                logger.warning(f"[DICOM] Не удалось удалить {path}: {e}")
