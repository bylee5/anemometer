from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GOLDEN_DIR = Path(__file__).parent / "golden"


def load_golden(name: str) -> list[dict[str, Any]]:
    """Load cases recorded from the original PHP implementation.

    Regenerate with ``tools/golden/run.sh <name>``.
    """
    with open(GOLDEN_DIR / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def golden_params(name: str) -> list[Any]:
    """Golden cases as pytest params, with a readable id for each."""
    import pytest

    return [
        pytest.param(case["input"], case["expected"], id=f"{i:02d}-{str(case['input'])[:40]!r}")
        for i, case in enumerate(load_golden(name))
    ]
