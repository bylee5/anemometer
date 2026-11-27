"""Build and run aggregate report queries from search form values.

:class:`TableReport` turns request parameters into a single SELECT over a
"fact" table joined to any number of "dimension" tables, grouped and ordered
as requested. It is aimed at time series data: aggregate some columns
(SUM/MIN/MAX/AVG) grouped by another.

Which form fields exist, and how each value ends up in the query, is defined by
a :class:`~anemometer.config.ReportSpec`. Every field has a chain of filters,
for example::

    "fields": {
        "fact": {"group": "group", "where": "raw_where"},
        "dimension": {
            "hostname_max": "clear|where",
            "ts_min": "date_range|reldate|clear|where",
            "pivot-hostname_max": "clear|pivot|select",
        },
    }

The form field for ``hostname_max`` on the dimension table is called
``dimension-hostname_max``. Its value runs through the filters left to right;
each filter receives ``(column, form_variable, value, operator)`` tuples and
returns the tuples for the next filter. Terminal filters (``where``, ``group``,
``select`` ...) record the value in the query and end the chain.

Available filters:

``clear``       drop empty values
``reldate``     resolve "now" / "-1 month" style values to timestamps
``date_range``  read ``<field>_start`` and ``<field>_end`` as a >= / <= range
``ge le gt lt ne like``  change the comparison operator
``where``       add a WHERE condition
``group order having limit``  set that clause to the raw value
``raw_where``   append the raw value to the WHERE clause
``pivot``       turn each distinct value of the column into its own SUM column
``select``      add the produced columns to the SELECT list

Values are interpolated into the SQL text exactly as the original PHP
implementation did; several fields (where, group, having, order, limit) are
raw SQL by design.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Callable, NamedTuple
from urllib.parse import quote_plus

from anemometer.config import ReportSpec
from anemometer.db import Connection, DatabaseError, Row
from anemometer.request_vars import RequestVars
from anemometer.util.timeutil import resolve_relative_date

__all__ = ["ReportError", "SelectColumn", "TableReport", "remove_schema_name"]

# Filters that see a field under a different form name (field_start/_end) and
# therefore have to run when building search URIs.
_URI_FILTERS = ("date_range",)

_AGGREGATE_NAME = re.compile(r"^([^_]+)_?.*_([^_]+)$", re.ASCII)
_AGGREGATE_CALL = re.compile(r"(SUM|MIN|MAX|AVG|COUNT)\(([.\w]+)\)", re.ASCII)
_PHP_BACKREF = re.compile(r"\\(\d{1,2})|\$(\d{1,2})|\$\{(\d{1,2})\}")

_PREFIX_AGGREGATES = {
    "SUM": "SUM",
    "COUNT": "SUM",
    "AVG": "AVG",
    "MIN": "MIN",
    "FIRST": "MIN",
    "MAX": "MAX",
    "LAST": "MAX",
}
_SUFFIX_AGGREGATES = {
    "sum": "SUM",
    "cnt": "SUM",
    "avg": "AVG",
    "median": "AVG",
    "95": "AVG",
    "min": "MIN",
    "stddev": "MIN",
    "max": "MAX",
}


class ReportError(Exception):
    """The report can't be built from the configuration and form values."""


class SelectColumn(NamedTuple):
    expression: str
    alias: str | None
    aggregate: str | None


class _Condition(NamedTuple):
    column: str
    value: Any
    operator: str


def _php_str(value: Any) -> str:
    """String conversion as PHP's string interpolation does it."""
    if value is None or value is False:
        return ""
    if value is True:
        return "1"
    if isinstance(value, (list, dict)):
        return "Array"
    return str(value)


def _is_blank(value: Any) -> bool:
    return value is None or value == ""


def _addslashes(value: Any) -> str:
    text = _php_str(value)
    return re.sub(r"(['\"\\])", r"\\\1", text).replace("\0", "\\0")


def _urlencode(value: Any) -> str:
    """PHP urlencode(): like quote_plus, but '~' is encoded too. Arrays encode as ''."""
    if isinstance(value, (list, dict)):
        return ""
    return quote_plus(_php_str(value), safe="").replace("~", "%7E")


def _php_replacement(template: str) -> Callable[[re.Match], str]:
    """Expand a preg_replace() replacement string (\\1, $1, ${1}; \\\\ and \\$ escapes)."""

    def expand(match: re.Match) -> str:
        out = []
        position = 0
        while position < len(template):
            char = template[position]
            if char == "\\" and template[position + 1 : position + 2] in ("\\", "$"):
                out.append(template[position + 1])
                position += 2
                continue
            if char in "\\$":
                backref = _PHP_BACKREF.match(template, position)
                if backref:
                    group = int(next(g for g in backref.groups() if g is not None))
                    if group <= (match.re.groups or 0):
                        out.append(match.group(group) or "")
                    position = backref.end()
                    continue
            out.append(char)
            position += 1
        return "".join(out)

    return expand


def remove_schema_name(column: str) -> str:
    """``alias.column`` -> ``column`` (only for a single dot, and not for IF(...) expressions)."""
    if column.count(".") == 1 and not column.startswith("IF"):
        return column.split(".", 1)[1]
    return column


class TableReport:
    """Builds (and optionally runs) the report query for one request."""

    def __init__(
        self,
        tables: Mapping[str, str],
        spec: ReportSpec,
        params: RequestVars,
        *,
        connection: Connection | None = None,
        schema: str | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        """
        :param tables: real table name -> alias; one alias must be "fact".
            The first table is the one selected FROM, the others are joined.
        :param spec: field definitions for this kind of datasource.
        :param params: the request parameters (read for every form field).
        :param connection: database connection, needed only to run queries.
        :param schema: database name, used to list table columns.
        :param now: clock used for relative dates.
        """
        self._tables = dict(tables)
        self._spec = spec
        self._params = params
        self._connection = connection
        self._schema = schema
        self._now = now
        self._pivot: dict[str, list[Any]] = {}
        self._non_aggregate_columns: list[str] = []

        self._select: list[SelectColumn] = []
        self._from: tuple[str, str] | None = None
        self._joins: list[tuple[str, str, str | None]] = []
        self._where: list[_Condition] = []
        self._extra_where: Any = None
        self._clauses: dict[str, Any] = {
            "group": None,
            "having": None,
            "order": None,
            "limit": None,
        }
        self._processed = False
        self._sql: str | None = None

        self._filters: dict[str, Callable[..., list[tuple] | None]] = {
            "clear": self._clear,
            "reldate": self._reldate,
            "date_range": self._date_range,
            "ge": self._operator(">="),
            "le": self._operator("<="),
            "gt": self._operator(">"),
            "lt": self._operator("<"),
            "ne": self._operator("!="),
            "like": self._like,
            "where": self._add_where,
            "group": self._clause("group"),
            "order": self._clause("order"),
            "having": self._clause("having"),
            "limit": self._clause("limit"),
            "raw_where": self._raw_where,
            "pivot": self._pivot_columns,
            "select": self._add_select,
        }

        self.table_for_alias("fact")  # validates the table list

    # -- configuration --------------------------------------------------

    @property
    def tables(self) -> list[str]:
        """Real table names, in join order."""
        return list(self._tables)

    def table_for_alias(self, alias: str) -> str:
        for table, table_alias in self._tables.items():
            if table_alias == alias:
                return table
        raise ReportError(f"No alias {alias}")

    def form_fields(self) -> list[str]:
        """Names of all form fields, e.g. ``["fact-checksum", "dimension-hostname_max"]``."""
        return [
            f"{alias}-{field}" for alias, fields in self._spec.fields.items() for field in fields
        ]

    def custom_fields(self) -> list[str]:
        return list(self._spec.custom_fields)

    def set_pivot_values(self, form_field: str, values: Iterable[Any]) -> None:
        """Values that become columns when the ``form_field`` pivot is used."""
        self._pivot[form_field] = list(values)

    def pivot_values(self, form_field: str) -> list[Any]:
        return self._pivot.get(form_field, [])

    def set_non_aggregate_columns(self, columns: Sequence[str]) -> None:
        """Columns selected as-is even if their name suggests an aggregate."""
        self._non_aggregate_columns = list(columns)

    # -- filters ---------------------------------------------------------

    @staticmethod
    def _clear(column, var_name, value, op=None):
        return [(column, var_name, None if _is_blank(value) else value, op)]

    def _reldate(self, column, var_name, value, op=None):
        if isinstance(value, str):
            value = resolve_relative_date(value, self._now())
        return [(column, var_name, value, op)]

    def _date_range(self, column, var_name, value=None, op=None):
        return [
            (column, f"{var_name}_start", self._params.get(f"{var_name}_start"), ">="),
            (column, f"{var_name}_end", self._params.get(f"{var_name}_end"), "<="),
        ]

    @staticmethod
    def _operator(operator: str) -> Callable[..., list[tuple]]:
        def apply(column, var_name, value, op=None):
            return [(column, var_name, value, operator)]

        return apply

    @staticmethod
    def _like(column, var_name, value, op=None):
        return [(column, var_name, None if value is None else f"%{_php_str(value)}%", "LIKE")]

    def _add_where(self, column, var_name, value, op=None):
        self._where.append(_Condition(column, value, op or "="))

    def _clause(self, name: str) -> Callable[..., None]:
        def apply(column, var_name, value, op=None):
            self._clauses[name] = value

        return apply

    def _raw_where(self, column, var_name, value, op=None):
        self._extra_where = value

    def _pivot_columns(self, column, var_name, value, op=None):
        """One conditional SUM column per pivot value (see set_pivot_values)."""
        if value is None:
            return None
        column = column.replace("pivot-", "")
        custom = self._spec.custom_fields.get(value) if isinstance(value, str) else None
        columns = []
        for pivot_value in self.pivot_values(var_name):
            condition = f"{column}='{_addslashes(pivot_value)}'"
            if custom is not None:
                # SUM(x) in the custom expression becomes SUM(IF(<condition>,x,0)).
                replacement = _php_replacement(f"\\1(IF({condition},\\2,0))")
                expression = _AGGREGATE_CALL.sub(replacement, custom)
                if expression not in ("", "0"):
                    columns.append((expression, pivot_value, None))
            else:
                columns.append((f"IF({condition},{_php_str(value)},0)", pivot_value, "SUM"))
        return columns

    def _add_select(self, expression, alias=None, aggregate=None, *_):
        self._select.append(SelectColumn(expression, alias, aggregate))

    # -- query building --------------------------------------------------

    def _aggregate_for(self, name: str) -> str | None:
        """Guess the aggregate function from a column name.

        ``Query_time_sum`` -> SUM, ``Rows_sent_max`` -> MAX, ``SUM_TIMER_WAIT`` -> SUM
        (performance_schema puts the aggregate first), ``ts_min`` -> MIN.
        """
        name = name.split(".", 1)[1] if "." in name else name
        if name in self._non_aggregate_columns:
            return None
        match = _AGGREGATE_NAME.match(name)
        if not match:
            return None
        prefix, suffix = match.groups()
        return _PREFIX_AGGREGATES.get(prefix) or _SUFFIX_AGGREGATES.get(suffix)

    def process_form_data(self) -> None:
        """Read the form values into the query parts. Runs once; called by query()."""
        if self._processed:
            return

        selected = self._params.get("table_fields")
        if isinstance(selected, dict):
            selected = list(selected.values())
        if not isinstance(selected, list) or not selected:
            raise ReportError("No fields selected")

        columns: dict[str, SelectColumn] = {}
        for name in selected:
            if not isinstance(name, (str, int)):
                continue  # nested arrays can't name a column
            name = str(name)
            custom = self._spec.custom_fields.get(name)
            if custom is not None:
                columns[name] = SelectColumn(custom, name, None)
            else:
                columns[name] = SelectColumn(name, None, self._aggregate_for(name))
        self._select.extend(columns.values())

        for position, (table, alias) in enumerate(self._tables.items()):
            if position == 0:
                self._from = (table, alias)
            else:
                self._joins.append((table, alias, self._spec.join.get(alias)))

        for alias in self._tables.values():
            for field, chain in self._spec.fields.get(alias, {}).items():
                var_name = f"{alias}-{field}"
                column = self._spec.custom_fields.get(field, f"{alias}.{field}")
                args: list[tuple] = [(column, var_name, self._params.get(var_name))]
                for name in chain.split("|"):
                    try:
                        apply = self._filters[name]
                    except KeyError:
                        raise ReportError(f"unknown filter {name!r} for {var_name}") from None
                    next_args: list[tuple] = []
                    for arg in args:
                        next_args.extend(apply(*arg) or [])
                    args = next_args

        self._processed = True

    def query(self) -> str:
        """The SQL for this report (built once, then cached)."""
        self.process_form_data()
        if self._sql is not None:
            return self._sql

        if not self._select:
            select = "*"
        else:
            parts = []
            for expression, alias, aggregate in self._select:
                if aggregate is not None:
                    expression = remove_schema_name(expression)
                    name = alias if alias is not None else expression
                    parts.append(f"{aggregate}({expression}) AS `{name}`")
                else:
                    parts.append(expression + (f" AS `{alias}`" if alias is not None else ""))
            select = ",\n  ".join(parts) + "\n"
        sql = f"SELECT {select}"

        assert self._from is not None
        sql += f" FROM `{self._from[0]}` AS `{self._from[1]}` \n"
        for table, alias, condition in self._joins:
            sql += f" JOIN `{table}` AS `{alias}` {_php_str(condition)} \n"

        where = [condition for condition in self._where if condition.value is not None]
        if where:
            sql += (
                " WHERE "
                + "\n  AND ".join(f'{c.column} {c.operator} "{_php_str(c.value)}"' for c in where)
                + "\n"
            )
        if not _is_blank(self._extra_where):
            keyword = "AND" if where else "WHERE"
            sql += f" {keyword} ({_php_str(self._extra_where)}) "

        for clause, keyword in (
            ("group", "GROUP BY"),
            ("having", "HAVING"),
            ("order", "ORDER BY"),
            ("limit", "LIMIT"),
        ):
            value = self._clauses[clause]
            if not _is_blank(value):
                sql += f" {keyword} {_php_str(value)} \n"

        self._sql = sql
        return sql

    def column_names(self) -> list[str]:
        """Names of the result columns, in order."""
        return [
            remove_schema_name(alias if alias not in (None, "") else expression)
            for expression, alias, _ in self._select
        ]

    def search_uri(self, exceptions: Iterable[str] | None = None) -> str:
        """URL query string reproducing this search (without ``exceptions`` fields)."""
        self.process_form_data()
        skipped = set(exceptions or ())
        params = []
        for alias in self._tables.values():
            for field, chain in self._spec.fields.get(alias, {}).items():
                var_name = f"{alias}-{field}"
                if var_name in skipped:
                    continue
                value = self._params.get(var_name)

                handled = False
                for name in chain.split("|"):
                    if name in _URI_FILTERS:
                        for _, arg_name, arg_value, _ in self._filters[name](
                            f"{alias}.{field}", var_name, value
                        ):
                            if not _is_blank(arg_value):
                                params.append(f"{arg_name}={_urlencode(arg_value)}")
                            handled = True
                if not handled and not _is_blank(value):
                    params.append(f"{var_name}={_urlencode(value)}")

        selected = self._params.get("table_fields")
        if isinstance(selected, dict):
            selected = list(selected.values())
        if isinstance(selected, list):
            params.extend(f"table_fields%5B%5D={_php_str(name)}" for name in selected)
        return "&".join(params)

    # -- database access -------------------------------------------------

    def _require_connection(self) -> Connection:
        if self._connection is None:
            raise ReportError("this report has no database connection")
        return self._connection

    def execute(self, sql: str | None = None) -> list[Row]:
        """Run ``sql`` (default: this report's query) and return all rows."""
        return self._require_connection().fetch_all(self.query() if sql is None else sql)

    def table_fields(self, table: str | None = None) -> list[str]:
        """Column names of ``table`` (default: all report tables) from INFORMATION_SCHEMA."""
        tables = [table] if table is not None else self.tables
        placeholders = ",".join(["%s"] * len(tables))
        rows = self._require_connection().fetch_tuples(
            "SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS"
            f" WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN ({placeholders})",
            [self._schema, *tables],
        )
        return [column for _, column in rows]

    def distinct_values(self, table: str, column: str) -> list[str | None]:
        """All distinct values of a column, e.g. for drop-downs or pivots ([] on error)."""
        try:
            rows = self._require_connection().fetch_tuples(
                f"SELECT DISTINCT `{column}` FROM `{table}`"
            )
        except DatabaseError:
            return []
        return [row[0] for row in rows]
