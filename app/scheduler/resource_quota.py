"""Renewing-quota windows for subscription-style resources.

Dependency-free (stdlib only) so it can move into the standalone resource /
credential manager unchanged.

Some providers sell a subscription with a free allowance that renews on a
schedule -- every 5 hours, weekly, monthly -- and several of those limits can
apply to the same key at once. A resource carries a list of windows; it is
usable only while EVERY window still has room.

Window kinds:
  rolling  - the last `seconds` seconds; capacity returns call by call.
  fixed    - consecutive `seconds`-long blocks counted from `anchor` (epoch
             seconds of any past reset); everything renews at the block edge.
  monthly  - renews at 00:00 UTC on `reset_day` (1-28) of each month.

Only calls the provider actually served should be recorded by the caller;
this module just counts the timestamps it is given.
"""
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

KINDS = ("rolling", "fixed", "monthly")
_MONTHLY_LOOKBACK = 31 * 86400


@dataclass(frozen=True)
class QuotaWindow:
    name: str
    max_calls: int
    kind: str = "rolling"
    seconds: int = 0
    anchor: Optional[float] = None
    reset_day: int = 1
    # Share of the allowance kept for the owner's own use outside this system
    # (their interactive sessions draw on the same plan but are not recorded here).
    reserved_for_user_pct: float = 0.0

    @property
    def agent_limit(self) -> int:
        return math.floor(self.max_calls * (100 - self.reserved_for_user_pct) / 100)


@dataclass
class WindowStatus:
    name: str
    kind: str
    used: int
    agent_limit: int
    max_calls: int
    window_start: float
    resets_at: Optional[float]
    exhausted: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_windows(raw: Optional[Sequence[Dict[str, Any]]]) -> List[QuotaWindow]:
    """Build windows from config. Raises ValueError on any bad entry -- a
    quota that is silently ignored would let the resource overspend."""
    windows: List[QuotaWindow] = []
    names = set()
    for i, w in enumerate(raw or []):
        if not isinstance(w, dict):
            raise ValueError(f"quotas[{i}] must be an object, got {type(w).__name__}")
        name = w.get("name")
        if not name or name in names:
            raise ValueError(f"quotas[{i}]: 'name' is required and must be unique")
        names.add(name)
        kind = w.get("kind", "rolling")
        if kind not in KINDS:
            raise ValueError(f"quota '{name}': kind must be one of {KINDS}, got {kind!r}")
        max_calls = w.get("max_calls")
        if not isinstance(max_calls, int) or isinstance(max_calls, bool) or max_calls <= 0:
            raise ValueError(f"quota '{name}': max_calls must be a positive integer")
        reserved = float(w.get("reserved_for_user_pct", 0.0))
        if not 0.0 <= reserved < 100.0:
            raise ValueError(f"quota '{name}': reserved_for_user_pct must be in [0, 100)")
        seconds = int(w.get("seconds", 0))
        anchor = w.get("anchor")
        reset_day = int(w.get("reset_day", 1))
        if kind in ("rolling", "fixed") and seconds <= 0:
            raise ValueError(f"quota '{name}': {kind} windows need positive 'seconds'")
        if kind == "fixed" and anchor is None:
            raise ValueError(f"quota '{name}': fixed windows need 'anchor' (epoch seconds of a past reset)")
        if kind == "monthly" and not 1 <= reset_day <= 28:
            raise ValueError(f"quota '{name}': reset_day must be 1-28")
        windows.append(QuotaWindow(
            name=name, max_calls=max_calls, kind=kind, seconds=seconds,
            anchor=float(anchor) if anchor is not None else None,
            reset_day=reset_day, reserved_for_user_pct=reserved,
        ))
    return windows


def _month_start(dt: datetime, reset_day: int) -> datetime:
    """Most recent reset instant at or before dt."""
    this = dt.replace(day=reset_day, hour=0, minute=0, second=0, microsecond=0)
    if this <= dt:
        return this
    year, month = (dt.year, dt.month - 1) if dt.month > 1 else (dt.year - 1, 12)
    return this.replace(year=year, month=month)


def _next_month_start(start: datetime) -> datetime:
    year, month = (start.year, start.month + 1) if start.month < 12 else (start.year + 1, 1)
    return start.replace(year=year, month=month)


def window_start(w: QuotaWindow, now: float) -> float:
    if w.kind == "rolling":
        return now - w.seconds
    if w.kind == "fixed":
        return w.anchor + math.floor((now - w.anchor) / w.seconds) * w.seconds
    dt = datetime.fromtimestamp(now, tz=timezone.utc)
    return _month_start(dt, w.reset_day).timestamp()


def evaluate(windows: Sequence[QuotaWindow], timestamps: Sequence[float], now: float) -> List[WindowStatus]:
    out = []
    for w in windows:
        start = window_start(w, now)
        in_window = sorted(ts for ts in timestamps if ts >= start)
        used = len(in_window)
        if w.kind == "rolling":
            resets_at = (in_window[0] + w.seconds) if in_window else None
        elif w.kind == "fixed":
            resets_at = start + w.seconds
        else:
            resets_at = _next_month_start(datetime.fromtimestamp(start, tz=timezone.utc)).timestamp()
        out.append(WindowStatus(
            name=w.name, kind=w.kind, used=used, agent_limit=w.agent_limit,
            max_calls=w.max_calls, window_start=start, resets_at=resets_at,
            exhausted=used >= w.agent_limit,
        ))
    return out


def lookback_seconds(windows: Sequence[QuotaWindow]) -> float:
    """How far back timestamps must be kept to evaluate every window."""
    span = 0.0
    for w in windows:
        span = max(span, _MONTHLY_LOOKBACK if w.kind == "monthly" else w.seconds)
    return span


# ---------------------------------------------------------------------------
# Provider-reported quota
#
# Some plans meter in tokens and show only a percentage in their console, so a
# call count configured by hand can only approximate them. Where the provider
# exposes the real figure, read it instead. The source is selected by config
# (`quota_source.type`); a new type is added only for a genuinely new wire format.
# ---------------------------------------------------------------------------
import json as _json
import urllib.error as _urlerr
import urllib.request as _urlreq


class QuotaSourceError(Exception):
    """The provider's quota could not be read or understood. Never swallowed:
    the caller records and surfaces it, and does not guess a value."""


def _percent(value: Any, what: str) -> float:
    try:
        return float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        raise QuotaSourceError(f"{what}: cannot read percentage from {value!r}")


def parse_minimax_token_plan(payload: Dict[str, Any], model_name: str, block_at_used_pct: float) -> List[WindowStatus]:
    """MiniMax GET .../backend/account/token_plan/remains_percent.

    Per model it reports a fixed interval window (the 5-hour block) and a weekly
    window, each with start/end in epoch milliseconds and used/total percent.
    Counts come back as -1 (percent-only plans), so percent is what we use.
    """
    base = payload.get("base_resp") or {}
    if base.get("status_code") != 0:
        raise QuotaSourceError(f"provider error: {base.get('status_code')} {base.get('status_msg')}")
    entry = next((m for m in payload.get("model_remains", []) if m.get("model_name") == model_name), None)
    if entry is None:
        names = [m.get("model_name") for m in payload.get("model_remains", [])]
        raise QuotaSourceError(f"model_name {model_name!r} not in provider response (has {names})")
    out = []
    for label, prefix, start_key, end_key in (
        ("5h", "current_interval", "start_time", "end_time"),
        ("weekly", "current_weekly", "weekly_start_time", "weekly_end_time"),
    ):
        used = _percent(entry.get(f"{prefix}_used_percent"), f"{label} used_percent")
        out.append(WindowStatus(
            name=label, kind="provider_percent", used=int(round(used)),
            agent_limit=int(round(block_at_used_pct)), max_calls=100,
            window_start=entry[start_key] / 1000.0, resets_at=entry[end_key] / 1000.0,
            exhausted=used >= block_at_used_pct,
        ))
    return out


def _fetch_minimax_token_plan(conf: Dict[str, Any], api_key: str, timeout: float) -> List[WindowStatus]:
    req = _urlreq.Request(conf["url"], headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
    try:
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            payload = _json.loads(resp.read(1_000_000))
    except _urlerr.HTTPError as e:
        raise QuotaSourceError(f"HTTP {e.code} from {conf['url']}")
    except (_urlerr.URLError, OSError, ValueError) as e:
        raise QuotaSourceError(f"{type(e).__name__}: {e}")
    return parse_minimax_token_plan(payload, conf["model_name"], float(conf.get("block_at_used_pct", 100)))


# z.ai GLM Coding Plan. GET <url> (https://api.z.ai/api/monitor/usage/quota/limit) answers
#   {"code":200,"data":{"level":"pro","limits":[
#       {"type":"CREDIT_LIMIT","unit":3,"number":5,"usage":12000,"currentValue":0,"remaining":12000,"percentage":0},
#       {"type":"CREDIT_LIMIT","unit":6,"number":1,"usage":60000,...,"percentage":0,"nextResetTime":<epoch ms>}]}}
# The plan is metered in token-weighted CREDITS, not calls, so a call count can never match it; the percentage
# the provider reports is the figure used. unit 3 = hours (the 5-hour window is ROLLING: credits return 5 hours
# after they were used, so it has no block end), unit 6 = weeks (a fixed 7-day cycle that ends at nextResetTime).
# An unknown unit is an error, never a guess. Verified against a live Pro account at 0% used; the meaning of
# `percentage` as "used" is confirmed only by that reading (0% with the full allowance remaining).
_ZAI_UNIT_SECONDS = {3: 3600, 6: 7 * 86400}
_ZAI_LIMIT_TYPES = ("CREDIT_LIMIT", "TOKENS_LIMIT")  # TIME_LIMIT counts MCP tool calls, a separate meter


def parse_zai_coding_plan(payload: Dict[str, Any], block_at_used_pct: float, now: Optional[float] = None) -> List[WindowStatus]:
    import time as _time
    now = _time.time() if now is None else now
    if not isinstance(payload, dict) or payload.get("success") is False or payload.get("code") not in (200, None):
        raise QuotaSourceError(f"provider error: {payload.get('code') if isinstance(payload, dict) else payload!r} "
                               f"{payload.get('msg') if isinstance(payload, dict) else ''}")
    limits = ((payload.get("data") or {}).get("limits")) or []
    out = []
    for lim in limits:
        if lim.get("type") not in _ZAI_LIMIT_TYPES:
            continue
        unit, number = lim.get("unit"), lim.get("number")
        if unit not in _ZAI_UNIT_SECONDS or not isinstance(number, int) or number <= 0:
            raise QuotaSourceError(f"unknown window unit {unit!r} x {number!r} in the provider response")
        span = number * _ZAI_UNIT_SECONDS[unit]
        if lim.get("percentage") is not None:
            used = _percent(lim["percentage"], "percentage")
        elif lim.get("usage"):
            used = (lim["usage"] - lim.get("remaining", lim["usage"])) / lim["usage"] * 100
        else:
            raise QuotaSourceError("limit carries neither percentage nor usage/remaining")
        reset_ms = lim.get("nextResetTime")
        name = f"{number}h" if unit == 3 else ("weekly" if number == 1 else f"{number}w")
        if unit == 6 and reset_ms:
            kind, resets_at, start = "provider_percent", reset_ms / 1000.0, reset_ms / 1000.0 - span
        else:  # hours: rolling. resets_at (if given) is when the oldest credits come back, not a block end.
            kind, resets_at, start = "provider_rolling", (reset_ms / 1000.0 if reset_ms else None), now - span
        out.append(WindowStatus(name=name, kind=kind, used=int(round(used)), agent_limit=int(round(block_at_used_pct)),
                                max_calls=100, window_start=start, resets_at=resets_at, exhausted=used >= block_at_used_pct))
    if not out:
        raise QuotaSourceError("no credit windows in the provider response")
    return out


def _fetch_zai_coding_plan(conf: Dict[str, Any], api_key: str, timeout: float) -> List[WindowStatus]:
    req = _urlreq.Request(conf["url"], headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
    try:
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            payload = _json.loads(resp.read(1_000_000))
    except _urlerr.HTTPError as e:
        raise QuotaSourceError(f"HTTP {e.code} from {conf['url']}")
    except (_urlerr.URLError, OSError, ValueError) as e:
        raise QuotaSourceError(f"{type(e).__name__}: {e}")
    return parse_zai_coding_plan(payload, float(conf.get("block_at_used_pct", 100)))


SOURCES = {"minimax_token_plan": _fetch_minimax_token_plan, "zai_coding_plan": _fetch_zai_coding_plan}
_SOURCE_REQUIRES = {"minimax_token_plan": ("url", "model_name"), "zai_coding_plan": ("url",)}


def validate_source(conf: Optional[Dict[str, Any]]) -> None:
    """Raise ValueError for an unusable quota_source config (None is fine)."""
    if conf is None:
        return
    if not isinstance(conf, dict) or conf.get("type") not in SOURCES:
        raise ValueError(f"quota_source.type must be one of {sorted(SOURCES)}")
    missing = [k for k in _SOURCE_REQUIRES[conf["type"]] if not conf.get(k)]
    if missing:
        raise ValueError(f"quota_source {conf['type']} needs {missing}")
    pct = conf.get("block_at_used_pct", 100)
    if not isinstance(pct, (int, float)) or not 0 < pct <= 100:
        raise ValueError("quota_source.block_at_used_pct must be in (0, 100]")


def fetch_provider_quota(conf: Dict[str, Any], api_key: str, timeout: float = 10.0) -> List[WindowStatus]:
    return SOURCES[conf["type"]](conf, api_key, timeout)


# ---------------------------------------------------------------------------
# Pacing: spend a renewing allowance evenly instead of by guesswork
#
# An allowance that renews is lost if unspent, so a subscription should be used -- but spending it all in the
# first hour of a week leaves nothing for the rest of it. The pace line says how much of a window's agent share
# should have been spent by now:
#
#     allowed_now = agent_limit * min(1, elapsed_fraction + head_start) * cost_scale
#
# A resource is "on pace" when no window is above its line. On pace it may rank at priority_while_quota
# (treated as nearly free); ahead of pace it ranks at its normal priority -- plus pace.ahead_penalty, for
# allowances with no boosted rank of their own (a free daily pool: demote it behind the subscriptions) --
# until time catches up. The line
# reaches the full share at the window's end, so allowance about to expire is always free to use.
#   - only the longest window with an end is paced (that is where spending now costs future allowance); shorter
#     windows and rolling windows (credits come back one by one) are hard caps only.
#   - head_start (default 10%) lets a window be used straight away instead of flapping after one call.
#   - cost_scale shrinks the line while the provider charges more per call (peak hours), so work drifts to
#     the cheap hours without ever being forbidden.
# ---------------------------------------------------------------------------
DEFAULT_HEAD_START = 0.10
_HARD_CAP_ONLY = ("rolling", "provider_rolling")


@dataclass
class PaceRow:
    name: str
    used: float
    agent_limit: float
    allowed_now: float
    ahead: bool
    elapsed_fraction: Optional[float]
    basis: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_pace(conf: Any) -> Optional[Dict[str, Any]]:
    """Validate a resource's `pace` setting. None/False = off; True or {} = on with defaults. Raises ValueError."""
    if conf in (None, False):
        return None
    if conf is True:
        conf = {}
    if not isinstance(conf, dict):
        raise ValueError("pace must be true or an object")
    head = conf.get("head_start", DEFAULT_HEAD_START)
    if not isinstance(head, (int, float)) or isinstance(head, bool) or not 0 <= head < 1:
        raise ValueError("pace.head_start must be in [0, 1)")
    sched = conf.get("cost_schedule")
    if sched is not None:
        _check_schedule(sched)
    penalty = conf.get("ahead_penalty", 0)
    if not isinstance(penalty, int) or isinstance(penalty, bool) or not 0 <= penalty <= 10000:
        raise ValueError("pace.ahead_penalty must be an integer in [0, 10000]")
    return {"head_start": float(head), "cost_schedule": sched, "ahead_penalty": penalty}


def _check_schedule(sched: Any) -> None:
    if not isinstance(sched, dict) or not isinstance(sched.get("default"), (int, float)) or sched["default"] <= 0:
        raise ValueError("pace.cost_schedule needs a positive 'default' multiplier")
    off = sched.get("utc_offset_hours", 0)
    if not isinstance(off, (int, float)) or not -14 <= off <= 14:
        raise ValueError("pace.cost_schedule.utc_offset_hours must be in [-14, 14]")
    for i, p in enumerate(sched.get("periods", [])):
        days, a, b, m = p.get("days"), p.get("from_hour"), p.get("to_hour"), p.get("multiplier")
        if not (isinstance(days, list) and days and all(isinstance(d, int) and 0 <= d <= 6 for d in days)):
            raise ValueError(f"pace.cost_schedule.periods[{i}].days must be weekday numbers 0 (Mon) - 6 (Sun)")
        if not (isinstance(a, (int, float)) and isinstance(b, (int, float)) and 0 <= a < b <= 24):
            raise ValueError(f"pace.cost_schedule.periods[{i}] needs 0 <= from_hour < to_hour <= 24")
        if not isinstance(m, (int, float)) or m <= 0:
            raise ValueError(f"pace.cost_schedule.periods[{i}].multiplier must be positive")


def cost_multiplier(sched: Optional[Dict[str, Any]], now: float) -> float:
    """What a call costs now relative to the schedule's other periods (provider-defined units)."""
    if not sched:
        return 1.0
    local = datetime.fromtimestamp(now + 3600 * sched.get("utc_offset_hours", 0), tz=timezone.utc)
    hour = local.hour + local.minute / 60.0
    for p in sched.get("periods", []):
        if local.weekday() in p["days"] and p["from_hour"] <= hour < p["to_hour"]:
            return float(p["multiplier"])
    return float(sched["default"])


def cost_scale(sched: Optional[Dict[str, Any]], now: float) -> float:
    """1.0 in the cheapest period, less while calls cost more: cheapest multiplier / current multiplier."""
    if not sched:
        return 1.0
    cheapest = min([float(sched["default"])] + [float(p["multiplier"]) for p in sched.get("periods", [])])
    return cheapest / cost_multiplier(sched, now)


def _span(s: WindowStatus, now: float) -> Optional[float]:
    """Length of a window with an end to pace towards; None for rolling windows (no end, capacity returns call by call)."""
    if s.kind in _HARD_CAP_ONLY or s.resets_at is None or s.resets_at <= s.window_start:
        return None
    return s.resets_at - s.window_start


def pace(statuses: Sequence[WindowStatus], now: float, head_start: float = DEFAULT_HEAD_START,
         scale: float = 1.0) -> List[PaceRow]:
    """Only the LONGEST window with an end is paced. Spending now costs future availability only there; in a
    shorter window the unspent remainder is lost at its edge anyway, so conserving inside it buys nothing and
    would strand allowance (MiniMax: a week at 0% used must not be held back by the 5-hour block inside it).
    Shorter and rolling windows stay hard caps; the long window's line is what stops short blocks draining it."""
    spans = [_span(s, now) for s in statuses]
    longest = max([x for x in spans if x is not None], default=None)
    rows = []
    for s, span in zip(statuses, spans):
        limit = float(s.agent_limit)
        if span is None:
            rows.append(PaceRow(s.name, s.used, limit, limit, s.used > limit, None, "rolling: hard cap only"))
            continue
        if span < 0.99 * longest:
            rows.append(PaceRow(s.name, s.used, limit, limit, s.used > limit, None,
                                "shorter than the longest window: hard cap only (its unspent part is lost at its edge)"))
            continue
        elapsed = min(1.0, max(0.0, (now - s.window_start) / span))
        allowed = limit * min(1.0, elapsed + head_start) * min(1.0, scale)
        rows.append(PaceRow(s.name, s.used, limit, allowed, s.used > allowed, elapsed,
                            f"{elapsed:.0%} of the window gone, line at {min(1.0, elapsed + head_start):.0%}"
                            + (f" x cost scale {scale:.2f}" if scale < 1.0 else "")))
    return rows


def urgency(statuses: Sequence[WindowStatus], now: float) -> float:
    """How much of the paced window's allowance is at risk of expiring unused: unspent share / time left.
    Used to break ties between resources of equal rank -- the one whose allowance is closest to being wasted
    goes first (MiniMax's week at 0% with a quarter left beats GLM's week at 0% with half left). 0 when
    there is no paced window (rolling-only or no windows): nothing to lose by waiting."""
    spans = [_span(s, now) for s in statuses]
    longest = max([x for x in spans if x is not None], default=None)
    if longest is None:
        return 0.0
    best = 0.0
    for s, span in zip(statuses, spans):
        if span is None or span < 0.99 * longest or s.agent_limit <= 0:
            continue
        left = max(0.0, 1.0 - min(1.0, max(0.0, (now - s.window_start) / span)))
        remaining = max(0.0, (s.agent_limit - s.used) / s.agent_limit)
        best = max(best, remaining / max(left, 0.02))
    return best


def on_pace(statuses: Sequence[WindowStatus], now: float, conf: Dict[str, Any]) -> bool:
    """True when the resource has windows and none of them is above its pace line. `conf` is parse_pace()'s result."""
    if not statuses:
        return False
    rows = pace(statuses, now, conf["head_start"], cost_scale(conf.get("cost_schedule"), now))
    return not any(r.ahead for r in rows)


def budget_report(statuses: Sequence[WindowStatus], now: float, conf: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """What the owner wants to see: per window, the agent's share, what is spent, what the pace line allows now,
    and how much is left per day until the window renews."""
    conf = conf or {"head_start": DEFAULT_HEAD_START, "cost_schedule": None}
    rows = pace(statuses, now, conf["head_start"], cost_scale(conf.get("cost_schedule"), now))
    out = []
    for s, r in zip(statuses, rows):
        left = max(0.0, float(s.agent_limit) - s.used)
        days = (s.resets_at - now) / 86400.0 if s.resets_at and s.resets_at > now else None
        out.append({"window": s.name, "kind": s.kind, "agent_share": r.agent_limit, "used": r.used, "remaining": left,
                    "allowed_now": round(r.allowed_now, 2), "ahead_of_pace": r.ahead, "basis": r.basis,
                    "resets_in_hours": round(days * 24, 1) if days is not None else None,
                    "remaining_per_day": round(left / days, 2) if days else None, "exhausted": s.exhausted})
    return out
