#!/usr/bin/env python3
"""
agentic_cli.py — Unified CLI for MoJoAssistant agentic operations

Sub-commands:
  resource  detect|show|add|add-cloud|remove   (delegates to resource_config.py)
  tasks     list|resume                         (reads scheduler_tasks.json)
  pool      status                              (personal resource pool summary)

Examples:
    python scripts/agentic_cli.py resource detect --suggest
    python scripts/agentic_cli.py resource add lmstudio_qwen_qwen3_5_35b_a3b
    python scripts/agentic_cli.py resource add-cloud gemini --api-key AIza...
    python scripts/agentic_cli.py tasks list
    python scripts/agentic_cli.py tasks resume <task_id> --reply yes
    python scripts/agentic_cli.py pool status
"""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

SCHEDULER_TASKS = Path.home() / ".memory" / "scheduler_tasks.json"
PERSONAL_POOL   = Path.home() / ".memory" / "config" / "resource_pool.json"


# ---------------------------------------------------------------------------
# tasks sub-commands
# ---------------------------------------------------------------------------

def tasks_list(args):
    if not SCHEDULER_TASKS.exists():
        print("No scheduler_tasks.json found.")
        return
    data = json.loads(SCHEDULER_TASKS.read_text())
    tasks = data.get("tasks", {})
    status_order = {"running": 0, "pending": 1, "waiting_for_input": 2,
                    "completed": 3, "failed": 4}
    rows = sorted(tasks.values(), key=lambda t: status_order.get(t["status"], 9))
    print(f"{'ID':12s} {'STATUS':22s} {'ROLE':18s} GOAL")
    for t in rows:
        goal = (t.get("config", {}).get("goal") or "")[:55]
        role = t.get("config", {}).get("role_id") or ""
        print(f"{t['id'][:12]:12s} {t['status']:22s} {role:18s} {goal}")


def tasks_resume(args):
    if not SCHEDULER_TASKS.exists():
        print("No scheduler_tasks.json found.")
        return
    data = json.loads(SCHEDULER_TASKS.read_text())
    tasks = data["tasks"]
    t = tasks.get(args.task_id)
    if not t:
        print(f"Task '{args.task_id}' not found.")
        sys.exit(1)
    if t["status"] != "waiting_for_input":
        print(f"Task is '{t['status']}', not waiting_for_input.")
        sys.exit(1)
    t["status"] = "pending"
    t["pending_question"] = None
    t.setdefault("config", {})["reply_to_question"] = args.reply
    SCHEDULER_TASKS.write_text(json.dumps(data, indent=2))
    print(f"Resumed {args.task_id} with reply: {args.reply}")


# ---------------------------------------------------------------------------
# pool sub-commands
# ---------------------------------------------------------------------------

def pool_status(args):
    pool = {}
    if PERSONAL_POOL.exists():
        pool = json.loads(PERSONAL_POOL.read_text()).get("resources", {})
    if not pool:
        print("Personal pool empty. Run: agentic_cli.py resource detect --suggest")
        return
    print(f"{'RESOURCE':35s} {'TIER':12s} {'PRI':4s} {'ON':3s} MODEL")
    for rid, entry in sorted(pool.items(), key=lambda x: x[1].get("priority", 99)):
        enabled = "✓" if entry.get("enabled", True) else "✗"
        tier = entry.get("tier", "?")
        pri = str(entry.get("priority", "?"))
        model = entry.get("model") or "(dynamic)"
        print(f"{rid[:35]:35s} {tier:12s} {pri:>4s} {enabled:3s} {model}")


# ---------------------------------------------------------------------------
# resource sub-command — delegates to resource_config.py
# ---------------------------------------------------------------------------

def resource_delegate(args):
    rc = Path(__file__).parent / "resource_config.py"
    cmd = [sys.executable, str(rc)] + args.resource_args
    sys.exit(subprocess.call(cmd))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="MoJoAssistant agentic CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="group", required=True)

    # resource
    p_res = sub.add_parser("resource", help="Resource pool management (detect/add/remove)")
    p_res.add_argument("resource_args", nargs=argparse.REMAINDER)
    p_res.set_defaults(func=resource_delegate)

    # tasks
    p_tasks = sub.add_parser("tasks", help="Scheduler task management")
    tasks_sub = p_tasks.add_subparsers(dest="tasks_cmd", required=True)

    p_tlist = tasks_sub.add_parser("list", help="List all tasks by status")
    p_tlist.set_defaults(func=tasks_list)

    p_tres = tasks_sub.add_parser("resume", help="Resume a waiting_for_input task")
    p_tres.add_argument("task_id")
    p_tres.add_argument("--reply", default="yes", help="Reply to inject (default: yes)")
    p_tres.set_defaults(func=tasks_resume)

    # pool
    p_pool = sub.add_parser("pool", help="Resource pool status")
    pool_sub = p_pool.add_subparsers(dest="pool_cmd", required=True)
    p_pstatus = pool_sub.add_parser("status", help="Show all pool entries")
    p_pstatus.set_defaults(func=pool_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
