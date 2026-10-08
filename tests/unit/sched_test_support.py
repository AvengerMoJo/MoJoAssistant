"""Wiring for tests that build a bare Scheduler via __new__ (they bypass __init__).

Run tracking state is created in __init__; without this helper a hand-built scheduler has
no ledger and the run-recording `finally` would raise. The ledger points at a temp dir so
tests can never write to the user's real ~/.memory/runs.
"""
import tempfile
from pathlib import Path

from app.scheduler.run_ledger import RunLedger


def wire_run_tracking(scheduler):
    tmp = tempfile.TemporaryDirectory()
    scheduler._tmp_ledger_dir = tmp  # keep alive for the scheduler's lifetime
    scheduler._run_ledger = RunLedger(Path(tmp.name) / "runs")
    scheduler._run_notes = {}
    scheduler._harvested_task_ids = set()
    return scheduler
