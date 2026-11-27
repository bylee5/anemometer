from __future__ import annotations

import pytest

from anemometer.sql.rewrite import QueryRewrite, QueryType
from tests.conftest import golden_params

# Cases ported from lib/TestQueryRewrite.php (PHPUnit).
PHPUNIT_CASES = [
    ("SELECT 123", QueryType.SELECT, "SELECT 123"),
    ("/* 123 * 456 */ SELECT 123 #214241*/", QueryType.SELECT, "SELECT 123"),
    (
        "\t\t    SELECT       \t\t\t   123\t\t\t    \t\t\t\n",
        QueryType.SELECT,
        "SELECT       \t\t\t   123",
    ),
    (
        "/* Script : /home/site/XXXXXXXXXX.php Utilisateur : prod_outils */ "
        "SELECT SQL_SMALL_RESULT DISTINCT ID_CLIENT\n"
        "FROM DB.CLIENT CL\n"
        "WHERE CL.TELEPHONE = '0000000000'\n"
        "LIMIT 1\n",
        QueryType.SELECT,
        "SELECT SQL_SMALL_RESULT DISTINCT ID_CLIENT FROM DB.CLIENT CL "
        "WHERE CL.TELEPHONE = '0000000000' LIMIT 1",
    ),
    (
        "SELECT id FROM ips WHERE ip='192.168.0.1' AND type=1 LIMIT 1",
        QueryType.SELECT,
        "SELECT id FROM ips WHERE ip='192.168.0.1' AND type=1 LIMIT 1",
    ),
    (
        "INSERT INTO tbl_old(\nSELECT * \nFROM tbl\nWHERE id =123 )",
        QueryType.INSERTSELECT,
        "SELECT *  FROM tbl WHERE id =123",
    ),
    ("DELETE FROM table WHERE id = 123", QueryType.DELETE, "SELECT 0 FROM table WHERE id = 123"),
    ("INSERT INTO table (col1, col2, col3) VALUES (1, 2, 3), (4, 5, 6)", QueryType.INSERT, None),
    ("INSERT INTO table SELECT * FROM table2", QueryType.INSERTSELECT, "SELECT * FROM table2"),
    ("INSERT INTO table (SELECT * FROM table2)", QueryType.INSERTSELECT, "SELECT * FROM table2"),
    (
        "UPDATE table SET col1 = 123 WHERE id = 456",
        QueryType.UPDATE,
        "SELECT col1 = 123 FROM table WHERE id = 456",
    ),
    ("ALTER TABLE MODIFY col1 INT NOT NULL DEFAULT 0", QueryType.ALTER, None),
    ("DROP TABLE table", QueryType.DROP, None),
    ("CREATE TABLE table (id INT)", QueryType.CREATE, None),
    (
        "DELETE table1 FROM table1 JOIN table2 ON table1.id = table2.id "
        "WHERE table1.col1 = 123 AND table2.col2 = 456 ",
        QueryType.DELETEMULTI,
        "SELECT 0 FROM table1 JOIN table2 ON table1.id = table2.id "
        "WHERE table1.col1 = 123 AND table2.col2 = 456",
    ),
    ("(SELECT 123) UNION (SELECT 456)", QueryType.UNION, "(SELECT 123) UNION (SELECT 456)"),
]


@pytest.mark.parametrize(("sql", "expected_type", "expected_select"), PHPUNIT_CASES)
def test_phpunit_cases(sql, expected_type, expected_select):
    query = QueryRewrite(sql)

    assert query.type is expected_type
    assert query.to_select() == expected_select
    if expected_select is None:
        assert query.as_explain() is None
        assert query.as_extended_explain() is None
    else:
        assert query.as_explain() == f"EXPLAIN {expected_select}"
        assert query.as_extended_explain() == f"EXPLAIN EXTENDED {expected_select}"


@pytest.mark.parametrize(("sql", "expected"), golden_params("query_rewrite"))
def test_matches_php(sql, expected):
    query = QueryRewrite(sql)

    assert query.sql == expected["normalized"]
    assert query.type == expected["type"]
    assert query.to_select() == expected["select"]
    assert query.as_explain() == expected["explain"]
    assert query.as_extended_explain() == expected["extended_explain"]
