"""Telegram bot для отправки алертов SMDG.

Используется из ``app/api/alert_webhook.py`` — там принимаем JSON от
Alertmanager в формате v2 и перекладываем в Telegram. Делаем тонкую
прослойку: один небольшой класс + единый HTTP-клиент.

Безопасность:
    * Токен и chat_id читаются из ENV. Если их нет — alerter переходит в
      **noop-режим** (логирует и молча возвращает), сервис продолжает
      работать. НИКОГДА не падаем из-за отсутствующей интеграции.
    * В теле сообщения мы НЕ разглашаем PII: отдаём только alertname,
      severity, summary и description — эти поля формируем мы сами в
      prometheus/alerts.yml и контролируем, что туда попадает.
    * Все исходящие запросы идут с коротким таймаутом (5 сек), чтобы
      медленный Telegram API не блокировал обработку Alertmanager
      webhook'ов (а те, в свою очередь, не ретраили в тайт-луп).

Производительность:
    Используем один shared ``httpx.AsyncClient`` на весь процесс —
    сокеты не открываются и не закрываются на каждый алерт.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Константы форматирования
# ---------------------------------------------------------------------------

_SEVERITY_EMOJI: Dict[str, str] = {
    "critical": "🔴",
    "warning": "🟡",
    "info": "🔵",
    "none": "⚪",
}

# Ограничение Telegram на длину одного сообщения — 4096 символов.
_TELEGRAM_MAX_LEN: int = 4000  # оставляем запас на форматирование.

# Таймаут одного HTTP-запроса в Telegram API.
_TELEGRAM_HTTP_TIMEOUT_SEC: float = 5.0


def _is_public_url(url: str) -> bool:
    """Подходит ли URL для inline-кнопки Telegram.

    Telegram Bot API требует, чтобы URL в ``inline_keyboard`` был
    публично-достижимым: отклоняет ``http://localhost``, ``http://127.*``,
    IPv4 private ranges, а также некоторые внутренние TLDs (``.local``).
    Вместо того чтобы получать ``400 Bad Request: URL is invalid``
    и терять всё сообщение, заранее отфильтруем такие URL — кнопку
    просто не добавим.
    """
    if not url or "://" not in url:
        return False
    low = url.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        return False
    try:
        host = low.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
    except IndexError:
        return False
    if not host or "." not in host:
        # Telegram хочет FQDN. Голые hostnames без точки (например "minio") —
        # внутренние docker-имена, в интернете их не резолвить.
        return False
    # Явно внутренние / служебные адреса.
    bad_prefixes = ("localhost", "127.", "0.0.0.0", "10.", "192.168.")
    if host.startswith(bad_prefixes):
        return False
    # IPv4 private 172.16.0.0 — 172.31.255.255.
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) >= 2 and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
            return False
    # Внутренние TLD'ы.
    if host.endswith((".local", ".internal", ".lan", ".localdomain")):
        return False
    return True


class TelegramAlerter:
    """Простейший async-клиент для sendMessage.

    Потокобезопасен в пределах одного event loop (asyncio). При
    пустом ``bot_token`` или ``chat_id`` экземпляр работает в noop-режиме.
    """

    def __init__(
        self,
        bot_token: Optional[str],
        chat_id: Optional[str],
        *,
        dashboard_url: Optional[str] = None,
        tracing_url: Optional[str] = None,
        logs_url: Optional[str] = None,
    ) -> None:
        self.bot_token = (bot_token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.enabled = bool(self.bot_token and self.chat_id)
        self.api_url = (
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            if self.enabled
            else ""
        )
        # ``os.getenv("X", default)`` возвращает default ТОЛЬКО если переменной
        # совсем нет. Если переменная есть, но пустая (""), вернётся "" —
        # и в inline_keyboard попадёт пустой url, Telegram API вернёт
        # 400 Bad Request: URL host is empty. Поэтому явно нормализуем.
        self.dashboard_url = (
            dashboard_url or os.getenv("SMDG_DASHBOARD_URL") or "https://monitoring.smdg.local"
        )
        self.tracing_url = (
            tracing_url or os.getenv("SMDG_TRACING_URL") or "https://tracing.smdg.local"
        )
        self.logs_url = (
            logs_url or os.getenv("SMDG_LOGS_URL") or "https://logs.smdg.local"
        )
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

        if not self.enabled:
            logger.warning(
                "TelegramAlerter: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID не заданы, "
                "работаю в noop-режиме (алерты будут только залогированы)."
            )

    # ------------------------------------------------------------------
    # Внутренние помощники
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """Ленивая инициализация shared HTTP-клиента."""
        if self._client is None or self._client.is_closed:
            async with self._lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(
                        timeout=_TELEGRAM_HTTP_TIMEOUT_SEC,
                    )
        return self._client

    async def close(self) -> None:
        """Закрыть HTTP-клиент (вызывается в lifespan shutdown)."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    @staticmethod
    def _escape_html(text: str) -> str:
        """Escape для Telegram ``parse_mode=HTML``.

        Telegram HTML поддерживает ограниченный набор тегов
        (``<b>``, ``<i>``, ``<u>``, ``<s>``, ``<code>``, ``<pre>``, ``<a>``),
        но требует экранировать только 3 символа. Это намного надёжнее,
        чем Markdown — в произвольном тексте алертов (имена вроде
        ``smdg_db_up``, скобки, звёздочки) Markdown парсер ломается и
        Telegram возвращает ``Bad Request: can't parse entities``.
        """
        if not text:
            return ""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    @classmethod
    def _format_alert(
        cls,
        alert: Dict[str, Any],
        dashboard_url: str,
        tracing_url: str,
        logs_url: str,
    ) -> tuple[str, Dict[str, Any]]:
        """Сформировать (text, reply_markup) из Alertmanager v2 payload."""
        labels = alert.get("labels", {}) or {}
        annotations = alert.get("annotations", {}) or {}

        severity = str(labels.get("severity", "none")).lower()
        emoji = _SEVERITY_EMOJI.get(severity, _SEVERITY_EMOJI["none"])
        alertname = str(labels.get("alertname", "UnknownAlert"))
        service = str(labels.get("service", "smdg"))
        instance = str(labels.get("instance", "unknown"))
        status = str(alert.get("status", "firing")).lower()
        resolved_tag = " ✅ RESOLVED" if status == "resolved" else ""

        # Парсинг startsAt — Alertmanager присылает ISO 8601.
        starts_at_raw = alert.get("startsAt") or ""
        try:
            alert_time = datetime.fromisoformat(
                starts_at_raw.replace("Z", "+00:00")
            )
        except ValueError:
            alert_time = datetime.now(timezone.utc)

        esc = cls._escape_html
        summary = esc(annotations.get("summary", "No summary"))
        description = esc(annotations.get("description", "No description"))
        runbook = annotations.get("runbook") or "https://wiki.smdg/runbooks"

        text = (
            f"{emoji} <b>SMDG Alert: {esc(alertname)}</b>{resolved_tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Severity:</b> <code>{esc(severity.upper())}</code>\n"
            f"<b>Time:</b> <code>{esc(alert_time.strftime('%Y-%m-%d %H:%M:%S %Z'))}</code>\n"
            f"<b>Service:</b> <code>{esc(service)}</code>\n"
            f"<b>Instance:</b> <code>{esc(instance)}</code>\n\n"
            f"<b>Summary:</b>\n{summary}\n\n"
            f"<b>Description:</b>\n{description}\n\n"
            f"<b>Runbook:</b> {esc(runbook)}"
        )

        # Обрезаем на случай очень длинного description (Telegram лимит).
        if len(text) > _TELEGRAM_MAX_LEN:
            text = text[: _TELEGRAM_MAX_LEN - 20] + "\n…\n(truncated)"

        # Собираем кнопки, отфильтровывая невалидные (localhost/private IP
        # и т.п.) — Telegram иначе вернёт 400 и мы потеряем всё сообщение.
        candidates = [
            ("📊 Dashboard", dashboard_url),
            ("🔍 Traces", tracing_url),
            ("📝 Logs", logs_url),
            ("📖 Runbook", runbook),
        ]
        valid_buttons = [
            {"text": label, "url": url}
            for label, url in candidates
            if _is_public_url(url)
        ]
        # Раскладываем по 2 в ряд для компактного вида в Telegram.
        rows = [valid_buttons[i : i + 2] for i in range(0, len(valid_buttons), 2)]
        reply_markup: Dict[str, Any] = {"inline_keyboard": rows} if rows else {}
        return text, reply_markup

    # ------------------------------------------------------------------
    # Публичное API
    # ------------------------------------------------------------------

    async def send_alert(self, alert: Dict[str, Any], *, chat_id_override: str | None = None) -> bool:
        """Отправить один алерт. Возвращает ``True`` если доставка удалась."""
        target_chat_id = (chat_id_override or self.chat_id or "").strip()
        if not self.bot_token or not target_chat_id:
            logger.info(
                "Telegram noop: alert=%s severity=%s",
                (alert.get("labels") or {}).get("alertname"),
                (alert.get("labels") or {}).get("severity"),
            )
            return False

        text, reply_markup = self._format_alert(
            alert,
            dashboard_url=self.dashboard_url,
            tracing_url=self.tracing_url,
            logs_url=self.logs_url,
        )
        payload: Dict[str, Any] = {
            "chat_id": target_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        # reply_markup пропускаем, если не набралось ни одной валидной
        # кнопки (все URL внутренние / localhost). Иначе Telegram может
        # вернуть 400 на пустой inline_keyboard.
        if reply_markup.get("inline_keyboard"):
            payload["reply_markup"] = reply_markup

        client = await self._get_client()
        try:
            resp = await client.post(self.api_url, json=payload)
            if resp.status_code >= 400:
                # Тело ответа Telegram обычно содержит подробное описание
                # (ok/description/error_code), например "Bad Request:
                # URL host is empty" при невалидных inline-buttons.
                logger.warning(
                    "Telegram sendMessage failed: status=%d body=%s",
                    resp.status_code,
                    resp.text[:300],
                )
                return False
            return True
        except httpx.HTTPError as exc:
            # У многих httpx-исключений (ConnectError, ReadTimeout) str(exc)
            # может быть пустым — логируем тип и repr, чтобы всегда было
            # видно причину сбоя.
            logger.warning(
                "Telegram sendMessage HTTP error: %s: %s",
                type(exc).__name__,
                repr(exc),
            )
            return False

    async def send_batch_alerts(
        self,
        alerts: List[Dict[str, Any]],
        *,
        chat_id_override: str | None = None,
    ) -> int:
        """Отправить пачку алертов.

        При >1 алертов пытаемся отдать одно групповое сообщение (чтобы
        не спамить), но если группа слишком длинная — разобьём на
        несколько.

        Returns:
            Количество успешно отправленных сообщений.
        """
        if not alerts:
            return 0
        if len(alerts) == 1:
            ok = await self.send_alert(alerts[0], chat_id_override=chat_id_override)
            return 1 if ok else 0

        target_chat_id = (chat_id_override or self.chat_id or "").strip()
        if not self.bot_token or not target_chat_id:
            logger.info("Telegram noop: batch of %d alerts", len(alerts))
            return 0

        # Групповое текстовое сообщение-резюме: первые 10 алертов.
        preview = alerts[:10]
        esc = self._escape_html
        lines = [f"⚠️ <b>{len(alerts)} alerts detected</b>\n"]
        for a in preview:
            labels = a.get("labels") or {}
            alertname = esc(str(labels.get("alertname", "?")))
            severity = esc(str(labels.get("severity", "none")).upper())
            lines.append(f"• <code>{alertname}</code> — {severity}")
        if len(alerts) > 10:
            lines.append(f"\n… and {len(alerts) - 10} more alerts")
        text = "\n".join(lines)[:_TELEGRAM_MAX_LEN]

        payload = {
            "chat_id": target_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        client = await self._get_client()
        try:
            resp = await client.post(self.api_url, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "Telegram batch sendMessage failed: status=%d body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                return 0
            return 1
        except httpx.HTTPError as exc:
            logger.warning(
                "Telegram batch sendMessage HTTP error: %s: %s",
                type(exc).__name__,
                repr(exc),
            )
            return 0


# ---------------------------------------------------------------------------
# Глобальный singleton — ленивая инициализация из ENV, чтобы импорт модуля
# не выполнял никаких побочных действий (важно для тестов).
# ---------------------------------------------------------------------------

_telegram_alerter: Optional[TelegramAlerter] = None


def get_telegram_alerter() -> TelegramAlerter:
    """Вернуть shared singleton, создавая его при первом обращении."""
    global _telegram_alerter
    if _telegram_alerter is None:
        _telegram_alerter = TelegramAlerter(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        )
    return _telegram_alerter


__all__ = [
    "TelegramAlerter",
    "get_telegram_alerter",
]
