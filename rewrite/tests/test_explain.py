from __future__ import annotations

import pytest

from anemometer.db import connect
from anemometer.explain import ExplainError, QueryExplainer


def _info(db):
    return {key: db[key] for key in ("host", "port", "user", "password", "db")}


@pytest.fixture
def target_db(mysql_db):
    with connect(**mysql_db) as connection:
        connection.execute(
            "CREATE TABLE t1 (id INT PRIMARY KEY, v VARCHAR(10)) COMMENT='첫 테이블'"
        )
        connection.execute("CREATE TABLE t2 (id INT PRIMARY KEY, t1_id INT, KEY (t1_id))")
    return mysql_db


@pytest.fixture
def explainer_for(target_db):
    opened = []

    def make(query, **sample):
        explainer = QueryExplainer.for_sample(
            lambda row: _info(target_db), {"sample": query, **sample}
        )
        opened.append(explainer)
        return explainer

    yield make
    for explainer in opened:
        explainer.close()


def test_explain_select(explainer_for):
    plan = explainer_for(
        "/* app */ SELECT * FROM t1 JOIN t2 ON t2.t1_id = t1.id WHERE t1.v = 'x'"
    ).explain()
    lines = plan.splitlines()
    assert lines[0].startswith("+----+")
    assert lines[1].split("|")[1:4] == [" id ", " select_type ", " table "]
    assert "| t1 " in plan and "| t2 " in plan
    assert len(lines) == 3 + 2 * 2  # header block + two rows


@pytest.mark.parametrize(
    "query",
    [
        "UPDATE t1 SET v = 'y' WHERE id = 1",
        "DELETE FROM t1 WHERE id = 1",
        "INSERT INTO t2 SELECT * FROM t2",
    ],
)
def test_explain_rewritten_dml(explainer_for, query):
    assert "| SIMPLE " in explainer_for(query).explain()


def test_explain_unsupported_statement(explainer_for):
    explainer = explainer_for("INSERT INTO t1 VALUES (1, 'a')")
    assert explainer.explain() == "unknown error getting explain plan\n"


def test_explain_sql_error(explainer_for):
    plan = explainer_for("SELECT nope FROM t1").explain()
    assert plan == "Unknown column 'nope' in 'field list' (1054)"


def test_create_statements(explainer_for):
    explainer = explainer_for("SELECT * FROM t1, t2, missing WHERE 1")
    assert explainer.tables() == ["t1", "t2", "missing"]
    statements = explainer.create_statements().split("\n\n")
    assert len(statements) == 2
    assert statements[0].startswith("CREATE TABLE `t1`")
    assert "COMMENT='첫 테이블'" in statements[0]
    assert statements[1].startswith("CREATE TABLE `t2`")


def test_table_status(explainer_for):
    status = explainer_for("SELECT * FROM t1 JOIN t2 USING (id)").table_status()
    blocks = status.split("\n\n")
    assert len(blocks) == 2
    first = blocks[0].splitlines()
    assert first[0] == "                Name : t1"
    assert "              Engine : InnoDB" in first
    assert "             Comment : 첫 테이블" in first
    assert any(line.endswith(" : ") for line in first)  # NULL values are blank


@pytest.mark.parametrize(
    ("info", "message"),
    [
        (None, "Missing field host"),
        ({"host": "h"}, "Missing field user"),
        ({"host": "h", "user": "u", "password": None, "db": "d"}, "Missing field password"),
        ({"host": "h", "user": "u", "password": ""}, "Missing field db"),
    ],
)
def test_missing_connection_details(info, message):
    with pytest.raises(ExplainError, match=message):
        QueryExplainer.for_sample(lambda row: info, {"sample": "SELECT 1"})


def test_connection_error(mysql_server):
    info = {**mysql_server, "password": "wrong", "db": "mysql"}
    with pytest.raises(ExplainError, match=r"^Connection error: Access denied .*\(1045\)$"):
        QueryExplainer.for_sample(lambda row: info, {"sample": "SELECT 1"})


def test_callback_receives_the_row(target_db):
    seen = []

    def callback(row):
        seen.append(row)
        return {**_info(target_db), "port": str(target_db["port"])}

    row = {"sample": "SELECT 1", "hostname_max": "db1:3306"}
    with QueryExplainer.for_sample(callback, row) as explainer:
        assert explainer.query == "SELECT 1"
    assert seen == [row]
