#!/usr/bin/env python3
"""Backup freshness monitoring for SMDG."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from prometheus_client import Gauge, start_http_server

BACKUP_AGE_SECONDS = Gauge("smdg_backup_age_seconds", "Age of latest DB backup in seconds")
BACKUP_FRESH = Gauge("smdg_backup_fresh", "1 when backup freshness is within threshold, else 0")


def latest_db_backup_mtime(backup_dir: Path) -> Optional[float]:
    latest: Optional[float] = None
    for entry in backup_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.name.startswith("db_") and entry.name.endswith(".sql.gz"):
            mtime = entry.stat().st_mtime
            latest = mtime if latest is None else max(latest, mtime)
    return latest


def check_backup_freshness(backup_dir: Path, max_age_hours: int = 24) -> Tuple[bool, str, float]:
    latest = latest_db_backup_mtime(backup_dir)
    if latest is None:
        return False, "No backups found", float("inf")

    age_seconds = time.time() - latest
    age_hours = age_seconds / 3600
    if age_hours > max_age_hours:
        return False, f"Last backup is {age_hours:.1f} hours old", age_seconds
    return True, f"Backup is {age_hours:.1f} hours old", age_seconds


def run_once(backup_dir: Path, max_age_hours: int) -> int:
    ok, message, age_seconds = check_backup_freshness(backup_dir, max_age_hours=max_age_hours)
    BACKUP_AGE_SECONDS.set(age_seconds if age_seconds != float("inf") else -1)
    BACKUP_FRESH.set(1 if ok else 0)
    status = "OK" if ok else "CRITICAL"
    print(f"[{status}] {message}")
    return 0 if ok else 1


def run_server(backup_dir: Path, max_age_hours: int, listen_port: int, interval: int) -> None:
    start_http_server(listen_port)
    print(f"[INFO] Metrics server started on :{listen_port}")
    print(f"[INFO] Monitoring backup dir: {backup_dir}")

    while True:
        ok, message, age_seconds = check_backup_freshness(backup_dir, max_age_hours=max_age_hours)
        BACKUP_AGE_SECONDS.set(age_seconds if age_seconds != float("inf") else -1)
        BACKUP_FRESH.set(1 if ok else 0)
        level = "OK" if ok else "WARN"
        print(f"[{level}] {message}")
        time.sleep(interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor SMDG backup freshness")
    parser.add_argument("--backup-dir", default=os.getenv("BACKUP_DIR", "/backups/smdg"), help="Backup directory")
    parser.add_argument("--max-age-hours", type=int, default=24, help="Maximum backup age in hours")
    parser.add_argument("--listen-port", type=int, default=9808, help="Prometheus metrics port")
    parser.add_argument("--interval", type=int, default=60, help="Polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run one check and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    backup_dir = Path(args.backup_dir)
    if not backup_dir.exists() or not backup_dir.is_dir():
        print(f"[ERROR] Backup directory does not exist: {backup_dir}")
        return 2

    if args.once:
        return run_once(backup_dir, args.max_age_hours)

    run_server(backup_dir, args.max_age_hours, args.listen_port, args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
