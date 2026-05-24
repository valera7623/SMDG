"""
Demo seeder — creates demo users, sample file records, and audit log entries.

Called at application startup (lifespan.py) when DEMO_MODE=true and
repeated every DEMO_RESET_INTERVAL_HOURS hours to reset user-generated data.

Design principles:
- Idempotent: safe to call multiple times (skips if demo users already exist).
- Lightweight: no actual file encryption during seeding; records point to
  real encrypted_path entries that are created via the normal upload flow
  on first actual demo use. Sample file bytes are pre-staged so the DICOM
  viewer can demonstrate playback immediately.
- Isolated: only touches rows tagged with `username IN (demo users)` or
  created_by IS NULL (synthetic audit rows).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.file import File
from app.models.file_link import FileLink
from app.models.tenant import Tenant
from app.models.user import User

logger = logging.getLogger(__name__)

# ── Demo user definitions ──────────────────────────────────────────────────────
DEMO_USERS = [
    {
        "username": "admin_demo",
        "email": "admin@smdg-demo.example",
        "password": "Demo1234!",
        "role": "admin",
    },
    {
        "username": "doctor_demo",
        "email": "doctor@smdg-demo.example",
        "password": "Demo1234!",
        "role": "doctor",
    },
    {
        "username": "user_demo",
        "email": "patient@smdg-demo.example",
        "password": "Demo1234!",
        "role": "user",
    },
]

DEMO_USERNAMES = {u["username"] for u in DEMO_USERS}

# ── Synthetic audit events (English, HIPAA-style language) ─────────────────────
_AUDIT_TEMPLATES = [
    ("file_uploaded",    "MRI_Brain_Scan_20240115.dcm",    "doctor_demo"),
    ("file_uploaded",    "CT_Chest_Report_Q1.pdf",         "doctor_demo"),
    ("file_uploaded",    "Lab_Results_CBC_Panel.pdf",      "doctor_demo"),
    ("file_downloaded",  "MRI_Brain_Scan_20240115.dcm",    "admin_demo"),
    ("file_viewed",      "CT_Chest_Report_Q1.pdf",         "user_demo"),
    ("link_created",     "Lab_Results_CBC_Panel.pdf",      "doctor_demo"),
    ("file_uploaded",    "XRay_LungScreening_2024.dcm",    "doctor_demo"),
    ("file_downloaded",  "XRay_LungScreening_2024.dcm",    "user_demo"),
    ("login_success",    None,                              "admin_demo"),
    ("login_success",    None,                              "doctor_demo"),
    ("login_success",    None,                              "user_demo"),
    ("file_uploaded",    "Pathology_Report_Biopsy.pdf",    "doctor_demo"),
    ("file_viewed",      "MRI_Brain_Scan_20240115.dcm",    "user_demo"),
    ("user_created",     None,                              "admin_demo"),
    ("audit_export",     None,                              "admin_demo"),
]

# Timestamp of last seed (UTC); used by /api/demo/info for next-reset estimate.
_LAST_SEED_TIME: float = 0.0


def get_last_seed_time() -> float:
    return _LAST_SEED_TIME


# ── Helpers ────────────────────────────────────────────────────────────────────

def _audit_log_dir() -> Path:
    return Path(settings.audit_logs_dir)


def _write_audit_events() -> None:
    """Write synthetic audit log JSON entries for the last 3 days."""
    log_dir = _audit_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    base_offsets = [
        timedelta(days=-2, hours=9),
        timedelta(days=-2, hours=14),
        timedelta(days=-1, hours=8),
        timedelta(days=-1, hours=11),
        timedelta(days=-1, hours=16),
        timedelta(hours=-5),
        timedelta(hours=-4),
        timedelta(hours=-3),
        timedelta(hours=-2, minutes=-30),
        timedelta(hours=-2),
        timedelta(hours=-1, minutes=-45),
        timedelta(hours=-1, minutes=-30),
        timedelta(hours=-1),
        timedelta(minutes=-45),
        timedelta(minutes=-20),
    ]

    entries_by_day: dict[str, list[dict]] = {}
    for i, (action, filename, user) in enumerate(_AUDIT_TEMPLATES):
        offset = base_offsets[i % len(base_offsets)]
        ts = now + offset
        day_key = ts.strftime("%Y-%m-%d")
        entry = {
            "timestamp": ts.isoformat(),
            "action": action,
            "filename": filename,
            "user": user,
            "ip": f"10.0.0.{(i % 5) + 1}",
            "reason": "",
            "success": True,
            "metadata": {
                "size": (i + 1) * 102400 if filename else 0,
                "demo": True,
            },
        }
        entries_by_day.setdefault(day_key, []).append(entry)

    for day_str, entries in entries_by_day.items():
        log_file = log_dir / f"audit_{day_str}.log"
        # Append only if no demo marker already present
        existing_content = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
        if '"demo": true' not in existing_content:
            with open(log_file, "a", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.info("Demo audit events written to %s", log_dir)


def _stage_dicom_file() -> Path | None:
    """Copy CT_small.dcm from test_data into encrypted/ as a demo file.

    Returns the staged path or None if source not found.
    """
    source = Path("test_data") / "CT_small.dcm"
    if not source.exists():
        logger.warning("Demo seeder: test_data/CT_small.dcm not found — skipping DICOM staging")
        return None

    encrypted_dir = Path("encrypted")
    encrypted_dir.mkdir(parents=True, exist_ok=True)

    dest_name = "demo_CT_brain_scan.dcm.demo"
    dest = encrypted_dir / dest_name
    if not dest.exists():
        shutil.copy2(source, dest)
        logger.info("Demo DICOM file staged: %s", dest)
    return dest


async def _ensure_tenant(db: AsyncSession) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.subdomain == "default"))
    tenant = result.scalar_one_or_none()
    if not tenant:
        tenant = Tenant(name="SMDG Demo", subdomain="default", settings={})
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)
    return tenant


async def _ensure_demo_users(db: AsyncSession, tenant_id: int) -> dict[str, User]:
    users: dict[str, User] = {}
    for spec in DEMO_USERS:
        result = await db.execute(
            select(User).where(User.username == spec["username"])
        )
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                username=spec["username"],
                email=spec["email"],
                hashed_password=get_password_hash(spec["password"]),
                role=spec["role"],
                is_active=True,
                tenant_id=tenant_id,
            )
            db.add(user)
            logger.info("Demo user created: %s (%s)", spec["username"], spec["role"])
        else:
            # Ensure password is up to date (allows future password changes)
            user.hashed_password = get_password_hash(spec["password"])
            user.is_active = True
            user.otp_secret = None  # demo logins must not require 2FA
        users[spec["username"]] = user

    await db.commit()
    for spec in DEMO_USERS:
        await db.refresh(users[spec["username"]])
    return users


async def _ensure_demo_files(
    db: AsyncSession, users: dict[str, User], tenant_id: int
) -> list[File]:
    """Create sample File records for demo.  Does not re-create if already present."""
    doctor = users["doctor_demo"]

    # Check if demo files already exist
    result = await db.execute(
        select(File).where(File.patient_id == "demo-patient-001")
    )
    existing = result.scalars().all()
    if existing:
        return list(existing)

    now = datetime.now(timezone.utc)
    dicom_path = _stage_dicom_file()

    sample_files = [
        {
            "original_name": "CT_Brain_Scan_Demo.dcm",
            "encrypted_name": dicom_path.name if dicom_path else "demo_CT_brain_scan.dcm.demo",
            "encrypted_path": str(dicom_path) if dicom_path else "encrypted/demo_CT_brain_scan.dcm.demo",
            "original_size": 98304,
            "encrypted_size": 99328,
            "mime_type": "application/dicom",
            "patient_id": "demo-patient-001",
            "medical_metadata": {
                "modality": "CT",
                "study_description": "Brain CT without contrast",
                "institution": "SMDG Demo Hospital",
                "demo": True,
            },
            "expires_at": now + timedelta(days=30),
        },
        {
            "original_name": "Lab_Results_CBC_Panel.pdf",
            "encrypted_name": "demo_lab_results_cbc.pdf.age",
            "encrypted_path": "encrypted/demo_lab_results_cbc.pdf.age",
            "original_size": 45056,
            "encrypted_size": 46080,
            "mime_type": "application/pdf",
            "patient_id": "demo-patient-001",
            "medical_metadata": {
                "document_type": "Laboratory Results",
                "test": "Complete Blood Count (CBC)",
                "demo": True,
            },
            "expires_at": now + timedelta(days=30),
        },
        {
            "original_name": "Radiology_Report_Chest_XRay.pdf",
            "encrypted_name": "demo_radiology_report.pdf.age",
            "encrypted_path": "encrypted/demo_radiology_report.pdf.age",
            "original_size": 32768,
            "encrypted_size": 33792,
            "mime_type": "application/pdf",
            "patient_id": "demo-patient-002",
            "medical_metadata": {
                "document_type": "Radiology Report",
                "study": "Chest X-Ray PA and Lateral",
                "demo": True,
            },
            "expires_at": now + timedelta(days=14),
        },
    ]

    created: list[File] = []
    for spec in sample_files:
        file_obj = File(
            tenant_id=tenant_id,
            user_id=doctor.id,
            original_name=spec["original_name"],
            encrypted_name=spec["encrypted_name"],
            encrypted_path=spec["encrypted_path"],
            original_size=spec["original_size"],
            encrypted_size=spec["encrypted_size"],
            original_hash=hashlib.sha256(spec["original_name"].encode()).hexdigest(),
            mime_type=spec["mime_type"],
            patient_id=spec["patient_id"],
            medical_metadata=spec["medical_metadata"],
            expires_at=spec["expires_at"],
        )
        db.add(file_obj)
        created.append(file_obj)

    await db.commit()
    for f in created:
        await db.refresh(f)

    logger.info("Demo file records created: %d", len(created))
    return created


async def _ensure_shared_links(
    db: AsyncSession, files: list[File]
) -> None:
    """Create one active shared link on the first demo file (CT scan)."""
    if not files:
        return

    ct_file = files[0]
    result = await db.execute(
        select(FileLink).where(FileLink.file_id == ct_file.id)
    )
    if result.scalar_one_or_none():
        return

    link = FileLink(
        token=str(uuid.uuid4()),
        file_id=ct_file.id,
        max_downloads=100,
        downloads_count=0,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(link)
    await db.commit()
    logger.info("Demo shared link created for file_id=%d", ct_file.id)


# ── Public interface ───────────────────────────────────────────────────────────

async def seed_demo_data() -> None:
    """Idempotent seed: creates demo users, files, links and audit events.

    Safe to call multiple times — skips already-created entities.
    """
    global _LAST_SEED_TIME
    logger.info("Demo seeder: starting seed...")

    async with AsyncSessionLocal() as db:
        tenant = await _ensure_tenant(db)
        users = await _ensure_demo_users(db, tenant.id)
        files = await _ensure_demo_files(db, users, tenant.id)
        await _ensure_shared_links(db, files)

    _write_audit_events()
    _LAST_SEED_TIME = time.time()
    logger.info("Demo seeder: seed complete (tenant_id=%d, users=%d, files=%d)",
                tenant.id, len(users), len(files))


async def reset_demo_data() -> None:
    """Delete all non-demo data and uploaded files created by demo users.

    Keeps the three demo users intact; removes files, links and user-uploaded
    data so the next seed_demo_data() call starts from a clean state.
    """
    logger.info("Demo reset: cleaning user-generated data...")

    async with AsyncSessionLocal() as db:
        # Delete file links for files owned by demo users
        demo_user_ids_result = await db.execute(
            select(User.id).where(User.username.in_(DEMO_USERNAMES))
        )
        demo_ids = [row[0] for row in demo_user_ids_result.all()]

        if demo_ids:
            file_ids_result = await db.execute(
                select(File.id).where(File.user_id.in_(demo_ids))
            )
            file_ids = [row[0] for row in file_ids_result.all()]

            if file_ids:
                await db.execute(
                    delete(FileLink).where(FileLink.file_id.in_(file_ids))
                )
                await db.execute(
                    delete(File).where(File.id.in_(file_ids))
                )

            # Reset demo accounts: no 2FA, known passwords (re-applied on next seed)
            await db.execute(
                update(User)
                .where(User.id.in_(demo_ids))
                .values(otp_secret=None)
            )

        # Delete non-demo users (users registered during the demo session)
        await db.execute(
            delete(User).where(
                User.username.not_in(DEMO_USERNAMES | {"admin"})
            )
        )

        await db.commit()

    # Remove demo-staged encrypted files from previous session (they'll be re-staged)
    encrypted_dir = Path("encrypted")
    for f in encrypted_dir.glob("demo_*") if encrypted_dir.exists() else []:
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass

    # Remove old demo audit lines — clear only the demo marker lines
    _clear_demo_audit_events()

    logger.info("Demo reset: complete")


def _clear_demo_audit_events() -> None:
    """Remove lines with 'demo': true from audit JSON logs."""
    log_dir = _audit_log_dir()
    if not log_dir.exists():
        return

    for log_file in log_dir.glob("audit_*.log"):
        try:
            lines = log_file.read_text(encoding="utf-8").splitlines()
            kept = [ln for ln in lines if '"demo": true' not in ln]
            if len(kept) != len(lines):
                log_file.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        except OSError:
            pass
