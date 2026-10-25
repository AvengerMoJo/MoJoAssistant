#!/usr/bin/env python3
"""Weekly and monthly resource-utilization report -- the evidence to read BEFORE ordering more subscription.

  venv/bin/python scripts/credential_engine_report.py            # prints 7-day and 30-day views, saves a markdown copy
  venv/bin/python scripts/credential_engine_report.py --days 7   # one period

Calls the credential engine's utilization_report (owner scope). Per renewing allowance: the plan's limit, the
agent's share (after the reserve kept for the owner), mean and peak % of that share used per COMPLETED cycle, %
left unspent at each reset, and cap hits -- plus a verdict: buy_more only when most of the share was used AND the
cap was hit (real refused demand); underused when little was used; insufficient_data until a cycle has completed.
History starts when recording began, so the first weeks say so rather than guess. Shared pools (an OpenRouter
account's daily 1000) are shown once, not once per model. The markdown copy goes to ~/.memory/research/.
"""
import argparse
import asyncio
import datetime
import json
import sys
from pathlib import Path

SIB = Path.home() / "Development" / "Personal"
sys.path[:0] = [str(SIB / "ai-credential-manager"), str(SIB / "ai-resource-manager")]
from credential_manager.owner_client import ServiceClient  # noqa: E402

OWNER_CLIENT = Path.home() / ".config" / "ai-credential-manager" / "owner_admin_client.json"
RESEARCH = Path.home() / ".memory" / "research"
OVERFLOW_LOG = Path.home() / ".memory" / "state" / "resource_overflow.jsonl"
INCIDENT_LOG = Path.home() / ".memory" / "state" / "task_incidents.jsonl"


def _fmt(v, suffix="%"):
    return "-" if v is None else f"{v}{suffix}"


def rows_of(report: dict):
    """One row per distinct allowance: a resource's own windows, or a shared pool once. The verdict belongs to the
    resource, so it is printed on its longest window's row only (rolling windows are caps, not the verdict's subject)."""
    seen, rows = set(), []
    for rid, r in sorted(report["resources"].items()):
        spans = [w.get("span_s", 0) for w in r["windows"]]
        longest = max(spans, default=0)
        for w in r["windows"]:
            pooled = "/" in w["window"]
            ident = w["window"] if pooled else f"{rid}:{w['window']}"
            if ident in seen:
                continue
            seen.add(ident)
            lead = w.get("span_s", 0) == longest
            cur = w.get("current") or {}
            rows.append({"who": w["window"].split("/")[0] if pooled else rid, "window": w["window"].split("/")[-1],
                         "share": w["agent_share"], "capacity": w.get("capacity"), "unit": w.get("capacity_unit"),
                         "cycles": w["cycles_complete"], "mean": w["mean_util_pct"], "peak": w["peak_util_pct"],
                         "unspent": w.get("mean_unspent_pct"), "caps": w["cap_hits"],
                         "now": cur.get("util_pct"), "elapsed": cur.get("elapsed_pct"), "proj": cur.get("projected_util_pct") if lead else None,
                         "verdict": r["verdict"] if lead else "", "why": r["why"] if lead else "",
                         "calls": r["calls"], "failed": r["failed"]})
    return rows


def overflow_section(days: float) -> list:
    """Refused demand: picks where an allowance that would have ranked first was used up and something else served.
    A cap hit alone only shows the share was spent (rank 0 spends it on purpose); an overflow shows work that wanted it."""
    import time
    if not OVERFLOW_LOG.exists():
        return ["", "### Overflow (demand an exhausted allowance could not serve)", "", "No overflow log yet."]
    horizon, by = time.time() - days * 86400, {}
    for line in OVERFLOW_LOG.read_text().splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d["t"] < horizon:
            continue
        for rid, why, _rank in d["displaced"]:
            e = by.setdefault(rid, {"n": 0, "paid": 0, "served": {}})
            e["n"] += 1
            e["paid"] += d["chosen_tier"] == "paid"
            e["served"][d["chosen"]] = e["served"].get(d["chosen"], 0) + 1
    out = ["", "### Overflow (demand an exhausted allowance could not serve)", ""]
    if not by:
        return out + ["None in this period: nothing was refused for lack of allowance."]
    out += ["| allowance | times skipped (exhausted) | served by a paid resource | mostly served by |", "|---|---|---|---|"]
    for rid, e in sorted(by.items(), key=lambda kv: -kv[1]["n"]):
        top = max(e["served"], key=e["served"].get)
        out.append(f"| {rid} | {e['n']} | {e['paid']} | {top} ({e['served'][top]}) |")
    out.append("")
    out.append("Read buy_more together with this: a recurring limit PLUS skips that landed on paid resources is the real case for a bigger plan.")
    return out


def usage_section(usage: dict) -> list:
    """What was actually called, from the engine's call ledger. Token totals cover only the calls that reported
    counts; the last column says how many did not, so a total is never read as complete when it is not."""
    rows = usage["usage"]
    out = ["", "### Usage (call ledger)", ""]
    if not rows:
        return out + ["No calls in the ledger for this period."]
    out += ["| client | task class | resource | calls | failed | tokens in | tokens out | calls w/o token counts | avg ms |",
            "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: -r["calls"]):
        out.append(f"| {r['client']} | {r['task_class']} | {r['resource']} | {r['calls']} | {r['failed']} | {r['tokens_in']:,} "
                   f"| {r['tokens_out']:,} | {r['calls_without_token_counts']} | {_fmt(r['avg_duration_ms'], '')} |")
    tin, tout = sum(r["tokens_in"] for r in rows), sum(r["tokens_out"] for r in rows)
    out += ["", f"Total: {sum(r['calls'] for r in rows)} calls, {tin:,} tokens in, {tout:,} tokens out "
                "(estimates for budgeting: providers count tokens their own way, and some calls report none)."]
    return out


def unmet_section(unmet: dict) -> list:
    """Asks refused because no resource had a fresh, sufficient profile -- the list of what to measure next."""
    out = ["", "### Unmet demand (asks no profiled resource could serve)", ""]
    rows = unmet["unmet"]
    if not rows:
        return out + ["None in this period."]
    out += ["| task class | profile | demand | refusals | to measure / shortfall |", "|---|---|---|---|---|"]
    for g in rows:
        todo = "; ".join(f"{rid}: {why}" for rid, why in sorted(g["to_measure"].items()))
        out.append(f"| {g['task_class'] or '-'} | {g['profile'] or '-'} | {g['demand']} | {g['refusals']} | {todo} |")
    out += ["", "unknown = measure it; expired = measure it again; insufficient = a real shortfall (a stronger resource is needed)."]
    return out


def incident_section(days: float) -> list:
    """Failures inside task runs (a provider refusing a call), including runs that finished anyway after a retry."""
    import time
    out = ["", "### Task incidents (failures inside runs, even ones that finished)", ""]
    if not INCIDENT_LOG.exists():
        return out + ["No incident log yet."]
    horizon, by = time.time() - days * 86400, {}
    for line in INCIDENT_LOG.read_text().splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d["t"] >= horizon:
            by.setdefault((d["kind"], d["resource"], d.get("last_tool") or "-"), []).append(d["task_id"])
    if not by:
        return out + ["None in this period."]
    out += ["| kind | resource | last tool before it | times | example task |", "|---|---|---|---|---|"]
    for (kind, rid, tool), tasks in sorted(by.items(), key=lambda kv: -len(kv[1])):
        out.append(f"| {kind} | {rid} | {tool} | {len(tasks)} | {tasks[-1]} |")
    return out


def render(report: dict) -> str:
    d = report["period_days"]
    t = report["thresholds"]
    lines = [f"## Last {d:g} days ({'weekly' if d <= 7 else 'monthly'} view)", "",
             "| allowance | window | limit | share | cycles done | mean used | peak | unspent | cap hits | now (elapsed) | verdict |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows_of(report):
        cap = f"{r['capacity']:,.0f} {r['unit']}" if r["capacity"] else "-"
        now = f"{r['now']}% ({r['elapsed']}%)" + (f" -> ~{r['proj']}%" if r["proj"] else "") if r["now"] is not None else "-"
        lines.append(f"| {r['who']} | {r['window']} | {cap} | {r['share']} | {r['cycles']} | {_fmt(r['mean'])} | {_fmt(r['peak'])} "
                     f"| {_fmt(r['unspent'])} | {r['caps']} | {now} | {('**' + r['verdict'] + '**') if r['verdict'] else ''} |")
    lines += [""] + [f"- **{r['who']}**: {r['why']}" for r in rows_of(report) if r["why"]] + [""]
    lines += [
              f"Verdict rule: buy_more = the longest window averaged >= {t['buy_more_if_mean_util_at_least']}% of the agent's share AND hit its cap, "
        f"OR any window (e.g. a 5h block) hit its cap in >= 50% of at least 5 active cycles -- a recurring limit even if the week is empty. "
        f"underused = the longest window averaged < {t['underused_if_mean_util_below']}% and no window hit its cap in 25%+ of its active cycles. "
        f"A greedy rank-0 policy fills allowances on purpose, so a cap hit shows the share was used, not that work was refused: "
        f"read buy_more together with whether tasks overflowed to paid resources. "
        f"Calls over the period (engine usage log): {sum(r['calls'] for r in report['resources'].values())} reported, "
        f"{sum(r['failed'] for r in report['resources'].values())} failed."]
    return "\n".join(lines)


async def main(days_list) -> int:
    client = ServiceClient.from_file(OWNER_CLIENT)
    tenant = json.loads(OWNER_CLIENT.read_text())["tenant_id"]
    admin = f"admin:vault:manage:{tenant}"
    parts = [f"# Resource utilization report -- {datetime.date.today()}", "",
             "Evidence for subscription decisions. Allowances only appear once they report to the credential engine; "
             "history begins when snapshot recording began, so early periods are mostly `insufficient_data`.", ""]
    for d in days_list:
        parts += [render(await client.call("utilization_report", admin, days=d))] + usage_section(await client.call("usage_summary", admin, days=d)) + unmet_section(await client.call("unmet_demand_report", admin, days=d)) + overflow_section(d) + incident_section(d) + [""]
    text = "\n".join(parts)
    print(text)
    RESEARCH.mkdir(parents=True, exist_ok=True)
    out = RESEARCH / f"resource_utilization_{datetime.date.today()}.md"
    out.write_text(text)
    print(f"\nsaved {out}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, action="append", help="period in days (default: 7 and 30)")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.days or [7, 30])))
