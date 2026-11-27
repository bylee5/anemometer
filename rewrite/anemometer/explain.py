"""EXPLAIN plans and table information for a query sample.

The query digest only stores the query text, so a site-specific callback
(``PLUGINS["explain"]`` in the configuration) maps a history row -- the sample
plus columns such as ``hostname_max`` -- to connection details for the server
the query ran on. :meth:`QueryExplainer.for_sample` calls it and connects.

An explainer is bound to one query and keeps its own connection.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Callable, Optional

from anemometer.db import Connection, DatabaseError, connect
from anemometer.sql.rewrite import QueryRewrite
from anemometer.sql.table_parser import parse_tables
from anemometer.util.text_table import format_table

__all__ = ["ExplainError", "QueryExplainer"]

CONNECT_TIMEOUT = 1  # seconds
REQUIRED_FIELDS = ("host", "user", "password", "db")

# Comments are removed before EXPLAIN (greedy, within a line).
_COMMENT = re.compile(r"/\*.*\*/")

ConnectionCallback = Callable[[Mapping[str, Any]], Optional[Mapping[str, Any]]]


class ExplainError(Exception):
    """No usable connection to the query's server."""


class QueryExplainer:
    def __init__(self, connection: Connection, query: str) -> None:
        self._connection = connection
        self.query = query

    @classmethod
    def for_sample(
        cls,
        get_connection: ConnectionCallback,
        sample: Mapping[str, Any],
        *,
        timeout: float = CONNECT_TIMEOUT,
    ) -> QueryExplainer:
        """Connect to the server a sample row came from.

        :param get_connection: returns ``{"host", "user", "password", "db"}`` and
            optionally ``"port"`` for the row, or ``None`` if unknown.
        :param sample: the history row; its ``"sample"`` column is the query.
        :raises ExplainError: if details are missing or the connection fails.
        """
        info = get_connection(sample) or {}
        for field in REQUIRED_FIELDS:
            if info.get(field) is None:
                raise ExplainError(f"Missing field {field}")
        try:
            connection = connect(
                info["host"],
                info["user"],
                info["password"],
                info["db"],
                port=int(info.get("port") or 3306),
                connect_timeout=timeout,
            )
        except DatabaseError as exc:
            raise ExplainError(f"Connection error: {exc.message}({exc.errno})") from exc
        return cls(connection, sample.get("sample") or "")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> QueryExplainer:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def tables(self) -> list[str]:
        """Table names referenced by the query (best effort)."""
        return parse_tables(self.query)

    def explain(self) -> str:
        """The EXPLAIN plan as a text table, or an error message."""
        statement = QueryRewrite(_COMMENT.sub("", self.query)).as_explain()
        if statement is None:
            return "unknown error getting explain plan\n"
        try:
            rows = self._connection.fetch_all(statement)
        except DatabaseError as exc:
            return str(exc)
        return format_table(rows)

    def create_statements(self) -> str:
        """SHOW CREATE TABLE output for each table, separated by blank lines."""
        statements = []
        for table in self.tables():
            try:
                rows = self._connection.fetch_tuples(f"SHOW CREATE TABLE {table}")
            except DatabaseError:
                continue
            if rows:
                statements.append(rows[0][1])
        return "\n\n".join(statements)

    def table_status(self) -> str:
        """SHOW TABLE STATUS for each table as "name : value" lines."""
        blocks = []
        for table in self.tables():
            try:
                row = self._connection.fetch_one("SHOW TABLE STATUS LIKE %s", [table])
            except DatabaseError:
                continue
            if row:
                blocks.append(
                    "".join(
                        f"{key:>20} : {'' if value is None else value}\n"
                        for key, value in row.items()
                    )
                )
        return "\n\n".join(blocks)
