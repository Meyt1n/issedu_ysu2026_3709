"""
No-redirect keyword scanner — HCT-004 compliance gate.

Scans frontend and backend source trees for prohibited keywords:
drug purchasing, teleconsultation, advertisements, commission flows, redirects.

Usage:
  uv run python scripts/scan_no_redirect.py [path]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Patterns that must NOT appear in source or dependency manifests.
# Grouped by category for readable output.
PROHIBITED: dict[str, list[str]] = {
    "drug_purchase": [
        "buy_medicine", "purchase_drug", "buy_drug", "purchase_medicine",
        "在线购药", "购买药品", "网上药店",
    ],
    "teleconsultation": [
        "online_consult", "telemedicine", "远程问诊", "在线问诊",
        "在线诊疗", "图文问诊", "视频问诊",
    ],
    "ad_redirect": [
        "ad_redirect", "adRedirect", "ad_link", "广告跳转",
        "广告链接", "推广链接",
    ],
    "commission": [
        "commission_link", "affiliate", "佣金链接", "返利链接",
        "推广佣金",
    ],
    "pharmacy": [
        "pharmacy_link", "pharmacy_url", "药店链接",
        "药房链接",
    ],
}


def scan_file(path: Path) -> list[str]:
    """Return list of violation descriptions for *path*."""
    violations: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return violations

    for category, keywords in PROHIBITED.items():
        for kw in keywords:
            if kw.lower() in text.lower():
                # Find line number for the first occurrence
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if kw.lower() in line.lower():
                        violations.append(
                            f"{path}:{lineno}: [{category}] prohibited keyword '{kw}' found"
                        )
                        break
    return violations


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    if not root.exists():
        print(f"ERROR: path not found: {root}", file=sys.stderr)
        return 1

    # Only scan source files and manifests, skip .git / node_modules / __pycache__ / venv
    skip_dirs = {
        ".git", "node_modules", "__pycache__", ".venv", "venv", ".tox",
        "dist", ".mypy_cache",
    }
    extensions = {
        ".py", ".ts", ".vue", ".js", ".json", ".toml", ".yaml", ".yml",
        ".md", ".html", ".css", ".env.example",
    }

    all_violations: list[str] = []
    for file_path in root.rglob("*"):
        if any(part in skip_dirs for part in file_path.parts):
            continue
        if file_path.suffix in extensions:
            all_violations.extend(scan_file(file_path))

    if all_violations:
        print(f"NO_REDIRECT_SCAN FAILED: {len(all_violations)} violation(s)")
        for v in all_violations:
            print(f"  {v}")
        return 1

    print("NO_REDIRECT_SCAN PASSED: 0 violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
