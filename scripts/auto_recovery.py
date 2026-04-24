#!/usr/bin/env python3
"""Automatic service recovery manager for SMDG."""

from __future__ import annotations

import argparse
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Dict

import requests


@dataclass
class ServiceConfig:
    port: int
    health_path: str
    max_retries: int
    recover_fn: Callable[[], bool]


class RecoveryManager:
    def __init__(self, interval: int = 30, timeout: int = 5) -> None:
        self.interval = interval
        self.timeout = timeout
        self.services: Dict[str, ServiceConfig] = {
            "db": ServiceConfig(port=5432, health_path="", max_retries=3, recover_fn=self.recover_db),
            "redis": ServiceConfig(port=6379, health_path="", max_retries=3, recover_fn=self.recover_redis),
            "smdg": ServiceConfig(port=8000, health_path="/health/live", max_retries=3, recover_fn=self.recover_smdg),
            "minio": ServiceConfig(port=9000, health_path="/minio/health/live", max_retries=2, recover_fn=self.recover_minio),
        }

    def _run(self, command: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, capture_output=True, text=True, check=check)

    def check_service(self, name: str) -> bool:
        if name == "db":
            return self._run(["docker", "compose", "exec", "-T", "db", "pg_isready", "-U", "smdg_user"]).returncode == 0
        if name == "redis":
            return self._run(["docker", "compose", "exec", "-T", "redis", "redis-cli", "ping"]).returncode == 0

        cfg = self.services[name]
        url = f"http://localhost:{cfg.port}{cfg.health_path}"
        try:
            response = requests.get(url, timeout=self.timeout)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def recover_db(self) -> bool:
        print("[RECOVERY] PostgreSQL: restart")
        self._run(["docker", "compose", "restart", "db"])
        time.sleep(10)
        if self.check_service("db"):
            print("[RECOVERY] PostgreSQL: recovered after restart")
            return True

        print("[RECOVERY] PostgreSQL: restore from latest backup")
        restore = self._run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "sh",
                "-lc",
                "ls /app/backups/manifest_latest.txt >/dev/null 2>&1 && echo ok || echo missing",
            ]
        )
        if "ok" in restore.stdout:
            self._run(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "db",
                    "sh",
                    "-lc",
                    "gunzip -c /app/backups/db_$(sed -n 's/^Backup Date: //p' /app/backups/manifest_latest.txt).sql.gz | psql -U smdg_user -d smdg",
                ]
            )
            time.sleep(10)

        return self.check_service("db")

    def recover_redis(self) -> bool:
        print("[RECOVERY] Redis: restart")
        self._run(["docker", "compose", "restart", "redis"])
        time.sleep(5)
        return self.check_service("redis")

    def recover_smdg(self) -> bool:
        print("[RECOVERY] SMDG: restart")
        self._run(["docker", "compose", "restart", "smdg"])
        time.sleep(10)
        return self.check_service("smdg")

    def recover_minio(self) -> bool:
        print("[RECOVERY] MinIO: restart")
        self._run(["docker", "compose", "restart", "minio"])
        time.sleep(10)
        return self.check_service("minio")

    def send_alert(self, service: str) -> None:
        print(f"[ALERT] Manual intervention required for service: {service}")

    def attempt_recovery(self, service: str) -> bool:
        cfg = self.services[service]
        for attempt in range(1, cfg.max_retries + 1):
            print(f"[INFO] Attempt {attempt}/{cfg.max_retries} for {service}")
            if cfg.recover_fn() and self.check_service(service):
                print(f"[OK] Service recovered: {service}")
                return True
            time.sleep(2)

        self.send_alert(service)
        return False

    def run(self, target_service: str | None = None, run_once: bool = False) -> int:
        print("[INFO] Starting Recovery Manager")
        services = [target_service] if target_service else list(self.services.keys())

        while True:
            all_ok = True
            for service in services:
                if not self.check_service(service):
                    all_ok = False
                    print(f"[WARN] Service is DOWN: {service}")
                    self.attempt_recovery(service)

            if run_once:
                return 0 if all_ok else 1

            time.sleep(self.interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SMDG automatic recovery manager")
    parser.add_argument("--service", choices=["db", "redis", "smdg", "minio"], help="Recover only one service")
    parser.add_argument("--once", action="store_true", help="Run one monitoring cycle and exit")
    parser.add_argument("--interval", type=int, default=30, help="Monitoring interval in seconds")
    parser.add_argument("--timeout", type=int, default=5, help="HTTP health-check timeout in seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manager = RecoveryManager(interval=args.interval, timeout=args.timeout)
    return manager.run(target_service=args.service, run_once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
