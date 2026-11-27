"""Render result rows as a table in the style of the ``mysql`` command line client."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

__all__ = ["format_table"]


def _cell(value: object) -> str:
    return "" if value is None else str(value)


def _width(text: str) -> int:
    # The original measured cells in bytes (PHP strlen), so multi-byte text such
    # as Hangul is padded by its UTF-8 length. Kept for identical output.
    return len(text.encode("utf-8"))


def format_table(rows: Iterable[Mapping[str, object]]) -> str:
    """Format ``rows`` like::

        +----+-------+
        | id | table |
        +----+-------+
        | 1  | t     |
        +----+-------+

    Columns appear in order of first appearance across all rows; a row that
    lacks a column shows an empty cell. ``None`` is shown as an empty cell.
    """
    rows = [{name: _cell(value) for name, value in row.items()} for row in rows]

    widths: dict[str, int] = {}
    for row in rows:
        for name, text in row.items():
            widths[name] = max(widths.get(name, 0), _width(text))
    for name in widths:
        widths[name] = max(widths[name], _width(name))

    def rule() -> str:
        return "+" + "+".join("-" * (width + 2) for width in widths.values()) + "+\n"

    def line(cells: Mapping[str, str]) -> str:
        padded = []
        for name, width in widths.items():
            text = cells.get(name, "")
            padded.append(" " + text + " " * (width - _width(text)) + " ")
        return "|" + "|".join(padded) + "|\n"

    parts = [rule(), line({name: name for name in widths}), rule()]
    for row in rows:
        parts += [line(row), rule()]
    return "".join(parts)
