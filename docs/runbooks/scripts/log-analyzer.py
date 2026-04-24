#!/usr/bin/env python3
"""
Log analyzer for SMDG.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta


def analyze_logs(log_file: str, hours: int = 24) -> dict[str, Counter]:
    patterns = {
        "error": re.compile(r"ERROR|Exception|Traceback", re.I),
        "timeout": re.compile(r"timeout|TimeoutError", re.I),
        "rate_limit": re.compile(r"rate limit|429|Too Many Requests", re.I),
        "auth_failure": re.compile(r"401|Unauthorized|Invalid credentials", re.I),
        "db_error": re.compile(r"database|postgres|psycopg", re.I),
        "storage_error": re.compile(r"s3|minio|storage|upload|download", re.I),
        "dicom_error": re.compile(r"dicom|render|pydicom", re.I),
    }

    stats: dict[str, Counter] = defaultdict(Counter)
    recent_errors: list[str] = []
    cutoff = datetime.now() - timedelta(hours=hours)

    with open(log_file, "r", encoding="utf-8", errors="ignore") as file_obj:
        for line in file_obj:
            match = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line)
            if match:
                try:
                    log_time = datetime.strptime(match.group(), "%Y-%m-%d %H:%M:%S")
                    if log_time < cutoff:
                        continue
                except ValueError:
                    pass

            for category, pattern in patterns.items():
                if pattern.search(line):
                    stats[category]["total"] += 1
                    if len(recent_errors) < 20:
                        recent_errors.append(line.strip())

    print("=" * 60)
    print(f"SMDG Log Analysis Report (last {hours} hours)")
    print("=" * 60)
    print("\nStatistics:")
    for category, data in stats.items():
        print(f"  {category}: {data['total']}")

    print("\nRecent Issues (max 20):")
    for error in recent_errors:
        print(f"  {error[:180]}")

    print("\nRecommendations:")
    if stats["error"]["total"] > 100:
        print("  - High error rate detected, investigate immediately")
    if stats["timeout"]["total"] > 50:
        print("  - Timeouts detected, review dependency latency and timeout budgets")
    if stats["rate_limit"]["total"] > 100:
        print("  - Rate limit saturation detected, review client traffic profile")

    return stats


if __name__ == "__main__":
    source = sys.argv[1] if len(sys.argv) > 1 else "/dev/stdin"
    hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    analyze_logs(source, hours=hours)
