from __future__ import annotations

import re
from zoneinfo import ZoneInfo

import pytest

from anemometer.request_vars import RequestVars
from anemometer.util.hexconv import dec2hex
from anemometer.views import (
    apply_callbacks,
    flatten_array,
    graph_series,
    make_environment,
    php_json_encode,
    php_truthy,
    print_r,
    report_json,
    report_json2,
    report_printr,
)
from tests.conftest import load_golden

SEOUL = ZoneInfo("Asia/Seoul")
SITE_URL = "/anemometer/index.php"
JSON_VIEWS = {"report_json", "report_json2", "report_printr"}


def _weekend(value):
    from datetime import datetime

    day = datetime.strptime(value[:10], "%Y-%m-%d")
    return value, "weekend" if day.isoweekday() >= 6 else ""


CALLBACKS = {
    "sample": {"date": _weekend, "checksum": lambda value: (dec2hex(value), "")},
    "site": {"date": _weekend, "checksum": lambda value: (value,)},
}


def _normalize(html: str) -> str:
    """Whitespace between and around tags differs between PHP and Jinja; nothing else may."""
    html = re.sub(r"\s+", " ", html)
    return re.sub(r">\s+<", "><", html).strip()


def _cases(json_views: bool):
    return [
        pytest.param(case["input"], case["expected"], id=f"{i:02d}-{case['input']['view']}")
        for i, case in enumerate(load_golden("views"))
        if (case["input"]["view"] in JSON_VIEWS) == json_views
    ]


@pytest.fixture(scope="module")
def env():
    return make_environment()


@pytest.mark.parametrize(("case", "expected"), _cases(json_views=False))
def test_templates_match_php(env, case, expected):
    params = RequestVars(case.get("get"))
    data = dict(case.get("data") or {})
    if isinstance(data.get("callbacks"), str):
        data["callbacks"] = CALLBACKS[data["callbacks"]]
    if case["view"] == "samples":
        rpp = data.get("rpp")
        data["rpp_number"] = int(rpp) if rpp else 0

    html = env.get_template(f"{case['view']}.html").render(
        **data, get_var=params.get, site_url=SITE_URL
    )
    # Known difference: the setup instructions name the Python config files.
    expected = expected.replace(
        "<code>conf/sample.config.inc.php</code>, rename it to <code>conf/config.inc.php</code>",
        "<code>conf/config.sample.py</code>, copy it to <code>conf/config.py</code>",
    )
    assert _normalize(html) == _normalize(expected)


@pytest.mark.parametrize(("case", "expected"), _cases(json_views=True))
def test_api_outputs_match_php(case, expected):
    data = case["data"]
    if case["view"] == "report_json":
        assert report_json(data["columns"], data["result"]) == expected
    elif case["view"] == "report_printr":
        assert report_printr(data["columns"], data["result"]) == expected
    else:
        get = case.get("get", {})
        output = report_json2(
            data["columns"],
            data["result"],
            get.get("fact-group"),
            debug_sql=case.get("sql") if get.get("debug") else None,
            tz=SEOUL,
        )
        # Known difference: PHP's dec2hex() turned the non-integer column
        # name "1.5" into "F"; only integer names are converted here.
        assert output == expected.replace('"label":"F"', '"label":"1.5"')


def test_php_json_encode():
    assert php_json_encode({"a": "x/y", "b": [1, None, True], "c": "é"}) == (
        '{"a":"x\\/y","b":[1,null,true],"c":"\\u00e9"}'
    )


def test_print_r_scalars():
    assert print_r(None) == ""
    assert print_r(True) == "1"
    assert print_r([]) == "Array\n(\n)\n"


def test_php_truthy():
    assert [php_truthy(v) for v in (None, "", "0", 0, [], {}, False)] == [False] * 7
    assert all(php_truthy(v) for v in ("1", "a", 1, [0], "0.0"))


def test_flatten_array():
    assert flatten_array({"t1": ["a", "b"], "t2": {"x": ["c"]}}) == ["a", "b", "c"]
    assert flatten_array(None) == []


def test_apply_callbacks():
    row, classes = apply_callbacks({"a": "1", "b": "2"}, {"a": lambda v: (v + "!", "x")})
    assert row == {"a": "1!", "b": "2"}
    assert classes == ["x"]
    assert apply_callbacks({"a": "1"}, None) == ({"a": "1"}, [])


def test_graph_series_local_time_default():
    series = graph_series(["ts", "v"], [{"ts": "2024-03-31 10:00:00", "v": "1"}], "ts")
    from datetime import datetime

    assert series == [{"label": "v", "data": [[int(datetime(2024, 3, 31, 10).timestamp()), "1"]]}]


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (None, "", True),
        (None, "0", False),
        (None, None, True),
        ("1", "1.0", True),
        ("10", "1e1", True),
        ("abc", "ABC", False),
        ("a", "a", True),
        ("", "0", False),
    ],
)
def test_php_eq(left, right, expected):
    from anemometer.views import php_eq

    assert php_eq(left, right) is expected
    assert php_eq(right, left) is expected


def test_concatenation_uses_php_strings(env):
    template = env.from_string("{{ 'a=' ~ missing ~ '&b=' ~ none_value ~ '&c=' ~ flag }}")
    assert template.render(none_value=None, flag=True) == "a=&b=&c=1"
