"""End-to-end comparison with the original PHP application.

tools/golden/e2e.sh ran every request in tools/golden/e2e_requests.json
through the original index.php against the database built from install.sql and
tools/golden/e2e_fixture.sql. Here the same database is rebuilt and the same
requests go through the Flask app; the responses must match apart from
whitespace and timestamps that depend on the current time.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from anemometer.config import Datasource, Plugins, load_config
from anemometer.db import connect
from anemometer.web import create_app
from tests.conftest import load_golden, load_schema

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tools" / "golden" / "e2e_fixture.sql"
DB_NAME = "anemometer_e2e"  # appears in error messages, so it must match e2e.sh

_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}(?: |\+|%20)\d{2}(?::|%3A)\d{2}(?::|%3A)\d{2}")


def _normalize(body: str) -> str:
    body = _TIMESTAMP.sub("<TS>", body)
    body = re.sub(r"\s+", " ", body)
    return re.sub(r">\s+<", "><", body).strip()


@pytest.fixture(scope="module")
def client(mysql_server):
    with connect(**mysql_server, db="") as admin:
        admin.execute(f"DROP DATABASE IF EXISTS `{DB_NAME}`")
        admin.execute(f"CREATE DATABASE `{DB_NAME}` CHARACTER SET utf8mb4")
    info = {**mysql_server, "db": DB_NAME}
    with connect(**info) as connection:
        load_schema(connection)
        lines = FIXTURE.read_text(encoding="utf-8").splitlines()
        sql = "\n".join(line for line in lines if not line.startswith("--"))
        for statement in filter(None, (s.strip() for s in sql.split(";"))):
            connection.execute(statement)

    sample = load_config(ROOT / "conf" / "config.sample.py")
    config = dataclasses.replace(
        sample,
        datasources={
            "test": Datasource(
                name="test",
                tables={"global_query_review": "fact", "global_query_review_history": "dimension"},
                source_type="slow_query_log",
                **info,
            )
        },
        plugins=Plugins(explain=lambda row: info, show_create=True, show_status=False),
    )
    # The PHP container ran in UTC.
    yield create_app(config, secret_key="test", timezone="UTC").test_client()

    with connect(**mysql_server, db="") as admin:
        admin.execute(f"DROP DATABASE IF EXISTS `{DB_NAME}`")


@pytest.mark.parametrize(
    ("request_", "expected"),
    [pytest.param(c["input"], c["expected"], id=c["input"]["name"]) for c in load_golden("e2e")],
)
def test_matches_php_application(client, request_, expected):
    url = "/index.php?" + request_["query"]
    if "post" in request_:
        response = client.post(
            url, data=request_["post"], content_type="application/x-www-form-urlencoded"
        )
    else:
        response = client.get(url)
    assert _normalize(response.get_data(as_text=True)) == _normalize(expected)
