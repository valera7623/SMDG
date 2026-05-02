#!/usr/bin/env python3
"""
Generate a consolidated security HTML report from scanner artifacts.

Supports SARIF (e.g. Trivy image scan) and raw JSON. Optional baseline JSON
for comparing counts between runs (triage / drift).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _count_bandit(report: Any) -> tuple[int, int, int, int]:
    if not isinstance(report, dict):
        return (0, 0, 0, 0)
    findings = report.get("results", [])
    high = sum(1 for i in findings if i.get("issue_severity") == "HIGH")
    medium = sum(1 for i in findings if i.get("issue_severity") == "MEDIUM")
    low = sum(1 for i in findings if i.get("issue_severity") == "LOW")
    return (len(findings), high, medium, low)


def _bandit_by_rule_and_file(report: Any) -> tuple[Counter[str], Counter[str]]:
    rules: Counter[str] = Counter()
    files: Counter[str] = Counter()
    if not isinstance(report, dict):
        return rules, files
    for i in report.get("results", []) or []:
        tid = str(i.get("test_id") or i.get("test_name") or "unknown")
        rules[tid] += 1
        fn = str(i.get("filename") or "")
        if fn:
            files[fn] += 1
    return rules, files


def _count_semgrep(report: Any) -> tuple[int, int, int, int]:
    if not isinstance(report, dict):
        return (0, 0, 0, 0)
    findings = report.get("results", [])
    high = sum(1 for i in findings if str(i.get("extra", {}).get("severity", "")).upper() == "ERROR")
    medium = sum(1 for i in findings if str(i.get("extra", {}).get("severity", "")).upper() == "WARNING")
    return (len(findings), high, medium, 0)


def _semgrep_by_rule_and_file(report: Any) -> tuple[Counter[str], Counter[str]]:
    rules: Counter[str] = Counter()
    files: Counter[str] = Counter()
    if not isinstance(report, dict):
        return rules, files
    for i in report.get("results", []) or []:
        rid = str(i.get("check_id") or "unknown")
        rules[rid] += 1
        p = str(i.get("path") or "")
        if p:
            files[p] += 1
    return rules, files


def _sarif_severity_to_bucket(sev: str) -> str | None:
    u = sev.strip().upper()
    if u in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        return u
    return None


def _count_trivy(report: Any) -> tuple[int, int]:
    """Count HIGH / CRITICAL from Trivy native JSON or Trivy SARIF."""
    if not isinstance(report, dict):
        return (0, 0)
    high = 0
    critical = 0

    # Native Trivy JSON: Results[].Vulnerabilities[].Severity
    for result in report.get("Results", []) or []:
        for vuln in result.get("Vulnerabilities", []) or []:
            sev = str(vuln.get("Severity", "")).upper()
            if sev == "HIGH":
                high += 1
            elif sev == "CRITICAL":
                critical += 1

    if high or critical:
        return high, critical

    # SARIF 2.1 (trivy-action --format sarif)
    for run in report.get("runs", []) or []:
        for res in run.get("results", []) or []:
            props = res.get("properties") or {}
            sev = None
            if isinstance(props, dict):
                sev = props.get("severity") or props.get("Severity")
            if sev is None:
                # Some generators put severity in tags / rule metadata only
                lvl = str(res.get("level", "")).lower()
                if lvl == "error":
                    sev = "CRITICAL"
                elif lvl == "warning":
                    sev = "HIGH"
                elif lvl == "note":
                    sev = "MEDIUM"
            bucket = _sarif_severity_to_bucket(str(sev or ""))
            if bucket == "HIGH":
                high += 1
            elif bucket == "CRITICAL":
                critical += 1

    return high, critical


def _count_grype(report: Any) -> tuple[int, int]:
    if not isinstance(report, dict):
        return (0, 0)
    high = 0
    critical = 0
    for match in report.get("matches", []):
        sev = str(match.get("vulnerability", {}).get("severity", "")).upper()
        if sev == "HIGH":
            high += 1
        elif sev == "CRITICAL":
            critical += 1
    return high, critical


def _count_simple_lines(path: Path) -> int:
    try:
        return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
    except Exception:
        return 0


def _top_rows(counter: Counter[str], limit: int = 15) -> str:
    if not counter:
        return "<tr><td colspan='2'><i>No data</i></td></tr>"
    rows = []
    for name, count in counter.most_common(limit):
        rows.append(f"<tr><td>{_html_escape(name)}</td><td>{count}</td></tr>")
    return "\n      ".join(rows)


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _blocking_policy_html(mode: str) -> str:
    m = (mode or "balanced").lower()
    if m == "strict":
        body = """
    <p><b>strict</b> — CI fails on SAST (Bandit, Semgrep), SCA (Safety), secrets scans,
    and dependency/container findings per tool thresholds. Use for release branches or manual gates.</p>
    """
    elif m == "audit":
        body = """
    <p><b>audit</b> — Scheduled/non-blocking: scanners run with <code>continue-on-error</code>
    where configured; collect artifacts without failing the workflow.</p>
    """
    else:
        body = """
    <p><b>balanced</b> (default for push/PR) — CI <b>blocks</b> on leaked secrets (Gitleaks, TruffleHog),
    API security tests, container policy (Trivy/Grype per workflow thresholds), and other non-SAST gates.
    Noisy SAST/SCA (Bandit, Semgrep, Safety) is <b>non-blocking</b> here so findings stay visible in reports
    without false-red merges; switch repository variable <code>SECURITY_SCAN_MODE=strict</code> to enforce SAST/SCA.</p>
    """
    return f'<h2>CI blocking policy ({_html_escape(m)})</h2>\n{body}'


def _load_baseline(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _delta_rows(
    label: str,
    current: int,
    baseline: int | None,
) -> str:
    if baseline is None:
        return f"<tr><td>{_html_escape(label)}</td><td>{current}</td><td>—</td><td>—</td></tr>"
    delta = current - baseline
    arrow = "±0"
    if delta > 0:
        arrow = f"+{delta}"
    elif delta < 0:
        arrow = str(delta)
    cls = ""
    if delta > 0:
        cls = ' style="color:#b71c1c"'
    elif delta < 0:
        cls = ' style="color:#1b5e20"'
    return (
        f"<tr><td>{_html_escape(label)}</td><td>{current}</td><td>{baseline}</td>"
        f"<td{cls}>{arrow}</td></tr>"
    )


def generate_report(
    input_dir: Path,
    output_file: Path,
    mode: str,
    baseline_path: Path | None,
    json_output: Path | None,
) -> None:
    bandit_data = _load_json(input_dir / "bandit-report" / "bandit-report.json")
    semgrep_data = _load_json(input_dir / "semgrep-report" / "semgrep-report.json")
    safety_data = _load_json(input_dir / "safety-report" / "safety-report.json")
    trivy_data = _load_json(input_dir / "trivy-report" / "trivy-report.sarif")
    grype_data = _load_json(input_dir / "grype-report" / "grype-report.json")
    gitleaks_data = _load_json(input_dir / "gitleaks-report" / "gitleaks-report.json")

    bandit_total, bandit_high, bandit_medium, bandit_low = _count_bandit(bandit_data)
    semgrep_total, semgrep_high, semgrep_medium, semgrep_low = _count_semgrep(semgrep_data)
    trivy_high, trivy_critical = _count_trivy(trivy_data)
    grype_high, grype_critical = _count_grype(grype_data)
    bandit_by_rule, bandit_by_file = _bandit_by_rule_and_file(bandit_data)
    semgrep_by_rule, semgrep_by_file = _semgrep_by_rule_and_file(semgrep_data)

    safety_issues = len(safety_data) if isinstance(safety_data, list) else 0
    gitleaks_issues = len(gitleaks_data) if isinstance(gitleaks_data, list) else 0
    trufflehog_lines = _count_simple_lines(input_dir / "trufflehog-report" / "trufflehog-report.json")
    nuclei_lines = _count_simple_lines(input_dir / "nuclei-report" / "nuclei-report.json")

    critical = trivy_critical + grype_critical
    high = bandit_high + semgrep_high + trivy_high + grype_high
    medium = bandit_medium + semgrep_medium
    low = bandit_low + semgrep_low

    baseline = _load_baseline(baseline_path)
    b_counts = (baseline or {}).get("counts") if baseline else None
    b_total = b_counts if isinstance(b_counts, dict) else None

    def b_get(key: str) -> int | None:
        if not b_total:
            return None
        v = b_total.get(key)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    summary_obj: dict[str, Any] = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "rollup": {
            "critical": critical,
            "high": high,
            "medium": medium,
            "low": low,
        },
        "tools": {
            "bandit": {
                "total": bandit_total,
                "high": bandit_high,
                "medium": bandit_medium,
                "low": bandit_low,
                "top_rules": dict(bandit_by_rule.most_common(20)),
            },
            "semgrep": {
                "total": semgrep_total,
                "error_severity": semgrep_high,
                "warning_severity": semgrep_medium,
                "top_rules": dict(semgrep_by_rule.most_common(20)),
            },
            "safety": {"issues": safety_issues},
            "trivy": {"high": trivy_high, "critical": trivy_critical},
            "grype": {"high": grype_high, "critical": grype_critical},
            "gitleaks": {"findings": gitleaks_issues},
            "trufflehog": {"json_lines": trufflehog_lines},
            "nuclei": {"json_lines": nuclei_lines},
        },
    }

    if baseline:
        summary_obj["baseline"] = {
            "path": str(baseline_path) if baseline_path else None,
            "delta_total_findings": {
                "bandit": bandit_total - b_get("bandit_total")
                if b_get("bandit_total") is not None
                else None,
                "semgrep": semgrep_total - b_get("semgrep_total")
                if b_get("semgrep_total") is not None
                else None,
            },
        }

    if json_output:
        # Compact serializable snapshot for dashboards / PR comments
        snap = {
            "generated_utc": summary_obj["generated_utc"],
            "mode": mode,
            "rollup": summary_obj["rollup"],
            "counts": {
                "bandit_total": bandit_total,
                "semgrep_total": semgrep_total,
                "safety_issues": safety_issues,
                "gitleaks_findings": gitleaks_issues,
            },
        }
        json_output.write_text(json.dumps(snap, indent=2), encoding="utf-8")

    delta_section = ""
    if baseline and b_total:
        delta_section = f"""
    <h2>New vs baseline</h2>
    <p>Baseline file: {_html_escape(str(baseline_path))}</p>
    <table>
      <tr><th>Metric</th><th>Current</th><th>Baseline</th><th>Δ</th></tr>
      {_delta_rows("Bandit findings", bandit_total, b_get("bandit_total"))}
      {_delta_rows("Semgrep findings", semgrep_total, b_get("semgrep_total"))}
      {_delta_rows("Safety issues", safety_issues, b_get("safety_issues"))}
      {_delta_rows("Gitleaks findings", gitleaks_issues, b_get("gitleaks_findings"))}
      {_delta_rows("Trivy HIGH", trivy_high, b_get("trivy_high"))}
      {_delta_rows("Trivy CRITICAL", trivy_critical, b_get("trivy_critical"))}
    </table>
"""
    elif baseline_path:
        delta_section = f"""
    <h2>New vs baseline</h2>
    <p><i>Baseline path set but file missing or invalid: {_html_escape(str(baseline_path))}</i></p>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>SMDG Security Summary</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f4f6f8; }}
    .wrap {{ max-width: 1100px; margin: 0 auto; background: #fff; padding: 24px; border-radius: 10px; }}
    .cards {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    .card {{ flex: 1; min-width: 140px; border-radius: 8px; padding: 14px; border: 1px solid #ddd; }}
    .critical {{ border-left: 6px solid #d32f2f; }}
    .high {{ border-left: 6px solid #f57c00; }}
    .medium {{ border-left: 6px solid #fbc02d; }}
    .low {{ border-left: 6px solid #1976d2; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background: #fafafa; }}
    code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 4px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>SMDG Security Scan Report</h1>
    <p>Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")} UTC · Mode: <code>{_html_escape(mode)}</code></p>
    <div class="cards">
      <div class="card critical"><b>Critical</b><br/>{critical}</div>
      <div class="card high"><b>High</b><br/>{high}</div>
      <div class="card medium"><b>Medium</b><br/>{medium}</div>
      <div class="card low"><b>Low</b><br/>{low}</div>
    </div>

    {_blocking_policy_html(mode)}

    <h2>SAST / SCA / DAST Overview</h2>
    <table>
      <tr><th>Tool</th><th>Findings</th><th>Notes</th></tr>
      <tr><td>Bandit</td><td>{bandit_total}</td><td>High={bandit_high}, Medium={bandit_medium}, Low={bandit_low}</td></tr>
      <tr><td>Semgrep</td><td>{semgrep_total}</td><td>Error={semgrep_high}, Warning={semgrep_medium}</td></tr>
      <tr><td>Safety</td><td>{safety_issues}</td><td>Dependency advisories</td></tr>
      <tr><td>Trivy</td><td>{trivy_high + trivy_critical}</td><td>Critical={trivy_critical}, High={trivy_high}</td></tr>
      <tr><td>Grype</td><td>{grype_high + grype_critical}</td><td>Critical={grype_critical}, High={grype_high}</td></tr>
      <tr><td>Gitleaks</td><td>{gitleaks_issues}</td><td>Potential leaked secrets</td></tr>
      <tr><td>TruffleHog</td><td>{trufflehog_lines}</td><td>JSON lines in report</td></tr>
      <tr><td>Nuclei</td><td>{nuclei_lines}</td><td>JSON lines in report</td></tr>
    </table>

    {delta_section}

    <h2>Top findings — Semgrep (by rule)</h2>
    <table>
      <tr><th>Rule</th><th>Count</th></tr>
      {_top_rows(semgrep_by_rule)}
    </table>

    <h2>Top findings — Semgrep (by file)</h2>
    <table>
      <tr><th>File</th><th>Count</th></tr>
      {_top_rows(semgrep_by_file)}
    </table>

    <h2>Top findings — Bandit (by test)</h2>
    <table>
      <tr><th>Test ID</th><th>Count</th></tr>
      {_top_rows(bandit_by_rule)}
    </table>

    <h2>Top findings — Bandit (by file)</h2>
    <table>
      <tr><th>File</th><th>Count</th></tr>
      {_top_rows(bandit_by_file)}
    </table>
  </div>
</body>
</html>
"""
    output_file.write_text(html, encoding="utf-8")
    print(f"Security summary generated: {output_file}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build consolidated HTML (and optional JSON) security summary for CI triage.",
    )
    parser.add_argument("--input", default="reports", help="Directory with downloaded artifacts")
    parser.add_argument("--output", default="security-summary.html", help="Output HTML file")
    parser.add_argument(
        "--mode",
        default="balanced",
        help="Scan mode label for policy text (audit|balanced|strict)",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help='Optional JSON file: { "counts": { "bandit_total", "semgrep_total", "safety_issues", '
        '"gitleaks_findings", "trivy_high", "trivy_critical" } } for delta table',
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="Optional path to write a small JSON snapshot for automation",
    )
    args = parser.parse_args()

    baseline_path = Path(args.baseline) if args.baseline else None
    json_out = Path(args.json_output) if args.json_output else None

    generate_report(
        Path(args.input),
        Path(args.output),
        str(args.mode),
        baseline_path,
        json_out,
    )


if __name__ == "__main__":
    main()
