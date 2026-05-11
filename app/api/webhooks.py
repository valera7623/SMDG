# app/api/webhooks.py
"""
Webhook Management API endpoints.

CRUD для управления webhook-подписками и просмотр истории доставки.
"""
import ipaddress
import socket
from typing import List, Optional, Any, Dict
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel, Field, HttpUrl, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select
from datetime import datetime, timezone

from app.core.auth import get_current_user, TokenData
from app.core.database import get_db
from app.core import audit_logger
from app.core.config import settings
from app.core.tenant import require_tenant, assert_tenant_access
from app.models.user import User
from app.models.webhook import WebhookSubscription, WebhookDelivery, WebhookEvent, DeliveryStatus
from app.core.webhook import webhook_dispatcher, WebhookPayload, sign_payload
from app.core.rate_limiter import limiter

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

_BLOCKED_WEBHOOK_HEADERS = {
    "connection",
    "content-length",
    "host",
    "transfer-encoding",
}


def _validate_webhook_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL должен начинаться с http:// или https://")
    if not parsed.hostname:
        raise ValueError("URL должен содержать hostname")
    if not settings.dev_mode and parsed.scheme != "https":
        raise ValueError("В production webhook URL должен использовать HTTPS")

    host = parsed.hostname.strip().lower()
    if not settings.dev_mode and (host == "localhost" or host.endswith(".local")):
        raise ValueError("Webhook URL не должен указывать на локальный hostname")

    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None

    addresses = set()
    if literal_ip is not None:
        addresses.add(literal_ip)
    elif not settings.dev_mode:
        try:
            for family, _, _, _, sockaddr in socket.getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            ):
                if family in {socket.AF_INET, socket.AF_INET6}:
                    addresses.add(ipaddress.ip_address(sockaddr[0]))
        except socket.gaierror as exc:
            raise ValueError("Webhook hostname не резолвится") from exc

    if not settings.dev_mode:
        for addr in addresses:
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_multicast
                or addr.is_reserved
                or addr.is_unspecified
            ):
                raise ValueError("Webhook URL не должен указывать на private/internal IP")

    return value


def _validate_webhook_headers(value: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    if value is None:
        return value
    if len(value) > 20:
        raise ValueError("Слишком много дополнительных заголовков")
    for key, header_value in value.items():
        normalized = key.strip().lower()
        if normalized in _BLOCKED_WEBHOOK_HEADERS:
            raise ValueError(f"Заголовок {key!r} запрещён")
        if len(key) > 80 or len(str(header_value)) > 500:
            raise ValueError("Дополнительный заголовок слишком длинный")
    return value


# ==================== Pydantic Models ====================

class WebhookSubscriptionCreate(BaseModel):
    url: str = Field(..., min_length=10, max_length=512, description="URL для отправки уведомлений")
    events: List[str] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Список событий (file.uploaded, file.deleted, и т.д.)"
    )
    secret: Optional[str] = Field(None, max_length=255, description="Секрет для HMAC подписи")
    description: Optional[str] = Field(None, max_length=255)
    headers: Optional[Dict[str, str]] = Field(None, description="Дополнительные HTTP заголовки")
    max_retries: int = Field(3, ge=0, le=10, description="Максимум попыток отправки")
    timeout_seconds: int = Field(10, ge=1, le=60, description="Таймаут запроса в секундах")

    @field_validator('events')
    @classmethod
    def validate_events(cls, v: List[str]) -> List[str]:
        valid_events = {e.value for e in WebhookEvent}
        for event in v:
            if event not in valid_events:
                raise ValueError(
                    f"Недопустимое событие: {event}. "
                    f"Допустимые: {', '.join(sorted(valid_events))}"
                )
        return v

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        return _validate_webhook_url(v)

    @field_validator('headers')
    @classmethod
    def validate_headers(cls, v: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        return _validate_webhook_headers(v)


class WebhookSubscriptionUpdate(BaseModel):
    url: Optional[str] = Field(None, min_length=10, max_length=512)
    events: Optional[List[str]] = None
    secret: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None
    headers: Optional[Dict[str, str]] = None
    max_retries: Optional[int] = Field(None, ge=0, le=10)
    timeout_seconds: Optional[int] = Field(None, ge=1, le=60)

    @field_validator('events')
    @classmethod
    def validate_events(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        valid_events = {e.value for e in WebhookEvent}
        for event in v:
            if event not in valid_events:
                raise ValueError(
                    f"Недопустимое событие: {event}. "
                    f"Допустимые: {', '.join(sorted(valid_events))}"
                )
        return v

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _validate_webhook_url(v)

    @field_validator('headers')
    @classmethod
    def validate_headers(cls, v: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        return _validate_webhook_headers(v)


class WebhookSubscriptionResponse(BaseModel):
    id: int
    url: str
    events: List[str]
    secret: Optional[str] = None
    description: Optional[str] = None
    is_active: bool
    headers: Optional[Dict[str, Any]] = None
    max_retries: int
    timeout_seconds: int
    created_at: str
    updated_at: Optional[str] = None
    last_triggered_at: Optional[str] = None

    model_config = {"from_attributes": True}


class WebhookDeliveryResponse(BaseModel):
    id: int
    subscription_id: int
    event: str
    status: str
    attempts: int
    max_attempts: int
    response_status: Optional[int] = None
    error_message: Optional[str] = None
    created_at: str
    delivered_at: Optional[str] = None
    next_retry_at: Optional[str] = None

    model_config = {"from_attributes": True}


class WebhookListResponse(BaseModel):
    count: int
    subscriptions: List[WebhookSubscriptionResponse]


class WebhookDeliveryListResponse(BaseModel):
    count: int
    deliveries: List[WebhookDeliveryResponse]


class WebhookPingResponse(BaseModel):
    success: bool
    message: str
    response_status: Optional[int] = None
    response_body: Optional[str] = None


# ==================== Helper ====================

def _serialize_subscription(sub: WebhookSubscription) -> WebhookSubscriptionResponse:
    """Сериализация подписки в response."""
    import json
    headers = None
    if sub.headers:
        try:
            headers = json.loads(sub.headers)
        except json.JSONDecodeError:
            pass

    return WebhookSubscriptionResponse(
        id=sub.id,
        url=sub.url,
        events=sub.events or [],
        secret=sub.secret[:8] + "..." if sub.secret else None,  # маскируем секрет
        description=sub.description,
        is_active=sub.is_active,
        headers=headers,
        max_retries=sub.max_retries,
        timeout_seconds=sub.timeout_seconds,
        created_at=sub.created_at.isoformat() if sub.created_at else None,
        updated_at=sub.updated_at.isoformat() if sub.updated_at else None,
        last_triggered_at=sub.last_triggered_at.isoformat() if sub.last_triggered_at else None,
    )


def _serialize_delivery(delivery: WebhookDelivery) -> WebhookDeliveryResponse:
    """Сериализация доставки в response."""
    return WebhookDeliveryResponse(
        id=delivery.id,
        subscription_id=delivery.subscription_id,
        event=delivery.event,
        status=delivery.status,
        attempts=delivery.attempts,
        max_attempts=delivery.max_attempts,
        response_status=delivery.response_status,
        error_message=delivery.error_message,
        created_at=delivery.created_at.isoformat() if delivery.created_at else None,
        delivered_at=delivery.delivered_at.isoformat() if delivery.delivered_at else None,
        next_retry_at=delivery.next_retry_at.isoformat() if delivery.next_retry_at else None,
    )


async def _resolve_scoped_user_id(db: AsyncSession, current_user: TokenData, tenant_id: int) -> int | None:
    result = await db.execute(
        select(User.id).where(User.username == current_user.sub, User.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


def _apply_scope_filter(stmt, current_user: TokenData, tenant_id: int, scoped_user_id: int | None):
    """Применяет фильтр видимости webhook-подписок по роли текущего пользователя.

    - super_admin видит всё;
    - admin/doctor — все подписки своего тенанта;
    - остальные — только свои подписки.
    """
    if current_user.role == "super_admin":
        return stmt
    if current_user.role in ("admin", "doctor"):
        return stmt.outerjoin(User, User.id == WebhookSubscription.user_id).where(
            or_(
                WebhookSubscription.tenant_id == tenant_id,
                User.tenant_id == tenant_id,
            )
        )
    return stmt.where(
        WebhookSubscription.tenant_id == tenant_id,
        WebhookSubscription.user_id == scoped_user_id,
    )


async def _get_scoped_subscription(
    db: AsyncSession,
    subscription_id: int,
    current_user: TokenData,
    tenant,
) -> WebhookSubscription:
    """Загрузить webhook-подписку с учётом роли пользователя и тенанта.

    Бросает HTTPException(404), если подписка не найдена или недоступна.
    """
    scoped_user_id = await _resolve_scoped_user_id(db, current_user, tenant.id)
    stmt = select(WebhookSubscription).where(WebhookSubscription.id == subscription_id)
    stmt = _apply_scope_filter(stmt, current_user, tenant.id, scoped_user_id)
    subscription = (await db.execute(stmt)).scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=404, detail="Webhook-подписка не найдена")
    return subscription


# ==================== CRUD Endpoints ====================

@router.post("", response_model=WebhookSubscriptionResponse, status_code=201)
@limiter.limit("10/minute")
async def create_webhook_subscription(
    request: Request,
    data: WebhookSubscriptionCreate,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Создать новую webhook-подписку."""
    import json

    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
    user_id = await _resolve_scoped_user_id(db, current_user, tenant.id)
    subscription = WebhookSubscription(
        tenant_id=tenant.id,
        user_id=user_id,
        url=data.url,
        events=data.events,
        secret=data.secret,
        description=data.description,
        headers=json.dumps(data.headers) if data.headers else None,
        max_retries=data.max_retries,
        timeout_seconds=data.timeout_seconds,
    )

    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)

    audit_logger.log_operation(
        action="webhook_created",
        filename="",
        user=current_user.sub,
        reason=f"Создана webhook-подписка: {data.url}",
        success=True,
        metadata={"url": data.url, "events": data.events}
    )

    return _serialize_subscription(subscription)


@router.get("", response_model=WebhookListResponse)
@limiter.limit("30/minute")
async def list_webhook_subscriptions(
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Получить список всех webhook-подписок."""
    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
    scoped_user_id = await _resolve_scoped_user_id(db, current_user, tenant.id)
    stmt = select(WebhookSubscription).order_by(WebhookSubscription.created_at.desc())
    stmt = _apply_scope_filter(stmt, current_user, tenant.id, scoped_user_id)

    result = await db.execute(stmt)
    subscriptions = result.scalars().all()

    return WebhookListResponse(
        count=len(subscriptions),
        subscriptions=[_serialize_subscription(s) for s in subscriptions]
    )


@router.get("/{subscription_id}", response_model=WebhookSubscriptionResponse)
@limiter.limit("30/minute")
async def get_webhook_subscription(
    subscription_id: int,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Получить информацию о конкретной webhook-подписке."""
    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
    subscription = await _get_scoped_subscription(db, subscription_id, current_user, tenant)
    return _serialize_subscription(subscription)


@router.put("/{subscription_id}", response_model=WebhookSubscriptionResponse)
@limiter.limit("10/minute")
async def update_webhook_subscription(
    subscription_id: int,
    request: Request,
    data: WebhookSubscriptionUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Обновить webhook-подписку."""
    import json

    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
    subscription = await _get_scoped_subscription(db, subscription_id, current_user, tenant)

    # Обновляем только переданные поля
    update_data = data.model_dump(exclude_unset=True)
    if "headers" in update_data and update_data["headers"] is not None:
        update_data["headers"] = json.dumps(update_data["headers"])

    for key, value in update_data.items():
        setattr(subscription, key, value)

    await db.commit()
    await db.refresh(subscription)

    audit_logger.log_operation(
        action="webhook_updated",
        filename="",
        user=current_user.sub,
        reason=f"Обновлена webhook-подписка: {subscription.url}",
        success=True,
        metadata={"id": subscription_id, "fields": list(update_data.keys())}
    )

    return _serialize_subscription(subscription)


@router.delete("/{subscription_id}", status_code=204)
@limiter.limit("10/minute")
async def delete_webhook_subscription(
    subscription_id: int,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Удалить webhook-подписку."""
    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
    subscription = await _get_scoped_subscription(db, subscription_id, current_user, tenant)

    await db.delete(subscription)
    await db.commit()

    audit_logger.log_operation(
        action="webhook_deleted",
        filename="",
        user=current_user.sub,
        reason=f"Удалена webhook-подписка: {subscription.url}",
        success=True,
        metadata={"id": subscription_id}
    )

    return None


# ==================== Delivery History ====================

@router.get("/{subscription_id}/deliveries", response_model=WebhookDeliveryListResponse)
@limiter.limit("30/minute")
async def list_webhook_deliveries(
    subscription_id: int,
    request: Request,
    status: Optional[str] = Query(None, description="Фильтр по статусу (success, failed, pending)"),
    limit: int = Query(50, ge=1, le=200, description="Максимум записей"),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Получить историю доставки для webhook-подписки."""
    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
    await _get_scoped_subscription(db, subscription_id, current_user, tenant)

    # Получаем доставки
    delivery_stmt = (
        select(WebhookDelivery)
        .where(WebhookDelivery.subscription_id == subscription_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
    )

    if status:
        delivery_stmt = delivery_stmt.where(WebhookDelivery.status == status)

    delivery_result = await db.execute(delivery_stmt)
    deliveries = delivery_result.scalars().all()

    return WebhookDeliveryListResponse(
        count=len(deliveries),
        deliveries=[_serialize_delivery(d) for d in deliveries]
    )


# ==================== Test Webhook ====================

@router.post("/{subscription_id}/ping", response_model=WebhookPingResponse)
@limiter.limit("5/minute")
async def ping_webhook(
    subscription_id: int,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Тестировать webhook-подписку — отправить тестовый запрос.

    Полезный для проверки работоспособности endpoint'а.
    """
    import json
    import aiohttp

    tenant = require_tenant(request)
    assert_tenant_access(current_user.tenant_id, tenant.id, current_user.role)
    subscription = await _get_scoped_subscription(db, subscription_id, current_user, tenant)

    # Создаём тестовый payload
    payload = WebhookPayload(
        event="webhook.ping",
        data={
            "message": "Тестовое webhook-уведомление от SMDG",
            "subscription_id": subscription_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    payload_json = payload.to_json()

    # Подготовка заголовков
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "SMDG-Webhook/1.0",
        "X-Webhook-Event": "webhook.ping",
    }

    if subscription.secret:
        signature = sign_payload(payload_json, subscription.secret)
        headers["X-Webhook-Signature"] = f"sha256={signature}"

    timeout = aiohttp.ClientTimeout(total=subscription.timeout_seconds or 10)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                subscription.url,
                data=payload_json,
                headers=headers,
                timeout=timeout
            ) as response:
                response_body = await response.text()

                # Логируем доставку
                delivery = WebhookDelivery(
                    subscription_id=subscription_id,
                    event="webhook.ping",
                    payload=payload_json,
                    status="success" if response.ok else "failed",
                    attempts=1,
                    max_attempts=1,
                    response_status=response.status,
                    response_body=response_body[:2000],
                )
                db.add(delivery)
                await db.commit()

                audit_logger.log_operation(
                    action="webhook_ping",
                    filename="",
                    user=current_user.sub,
                    reason=f"Тест webhook: {subscription.url}",
                    success=response.ok,
                    metadata={"status": response.status}
                )

                return WebhookPingResponse(
                    success=response.ok,
                    message=f"HTTP {response.status}: {'OK' if response.ok else 'Failed'}",
                    response_status=response.status,
                    response_body=response_body[:500] if not response.ok else None,
                )

    except asyncio.TimeoutError:
        return WebhookPingResponse(
            success=False,
            message=f"Timeout after {timeout.total or 10}s",
            response_status=None,
            response_body=None,
        )

    except aiohttp.ClientError as e:
        return WebhookPingResponse(
            success=False,
            message=f"Connection error: {str(e)}",
            response_status=None,
            response_body=None,
        )


# ==================== Available Events ====================

@router.get("/meta/events", response_model=List[str])
async def list_available_events(
    current_user: TokenData = Depends(get_current_user),
):
    """Получить список доступных событий для webhook-подписок."""
    return sorted([e.value for e in WebhookEvent])
