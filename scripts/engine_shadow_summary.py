#!/usr/bin/env python3
"""Where does the credential engine's ranking disagree with MoJoAssistant's own table?

  venv/bin/python scripts/engine_shadow_summary.py            # last 24h
  venv/bin/python scripts/engine_shadow_summary.py --hours 168

Reads ~/.memory/state/engine_shadow.jsonl (written when "shadow_engine_selection": true in resource_pool.json).
Agreement counts an exact match and a pick inside the same account group (round-robin). A disagreement is shown
with the engine's reason for not ranking MoJo's pick first, and split into EXPECTED (the engine has the resource
disabled for no credential -- it is not migrated yet) and REAL (needs a look before the engine can take over).
Engine errors are counted separately: they are not disagreements.
"""
import argparse
import json
import time
from collections import Counter
from pathlib import Path

LOG = Path.home() / ".memory" / "state" / "engine_shadow.jsonl"


def main(hours: float) -> int:
    if not LOG.exists():
        print("no shadow log yet (is shadow_engine_selection on, and has anything been acquired?)")
        return 1
    horizon, rows = time.time() - hours * 3600, []
    for line in LOG.read_text().splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d["t"] >= horizon:
            rows.append(d)
    if not rows:
        print(f"no rows in the last {hours:g}h")
        return 1
    by = Counter(r["level"] for r in rows)
    judged = [r for r in rows if r["level"] in ("exact", "same_group", "differs", "engine_none")]
    agree = by["exact"] + by["same_group"]
    print(f"last {hours:g}h: {len(rows)} comparisons | exact {by['exact']} | same account group {by['same_group']} | "
          f"differs {by['differs']} | engine had nothing {by['engine_none']} | engine errors {by['engine_error']}")
    if judged:
        print(f"agreement: {100 * agree / len(judged):.1f}% of {len(judged)} answered picks")
    pairs: dict = {}
    for r in judged:
        if r["level"] in ("differs", "engine_none"):
            k = (r["mojo"], r.get("engine"))
            e = pairs.setdefault(k, {"n": 0, "why": Counter(), "pos": []})
            e["n"] += 1
            e["why"][r.get("engine_excluded_mojo") or ("engine ranks it #%s" % r.get("mojo_position_in_engine"))] += 1
    exp = real = 0
    if pairs:
        print("\ndisagreements (MoJo picked -> engine would pick):")
        for (m, e), v in sorted(pairs.items(), key=lambda kv: -kv[1]["n"])[:12]:
            why, n = v["why"].most_common(1)[0]
            expected = "no credential" in why
            exp += v["n"] if expected else 0
            real += 0 if expected else v["n"]
            print(f"  {v['n']:>4}x  {m}  ->  {e}   [{'EXPECTED' if expected else 'REAL'}] {why}")
        print(f"\nexpected (not migrated yet): {exp} | real (needs a look): {real}")
    errs = [r for r in rows if r["level"] == "engine_error"]
    if errs:
        print(f"\nengine errors: {len(errs)}; latest: {errs[-1]['engine_error']}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    raise SystemExit(main(ap.parse_args().hours))
