#!/usr/bin/env python3
"""
Черновик ежемесячного SLA-отчёта (HTML на stdout). Опционально — отправка по SMTP.

Переменные окружения (опционально):
  PROMETHEUS_URL  — для запросов smdg:api_availability:30d (если доступен)
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SLA_REPORT_TO, SLA_REPORT_FROM

Пример:
  poetry run python scripts/monthly_sla_report.py > /tmp/sla-report.html
"""
from __future__ import annotations

import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.sla_tracker import SLATracker  # noqa: E402


def _html_report() -> str:
    t = SLATracker()
    now = datetime.now(timezone.utc)
    av = t.get_uptime_30d()
    av_str = f"{av:.4f}%" if av is not None else "n/a (нет SLO/Prom)"
    eb = t.get_error_budget()
    lat = t.get_latency_p95()
    status = t.get_current_status()
    met = av is not None and av >= 99.9
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>SMDG SLA report</title></head>
<body>
<h1>SMDG monthly SLA snapshot</h1>
<p>Generated (UTC): {now.isoformat()}</p>
<h2>Summary</h2>
<ul>
  <li>Overall status: <strong>{status}</strong></li>
  <li>Availability proxy (30d / in-process): <strong>{av_str}</strong></li>
  <li>Target: 99.9% — {'MET' if met else 'REVIEW / n/a'}</li>
  <li>Error budget remaining (api_availability): <strong>{eb:.2f}%</strong></li>
  <li>Latency p95 (ms, see API notes): <strong>{lat}</strong></li>
</ul>
<p><em>Figures combine Prometheus (if PROMETHEUS_URL works) and in-app SLO gauges.</em></p>
</body></html>
"""


def _maybe_send(html: str) -> None:
    host = os.getenv("SMTP_HOST")
    to_addr = os.getenv("SLA_REPORT_TO")
    if not host or not to_addr:
        return
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    from_addr = os.getenv("SLA_REPORT_FROM", user or "noreply@localhost")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"SMDG SLA report — {datetime.now(timezone.utc).strftime('%Y-%m')}"
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(host, port, timeout=30) as server:
        if port == 587:
            server.starttls()
        if user and password:
            server.login(user, password)
        server.sendmail(from_addr, [to_addr], msg.as_string())


def main() -> None:
    html = _html_report()
    sys.stdout.write(html)
    try:
        _maybe_send(html)
    except OSError as exc:
        print(f"<!-- SMTP skipped: {exc} -->", file=sys.stderr)


if __name__ == "__main__":
    main()
