"""Very rough extraction of table names from a SQL statement.

The parser splits the statement on whitespace and collects the token that
follows FROM, JOIN, UPDATE or INTO (plus comma-separated tables of an old style
join). It does not understand aliases, subqueries, string literals or quoted
identifiers containing spaces; those limitations are kept on purpose so the
result matches the original PHP ``QueryTableParser``.
"""

from __future__ import annotations

import re

__all__ = ["parse_tables"]

TABLE_KEYWORDS = frozenset({"from", "join", "update", "into"})

_WHITESPACE = re.compile(r"\s+", re.ASCII)
# PCRE without /u: only ASCII word characters count, so e.g. Hangul names are ignored.
_WORD = re.compile(r"\w", re.ASCII)


def parse_tables(query: str) -> list[str]:
    """Return the table names referenced by ``query``, in order of first appearance."""
    tokens = iter(_WHITESPACE.sub(" ", query).split(" "))
    tables: dict[str, None] = {}

    def add(token: str) -> None:
        if _WORD.search(token):
            tables[token.replace("`", "")] = None

    for token in tokens:
        if token.lower() not in TABLE_KEYWORDS:
            continue
        table = next(tokens, "")
        # Old style joins: "FROM a, b, c" -- keep reading while tokens end in a comma.
        while "," in table:
            add(table.replace(",", ""))
            table = next(tokens, "")
        add(table)

    return list(tables)
