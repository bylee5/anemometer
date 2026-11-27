"""Page rendering: Jinja2 templates plus the JSON / debug outputs of the report API.

The templates in ``anemometer/templates`` were converted from the original PHP
views and keep their markup. Like the PHP views they print values *without*
HTML escaping (autoescape is off) so the output stays identical; see
PORTING_PLAN.md (decision 1: port as-is, fix afterwards).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, tzinfo
from typing import Any

from jinja2 import Environment, PackageLoader, nodes
from jinja2.compiler import CodeGenerator, Frame

from anemometer.util.hexconv import dec2hex

__all__ = [
    "apply_callbacks",
    "flatten_array",
    "graph_series",
    "make_environment",
    "php_json_encode",
    "php_truthy",
    "print_r",
    "report_json",
    "report_json2",
    "report_printr",
]

_DIGITS = re.compile(r"^\d+$")
# PHP 7 is_numeric(): optional leading whitespace, sign, decimal or exponent.
_NUMERIC = re.compile(r"^[ \t\n\r\v\f]*[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
# strptime("%Y-%m-%d %H:%M:%S") accepts a matching prefix.
_DATETIME = re.compile(r"^\s*(\d{1,4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2}):(\d{1,2})")


# -- PHP value semantics used by the views -------------------------------------


def php_echo(value: Any) -> Any:
    """How PHP prints a value: null and false print nothing, true prints 1."""
    if value is None or value is False:
        return ""
    if value is True:
        return "1"
    return value


def php_truthy(value: Any) -> bool:
    """PHP truthiness: "", "0", 0, empty arrays and null are false."""
    return value not in (None, False, "", "0", 0, 0.0) and value != [] and value != {}


def php_str(value: Any) -> str:
    """PHP string conversion (null -> "", true -> "1")."""
    return str(php_echo(value))


def _php_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and _NUMERIC.match(value):
        return float(value)
    return None


def php_eq(left: Any, right: Any) -> bool:
    """PHP 7 loose equality (``==``) for the scalar values the views compare."""
    if left is None or right is None:
        other = right if left is None else left
        return other is None or other == "" or other is False or other == 0
    left_number, right_number = _php_number(left), _php_number(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return php_str(left) == php_str(right)


def php_filled(value: Any) -> bool:
    """``$value != ''`` in PHP (null counts as empty)."""
    return value is not None and value != ""


def flatten_array(value: Any) -> list[Any]:
    """All leaf values of nested lists/dicts, in order."""
    items = value.values() if isinstance(value, Mapping) else value
    flat: list[Any] = []
    for item in items or []:
        if isinstance(item, (Mapping, list, tuple)):
            flat.extend(flatten_array(item))
        else:
            flat.append(item)
    return flat


def php_json_encode(value: Any) -> str:
    """json_encode() with PHP's default flags: escaped slashes and \\u escapes."""
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).replace("/", "\\/")


def print_r(value: Any, indent: int = 0) -> str:
    """PHP print_r() output for scalars, lists and dicts."""
    if isinstance(value, (Mapping, list, tuple)):
        items = value.items() if isinstance(value, Mapping) else enumerate(value)
        pad = " " * indent
        lines = [f"Array\n{pad}(\n"]
        for key, item in items:
            lines.append(f"{pad}    [{key}] => {print_r(item, indent + 8)}\n")
        lines.append(f"{pad})\n")
        return "".join(lines)
    return str(php_echo(value))


def apply_callbacks(
    row: Mapping[str, Any], callbacks: Mapping[str, Callable] | None
) -> tuple[dict[str, Any], list[Any]]:
    """Run per-column display callbacks; returns the new row and the row's CSS classes.

    A callback returns ``(value, css_class)``; the class is optional.
    """
    row = dict(row)
    classes: list[Any] = []
    for column, callback in (callbacks or {}).items():
        if column in row:
            result = callback(row[column])
            row[column] = result[0]
            classes.append(php_echo(result[1]) if len(result) > 1 else "")
    return row, classes


# -- templates -----------------------------------------------------------------


class _PhpConcatCodeGenerator(CodeGenerator):
    """Compile ``a ~ b`` with PHP string conversion, so None joins as ""."""

    def visit_Concat(self, node: nodes.Concat, frame: Frame) -> None:
        self.write("environment.php_concat((")
        for arg in node.nodes:
            self.visit(arg, frame)
            self.write(", ")
        self.write("))")


class _PhpEnvironment(Environment):
    code_generator_class = _PhpConcatCodeGenerator

    @staticmethod
    def php_concat(values: Iterable[Any]) -> str:
        return "".join(php_str(value) for value in values)


def make_environment() -> Environment:
    env = _PhpEnvironment(
        loader=PackageLoader("anemometer", "templates"),
        autoescape=False,
        finalize=php_echo,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["php_json"] = php_json_encode
    env.filters["flatten"] = flatten_array
    env.filters["php_filled"] = php_filled
    env.filters["php_truthy"] = php_truthy
    env.tests["php_eq"] = php_eq
    env.globals["apply_callbacks"] = apply_callbacks
    return env


# -- report API outputs ----------------------------------------------------------


def report_json(columns: Sequence[str], result: Sequence[Mapping[str, Any]]) -> str:
    return php_json_encode({"columns": list(columns), "result": list(result)})


def report_printr(columns: Sequence[str], result: Sequence[Mapping[str, Any]]) -> str:
    return print_r(list(columns)) + print_r(list(result))


def _timestamp(value: Any, tz: tzinfo | None) -> int:
    """mktime() of a "YYYY-MM-DD HH:MM:SS" string in local time (or ``tz``)."""
    match = _DATETIME.match(value) if isinstance(value, str) else None
    if match:
        year, month, day, hour, minute, second = (int(part) for part in match.groups())
        moment = datetime(year, month, day, hour, minute, second)
    else:
        # strptime() failed: PHP ends up with mktime(0, 0, 0, 1, 0, 1900).
        moment = datetime(1899, 12, 31)
    return int(moment.replace(tzinfo=tz).timestamp() if tz else moment.timestamp())


def graph_series(
    columns: Iterable[str],
    result: Sequence[Mapping[str, Any]],
    group: str | None,
    *,
    tz: tzinfo | None = None,
) -> list[dict[str, Any]] | None:
    """Turn report rows into flot series: one series per non-group column.

    Each point is ``[x, value]`` where x is the group column -- as is when it
    is numeric (e.g. ``minute_ts``), otherwise parsed as a datetime and
    converted to a Unix timestamp in local time (``tz`` to override).
    Numeric column names (checksum pivots) are labelled in hex.
    """
    series = [column for column in columns if column != group]
    if not series:
        return None

    data: dict[str, list[list[Any]]] = {}
    if result:
        first = result[0].get(group)
        is_datetime = not (isinstance(first, str) and _DIGITS.match(first))
        for row in result:
            for column in series:
                x = row.get(group)
                if is_datetime:
                    x = _timestamp(x, tz)
                data.setdefault(column, []).append([x, row.get(column)])

    labelled = []
    for column in series:
        label = column
        if _NUMERIC.match(column) and column.strip().isdigit():
            label = dec2hex(column.strip())
        labelled.append({"label": label, "data": data.get(column)})
    return labelled


def report_json2(
    columns: Sequence[str],
    result: Sequence[Mapping[str, Any]],
    group: str | None,
    *,
    debug_sql: str | None = None,
    tz: tzinfo | None = None,
) -> str:
    """Graph data for the flot charts (``output=json2``)."""
    prefix = f"<pre>{debug_sql}</pre>" if debug_sql is not None else ""
    return prefix + php_json_encode(graph_series(columns, result, group, tz=tz))
