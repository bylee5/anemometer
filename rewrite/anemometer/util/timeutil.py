"""Relative date expressions used by the search form ("now", "-1 month", ...)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

__all__ = ["DATETIME_FORMAT", "shift", "resolve_relative_date"]

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

_RELATIVE = re.compile(r"^\s*([+-])?(\d+)\s(\w+)$", re.ASCII)

# unit -> (kind, multiplier); plural forms are accepted as well.
_UNITS = {
    "sec": ("seconds", 1),
    "second": ("seconds", 1),
    "min": ("seconds", 60),
    "minute": ("seconds", 60),
    "hour": ("seconds", 3600),
    "day": ("days", 1),
    "week": ("days", 7),
    "fortnight": ("days", 14),
    "month": ("months", 1),
    "year": ("months", 12),
}


def _add_months(moment: datetime, months: int) -> datetime:
    """Add calendar months the way PHP's strtotime does.

    The day of month is kept and any overflow rolls into the next month, so
    2024-03-31 minus one month is 2024-03-02 (not 2024-02-29).
    """
    years, month_index = divmod(moment.month - 1 + months, 12)
    first = moment.replace(year=moment.year + years, month=month_index + 1, day=1)
    return first + timedelta(days=moment.day - 1)


def shift(moment: datetime, amount: int, unit: str) -> datetime:
    """Move ``moment`` by ``amount`` units ("day", "Months", "secs", ...).

    Raises ``ValueError`` for an unknown unit.
    """
    name = unit.lower()
    if name not in _UNITS and name.endswith("s"):
        name = name[:-1]
    try:
        kind, multiplier = _UNITS[name]
    except KeyError:
        raise ValueError(f"unknown time unit: {unit!r}") from None

    if kind == "months":
        return _add_months(moment, amount * multiplier)
    return moment + timedelta(**{kind: amount * multiplier})


def resolve_relative_date(expression: str | None, now: datetime | None = None) -> str | None:
    """Turn "now" or "[+-]N unit" into a ``YYYY-MM-DD HH:MM:SS`` timestamp.

    Anything else (including absolute dates) is returned unchanged. Any value
    starting with "now" counts as now. ``now`` defaults to the local time.

    Unlike PHP's strtotime, weekday names and other free-form words are not
    interpreted; such expressions are returned unchanged.
    """
    if expression is None:
        return None
    now = now or datetime.now()

    if expression[:3].lower() == "now":
        return now.strftime(DATETIME_FORMAT)

    match = _RELATIVE.match(expression)
    if not match:
        return expression
    sign, amount, unit = match.groups()
    try:
        moment = shift(now, -int(amount) if sign == "-" else int(amount), unit)
    except ValueError:
        return expression
    return moment.strftime(DATETIME_FORMAT)
