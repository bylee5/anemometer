from __future__ import annotations

from datetime import datetime

import pytest

from anemometer.util.hexconv import dec2hex
from anemometer.util.text_table import format_table
from anemometer.util.timeutil import resolve_relative_date, shift
from tests.conftest import golden_params, load_golden

# --- dec2hex ---------------------------------------------------------------


@pytest.mark.parametrize(("number", "expected"), golden_params("hexconv"))
def test_dec2hex_matches_php(number, expected):
    assert dec2hex(number) == expected


def test_dec2hex_accepts_int():
    assert dec2hex(255) == "FF"


# --- format_table ------------------------------------------------------------


@pytest.mark.parametrize(("rows", "expected"), golden_params("text_table"))
def test_format_table_matches_php(rows, expected):
    assert format_table(rows) == expected


def test_format_table_converts_values_to_text():
    assert format_table([{"rows": 10, "filtered": None}]) == (
        "+------+----------+\n"
        "| rows | filtered |\n"
        "+------+----------+\n"
        "| 10   |          |\n"
        "+------+----------+\n"
    )


# --- resolve_relative_date ---------------------------------------------------

# strtotime() interprets these free-form expressions in surprising ways
# ("-1 foo" becomes a UTC-1 timezone shift, weekday names jump to midnight).
# The port deliberately leaves them unchanged instead.
UNSUPPORTED = {"-1 foo", "+1 monday", "-1 weekday", "-1 weekdays", "-1 msec"}


def _reldate_cases():
    cases = []
    for case in load_golden("reldate"):
        base, expression = case["input"]["now"], case["input"]["expression"]
        expected = expression if expression in UNSUPPORTED else case["expected"]
        cases.append(pytest.param(base, expression, expected, id=f"{base}|{expression}"))
    return cases


@pytest.mark.parametrize(("base", "expression", "expected"), _reldate_cases())
def test_resolve_relative_date_matches_php(base, expression, expected):
    now = datetime.strptime(base, "%Y-%m-%d %H:%M:%S")
    assert resolve_relative_date(expression, now) == expected


def test_resolve_relative_date_none():
    assert resolve_relative_date(None) is None


def test_resolve_relative_date_defaults_to_local_now():
    before = datetime.now().replace(microsecond=0)
    resolved = datetime.strptime(resolve_relative_date("now"), "%Y-%m-%d %H:%M:%S")
    assert before <= resolved <= datetime.now()


def test_shift_rejects_unknown_unit():
    with pytest.raises(ValueError, match="unknown time unit"):
        shift(datetime(2024, 1, 1), 1, "lightyears")
