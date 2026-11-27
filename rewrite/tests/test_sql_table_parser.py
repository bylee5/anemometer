from __future__ import annotations

import pytest

from anemometer.sql.table_parser import parse_tables
from tests.conftest import golden_params


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT * FROM t", ["t"]),
        ("select * from t1 join t2 using (id)", ["t1", "t2"]),
        ("SELECT * FROM `db`.`t`, `db`.`u`", ["db.t", "db.u"]),
        ("UPDATE t SET a = 1", ["t"]),
        ("INSERT INTO t SELECT * FROM s", ["t", "s"]),
        ("SELECT * FROM t1 JOIN t1 ON 1", ["t1"]),
        ("SELECT 1", []),
        ("", []),
    ],
)
def test_parse_tables(sql, expected):
    assert parse_tables(sql) == expected


@pytest.mark.parametrize(("sql", "expected"), golden_params("table_parser"))
def test_matches_php(sql, expected):
    assert parse_tables(sql) == expected
