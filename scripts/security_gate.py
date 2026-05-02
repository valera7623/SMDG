#!/usr/bin/env python3
"""
Enforce consolidated security policy from security-summary.json (CI final gate).

Aligned with SECURITY_SCAN_MODE in .github/workflows/security-scan.yml:
  - audit: never fail
  - balanced: block on critical container rollup + leaked secrets in summary; optional Trivy HIGH via env
  - strict: block on broad SAST/SCA/secret signals reflected in the summary JSON
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _load_summary(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def evaluate_gate(mode: str, summary: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (ok, reasons)."""
    m = (mode or "balanced").lower()
    counts = summary.get("counts")
    if not isinstance(counts, dict):
        counts = {}
    rollup = summary.get("rollup")
    if not isinstance(rollup, dict):
        rollup = {}

    def ikey(key: str) -> int:
        v = counts.get(key)
        if isinstance(v, bool) or v is None:
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    def rkey(key: str) -> int:
        v = rollup.get(key)
        if isinstance(v, bool) or v is None:
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    reasons: list[str] = []

    if m == "audit":
        return True, []

    critical = rkey("critical")
    high = rkey("high")

    gitleaks = ikey("gitleaks_findings")
    safety = ikey("safety_issues")
    trivy_high = ikey("trivy_high")

    medium = rkey("medium")
    low = rkey("low")

    if m == "balanced":
        if critical > 0:
            reasons.append(f"rollup.critical={critical} (Trivy/Grype CRITICAL in summary)")
        if gitleaks > 0:
            reasons.append(f"gitleaks_findings={gitleaks}")
        if os.environ.get("SECURITY_GATE_BALANCED_FAIL_TRIVY_HIGH", "").lower() in (
            "1",
            "true",
            "yes",
        ):
            if trivy_high > 0:
                reasons.append(
                    f"trivy_high={trivy_high} (SECURITY_GATE_BALANCED_FAIL_TRIVY_HIGH enabled)"
                )
        return (len(reasons) == 0), reasons

    if m == "strict":
        # Mirrors broad SAST/SCA coverage: any rollup severity from consolidated summary,
        # plus secrets (Gitleaks) and dependency advisories (Safety) which are not in rollup.
        if critical > 0:
            reasons.append(f"rollup.critical={critical}")
        if high > 0:
            reasons.append(f"rollup.high={high}")
        if medium > 0:
            reasons.append(f"rollup.medium={medium}")
        if low > 0:
            reasons.append(f"rollup.low={low}")
        if gitleaks > 0:
            reasons.append(f"gitleaks_findings={gitleaks}")
        if safety > 0:
            reasons.append(f"safety_issues={safety}")
        return (len(reasons) == 0), reasons

    # Unknown mode: behave like balanced
    return evaluate_gate("balanced", summary)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exit non-zero if security-summary.json violates policy for the given mode.",
    )
    parser.add_argument(
        "summary_json",
        type=Path,
        help="Path to security-summary.json (from generate_security_report.py --json-output)",
    )
    parser.add_argument(
        "--mode",
        default=os.environ.get("SECURITY_SCAN_MODE", "balanced"),
        help="audit | balanced | strict (default: env SECURITY_SCAN_MODE or balanced)",
    )
    args = parser.parse_args()

    summary = _load_summary(args.summary_json)
    if summary is None:
        print(f"ERROR: cannot read or parse {args.summary_json}", file=sys.stderr)
        sys.exit(2)

    ok, reasons = evaluate_gate(str(args.mode), summary)
    if ok:
        print(f"Security gate OK (mode={args.mode!r}).")
        sys.exit(0)

    print(f"Security gate FAILED (mode={args.mode!r}):", file=sys.stderr)
    for r in reasons:
        print(f"  - {r}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
