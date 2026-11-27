from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path

import pytest

from anemometer.config import ReportSpec, load_config
from anemometer.db import connect
from anemometer.report import ReportError, TableReport, remove_schema_name
from anemometer.request_vars import RequestVars
from tests.conftest import load_golden, load_schema

SAMPLE = Path(__file__).parents[1] / "conf" / "config.sample.py"
SLOW_TABLES = {"global_query_review": "fact", "global_query_review_history": "dimension"}


def _reports() -> dict[str, ReportSpec]:
    reports = dict(load_config(SAMPLE).reports)
    # Recorded with a variant matching the production config's report settings.
    sample = reports["slow_query_log"]
    reports["slow_query_log_site"] = dataclasses.replace(
        sample,
        join={**sample.join, "dimension": "USE INDEX (idx_ts_min_01) USING (`checksum`)"},
        custom_fields={
            **sample.custom_fields,
            "snippet": "LEFT(dimension.sample,100)",
            "rows_examined_avg": "ROUND(SUM(Rows_examined_sum)/SUM(ts_cnt),0)",
            "rows_examined/sent_avg": (
                "ROUND(SUM(Rows_examined_sum)/SUM(Rows_sent_sum)/SUM(ts_cnt),0)"
            ),
        },
    )
    return reports


REPORTS = _reports()


def _golden_cases():
    return [
        pytest.param(case["input"], case["expected"], id=case["input"]["name"])
        for case in load_golden("report")
    ]


def _build(case) -> TableReport:
    now = datetime.strptime(case["now"], "%Y-%m-%d %H:%M:%S")
    report = TableReport(
        case["tables"],
        REPORTS[case["report"]],
        RequestVars(case["get"], case.get("post")),
        now=lambda: now,
    )
    if "non_aggregate" in case:
        report.set_non_aggregate_columns(case["non_aggregate"])
    for name, values in case.get("pivot", {}).items():
        report.set_pivot_values(name, values)
    return report


@pytest.mark.parametrize(("case", "expected"), _golden_cases())
def test_matches_php(case, expected):
    report = _build(case)
    assert report.form_fields() == expected["form_fields"]
    assert report.custom_fields() == expected["custom_fields"]

    if "error" in expected:
        with pytest.raises(ReportError, match=expected["error"]):
            report.query()
        return

    assert report.query() == expected["sql"]
    assert report.column_names() == expected["columns"]
    assert report.search_uri() == expected["search_uri"]
    exceptions = case.get("uri_exceptions", ["dimension-ts_min"])
    assert report.search_uri(exceptions) == expected["search_uri_except"]


def test_query_is_cached_and_processing_runs_once():
    params = RequestVars({"table_fields": ["checksum"], "fact-limit": "5"})
    report = TableReport(SLOW_TABLES, REPORTS["slow_query_log"], params)
    sql = report.query()
    params.set("fact-limit", "10")
    report.process_form_data()
    assert report.query() is sql
    assert "LIMIT 5" in sql


def test_requires_fact_table():
    with pytest.raises(ReportError, match="No alias fact"):
        TableReport({"t": "dimension"}, REPORTS["slow_query_log"], RequestVars())


def test_table_lookup():
    report = TableReport(SLOW_TABLES, REPORTS["slow_query_log"], RequestVars())
    assert report.tables == list(SLOW_TABLES)
    assert report.table_for_alias("dimension") == "global_query_review_history"
    with pytest.raises(ReportError, match="No alias nope"):
        report.table_for_alias("nope")
    assert report.pivot_values("dimension-pivot-hostname_max") == []


def test_unknown_filter():
    spec = ReportSpec(fields={"fact": {"x": "clear|typo"}})
    report = TableReport(SLOW_TABLES, spec, RequestVars({"table_fields": ["x"]}))
    with pytest.raises(ReportError, match="unknown filter 'typo' for fact-x"):
        report.query()


def test_database_access_needs_a_connection():
    report = TableReport(SLOW_TABLES, REPORTS["slow_query_log"], RequestVars())
    with pytest.raises(ReportError, match="no database connection"):
        report.execute("SELECT 1")


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("dimension.ts_min", "ts_min"),
        ("a.b.c", "a.b.c"),
        ("IF(a.b='x',c,0)", "IF(a.b='x',c,0)"),
        ("plain", "plain"),
    ],
)
def test_remove_schema_name(column, expected):
    assert remove_schema_name(column) == expected


# -- with a database ---------------------------------------------------------


@pytest.fixture
def slow_log_db(mysql_db):
    with connect(**mysql_db) as connection:
        load_schema(connection)
        connection.execute(
            "INSERT INTO global_query_review (checksum, fingerprint, sample, first_seen)"
            " VALUES ('A', 'select ?', 'select 1', '2024-03-01'),"
            " ('B', 'select ?', 'select 2', '2024-03-02')"
        )
        connection.execute(
            "INSERT INTO global_query_review_history"
            " (hostname_max, checksum, sample, ts_min, ts_max, ts_cnt, Query_time_sum)"
            " VALUES ('h1', 'A', 'select 1', '2024-03-30 10:00:00', '2024-03-30 10:00:00', 2, 0.5),"
            " ('h2', 'A', 'select 1', '2024-03-31 10:00:00', '2024-03-31 10:00:00', 1, 1.5),"
            " ('h1', 'B', 'select 2', '2024-03-31 11:00:00', '2024-03-31 11:00:00', 4, 2)"
        )
        yield connection, mysql_db["db"]


def test_execute_report(slow_log_db):
    connection, schema = slow_log_db
    params = RequestVars(
        {
            "table_fields": ["checksum", "ts_cnt", "Query_time_sum"],
            "fact-group": "checksum",
            "fact-order": "checksum",
            "dimension-ts_min_start": "2024-03-31 00:00:00",
        }
    )
    report = TableReport(
        SLOW_TABLES, REPORTS["slow_query_log"], params, connection=connection, schema=schema
    )
    assert report.execute() == [
        {"checksum": "A", "ts_cnt": "1", "Query_time_sum": "1.5"},
        {"checksum": "B", "ts_cnt": "4", "Query_time_sum": "2"},
    ]
    assert report.distinct_values("global_query_review_history", "hostname_max") == ["h1", "h2"]
    assert report.distinct_values("missing_table", "x") == []

    fields = report.table_fields("global_query_review")
    assert fields[:3] == ["checksum", "fingerprint", "sample"]
    assert "hostname_max" in report.table_fields()


def test_execute_reports_sql_errors(slow_log_db):
    connection, schema = slow_log_db
    params = RequestVars({"table_fields": ["no_such_column"]})
    report = TableReport(SLOW_TABLES, REPORTS["slow_query_log"], params, connection=connection)
    with pytest.raises(Exception, match=r"Unknown column 'no_such_column' .*\(1054\)"):
        report.execute()
