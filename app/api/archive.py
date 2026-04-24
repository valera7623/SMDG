from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.core.auth import get_current_admin
from app.core.auth_utils import TokenData
from app.core.database import AsyncSessionLocal
from app.models.archive import ArchiveRecord, ArchiveRestoreRequest
from app.services.archive_service import archive_service

router = APIRouter(prefix="/api/archive", tags=["Archive"])


@router.get("/stats")
async def get_archive_stats(_admin: TokenData = Depends(get_current_admin)):
    return await archive_service.get_archive_stats()


@router.get("/records")
async def list_archive_records(
    source_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _admin: TokenData = Depends(get_current_admin),
):
    async with AsyncSessionLocal() as session:
        base_query = select(ArchiveRecord)
        count_query = select(func.count(ArchiveRecord.id))

        if source_type:
            base_query = base_query.where(ArchiveRecord.source_type == source_type)
            count_query = count_query.where(ArchiveRecord.source_type == source_type)

        base_query = base_query.order_by(ArchiveRecord.archived_at.desc()).offset(offset).limit(limit)

        total = int((await session.execute(count_query)).scalar_one())
        result = await session.execute(base_query)
        records = result.scalars().all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "records": [
            {
                "archive_id": item.archive_id,
                "source_type": item.source_type,
                "source_id": item.source_id,
                "archive_size_bytes": item.archive_size_bytes,
                "storage_tier": item.storage_tier,
                "retention_until": item.retention_until.isoformat(),
                "status": item.status,
                "archived_at": item.archived_at.isoformat(),
            }
            for item in records
        ],
    }


@router.post("/restore/{archive_id}")
async def restore_from_archive(
    archive_id: str,
    reason: str = Query(..., min_length=3, max_length=512),
    current_admin: TokenData = Depends(get_current_admin),
):
    try:
        request_id = await archive_service.restore_from_archive(
            archive_id=archive_id,
            user_id=current_admin.sub,
            reason=reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"request_id": request_id, "status": "pending"}


@router.get("/restore-requests")
async def list_restore_requests(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    _admin: TokenData = Depends(get_current_admin),
):
    async with AsyncSessionLocal() as session:
        query = select(ArchiveRestoreRequest)
        if status:
            query = query.where(ArchiveRestoreRequest.status == status)
        query = query.order_by(ArchiveRestoreRequest.created_at.desc()).limit(limit)

        result = await session.execute(query)
        requests = result.scalars().all()

    return {
        "requests": [
            {
                "request_id": req.request_id,
                "archive_id": req.archive_id,
                "requested_by": req.requested_by,
                "status": req.status,
                "created_at": req.created_at.isoformat(),
                "completed_at": req.completed_at.isoformat() if req.completed_at else None,
                "error_message": req.error_message,
            }
            for req in requests
        ]
    }
