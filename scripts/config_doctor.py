#!/usr/bin/env python3
"""
Config Doctor CLI

Validates all runtime configuration and reports errors/warnings.

Usage:
    python3 scripts/config_doctor.py              # text output
    python3 scripts/config_doctor.py --json       # JSON output
    python3 scripts/config_doctor.py --errors-only  # only show errors/warnings

Exit codes:
    0 — no errors (warnings are OK)
    1 — one or more errors found
"""

import argparse
import json
import sys
import os

# Ensure project root is on the path when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ansi(code: str) -> str:
    """Return ANSI escape code if stdout is a tty."""
    return f"\033[{code}m" if sys.stdout.isatty() else ""


RED = _ansi("31")
YELLOW = _ansi("33")
GREEN = _ansi("32")
RESET = _ansi("0")
BOLD = _ansi("1")


def main():
    parser = argparse.ArgumentParser(description="Validate MoJoAssistant runtime configuration")
    parser.add_argument("--json", action="store_true", help="Output raw JSON report")
    parser.add_argument("--errors-only", action="store_true", help="Show only errors and warnings")
    args = parser.parse_args()

    from app.config.doctor import ConfigDoctor
    doctor = ConfigDoctor()
    report = doctor.run_all_checks()
    data = report.to_dict()

    if args.json:
        print(json.dumps(data, indent=2))
        sys.exit(1 if data["summary"]["errors"] > 0 else 0)

    # Pretty text output
    icon_map = {"pass": f"{GREEN}✓{RESET}", "warn": f"{YELLOW}⚠{RESET}", "error": f"{RED}✗{RESET}"}

    checks = data["checks"]
    if args.errors_only:
        checks = [c for c in checks if c["status"] != "pass"]

    # Group by category
    by_category: dict = {}
    for c in checks:
        by_category.setdefault(c["category"], []).append(c)

    for category, items in sorted(by_category.items()):
        print(f"\n{BOLD}[{category.upper()}]{RESET}")
        for c in items:
            icon = icon_map.get(c["status"], "?")
            val_str = f" = {c['value']!r}" if c["value"] is not None else ""
            print(f"  {icon}  {c['id']}.{c['field']}{val_str}")
            print(f"       {c['message']}")

    summary = data["summary"]
    print()
    print(f"{BOLD}Summary:{RESET} "
          f"{RED}{summary['errors']} error(s){RESET}  "
          f"{YELLOW}{summary['warnings']} warning(s){RESET}  "
          f"{GREEN}{summary['passed']} passed{RESET}  "
          f"({summary['total']} total)")

    sys.exit(1 if summary["errors"] > 0 else 0)


if __name__ == "__main__":
    main()
