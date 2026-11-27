"""Thin MySQL access layer on top of PyMySQL.

Results deliberately look like what the original PHP code got from mysqli:

* every value is a ``str`` (or ``None`` for NULL) -- no int/float/datetime
  conversion, so numbers keep MySQL's own formatting ("10.00", "0.00001");
* rows are dicts keyed by column name, and when two columns share a name the
  later one wins (as with ``mysqli_result::fetch_assoc``).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Optional

import pymysql
from pymysql.converters import conversions, escape_string

__all__ = ["Connection", "DatabaseError", "ConnectError", "connect"]

Row = dict[str, Optional[str]]
Params = Optional[Sequence[Any]]

# PyMySQL keeps result decoders (keyed by MySQL field type, an int) and query
# parameter encoders (keyed by Python type) in one mapping. Dropping the
# decoders makes every result value come back as text, like mysqli.
_ENCODERS_ONLY = {key: value for key, value in conversions.items() if not isinstance(key, int)}


class DatabaseError(Exception):
    """A MySQL error; ``str()`` gives "message (errno)" like the original error display."""

    def __init__(self, errno: int, message: str) -> None:
        super().__init__(errno, message)
        self.errno = errno
        self.message = message

    def __str__(self) -> str:
        return f"{self.message} ({self.errno})"

    @classmethod
    def wrap(cls, exc: pymysql.MySQLError) -> DatabaseError:
        if len(exc.args) >= 2 and isinstance(exc.args[0], int):
            return cls(exc.args[0], str(exc.args[1]))
        return cls(0, str(exc))


class ConnectError(DatabaseError):
    """The server could not be reached or refused the login."""


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):  # binary columns
        return bytes(value).decode("utf-8", errors="replace")
    return str(value)


class Connection:
    """An open connection. Use :func:`connect` to create one."""

    def __init__(self, raw: pymysql.connections.Connection) -> None:
        self._raw = raw

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._raw.open:
            self._raw.close()

    @property
    def server_version(self) -> str:
        return self._raw.get_server_info()

    @property
    def host_info(self) -> str:
        return self._raw.host_info

    @contextmanager
    def _cursor(self, sql: str, params: Params) -> Iterator[pymysql.cursors.Cursor]:
        try:
            with self._raw.cursor() as cursor:
                cursor.execute(sql, params)
                yield cursor
        except pymysql.MySQLError as exc:
            raise DatabaseError.wrap(exc) from exc

    def fetch_all(self, sql: str, params: Params = None) -> list[Row]:
        """Run a query and return all rows as dicts."""
        with self._cursor(sql, params) as cursor:
            if cursor.description is None:
                return []
            names = [column[0] for column in cursor.description]
            return [
                {name: _text(value) for name, value in zip(names, row)} for row in cursor.fetchall()
            ]

    def fetch_one(self, sql: str, params: Params = None) -> Row | None:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def fetch_tuples(self, sql: str, params: Params = None) -> list[tuple[str | None, ...]]:
        """Run a query and return rows as tuples (for positional access)."""
        with self._cursor(sql, params) as cursor:
            return [tuple(_text(value) for value in row) for row in cursor.fetchall()]

    def execute(self, sql: str, params: Params = None) -> int:
        """Run a statement and return the number of affected rows."""
        with self._cursor(sql, params) as cursor:
            return cursor.rowcount

    @staticmethod
    def escape_string(value: str) -> str:
        """Escape a value for use inside a quoted SQL string literal."""
        return escape_string(value)


def connect(
    host: str,
    user: str,
    password: str,
    db: str,
    port: int = 3306,
    *,
    connect_timeout: float | None = None,
    charset: str = "utf8mb4",
) -> Connection:
    """Open a connection; raises :class:`ConnectError` on failure."""
    try:
        raw = pymysql.connect(
            host=host,
            user=user,
            password=password,
            database=db,
            port=int(port),
            charset=charset,
            connect_timeout=connect_timeout or 10,
            autocommit=True,
            conv=_ENCODERS_ONLY,
        )
    except pymysql.MySQLError as exc:
        error = DatabaseError.wrap(exc)
        raise ConnectError(error.errno, error.message) from exc
    return Connection(raw)
