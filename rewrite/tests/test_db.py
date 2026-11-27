from __future__ import annotations

import pytest

from anemometer.db import ConnectError, Connection, DatabaseError, connect


def test_database_error_text():
    assert (
        str(DatabaseError(1146, "Table 'x.y' doesn't exist")) == "Table 'x.y' doesn't exist (1146)"
    )


def test_escape_string():
    assert Connection.escape_string('it\'s "x"\n\\') == 'it\\\'s \\"x\\"\\n\\\\'


@pytest.fixture
def conn(mysql_db):
    with connect(**mysql_db) as connection:
        connection.execute(
            "CREATE TABLE t (id INT PRIMARY KEY, f FLOAT, d DECIMAL(6,2), ts DATETIME,"
            " name VARCHAR(20), note TEXT, bin VARBINARY(4))"
        )
        connection.execute(
            "INSERT INTO t VALUES"
            " (1, 0.5, 10, '2024-03-31 12:00:00', '한글', NULL, 0x6869),"
            " (2, 1e-05, 1.5, '0000-00-00 00:00:00', 'b', 'x', NULL)"
        )
        yield connection


def test_values_are_text_like_mysqli(conn):
    rows = conn.fetch_all("SELECT * FROM t ORDER BY id")
    assert rows == [
        {
            "id": "1",
            "f": "0.5",
            "d": "10.00",
            "ts": "2024-03-31 12:00:00",
            "name": "한글",
            "note": None,
            "bin": "hi",
        },
        {
            "id": "2",
            "f": "0.00001",
            "d": "1.50",
            "ts": "0000-00-00 00:00:00",
            "name": "b",
            "note": "x",
            "bin": None,
        },
    ]


def test_duplicate_column_names_keep_the_last_value(conn):
    row = conn.fetch_one("SELECT 'first' AS a, id, 'second' AS a FROM t WHERE id = 1")
    assert row == {"a": "second", "id": "1"}
    assert list(row) == ["a", "id"]


def test_parameters_and_tuples(conn):
    assert conn.fetch_tuples("SELECT id, name FROM t WHERE name = %s", ["한글"]) == [("1", "한글")]
    assert conn.fetch_one("SELECT id FROM t WHERE id = %s", [99]) is None


def test_execute_returns_affected_rows(conn):
    assert conn.execute("UPDATE t SET note = %s WHERE id > %s", ["y", 0]) == 2
    assert conn.fetch_all("SHOW TABLES LIKE 'nothing'") == []
    assert conn.fetch_all("DO 1") == []


def test_query_errors(conn):
    with pytest.raises(DatabaseError) as error:
        conn.fetch_all("SELECT * FROM missing_table")
    assert error.value.errno == 1146
    assert str(error.value).endswith("(1146)")


def test_server_info(conn):
    assert conn.server_version[0].isdigit()
    assert conn.host_info


def test_connect_errors(mysql_server):
    with pytest.raises(ConnectError) as error:
        connect(**{**mysql_server, "password": "wrong"}, db="")
    assert error.value.errno == 1045

    with pytest.raises(ConnectError):
        connect("127.0.0.1", "root", "", "", port=1, connect_timeout=1)
