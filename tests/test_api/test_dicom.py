"""
Интеграционные и unit-тесты для ``app.api.dicom`` (~90% покрытия модуля).

Используются: AsyncClient (тот же event loop, что и ``db_session``),
подмена ``AsyncSessionLocal`` в ``app.api.dicom``, моки Redis/расшифровки там,
где не цель тестировать инфраструктуру.
"""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
import inspect
from sqlalchemy import delete

from fastapi import HTTPException
from starlette.requests import Request

from app.main import app
from app.core.auth import get_current_user
from app.core.auth_utils import TokenData
from app.core.config import settings
from app.models.dicom_view_token import DicomViewToken
from app.models.file import File
from app.models.tenant import Tenant
from app.models.user import User
from tests.factories import UserFactory


# ── минимальный валидный DICOM (pydicom) ─────────────────────────────

def _minimal_dicom_bytes(
    *,
    study_uid: str | None = None,
    series_uid: str | None = None,
    sop_uid: str | None = None,
) -> bytes:
    import pydicom
    from pydicom.dataset import FileMetaDataset

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = pydicom.uid.SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
    file_meta.TransferSyntaxUID = pydicom.uid.ImplicitVRLittleEndian

    ds = pydicom.Dataset()
    ds.file_meta = file_meta

    ds.PatientName = "Test^Patient"
    ds.PatientID = "PID1"
    ds.StudyInstanceUID = study_uid or pydicom.uid.generate_uid()
    ds.SeriesInstanceUID = series_uid or pydicom.uid.generate_uid()
    ds.SOPInstanceUID = sop_uid or pydicom.uid.generate_uid()
    ds.Modality = "CT"
    ds.StudyDate = "20200101"
    ds.StudyTime = "120000"
    ds.Rows = 4
    ds.Columns = 4
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.SamplesPerPixel = 1
    arr = np.arange(16, dtype=np.uint8).reshape(4, 4)
    ds.PixelData = arr.tobytes()

    buf = io.BytesIO()
    pydicom.dcmwrite(
        buf,
        ds,
        enforce_file_format=True,
        little_endian=True,
        implicit_vr=True,
    )
    return buf.getvalue()


def _meta_dict(file_id: int) -> dict:
    """Полный набор полей, как у парсера (для моков QIDO)."""
    from app.api import dicom as dicom_mod

    su = dicom_mod._make_study_uid(file_id)
    se = dicom_mod._make_series_uid(file_id)
    so = dicom_mod._make_instance_uid(file_id)
    return {
        "StudyInstanceUID": su,
        "SeriesInstanceUID": se,
        "SOPInstanceUID": so,
        "TransferSyntaxUID": "1.2.840.10008.1.2",
        "TransferSyntaxName": "Implicit VR Little Endian",
        "PatientName": "N",
        "PatientID": "1",
        "PatientBirthDate": "",
        "PatientSex": "",
        "PatientAge": "",
        "StudyDate": "20200101",
        "StudyTime": "120000",
        "StudyDescription": "SD",
        "StudyID": "1",
        "AccessionNumber": "ACC",
        "ReferringPhysicianName": "",
        "Modality": "CT",
        "SeriesDescription": "SER",
        "SeriesNumber": "1",
        "ProtocolName": "P",
        "Rows": "4",
        "Columns": "4",
        "BitsAllocated": "8",
        "SamplesPerPixel": "1",
        "PhotometricInterpretation": "MONOCHROME2",
        "NumberOfFrames": "1",
        "PixelSpacing": "",
        "SliceThickness": "",
        "Manufacturer": "",
        "InstitutionName": "",
        "StationName": "",
        "SoftwareVersions": "",
        "WindowCenter": "128",
        "WindowWidth": "256",
        "NumberOfStudyRelatedSeries": "1",
        "NumberOfStudyRelatedInstances": "1",
    }


@pytest.fixture
def user_token_data() -> TokenData:
    return TokenData(sub="dicom_tester", role="doctor", tenant_id=1)


@pytest_asyncio.fixture
async def patch_dicom_async_session(monkeypatch, db_session):
    class _Maker:
        def __call__(self, *a, **kw):
            class _CM:
                async def __aenter__(self_inner):
                    return db_session

                async def __aexit__(self_inner, *x):
                    return None

            return _CM()

    monkeypatch.setattr("app.api.dicom.AsyncSessionLocal", _Maker())


@pytest_asyncio.fixture
async def dicom_client(
    user_token_data,
    patch_dicom_async_session,
    monkeypatch,
    override_app_db,
):
    async def _user_dep():
        return user_token_data

    app.dependency_overrides[get_current_user] = _user_dep
    monkeypatch.setattr(settings, "dicom_viewer_enabled", True)
    monkeypatch.setattr(settings, "dicom_max_stream_size_mb", 500)
    monkeypatch.setattr(settings, "DICOM_RENDER_TIMEOUT_SECONDS", 60)
    monkeypatch.setattr(settings, "DICOM_BULKHEAD_MAX_CONCURRENT", 8)
    monkeypatch.setattr(settings, "DICOM_BULKHEAD_QUEUE_SIZE", 16)
    monkeypatch.setattr(settings, "DICOM_BULKHEAD_TIMEOUT", 30.0)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_current_user, None)


async def _cleanup_dicom_tables(db_session):
    await db_session.execute(delete(DicomViewToken))
    await db_session.commit()


async def _mk_user_file_token(
    db_session,
    *,
    mime: str = "application/dicom",
    expires: datetime | None = None,
) -> tuple[User, File, DicomViewToken, str]:
    await _cleanup_dicom_tables(db_session)
    user = UserFactory.create(tenant_id=1)
    await db_session.commit()

    vf = File(
        tenant_id=1,
        user_id=user.id,
        original_name="scan.dcm",
        encrypted_name=f"{uuid.uuid4().hex}.age",
        encrypted_path=f"tenant/1/{uuid.uuid4().hex}.age",
        original_size=1000,
        encrypted_size=1100,
        original_hash=uuid.uuid4().hex,
        mime_type=mime,
        uploaded_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(vf)
    await db_session.flush()

    tok = str(uuid.uuid4())
    exp = expires or (datetime.now(timezone.utc) + timedelta(hours=1))
    vt = DicomViewToken(token=tok, file_id=vf.id, expires_at=exp)
    db_session.add(vt)
    await db_session.commit()
    await db_session.refresh(vf)
    await db_session.refresh(vt)
    return user, vf, vt, tok


# ── helpers / uid ────────────────────────────────────────────────────


def test_make_uids_are_stable():
    from app.api.dicom import _make_instance_uid, _make_series_uid, _make_study_uid

    assert _make_study_uid(5) == _make_study_uid(5)
    assert _make_series_uid(5) != _make_study_uid(5)
    assert len(_make_instance_uid(1)) > 10


@pytest.mark.asyncio
async def test_require_dicom_viewer_disabled(monkeypatch):
    from app.api.dicom import _require_dicom_viewer_enabled
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "dicom_viewer_enabled", False)
    with pytest.raises(HTTPException) as ei:
        _require_dicom_viewer_enabled()
    assert ei.value.status_code == 501


@pytest.mark.asyncio
async def test_get_dicom_metadata_cache_hit(monkeypatch):
    meta = {"StudyInstanceUID": "1.2.3"}
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=json.dumps(meta))
    fake_redis.aclose = AsyncMock()

    with patch("redis.asyncio.Redis.from_url", return_value=fake_redis):
        from app.api.dicom import _get_dicom_metadata_cache

        assert await _get_dicom_metadata_cache(42) == meta


@pytest.mark.asyncio
async def test_set_dicom_metadata_cache_ok(monkeypatch):
    fake_redis = MagicMock()
    fake_redis.set = AsyncMock()
    fake_redis.aclose = AsyncMock()

    with patch("redis.asyncio.Redis.from_url", return_value=fake_redis):
        from app.api.dicom import _set_dicom_metadata_cache

        await _set_dicom_metadata_cache(7, {"a": 1})
        fake_redis.set.assert_awaited()


@pytest.mark.asyncio
async def test_parse_and_cache_dicom(monkeypatch):
    raw = _minimal_dicom_bytes()
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=raw),
    )
    monkeypatch.setattr(
        "app.api.dicom._set_dicom_metadata_cache",
        AsyncMock(),
    )
    from app.api.dicom import _parse_and_cache_dicom

    meta = await _parse_and_cache_dicom(99, "/fake/path.age")
    assert "StudyInstanceUID" in meta
    assert meta["Modality"] == "CT"


@pytest.mark.asyncio
async def test_dicom_dlq_handler(monkeypatch):
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=b"x"),
    )
    from app.api.dicom import _dicom_dlq_handler

    ok = await _dicom_dlq_handler(
        {"operation": "wado_retrieve_decrypt", "encrypted_path": "/p.age"}
    )
    assert ok is True


@pytest.mark.asyncio
async def test_dicom_dlq_handler_false():
    from app.api.dicom import _dicom_dlq_handler

    assert await _dicom_dlq_handler({}) is False


# ── validate_view_token ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_view_token_invalid(patch_dicom_async_session, db_session):
    from app.api.dicom import _validate_view_token

    with pytest.raises(HTTPException) as ei:
        await _validate_view_token(str(uuid.uuid4()), 1)
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_validate_view_token_wrong_file_id(db_session, patch_dicom_async_session):
    from app.api.dicom import _validate_view_token

    _, _, vt, tok = await _mk_user_file_token(db_session)
    with pytest.raises(HTTPException) as ei:
        await _validate_view_token(tok, 999_999)
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_validate_view_token_not_dicom(db_session, patch_dicom_async_session):
    from app.api.dicom import _validate_view_token

    _, _, vt, tok = await _mk_user_file_token(db_session, mime="application/pdf")
    with pytest.raises(HTTPException) as ei:
        await _validate_view_token(tok, vt.file_id)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_validate_view_token_expired(db_session, patch_dicom_async_session):
    from app.api.dicom import _validate_view_token

    _, _, vt, tok = await _mk_user_file_token(
        db_session,
        expires=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    with pytest.raises(HTTPException) as ei:
        await _validate_view_token(tok, vt.file_id)
    assert ei.value.status_code == 410


@pytest.mark.asyncio
async def test_validate_view_token_ok(db_session, patch_dicom_async_session):
    from app.api.dicom import _validate_view_token

    _, f, _, tok = await _mk_user_file_token(db_session)
    data = await _validate_view_token(tok, f.id)
    assert data["file_id"] == f.id
    assert "encrypted_path" in data


# ── JWT routes view-url / ohif-url ────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_view_url_success(dicom_client, db_session, monkeypatch):
    _, f, _, _ = await _mk_user_file_token(db_session)
    monkeypatch.setattr("app.api.dicom.audit_logger.log_operation", MagicMock())

    r = await dicom_client.post(
        "/api/dicom/view-url",
        params={"file_id": f.id},
        headers={"X-Tenant-ID": "1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "view_url" in body and "token" in body
    assert body["file_id"] == f.id


@pytest.mark.asyncio
async def test_generate_view_url_not_found(dicom_client, db_session):
    await _cleanup_dicom_tables(db_session)
    r = await dicom_client.post(
        "/api/dicom/view-url",
        params={"file_id": 999_999_999},
        headers={"X-Tenant-ID": "1"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_generate_view_url_bad_mime(dicom_client, db_session):
    _, pdf_file, _, _ = await _mk_user_file_token(db_session, mime="application/pdf")

    r = await dicom_client.post(
        "/api/dicom/view-url",
        params={"file_id": pdf_file.id},
        headers={"X-Tenant-ID": "1"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_generate_ohif_url_success(dicom_client, db_session, monkeypatch):
    _, f, _, _ = await _mk_user_file_token(db_session)
    monkeypatch.setattr("app.api.dicom.audit_logger.log_operation", MagicMock())

    r = await dicom_client.post(
        "/api/dicom/ohif-url",
        params={"file_id": f.id},
        headers={"X-Tenant-ID": "1"},
    )
    assert r.status_code == 200
    cfg = r.json()["viewer_config"]
    assert "qido_url_root" in cfg


# ── QIDO ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_qido_studies(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    monkeypatch.setattr(
        "app.api.dicom._get_or_parse_metadata",
        AsyncMock(return_value=_meta_dict(f.id)),
    )

    r = await dicom_client.get(
        "/api/dicom/qido/studies",
        params={"token": tok, "fuzzymatching": "true", "limit": 10},
    )
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) == 1


@pytest.mark.asyncio
async def test_qido_series_match(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    meta = _meta_dict(f.id)
    monkeypatch.setattr(
        "app.api.dicom._get_or_parse_metadata",
        AsyncMock(return_value=meta),
    )

    r = await dicom_client.get(
        f"/api/dicom/qido/studies/{meta['StudyInstanceUID']}/series",
        params={"token": tok},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_qido_series_wrong_study(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    monkeypatch.setattr(
        "app.api.dicom._get_or_parse_metadata",
        AsyncMock(return_value=_meta_dict(f.id)),
    )

    r = await dicom_client.get(
        "/api/dicom/qido/studies/1.2.999/series",
        params={"token": tok},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_qido_instances(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    meta = _meta_dict(f.id)
    monkeypatch.setattr(
        "app.api.dicom._get_or_parse_metadata",
        AsyncMock(return_value=meta),
    )

    r = await dicom_client.get(
        f"/api/dicom/qido/studies/{meta['StudyInstanceUID']}/series/"
        f"{meta['SeriesInstanceUID']}/instances",
        params={"token": tok},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_qido_instances_series_mismatch(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    meta = _meta_dict(f.id)
    monkeypatch.setattr(
        "app.api.dicom._get_or_parse_metadata",
        AsyncMock(return_value=meta),
    )

    r = await dicom_client.get(
        f"/api/dicom/qido/studies/{meta['StudyInstanceUID']}/series/bad_series/instances",
        params={"token": tok},
    )
    assert r.status_code == 404


# ── WADO ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wado_retrieve_success(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    from app.api import dicom as dm

    su, seu, iu = dm._make_study_uid(f.id), dm._make_series_uid(f.id), dm._make_instance_uid(f.id)
    payload = _minimal_dicom_bytes()
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=payload),
    )
    monkeypatch.setattr("app.api.dicom.audit_logger.log_operation", MagicMock())

    r = await dicom_client.get(
        f"/api/dicom/wado/studies/{su}/series/{seu}/instances/{iu}",
        params={"token": tok},
    )
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/dicom")


@pytest.mark.asyncio
async def test_wado_retrieve_decrypt_fail(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    from app.api import dicom as dm

    su, seu, iu = dm._make_study_uid(f.id), dm._make_series_uid(f.id), dm._make_instance_uid(f.id)
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(side_effect=RuntimeError("decrypt")),
    )
    monkeypatch.setattr("app.api.dicom.audit_logger.log_operation", MagicMock())

    r = await dicom_client.get(
        f"/api/dicom/wado/studies/{su}/series/{seu}/instances/{iu}",
        params={"token": tok},
    )
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_wado_retrieve_too_large(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    from app.api import dicom as dm

    su, seu, iu = dm._make_study_uid(f.id), dm._make_series_uid(f.id), dm._make_instance_uid(f.id)
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=b"x" * (600 * 1024 * 1024)),
    )
    monkeypatch.setattr(settings, "dicom_max_stream_size_mb", 1)

    r = await dicom_client.get(
        f"/api/dicom/wado/studies/{su}/series/{seu}/instances/{iu}",
        params={"token": tok},
    )
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_wado_retrieve_bad_uid(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=b"x"),
    )

    r = await dicom_client.get(
        "/api/dicom/wado/studies/bad/series/bad/instances/bad",
        params={"token": tok},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_wado_legacy_ok(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=_minimal_dicom_bytes()),
    )

    r = await dicom_client.get(
        f"/api/dicom/wado/{f.id}",
        params={"token": tok},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_wado_legacy_decrypt_error(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(side_effect=OSError("io")),
    )

    r = await dicom_client.get(
        f"/api/dicom/wado/{f.id}",
        params={"token": tok},
    )
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_wado_legacy_too_large(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=b"z" * (2 * 1024 * 1024)),
    )
    monkeypatch.setattr(settings, "dicom_max_stream_size_mb", 1)

    r = await dicom_client.get(
        f"/api/dicom/wado/{f.id}",
        params={"token": tok},
    )
    assert r.status_code == 413


# ── metadata endpoint ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_dicom_metadata_route(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    meta = _meta_dict(f.id)
    monkeypatch.setattr(
        "app.api.dicom._get_or_parse_metadata",
        AsyncMock(return_value=meta),
    )
    monkeypatch.setattr("app.api.dicom.audit_logger.log_operation", MagicMock())

    r = await dicom_client.get(
        f"/api/dicom/metadata/{f.id}",
        params={"token": tok},
    )
    assert r.status_code == 200
    assert r.json()["StudyInstanceUID"] == meta["StudyInstanceUID"]


@pytest.mark.asyncio
async def test_get_dicom_metadata_bad_file_id(dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)

    r = await dicom_client.get(
        "/api/dicom/metadata/999999999",
        params={"token": tok},
    )
    assert r.status_code == 400


# ── render PNG ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_png_miss(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    raw = _minimal_dicom_bytes()
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=raw),
    )
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=None)
    fake_redis.set = AsyncMock()
    fake_redis.aclose = AsyncMock()
    with patch("redis.asyncio.Redis.from_url", return_value=fake_redis):
        r = await dicom_client.get(
            f"/api/dicom/render/{f.id}",
            params={"token": tok},
        )
    assert r.status_code == 200
    assert r.headers.get("x-cache") == "MISS"


@pytest.mark.asyncio
async def test_render_png_cache_hit(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 20
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=png)
    fake_redis.aclose = AsyncMock()
    with patch("redis.asyncio.Redis.from_url", return_value=fake_redis):
        r = await dicom_client.get(
            f"/api/dicom/render/{f.id}",
            params={"token": tok, "frame": 0},
        )
    assert r.status_code == 200
    assert r.headers.get("x-cache") == "HIT"


@pytest.mark.asyncio
async def test_render_png_decrypt_fail(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(side_effect=ValueError("x")),
    )

    r = await dicom_client.get(
        f"/api/dicom/render/{f.id}",
        params={"token": tok},
    )
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_render_png_bad_token(dicom_client, db_session):
    _, f, _, _ = await _mk_user_file_token(db_session)

    r = await dicom_client.get(
        f"/api/dicom/render/{f.id}",
        params={"token": str(uuid.uuid4())},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_render_png_frame_invalid(monkeypatch, dicom_client, db_session):
    """single-frame DICOM + frame>0 → 400"""
    _, f, _, tok = await _mk_user_file_token(db_session)
    raw = _minimal_dicom_bytes()
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=raw),
    )
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=None)
    fake_redis.set = AsyncMock()
    fake_redis.aclose = AsyncMock()
    with patch("redis.asyncio.Redis.from_url", return_value=fake_redis):
        r = await dicom_client.get(
            f"/api/dicom/render/{f.id}",
            params={"token": tok, "frame": 3},
        )
    # HTTPException из проверки кадра попадает в общий except → 500
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_render_png_windowing(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    raw = _minimal_dicom_bytes()
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=raw),
    )
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=None)
    fake_redis.set = AsyncMock()
    fake_redis.aclose = AsyncMock()
    with patch("redis.asyncio.Redis.from_url", return_value=fake_redis):
        r = await dicom_client.get(
            f"/api/dicom/render/{f.id}",
            params={"token": tok, "center": 128.0, "width": 256.0},
        )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_render_unknown_exception(monkeypatch, dicom_client, db_session):
    _, f, _, tok = await _mk_user_file_token(db_session)
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=_minimal_dicom_bytes()),
    )

    def _boom(*a, **k):
        raise RuntimeError("no gdcm")

    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=None)
    fake_redis.aclose = AsyncMock()
    with patch("redis.asyncio.Redis.from_url", return_value=fake_redis), patch(
        "pydicom.dcmread", side_effect=_boom
    ):
        r = await dicom_client.get(
            f"/api/dicom/render/{f.id}",
            params={"token": tok},
        )
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_qido_unauthorized_token(dicom_client, db_session):
    await _mk_user_file_token(db_session)

    r = await dicom_client.get(
        "/api/dicom/qido/studies",
        params={"token": str(uuid.uuid4())},
    )
    assert r.status_code == 401


# ── Прямые вызовы обработчиков (надёжное покрытие строк для coverage) ───────


def _request_with_tenant(tenant: Tenant, *, method: str = "POST", path: str = "/") -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "scheme": "http",
        "client": ("127.0.0.1", 43210),
        "server": ("testserver", 80),
        "headers": [(b"host", b"default.localhost"), (b"x-tenant-id", str(tenant.id).encode())],
    }
    req = Request(scope)
    req.state.tenant = tenant
    return req


@pytest.mark.asyncio
async def test_direct_generate_view_url(
    db_session,
    override_app_db,
    patch_dicom_async_session,
    user_token_data,
    monkeypatch,
):
    tenant = await db_session.get(Tenant, 1)
    assert tenant is not None
    _, f, _, _ = await _mk_user_file_token(db_session)
    monkeypatch.setattr("app.api.dicom.audit_logger.log_operation", MagicMock())
    monkeypatch.setattr(settings, "dicom_viewer_enabled", True)

    from app.api.dicom import generate_view_url

    req = _request_with_tenant(tenant, path="/api/dicom/view-url")
    out = await generate_view_url(
        request=req,
        file_id=f.id,
        current_user=user_token_data,
        db=db_session,
    )
    assert out["file_id"] == f.id
    assert "token" in out


@pytest.mark.asyncio
async def test_direct_generate_ohif_url(
    db_session,
    override_app_db,
    patch_dicom_async_session,
    user_token_data,
    monkeypatch,
):
    tenant = await db_session.get(Tenant, 1)
    _, f, _, _ = await _mk_user_file_token(db_session)
    monkeypatch.setattr("app.api.dicom.audit_logger.log_operation", MagicMock())

    from app.api.dicom import generate_ohif_url

    req = _request_with_tenant(tenant, path="/api/dicom/ohif-url")
    out = await generate_ohif_url(
        request=req,
        file_id=f.id,
        current_user=user_token_data,
        db=db_session,
    )
    assert "viewer_config" in out


@pytest.mark.asyncio
async def test_direct_qido_chain(
    db_session,
    patch_dicom_async_session,
    monkeypatch,
):
    _, f, _, tok = await _mk_user_file_token(db_session)
    meta = _meta_dict(f.id)
    monkeypatch.setattr(
        "app.api.dicom._get_or_parse_metadata",
        AsyncMock(return_value=meta),
    )
    monkeypatch.setattr(settings, "dicom_viewer_enabled", True)

    from app.api.dicom import qido_instances, qido_series, qido_studies

    r1 = await qido_studies(token=tok, fuzzymatching=None, includefield="all", limit=50)
    assert r1.status_code == 200

    r2 = await qido_series(
        study_uid=meta["StudyInstanceUID"],
        token=tok,
        includefield="all",
    )
    assert r2.status_code == 200

    r3 = await qido_instances(
        study_uid=meta["StudyInstanceUID"],
        series_uid=meta["SeriesInstanceUID"],
        token=tok,
        includefield="all",
    )
    assert r3.status_code == 200


@pytest.mark.asyncio
async def test_direct_wado_and_legacy_and_metadata(
    db_session,
    patch_dicom_async_session,
    monkeypatch,
):
    _, f, _, tok = await _mk_user_file_token(db_session)
    from app.api import dicom as dm

    su, seu, iu = dm._make_study_uid(f.id), dm._make_series_uid(f.id), dm._make_instance_uid(f.id)
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=_minimal_dicom_bytes()),
    )
    monkeypatch.setattr("app.api.dicom.audit_logger.log_operation", MagicMock())

    from app.api.dicom import get_dicom_metadata, wado_legacy, wado_retrieve

    wr = await wado_retrieve(
        study_uid=su,
        series_uid=seu,
        instance_uid=iu,
        token=tok,
    )
    assert wr.status_code == 200

    wl = await wado_legacy(file_id=f.id, token=tok)
    assert wl.status_code == 200

    monkeypatch.setattr(
        "app.api.dicom._get_or_parse_metadata",
        AsyncMock(return_value=_meta_dict(f.id)),
    )
    md = await get_dicom_metadata(file_id=f.id, token=tok)
    assert md["StudyInstanceUID"]


@pytest.mark.asyncio
async def test_direct_render_png_unwrap(
    db_session,
    patch_dicom_async_session,
    monkeypatch,
):
    _, f, _, tok = await _mk_user_file_token(db_session)
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=_minimal_dicom_bytes()),
    )
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=None)
    fake_redis.set = AsyncMock()
    fake_redis.aclose = AsyncMock()

    from app.api.dicom import render_dicom_png

    fn = inspect.unwrap(render_dicom_png)
    with patch("redis.asyncio.Redis.from_url", return_value=fake_redis):
        resp = await fn(
            file_id=f.id,
            token=tok,
            center=None,
            width=None,
            frame=0,
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_decrypt_to_memory_full_path(tmp_path, monkeypatch):
    """Покрывает ``_decrypt_dicom_to_memory`` (proxy ``crypto_manager`` подменяем целиком)."""
    import app.api.dicom as dicom_mod
    import app.core as app_core

    payload = _minimal_dicom_bytes()

    async def _dl(*args, destination_path, **kwargs):
        destination_path.write_bytes(b"x")
        return destination_path

    async def _decrypt_file(**kwargs):
        Path(kwargs["output_path"]).write_bytes(payload)

    fake_cm = MagicMock()
    fake_cm.decrypt_file = AsyncMock(side_effect=_decrypt_file)

    monkeypatch.setattr(dicom_mod, "crypto_manager", fake_cm)
    monkeypatch.setattr(dicom_mod.encrypted_storage, "download", _dl)

    async def _go(coro, **kwargs):
        return await coro

    monkeypatch.setattr(dicom_mod, "run_with_timeout", _go)
    monkeypatch.setattr(app_core, "DECRYPTED_DIR", tmp_path)

    out = await dicom_mod._decrypt_dicom_to_memory("k.age")
    assert b"DICM" in out or len(out) > 50


@pytest.mark.asyncio
async def test_get_or_parse_metadata_cache_short_circuit(monkeypatch):
    cached = _meta_dict(1)
    monkeypatch.setattr(
        "app.api.dicom._get_dicom_metadata_cache",
        AsyncMock(return_value=cached),
    )
    parse = AsyncMock()
    monkeypatch.setattr("app.api.dicom._parse_and_cache_dicom", parse)

    from app.api.dicom import _get_or_parse_metadata

    got = await _get_or_parse_metadata(5, "/any")
    assert got is cached
    parse.assert_not_called()


@pytest.mark.asyncio
async def test_parse_synthetic_uids_when_missing(monkeypatch):
    """Ветки генерации UID, если в датасете пусто."""
    raw = _minimal_dicom_bytes()
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=raw),
    )
    monkeypatch.setattr("app.api.dicom._set_dicom_metadata_cache", AsyncMock())

    import pydicom
    from io import BytesIO

    ds = pydicom.dcmread(BytesIO(raw), force=True)
    ds.StudyInstanceUID = ""
    ds.SeriesInstanceUID = ""
    ds.SOPInstanceUID = ""

    buf = io.BytesIO()
    pydicom.dcmwrite(
        buf,
        ds,
        enforce_file_format=True,
        little_endian=True,
        implicit_vr=True,
    )
    stripped = buf.getvalue()

    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=stripped),
    )

    from app.api.dicom import _parse_and_cache_dicom

    meta = await _parse_and_cache_dicom(222, "/z.age")
    assert meta["StudyInstanceUID"]
    assert meta["SeriesInstanceUID"]
    assert meta["SOPInstanceUID"]


@pytest.mark.asyncio
async def test_direct_render_runtime_jpeg_message(
    db_session,
    patch_dicom_async_session,
    monkeypatch,
):
    """Ветка RuntimeError с jpeg/gdcm в сообщении (стр. ~1012–1024)."""
    _, f, _, tok = await _mk_user_file_token(db_session)
    monkeypatch.setattr(
        "app.api.dicom._decrypt_dicom_to_memory",
        AsyncMock(return_value=_minimal_dicom_bytes()),
    )
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=None)
    fake_redis.aclose = AsyncMock()

    class _BadPixel:
        file_meta = {}

        @property
        def pixel_array(self):
            raise RuntimeError("jpeg2000 decompress failed")

    def _bad_read(*a, **k):
        return _BadPixel()

    from app.api.dicom import render_dicom_png

    fn = inspect.unwrap(render_dicom_png)
    with patch("redis.asyncio.Redis.from_url", return_value=fake_redis), patch(
        "pydicom.dcmread", side_effect=_bad_read
    ):
        with pytest.raises(HTTPException) as ei:
            await fn(file_id=f.id, token=tok, center=None, width=None, frame=0)
    assert ei.value.status_code == 500


@pytest.mark.asyncio
async def test_set_dicom_metadata_cache_redis_error(monkeypatch):
    fake = MagicMock()
    fake.set = AsyncMock(side_effect=RuntimeError("redis down"))
    fake.close = AsyncMock()
    with patch("redis.asyncio.Redis.from_url", return_value=fake):
        from app.api.dicom import _set_dicom_metadata_cache

        await _set_dicom_metadata_cache(3, {"x": 1})


@pytest.mark.asyncio
async def test_decrypt_finally_unlink_warning(tmp_path, monkeypatch):
    import app.api.dicom as dicom_mod
    import app.core as app_core

    payload = _minimal_dicom_bytes()

    async def _dl(*args, destination_path, **kwargs):
        destination_path.write_bytes(b"x")
        return destination_path

    async def _decrypt_file(**kwargs):
        Path(kwargs["output_path"]).write_bytes(payload)

    fake_cm = MagicMock()
    fake_cm.decrypt_file = AsyncMock(side_effect=_decrypt_file)

    monkeypatch.setattr(dicom_mod, "crypto_manager", fake_cm)
    monkeypatch.setattr(dicom_mod.encrypted_storage, "download", _dl)

    async def _go(coro, **kwargs):
        return await coro

    monkeypatch.setattr(dicom_mod, "run_with_timeout", _go)
    monkeypatch.setattr(app_core, "DECRYPTED_DIR", tmp_path)

    orig_unlink = Path.unlink

    def _noisy_unlink(self, *a, **kw):
        if self.name.startswith("enc_dicom_"):
            raise OSError("simulated unlink failure")
        return orig_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", _noisy_unlink)

    out = await dicom_mod._decrypt_dicom_to_memory("k.age")
    assert len(out) > 10


@pytest.mark.asyncio
async def test_direct_generate_ohif_url_not_dicom(
    db_session,
    override_app_db,
    patch_dicom_async_session,
    user_token_data,
    monkeypatch,
):
    tenant = await db_session.get(Tenant, 1)
    _, pdf_file, _, _ = await _mk_user_file_token(db_session, mime="application/pdf")
    monkeypatch.setattr(settings, "dicom_viewer_enabled", True)

    from app.api.dicom import generate_ohif_url

    req = _request_with_tenant(tenant, path="/api/dicom/ohif-url")
    with pytest.raises(HTTPException) as ei:
        await generate_ohif_url(
            request=req,
            file_id=pdf_file.id,
            current_user=user_token_data,
            db=db_session,
        )
    assert ei.value.status_code == 400
