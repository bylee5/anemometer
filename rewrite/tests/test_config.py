from __future__ import annotations

import dataclasses
from datetime import date, datetime
from pathlib import Path

import pytest

from anemometer.config import AppConfig, ConfigError, load_config, relative_time
from tests.conftest import load_golden

SAMPLE = Path(__file__).parents[1] / "conf" / "config.sample.py"


@pytest.fixture(scope="module")
def sample() -> AppConfig:
    config = load_config(SAMPLE)
    assert config is not None
    return config


def _golden(kind):
    return [
        case
        for case in load_golden("config_sample")
        if case["input"] == kind
        or (isinstance(case["input"], dict) and case["input"].get("callback") == kind)
    ]


def _describe(value):
    """Mirror tools/golden/config_sample.php: callables as markers, times as day offsets."""
    if isinstance(value, dict):
        return {key: _describe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_describe(item) for item in value]
    if callable(value):
        if getattr(value, "__qualname__", "").startswith("relative_time("):
            moment = datetime.strptime(value(), "%Y-%m-%d %H:%M:%S")
            return f"{round((moment - datetime.now()).total_seconds() / 86400):+d} day"
        return "<callable>"
    return value


def _php_defaults(by_source):
    """PHP kept per-source-type defaults nested inside the default block."""
    merged = dict(by_source["default"])
    merged.update({name: values for name, values in by_source.items() if name != "default"})
    return merged


def _non_empty(values):
    return {key: value for key, value in values.items() if value not in (None, {}, [], ())}


def test_sample_matches_php_sample(sample):
    expected = _golden("conf")[0]["expected"]

    datasources = {
        name: {k: v for k, v in dataclasses.asdict(ds).items() if k != "name"}
        for name, ds in sample.datasources.items()
    }
    assert datasources == expected["datasources"]
    assert sample.default_report_action == expected["default_report_action"]
    assert list(sample.reviewers) == expected["reviewers"]
    assert list(sample.review_types) == expected["review_types"]
    for kind in ("report_defaults", "history_defaults", "graph_defaults"):
        assert _describe(_php_defaults(getattr(sample, kind))) == expected[kind], kind
    plugins = _non_empty(
        {f.name: getattr(sample.plugins, f.name) for f in dataclasses.fields(sample.plugins)}
    )
    assert _describe(plugins) == expected["plugins"]

    assert list(sample.reports) == list(expected["reports"])
    for name, spec in sample.reports.items():
        values = _non_empty({f.name: getattr(spec, f.name) for f in dataclasses.fields(spec)})
        assert _describe(values) == expected["reports"][name], name
        # field order decides the order of URL parameters
        for alias, fields in spec.fields.items():
            assert list(fields) == list(expected["reports"][name]["fields"][alias])


@pytest.mark.parametrize("case", _golden("date"), ids=lambda c: c["input"]["value"])
def test_date_callback_matches_php(sample, case):
    callback = sample.reports["slow_query_log"].callbacks["table"]["date"]
    assert list(callback(case["input"]["value"])) == case["expected"]


def test_date_callback_accepts_date_objects_and_junk(sample):
    callback = sample.reports["slow_query_log"].callbacks["table"]["date"]
    assert callback(date(2024, 3, 30)) == (date(2024, 3, 30), "weekend")
    assert callback("not a date") == ("not a date", "")


def test_checksum_callback_keeps_hex_checksums(sample):
    # Deliberately differs from the PHP sample, which still assumed BIGINT
    # checksums and converted them with dec2hex (see install.sql: CHAR(32)).
    callback = sample.reports["slow_query_log"].callbacks["table"]["checksum"]
    assert callback("0123456789ABCDEF0123456789ABCDEF") == ("0123456789ABCDEF0123456789ABCDEF",)


@pytest.mark.parametrize("case", _golden("explain"), ids=lambda c: str(c["input"]["value"]))
def test_explain_callback_matches_php(sample, case):
    result = sample.plugins.explain(case["input"]["value"])
    expected = case["expected"]
    if expected is not None:
        # PHP passed the port on as a string; the port is an int here.
        expected = {**expected, "port": int(expected["port"])}
    assert result == expected


def test_missing_file_returns_none(tmp_path):
    assert load_config(tmp_path / "nope.py") is None


MINIMAL = """
DATASOURCES = {"db": {"host": "h", "db": "d", "user": "u", "password": "",
                      "tables": {"review": "fact", "history": "dimension"}}}
REPORTS = {"slow_query_log": {"fields": {"fact": {"group": "group"}}}}
REPORT_DEFAULTS = {"default": {"fact-limit": "20"}, "special": {"fact-limit": "5"}}
HISTORY_DEFAULTS = {"default": {}}
GRAPH_DEFAULTS = {"default": {"start": CLOCK}}
"""


def _write(tmp_path, text, clock="'fixed'"):
    path = tmp_path / "config.py"
    path.write_text(text.replace("CLOCK", clock), encoding="utf-8")
    return path


def test_minimal_config_and_defaults(tmp_path):
    config = load_config(_write(tmp_path, MINIMAL))

    datasource = config.datasources["db"]
    assert (datasource.name, datasource.port, datasource.source_type) == ("db", 3306, None)
    assert datasource.table_for("dimension") == "history"
    assert datasource.table_for("missing") is None
    assert config.default_report_action == "report"
    assert config.plugins.explain is None

    assert config.defaults("report_defaults", "special") == {"fact-limit": "5"}
    assert config.defaults("report_defaults", "other") == {"fact-limit": "20"}
    assert config.defaults("report_defaults", None) == {"fact-limit": "20"}
    with pytest.raises(ValueError):
        config.defaults("nonsense", None)


def test_callable_defaults_are_evaluated_each_time(tmp_path):
    clock = "__import__('itertools').count().__next__"
    config = load_config(_write(tmp_path, MINIMAL, clock))
    assert config.defaults("graph_defaults", None) == {"start": 0}
    assert config.defaults("graph_defaults", None) == {"start": 1}


def test_relative_time():
    resolved = datetime.strptime(relative_time("-1 day")(), "%Y-%m-%d %H:%M:%S")
    assert abs((datetime.now() - resolved).total_seconds() - 86400) < 5


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda t: t.replace('"review": "fact"', '"review": "x"'), "alias 'fact'"),
        (lambda t: t.replace('"host": "h", ', ""), "host"),
        (lambda t: t + "\nUNKNOWN_SETTING = 1\n", "UNKNOWN_SETTING"),
        (lambda t: t.replace("HISTORY_DEFAULTS", "# HISTORY_DEFAULTS"), "history_defaults"),
        (lambda t: t + "\nPLUGINS = {'explian': None}\n", "explian"),
    ],
)
def test_invalid_config(tmp_path, change, message):
    with pytest.raises(ConfigError, match=message):
        load_config(_write(tmp_path, change(MINIMAL)))


def test_defaults_are_copies(sample):
    first = sample.defaults("graph_defaults", "slow_query_log")
    first["table_fields"].append("changed")
    assert sample.defaults("graph_defaults", "slow_query_log")["table_fields"] == ["minute_ts"]


def test_private_module_names_are_ignored(tmp_path):
    config = load_config(_write(tmp_path, MINIMAL + "\n_SERVER = {'host': 'x'}\n"))
    assert config.datasources["db"].host == "h"
