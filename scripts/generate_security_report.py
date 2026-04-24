#!/usr/bin/env python3
"""
Generate a consolidated security HTML report from scanner artifacts.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
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


def _count_semgrep(report: Any) -> tuple[int, int, int, int]:
    if not isinstance(report, dict):
        return (0, 0, 0, 0)
    findings = report.get("results", [])
    high = sum(1 for i in findings if str(i.get("extra", {}).get("severity", "")).upper() == "ERROR")
    medium = sum(1 for i in findings if str(i.get("extra", {}).get("severity", "")).upper() == "WARNING")
    return (len(findings), high, medium, 0)


def _count_trivy(report: Any) -> tuple[int, int]:
    if not isinstance(report, dict):
        return (0, 0)
    high = 0
    critical = 0
    for result in report.get("Results", []):
        for vuln in result.get("Vulnerabilities", []) or []:
            sev = vuln.get("Severity", "")
            if sev == "HIGH":
                high += 1
            elif sev == "CRITICAL":
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


def generate_report(input_dir: Path, output_file: Path) -> None:
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

    safety_issues = len(safety_data) if isinstance(safety_data, list) else 0
    gitleaks_issues = len(gitleaks_data) if isinstance(gitleaks_data, list) else 0
    trufflehog_lines = _count_simple_lines(input_dir / "trufflehog-report" / "trufflehog-report.json")
    nuclei_lines = _count_simple_lines(input_dir / "nuclei-report" / "nuclei-report.json")

    critical = trivy_critical + grype_critical
    high = bandit_high + semgrep_high + trivy_high + grype_high
    medium = bandit_medium + semgrep_medium
    low = bandit_low + semgrep_low

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
  </style>
</head>
<body>
  <div class="wrap">
    <h1>SMDG Security Scan Report</h1>
    <p>Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC</p>
    <div class="cards">
      <div class="card critical"><b>Critical</b><br/>{critical}</div>
      <div class="card high"><b>High</b><br/>{high}</div>
      <div class="card medium"><b>Medium</b><br/>{medium}</div>
      <div class="card low"><b>Low</b><br/>{low}</div>
    </div>

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
  </div>
</body>
</html>
"""
    output_file.write_text(html, encoding="utf-8")
    print(f"Security summary generated: {output_file}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="reports", help="Directory with downloaded artifacts")
    parser.add_argument("--output", default="security-summary.html", help="Output HTML file")
    args = parser.parse_args()

    generate_report(Path(args.input), Path(args.output))


if __name__ == "__main__":
    main()
