from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

GOLDEN_DIR = Path(__file__).parent / "golden"
INSTALL_SQL = Path(__file__).parents[2] / "install.sql"


def load_schema(connection, path=INSTALL_SQL):
    """Run the CREATE TABLE statements of install.sql (it creates its own database)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    sql = "\n".join(line for line in lines if not line.lstrip().startswith("--"))
    for statement in sql.split(";"):
        statement = statement.strip()
        if statement.upper().startswith("CREATE TABLE"):
            connection.execute(statement)


@pytest.fixture(scope="session")
def mysql_server() -> dict[str, Any]:
    """Connection settings of the test MySQL server (see tools/test_mysql.sh).

    Tests using this fixture are skipped unless ANEMOMETER_TEST_MYSQL is set
    to ``user:password@host:port``.
    """
    url = os.environ.get("ANEMOMETER_TEST_MYSQL")
    if not url:
        pytest.skip("ANEMOMETER_TEST_MYSQL is not set (start one with tools/test_mysql.sh)")
    match = re.fullmatch(r"([^:@]+):([^@]*)@([^:]+):(\d+)", url)
    if not match:
        raise ValueError(f"bad ANEMOMETER_TEST_MYSQL value: {url!r}")
    user, password, host, port = match.groups()
    return {"host": host, "port": int(port), "user": user, "password": password}


@pytest.fixture
def mysql_db(mysql_server) -> Iterator[dict[str, Any]]:
    """A fresh, empty database on the test server; dropped afterwards."""
    from anemometer.db import connect

    name = f"anemometer_test_{uuid.uuid4().hex[:12]}"
    with connect(**mysql_server, db="") as admin:
        admin.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4")
    try:
        yield {**mysql_server, "db": name}
    finally:
        with connect(**mysql_server, db="") as admin:
            admin.execute(f"DROP DATABASE IF EXISTS `{name}`")


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
