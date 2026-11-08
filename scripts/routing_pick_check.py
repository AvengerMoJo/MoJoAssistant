#!/usr/bin/env python3
"""
routing_pick_check.py — show which resource the pool would pick, and why the others were passed over.

READ-ONLY inspection of the routing decision. It asks the pool for its
`selection_order()` — the same call the scheduler's `acquire()` ranks candidates with — so the
order printed here cannot drift from the order the scheduler would pick. It never acquires a
resource, never disables, excludes or re-ranks one, and never writes the pool config.

Usage:
    python scripts/routing_pick_check.py
    python scripts/routing_pick_check.py --tiers free,free_api --min-context 128000
    python scripts/routing_pick_check.py --tiers free,free_api,paid --min-output 4096
    python scripts/routing_pick_check.py --json

Options:
    --tiers free,free_api,paid   tier list to allow (default: free,free_api — the pool's own default)
    --min-context 128000         only resources whose context window is at least this
    --min-output 4096            only resources whose output limit is at least this
    --max-data-scope public      only resources whose data scope is at most this wide
    --json                       machine-readable output (one JSON object)

Exit codes:
    0 — a resource would be picked
    2 — nothing would be picked (every resource is excluded; the reasons are printed)
    1 — the pool could not be loaded

Run it from anywhere; the script moves to the project root itself, because the pool config is
read from a path relative to the project root (config/resource_pool.json plus the personal
layer ~/.memory/config/resource_pool.json).
"""
import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_TIERS = "free,free_api"


def parse_tiers(raw: str):
    """Tier names -> ResourceTier values. An unknown name is an error, not a silent default."""
    from app.scheduler.resource_pool import ResourceTier

    by_name = {t.value: t for t in ResourceTier}
    tiers = []
    for part in (raw or "").split(","):
        name = part.strip()
        if not name:
            continue
        if name not in by_name:
            raise SystemExit(f"unknown tier {name!r} (known tiers: {', '.join(sorted(by_name))})")
        tiers.append(by_name[name])
    if not tiers:
        raise SystemExit("no tiers given")
    return tiers


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only: show the pool's selection order and the first resource it would pick")
    parser.add_argument("--tiers", default=DEFAULT_TIERS,
                        help="comma-separated tier list (default: %(default)s)")
    parser.add_argument("--min-context", type=int, default=0,
                        help="require at least this context window (default: %(default)s)")
    parser.add_argument("--min-output", type=int, default=0,
                        help="require at least this output limit (default: %(default)s)")
    parser.add_argument("--max-data-scope", default=None,
                        help="only resources whose data scope is at most this wide (local|lan|tailnet|public)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    # The pool reads config/resource_pool.json relative to the project root.
    os.chdir(PROJECT_ROOT)

    tiers = parse_tiers(args.tiers)

    from app.scheduler.resource_pool import ResourceManager

    try:
        rm = ResourceManager()
    except Exception as e:
        print(f"could not load the resource pool: {e}", file=sys.stderr)
        return 1

    rows = rm.selection_order(
        tier_preference=tiers,
        min_context=args.min_context,
        min_output=args.min_output,
        max_data_scope=args.max_data_scope,
    )
    eligible = [r for r in rows if r["eligible"]]
    excluded = [r for r in rows if not r["eligible"]]
    first = eligible[0] if eligible else None

    if args.json:
        print(json.dumps({
            "tiers": [t.value for t in tiers],
            "min_context": args.min_context,
            "min_output": args.min_output,
            "max_data_scope": args.max_data_scope,
            "selection_order": rows,
            "first_pick": first,
            "eligible_count": len(eligible),
            "excluded_count": len(excluded),
        }, indent=2))
        return 0 if first else 2

    print("Routing pick check (read-only — nothing was acquired, disabled, excluded or re-ranked)")
    print(f"  tiers          : {', '.join(t.value for t in tiers)}")
    print(f"  min_context    : {args.min_context}")
    print(f"  min_output     : {args.min_output}")
    if args.max_data_scope:
        print(f"  max_data_scope : {args.max_data_scope}")
    print(f"  resources      : {len(eligible)} eligible of {len(rows)} configured")
    print()

    print("Selection order (eligible first, in the order acquire() would try them):")
    for row in eligible:
        flags = []
        if row.get("cold_load_penalty"):
            flags.append("cold")
        if row.get("busy"):
            flags.append("busy")
        flag_text = f"  [{', '.join(flags)}]" if flags else ""
        print(f"  {row.get('position')}. {row['id']}  tier={row.get('tier')}  model={row.get('model')}  "
              f"priority={row.get('effective_priority')}{flag_text}")

    if excluded:
        print()
        print("Passed over (the reason acquire() would skip them):")
        for row in excluded:
            print(f"  -  {row['id']}  tier={row.get('tier')}  model={row.get('model')}  "
                  f"because: {row.get('excluded_because')}")

    print()
    if first:
        print(f"First resource that would be picked: {first['id']}  "
              f"(model={first.get('model')}, tier={first.get('tier')})")
        return 0
    print("First resource that would be picked: none — every resource is excluded (see the reasons above)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
