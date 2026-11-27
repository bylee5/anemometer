"""Turn DML statements into SELECTs so that MySQL can EXPLAIN them.

Older MySQL versions can only EXPLAIN SELECT statements, so DELETE, UPDATE and
INSERT ... SELECT are rewritten into an equivalent SELECT that touches the same
tables and conditions. The rewriting is purely regex based and intentionally
mirrors the behaviour of the original PHP ``QueryRewrite`` class.
"""

from __future__ import annotations

import re
from enum import IntEnum

__all__ = ["QueryType", "QueryRewrite"]


class QueryType(IntEnum):
    UNKNOWN = 0
    SELECT = 1
    DELETE = 2
    INSERT = 3
    UPDATE = 4
    ALTER = 5
    DROP = 6
    CREATE = 7
    DELETEMULTI = 8
    UNION = 9
    INSERTSELECT = 10


# PCRE patterns in the original were used without the /u modifier, so \s and \w
# are ASCII-only. re.ASCII keeps the Python behaviour identical.
_FLAGS = re.ASCII
_I = re.ASCII | re.IGNORECASE

_TABLEREF = r"`?[A-Za-z0-9_]+`?(\.`?[A-Za-z0-9_]+`?)?"

_COMMENT_PATTERNS = (
    re.compile(r"\s*/\*.*?\*/\s*", _FLAGS),  # /* ... */
    re.compile(r"#.*$", _FLAGS),  # # ... (only on the last line)
    re.compile(r"--\s+.*$", _FLAGS),  # -- ... (only on the last line)
)

# Order matters: the first matching pattern decides the type.
_TYPE_PATTERNS = (
    (QueryType.SELECT, re.compile(r"^SELECT\s", _I)),
    (QueryType.DELETE, re.compile(r"^DELETE\s+FROM\s", _I)),
    (QueryType.DELETEMULTI, re.compile(rf"^DELETE\s+{_TABLEREF}\s+FROM\s", _I)),
    (QueryType.INSERTSELECT, re.compile(rf"^INSERT\s+INTO\s{_TABLEREF}[\s(]*SELECT\s+", _I)),
    (QueryType.INSERT, re.compile(r"^INSERT\s+INTO\s", _I)),
    (QueryType.UNION, re.compile(r"^(.*)\s+UNION\s+(.*)$", _I)),
    (QueryType.UPDATE, re.compile(r"^UPDATE\s", _I)),
    (QueryType.ALTER, re.compile(r"^ALTER\s", _I)),
    (QueryType.CREATE, re.compile(r"^CREATE\s", _I)),
    (QueryType.DROP, re.compile(r"^DROP\s", _I)),
)

_DELETE_PREFIX = re.compile(r"^DELETE\s+FROM\s", _I)
_DELETEMULTI_PREFIX = re.compile(rf"^DELETE\s+{_TABLEREF}\s+FROM\s", _I)
_UPDATE_PARTS = re.compile(r"^UPDATE\s+(.*)\s+SET\s+(.*)\s+WHERE\s+(.*)$", _I)
_PARENTHESIZED_SELECT = re.compile(r"\(\s*(SELECT\s+.*)\)", _FLAGS)  # case-sensitive
_INSERT_SELECT_TAIL = re.compile(r"^INSERT\s+INTO\s+\w+\s+(SELECT.*)", _I)

# Characters stripped by PHP's trim().
_PHP_WHITESPACE = " \t\n\r\0\x0b"


def _normalize(sql: str) -> str:
    for pattern in _COMMENT_PATTERNS:
        sql = pattern.sub("", sql)
    return sql.strip(_PHP_WHITESPACE).replace("\n", " ")


def _classify(sql: str) -> QueryType:
    for query_type, pattern in _TYPE_PATTERNS:
        if pattern.search(sql):
            return query_type
    return QueryType.UNKNOWN


class QueryRewrite:
    """A single SQL statement, normalized and classified.

    Comments are stripped and newlines are folded into spaces on construction.
    """

    def __init__(self, sql: str | None = None) -> None:
        self.sql: str | None = None if sql is None else _normalize(sql)
        self.type = QueryType.UNKNOWN if self.sql is None else _classify(self.sql)

    def __repr__(self) -> str:
        return f"QueryRewrite(type={self.type.name}, sql={self.sql!r})"

    def to_select(self) -> str | None:
        """Return an equivalent SELECT, or ``None`` if the statement can't be rewritten."""
        sql = self.sql
        if sql is None:
            return None

        if self.type in (QueryType.SELECT, QueryType.UNION):
            select = sql
        elif self.type is QueryType.DELETE:
            select = _DELETE_PREFIX.sub("SELECT 0 FROM ", sql, count=1)
        elif self.type is QueryType.DELETEMULTI:
            select = _DELETEMULTI_PREFIX.sub("SELECT 0 FROM ", sql, count=1)
        elif self.type is QueryType.UPDATE:
            # Like the original, an UPDATE without a WHERE clause yields an empty
            # skeleton ("SELECT  FROM  WHERE"); MySQL then reports the syntax error.
            match = _UPDATE_PARTS.search(sql)
            tables, assignments, where = match.groups() if match else ("", "", "")
            select = f"SELECT {assignments} FROM {tables} WHERE {where}"
        elif self.type is QueryType.INSERTSELECT:
            match = _PARENTHESIZED_SELECT.search(sql) or _INSERT_SELECT_TAIL.search(sql)
            select = match.group(1) if match else ""
        else:
            return None

        return select.strip(_PHP_WHITESPACE)

    def as_explain(self) -> str | None:
        select = self.to_select()
        return None if select is None else f"EXPLAIN {select}"

    def as_extended_explain(self) -> str | None:
        select = self.to_select()
        return None if select is None else f"EXPLAIN EXTENDED {select}"
