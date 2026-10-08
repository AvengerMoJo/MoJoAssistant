#!/usr/bin/env python3
"""End-to-end probe of the RUNNING scheduler.

Unit tests passed (1,400+) while three production blockers existed -- `lms` missing from the systemd
PATH, blocking calls freezing the event loop, stale resume state in recurring jobs. Only real
scheduled runs exposed them. This script is that check, repeatable: it adds small read-only,
ephemeral tasks to the live service over its local MCP endpoint, waits for them to run, and verifies
each outcome against the run ledger and against ground truth it computes itself.

Scenarios
  tier_path          a role without resource_requirements runs a tool and answers correctly
  requirements_path  a role with resource_requirements (paul) reads a file and answers correctly
  pinned_failure     a task pinned to a nonexistent resource fails explicitly (no silent fallback)
  cron_timeout       a recurring task that exceeds its wall-clock limit is cut off on time and
                     put back on its schedule (not left dead)

Usage:  scripts/scheduler_e2e_probe.py [--url http://127.0.0.1:8000/] [--keep]
Needs MCP_API_KEY (environment or the repo's .env). Exit status 0 only if every scenario passed.
Nothing here writes to long-term memory: the tasks are marked ephemeral.
"""
import argparse
import json
import os
import socket
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_key() -> str:
    key = os.environ.get("MCP_API_KEY")
    if key:
        return key
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("MCP_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("MCP_API_KEY not found in the environment or .env")


class Client:
    def __init__(self, url: str, key: str):
        self.url, self.key, self._id = url, key, 0

    def call(self, tool: str, **arguments):
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                           "params": {"name": tool, "arguments": arguments}}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json", "MCP-API-Key": self.key})
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.load(resp)
        text = payload["result"]["content"][0]["text"]
        try:
            return json.loads(text)
        except ValueError:
            return {"raw": text}


def add_task(c: Client, tid, goal, role, tools, delay_s=3, cron=None, iterations=6, **config):
    args = {
        "action": "add", "task_id": tid, "type": "internal_assignment", "goal": goal, "role_id": role,
        "available_tools": tools, "max_iterations": iterations, "priority": "high",
        "schedule": (datetime.now() + timedelta(seconds=delay_s)).isoformat(timespec="seconds"),
        "config": {"ephemeral": True, "notify_on_completion": False, **config},
    }
    if cron:
        args["cron"] = cron
    result = c.call("scheduler", **args)
    if result.get("status") not in ("success", "ok"):
        raise RuntimeError(f"could not add {tid}: {result}")


def wait_for_run(c: Client, tid, timeout_s):
    """First ledger entry for the task, or None."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        runs = c.call("scheduler", action="runs", task_id=tid, limit=3).get("runs") or []
        if runs:
            return runs[0]
        time.sleep(5)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/")
    ap.add_argument("--keep", action="store_true", help="leave the probe tasks in the queue")
    ap.add_argument("--timeout", type=int, default=420, help="seconds to wait per scenario")
    args = ap.parse_args()
    c = Client(args.url, load_key())

    tag = datetime.now().strftime("%H%M%S")
    n_projects = len(list((Path.home() / ".memory" / "projects").glob("*.json")))
    hostname = socket.gethostname()
    ids = {
        "tier_path": f"probe_tier_{tag}", "requirements_path": f"probe_req_{tag}",
        "pinned_failure": f"probe_pinned_{tag}", "cron_timeout": f"probe_cron_{tag}",
    }
    try:
        add_task(c, ids["tier_path"], "Use bash_exec to run: ls ~/.memory/projects | wc -l . Then give your final answer stating that number. "
                 "Done when: the final answer contains the number the command returned. Read-only: change nothing.",
                 "carl", ["bash_exec"])
        add_task(c, ids["requirements_path"], "Use read_file on /etc/hostname and state the host name it contains in your final answer. "
                 "Done when: the final answer contains the host name. Read-only: change nothing.", "paul", ["read_file"])
        add_task(c, ids["pinned_failure"], "Use bash_exec to run: echo hi . Read-only: change nothing.", "carl", ["bash_exec"],
                 pinned_resource="resource_that_does_not_exist")
        add_task(c, ids["cron_timeout"], "Use bash_exec to run: sleep 50 . Then say done. Read-only: change nothing.", "carl",
                 ["bash_exec"], cron="0 0 1 1 *", max_duration_seconds=15)
    except Exception as e:
        print(f"setup failed: {e}")
        return 2

    results = []

    def check(name, ok, detail):
        results.append((name, ok, detail))

    runs = {name: wait_for_run(c, tid, args.timeout) for name, tid in ids.items()}

    r = runs["tier_path"]
    check("tier_path", bool(r) and r["outcome"] == "completed" and str(n_projects) in json.dumps(
        c.call("scheduler", action="get", task_id=ids["tier_path"])),
        f"outcome={r and r['outcome']} resources={r and r.get('resources')} expected answer to contain {n_projects}")
    r = runs["requirements_path"]
    got = json.dumps(c.call("scheduler", action="get", task_id=ids["requirements_path"]))
    check("requirements_path", bool(r) and r["outcome"] == "completed" and hostname in got,
          f"outcome={r and r['outcome']} resources={r and r.get('resources')} expected host name {hostname!r}")
    r = runs["pinned_failure"]
    check("pinned_failure", bool(r) and r["outcome"] in ("failed", "failed_will_retry") and r.get("error_class") == "pinned_resource_unavailable",
          f"outcome={r and r['outcome']} error_class={r and r.get('error_class')}")
    r = runs["cron_timeout"]
    task = c.call("scheduler", action="get", task_id=ids["cron_timeout"])
    blob = json.dumps(task)
    next_year = str(datetime.now().year + (0 if datetime.now().month == 1 and datetime.now().day == 1 else 1))
    check("cron_timeout", bool(r) and r["outcome"] == "timed_out" and r["duration_s"] < 60 and next_year in blob and "pending" in blob,
          f"outcome={r and r['outcome']} duration={r and r['duration_s']}s (limit 15s) rescheduled_to_{next_year}={next_year in blob}")

    if not args.keep:
        for tid in ids.values():
            c.call("scheduler", action="remove", task_id=tid)

    width = max(len(n) for n, _, _ in results)
    print(f"\nscheduler end-to-end probe @ {datetime.now():%Y-%m-%d %H:%M:%S}")
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} scenarios passed" + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
