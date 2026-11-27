"""Request parameters with the semantics the original PHP code relied on.

The PHP controller looked values up with ``get_var()`` (POST first, then GET)
and frequently *wrote* into ``$_GET`` to pass search settings on to the report
builder. :class:`RequestVars` reproduces that: it holds a copy of the form and
query parameters for one request, and writes always go to the query layer.

Parameter names follow PHP's rules, so ``table_fields[]=a&table_fields[]=b``
becomes ``{"table_fields": ["a", "b"]}``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import parse_qsl

__all__ = ["RequestVars", "parse_php_params"]

_CANONICAL_INT = re.compile(r"^(0|-?[1-9][0-9]*)$")
_INDEX = re.compile(r"\[([^\]]*)\]")

# A PHP array: keys are ints or strings, insertion ordered.
PhpArray = dict


def _php_key(key: str) -> int | str:
    """Integer-like strings become int keys, as in PHP arrays."""
    if _CANONICAL_INT.match(key) and -(2**63) <= int(key) < 2**63:
        return int(key)
    return key


def _next_index(array: PhpArray) -> int:
    return max([key + 1 for key in array if isinstance(key, int)] + [0])


def _split_name(name: str) -> tuple[str, list[str]] | None:
    """Split ``a[b][c]`` into ("a", ["b", "c"]) following PHP's variable name rules.

    Returns ``None`` for names PHP ignores (an empty base name).
    """
    name = name.lstrip(" ")
    base, bracket, rest = name.partition("[")
    base = base.replace(" ", "_").replace(".", "_")
    if not base:
        return None
    if not bracket:
        return base, []
    if "]" not in rest:
        # An unterminated '[' is not an index; it becomes part of the name.
        return f"{base}_{rest}", []

    indexes = []
    rest = bracket + rest
    while match := _INDEX.match(rest):  # anything after the last ']' is ignored
        indexes.append(match.group(1))
        rest = rest[match.end() :]
    return base, indexes


def _to_python(value: Any) -> Any:
    """Turn PHP arrays with keys 0..n-1 (in order) into lists, recursively."""
    if not isinstance(value, dict):
        return value
    converted = {key: _to_python(item) for key, item in value.items()}
    if list(converted) == list(range(len(converted))):
        return list(converted.values())
    return converted


def parse_php_params(pairs: Iterable[tuple[str, str]]) -> dict[str, Any]:
    """Build a PHP-style parameter dict (like ``$_GET``) from decoded name/value pairs."""
    root: PhpArray = {}
    for raw_name, value in pairs:
        split = _split_name(raw_name)
        if split is None:
            continue
        base, indexes = split
        keys: list[int | str | None] = [base] + [
            _php_key(index) if index != "" else None for index in indexes
        ]

        container = root
        for position, key in enumerate(keys):
            if key is None:
                key = _next_index(container)
            if position == len(keys) - 1:
                container[key] = value
            else:
                child = container.get(key)
                if not isinstance(child, dict):
                    child = container[key] = {}
                container = child
    return {key: _to_python(value) for key, value in root.items()}


class RequestVars:
    """Mutable view of one request's parameters (form values win over query values)."""

    def __init__(
        self,
        query: Mapping[str, Any] | None = None,
        form: Mapping[str, Any] | None = None,
    ) -> None:
        self._query: dict[str, Any] = dict(query or {})
        self._form: dict[str, Any] = dict(form or {})

    @classmethod
    def from_strings(cls, query_string: str = "", form_body: str = "") -> RequestVars:
        """Parse url-encoded query and form strings with PHP's rules."""

        def parse(text: str) -> dict[str, Any]:
            return parse_php_params(parse_qsl(text, keep_blank_values=True))

        return cls(parse(query_string), parse(form_body))

    def get(self, name: str, default: Any = None) -> Any:
        """Return the first non-``None`` value from the form, then the query."""
        for layer in (self._form, self._query):
            value = layer.get(name)
            if value is not None:
                return value
        return default

    def set(self, name: str, value: Any) -> None:
        """Set a query parameter (form values with the same name still take precedence)."""
        self._query[name] = value

    def append(self, name: str, value: Any) -> None:
        """Append to a list-valued query parameter, creating it if needed."""
        current = self._query.get(name)
        if current is None:
            self._query[name] = [value]
        elif isinstance(current, list):
            current.append(value)
        elif isinstance(current, dict):
            current[_next_index(current)] = value
        else:
            raise TypeError(f"query parameter {name!r} is not a list")

    def discard(self, name: str) -> None:
        """Remove a query parameter if present."""
        self._query.pop(name, None)

    def in_query(self, name: str) -> bool:
        """True if the query layer has ``name`` (even when its value is ``None``)."""
        return name in self._query

    @property
    def query(self) -> Mapping[str, Any]:
        return dict(self._query)

    @property
    def form(self) -> Mapping[str, Any]:
        return dict(self._form)

    def __repr__(self) -> str:
        return f"RequestVars(query={self._query!r}, form={self._form!r})"
