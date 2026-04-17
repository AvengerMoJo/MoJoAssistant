#!/usr/bin/env python3
"""
MoJoAssistant Preflight Checker
Validates system dependencies and MCP tool installation.
Run this before starting the service for the first time.

Usage:
    python scripts/preflight.py           # interactive: check + offer to fix
    python scripts/preflight.py --check   # check only, no install prompts
    python scripts/preflight.py --auto    # auto-install all non-manual items
"""

import argparse
import sys
from pathlib import Path

# Allow running from project root or scripts/ directory
_here = Path(__file__).resolve().parent
_project_root = _here.parent
sys.path.insert(0, str(_project_root))

from app.setup.preflight import PreflightChecker, PreflightItem

# ANSI colours
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_RED    = "\033[31m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_CYAN   = "\033[36m"
_DIM    = "\033[2m"


def _icon(status: str) -> str:
    return {"pass": f"{_GREEN}✓{_RESET}", "fail": f"{_RED}✗{_RESET}", "skip": f"{_YELLOW}−{_RESET}"}.get(status, "?")


def _print_header():
    print(f"\n{_BOLD}MoJoAssistant — Preflight Check{_RESET}")
    print("─" * 50)


def _print_item(item: PreflightItem):
    icon = _icon(item.status)
    source_tag = f"{_DIM}[{item.source}]{_RESET}"
    print(f"  {icon}  {item.name:<32} {source_tag}")
    if item.status == "fail":
        print(f"     {_DIM}↳ {item.detail}{_RESET}")


def _print_summary(summary: dict):
    print("─" * 50)
    total, passed, failed = summary["total"], summary["passed"], summary["failed"]
    if summary["ready"]:
        print(f"{_GREEN}{_BOLD}All {total} checks passed — MoJoAssistant is ready.{_RESET}\n")
    else:
        print(f"{_RED}{_BOLD}{failed} of {total} checks failed.{_RESET}  "
              f"{_GREEN}{passed} passed{_RESET}.\n")


def _offer_install(item: PreflightItem, auto: bool) -> bool:
    """
    Offer to install a failed item. Returns True if the fix was attempted.
    """
    print(f"\n  {_CYAN}Fix available:{_RESET} {item.name}")
    if item.manual:
        print(f"  {_YELLOW}Manual step required:{_RESET}")
        print(f"    {_BOLD}{item.hint}{_RESET}")
        print(f"  {_DIM}Run the command above, then re-run preflight.{_RESET}")
        return False

    print(f"  Command: {_BOLD}{item.hint}{_RESET}")
    if auto:
        run = True
    else:
        answer = input("  Run this command now? [y/N] ").strip().lower()
        run = answer in ("y", "yes")

    if run:
        print(f"  {_DIM}Running...{_RESET}", flush=True)
        success, output = PreflightChecker().install_item(item)
        if success:
            print(f"  {_GREEN}Done.{_RESET}" + (f" {_DIM}{output[:120]}{_RESET}" if output else ""))
        else:
            print(f"  {_RED}Failed:{_RESET} {output[:200]}")
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="MoJoAssistant preflight checker")
    parser.add_argument("--check", action="store_true", help="Check only — no install prompts")
    parser.add_argument("--auto",  action="store_true", help="Auto-install all non-manual items without prompting")
    parser.add_argument("--json",  action="store_true", help="Output results as JSON (for MCP integration)")
    args = parser.parse_args()

    checker = PreflightChecker()

    if args.json:
        import json
        items = checker.check_all()
        summary = checker.summary(items)
        out = {
            "summary": summary,
            "items": [
                {
                    "name": i.name,
                    "source": i.source,
                    "status": i.status,
                    "detail": i.detail,
                    "hint": i.hint,
                    "manual": i.manual,
                }
                for i in items
            ],
        }
        print(json.dumps(out, indent=2))
        sys.exit(0 if summary["ready"] else 1)

    _print_header()

    # First pass: run all checks
    items = checker.check_all()
    for item in items:
        _print_item(item)

    summary = checker.summary(items)
    _print_summary(summary)

    if summary["ready"] or args.check:
        sys.exit(0 if summary["ready"] else 1)

    # Second pass: offer fixes for failed items
    failed = [i for i in items if i.status == "fail"]
    if failed:
        print(f"{_BOLD}Fixing {len(failed)} issue(s):{_RESET}")

    attempted = []
    for item in failed:
        _offer_install(item, auto=args.auto)
        attempted.append(item.name)

    if attempted:
        # Re-run checks after installs
        print(f"\n{_BOLD}Re-checking...{_RESET}")
        items2 = checker.check_all()
        for item in items2:
            _print_item(item)
        summary2 = checker.summary(items2)
        _print_summary(summary2)
        sys.exit(0 if summary2["ready"] else 1)

    sys.exit(0 if summary["ready"] else 1)


if __name__ == "__main__":
    main()
