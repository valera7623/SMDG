#!/usr/bin/env python3
"""
CLI: печать JSON-отчёта SLATracker (тот же источник, что /api/sli/report).

Usage:
  PROMETHEUS_URL=http://prometheus:9090 poetry run python scripts/sla_tracker.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.sla_tracker import SLATracker  # noqa: E402


def main() -> None:
    report = SLATracker().generate_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
