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
