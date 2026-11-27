from __future__ import annotations

import json
from urllib.parse import parse_qsl

import pytest

from anemometer.request_vars import RequestVars, parse_php_params
from tests.conftest import golden_params


@pytest.mark.parametrize(("query_string", "expected"), golden_params("request_params"))
def test_parse_matches_php(query_string, expected):
    parsed = parse_php_params(parse_qsl(query_string, keep_blank_values=True))
    # JSON round trip: PHP integer array keys are encoded as strings.
    assert json.loads(json.dumps(parsed)) == expected


def test_array_parameters_become_lists():
    params = RequestVars.from_strings("table_fields[]=a&table_fields[]=b&x=1")
    assert params.get("table_fields") == ["a", "b"]
    assert params.get("x") == "1"


def test_form_values_take_precedence_over_query():
    params = RequestVars.from_strings("checksum=from-query", "checksum=from-form")
    assert params.get("checksum") == "from-form"

    params.set("checksum", "written")
    assert params.get("checksum") == "from-form"


def test_none_values_fall_through():
    params = RequestVars({"a": None, "b": "query"}, {"b": None})
    assert params.get("a") is None
    assert params.get("a", "default") == "default"
    assert params.get("b") == "query"


def test_set_and_discard():
    params = RequestVars()
    params.set("a", "1")
    assert params.get("a") == "1"
    assert params.in_query("a")

    params.set("a", None)
    assert params.in_query("a")
    assert params.get("a") is None

    params.discard("a")
    params.discard("missing")
    assert not params.in_query("a")


def test_append():
    params = RequestVars({"fields": ["a"]})
    params.append("fields", "b")
    params.append("new", "x")
    assert params.get("fields") == ["a", "b"]
    assert params.get("new") == ["x"]


def test_append_to_php_style_array():
    params = RequestVars.from_strings("a[3]=x")
    params.append("a", "y")
    assert params.get("a") == {3: "x", 4: "y"}


def test_append_to_scalar_fails():
    params = RequestVars({"a": "scalar"})
    with pytest.raises(TypeError):
        params.append("a", "x")


def test_copies_are_independent():
    query = {"a": "1"}
    params = RequestVars(query)
    params.set("a", "2")
    assert query == {"a": "1"}
    assert params.query == {"a": "2"}


def test_set_copies_lists():
    defaults = ["a"]
    params = RequestVars()
    params.set("fields", defaults)
    params.append("fields", "b")
    assert defaults == ["a"]
