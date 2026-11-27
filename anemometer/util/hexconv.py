"""Conversion of (possibly 64-bit unsigned) decimal checksums to hex."""

from __future__ import annotations

__all__ = ["dec2hex"]


def dec2hex(value: str | int) -> str:
    """Return the upper-case hex representation of a non-negative decimal number.

    >>> dec2hex("18446744073709551615")
    'FFFFFFFFFFFFFFFF'
    """
    return format(int(value), "X")
