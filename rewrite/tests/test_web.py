from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from anemometer.config import Datasource, Plugins, load_config
from anemometer.db import connect
from anemometer.web import create_app
from tests.conftest import load_schema

SAMPLE = Path(__file__).parents[1] / "conf" / "config.sample.py"
REPO_ROOT = Path(__file__).parents[2]
TABLES = {"global_query_review": "fact", "global_query_review_history": "dimension"}


def test_noconfig_page():
    client = create_app(None, secret_key="test").test_client()
    page = client.get("/").get_data(as_text=True)
    assert "You're seeing this page because you haven't configured Anemometer yet." in page
    assert page.rstrip().endswith("</html>")


def test_static_files():
    client = create_app(None, static_dir=REPO_ROOT, secret_key="test").test_client()
    assert client.get("/js/jquery-1.8.3.min.js").status_code == 200
    assert client.get("/img/anemometer.png").status_code == 200
    assert client.get("/js/missing.js").status_code == 404
    assert client.get("/lib/Anemometer.php").status_code == 404


@pytest.fixture
def db_info(mysql_db):
    with connect(**mysql_db) as connection:
        load_schema(connection)
        connection.execute(
            "INSERT INTO global_query_review (checksum, fingerprint, sample, first_seen, last_seen)"
            " VALUES ('A1', 'select * from global_query_review where checksum = ?',"
            " 'select * from global_query_review where checksum = 1', '2024-03-01', '2024-03-31'),"
            " ('B2', 'select ?', 'select 2', '2024-03-02', '2024-03-30')"
        )
        query = "select * from global_query_review where checksum = "
        for host, checksum, sample, ts, count, total in [
            ("db1", "A1", query + "'x'", "2024-03-30 10:00:00", 2, 0.5),
            ("db2", "A1", query + "'y'", "2024-03-31 10:00:00", 1, 1.5),
            ("db1", "B2", "select 2", "2024-03-31 11:00:00", 4, 2),
        ]:
            connection.execute(
                "INSERT INTO global_query_review_history (hostname_max, db_max, checksum,"
                " sample, ts_min, ts_max, ts_cnt, Query_time_sum)"
                " VALUES (%s, 'app', %s, %s, %s, %s, %s, %s)",
                [host, checksum, sample, ts, ts, count, total],
            )
    return {key: mysql_db[key] for key in ("host", "port", "user", "password", "db")}


def _config(db_info, **extra_datasources):
    sample = load_config(SAMPLE)
    datasource = Datasource(name="test", tables=TABLES, source_type="slow_query_log", **db_info)
    return dataclasses.replace(
        sample,
        datasources={"test": datasource, **extra_datasources},
        plugins=Plugins(explain=lambda row: db_info, show_create=True, show_status=True),
    )


@pytest.fixture
def client(db_info):
    app = create_app(_config(db_info), secret_key="test", timezone="Asia/Seoul")
    return app.test_client()


def _text(response):
    return response.get_data(as_text=True)


ALL_TIME = "&dimension-ts_min_start=2024-01-01+00:00:00&dimension-ts_min_end=2025-01-01+00:00:00"


def test_index_redirects_with_one_datasource(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"] == "/?action=report&datasource=test"


def test_index_lists_datasources(db_info):
    other = Datasource(name="other", tables=TABLES, **db_info)
    client = create_app(_config(db_info, other=other), secret_key="t").test_client()
    page = _text(client.get("/index.php"))
    assert "Choose a Datasource" in page
    assert '<option value="other"' in page


def test_report_page(client):
    page = _text(client.get(f"/index.php?action=report&datasource=test{ALL_TIME}"))
    assert '<select name="table_fields[]"' in page
    assert "FROM `global_query_review` AS `fact`" in page
    assert "Showing <b>2</b> results" in page
    assert 'href="/index.php?action=show_query&datasource=test&checksum=A1">A1</a>' in page
    assert '<option value="db2" >db2</option>' in page
    assert page.rstrip().endswith("</html>")


def test_api_json(client):
    response = client.get(
        "/?action=api&output=json&datasource=test&table_fields[]=checksum&table_fields[]=ts_cnt"
        f"&fact-group=checksum&fact-order=checksum{ALL_TIME}"
    )
    assert response.mimetype == "text/html"
    assert json.loads(_text(response)) == {
        "columns": ["checksum", "ts_cnt"],
        "result": [{"checksum": "A1", "ts_cnt": "3"}, {"checksum": "B2", "ts_cnt": "4"}],
    }


def test_api_json2_and_print_r(client):
    query = (
        "&datasource=test&table_fields[]=hour_ts&table_fields[]=ts_cnt&fact-group=hour_ts"
        f"&fact-order=hour_ts{ALL_TIME}"
    )
    series = json.loads(_text(client.get("/?action=api&output=json2" + query)))
    assert series[0]["label"] == "ts_cnt"
    assert [value for _, value in series[0]["data"]] == ["2", "1", "4"]

    printed = _text(client.get("/?action=api&output=print_r" + query))
    assert printed.startswith("Array\n(\n    [0] => hour_ts\n    [1] => ts_cnt\n)\n")


def test_api_reports_sql_errors_inline(client):
    page = _text(client.get("/?action=api&datasource=test&table_fields[]=nope&noheader=1"))
    assert "Unknown column 'nope'" in page
    assert '<pre class="prettyprint">SELECT nope' in page


def test_graph_search_page(client):
    page = _text(client.get("/?action=graph_search&datasource=test"))
    assert 'var GRAPH_DATA_URL = "/?action=api&output=json2&noheader=1&datasource=test&' in page
    assert "plot_field=Query_time_sum" in page
    assert "TIMEZONE_OFFSET = 32400 * 1000" in page


def test_show_query(client):
    page = _text(client.get("/?action=show_query&datasource=test&checksum=A1"))
    assert "Query A1</a>" in page
    assert "CREATE TABLE `global_query_review`" in page
    assert "Name : global_query_review" in page
    assert "on host <strong>db2</strong>" in page
    assert "60 Day(s) History" in page


def test_show_query_unknown_and_invalid(client):
    page = _text(client.get("/?action=show_query&datasource=test&checksum=FF"))
    assert '<div class="alert alert-warning">Unknown checksum: FF</div>' in page

    response = client.get("/?action=show_query&datasource=test&checksum=nothex!")
    assert response.status_code == 500
    assert "Invalid query checksum" in _text(response)


def test_samples_paging(client):
    page = _text(client.get("/?action=samples&datasource=test&checksum=A1&rpp=1"))
    assert "Displaying samples <strong>1 - 1 </strong>" in page
    assert "checksum = &#39;y&#39;" not in page  # no escaping, like the original
    assert "checksum = 'y'" in page
    assert "rpp=1&start=1" in page  # "Older" link


def test_quicksearch(client):
    response = client.post("/?action=quicksearch&datasource=test", data={"checksum": "B2"})
    assert response.headers["Location"] == "/?action=show_query&datasource=test&checksum=B2"
    page = _text(client.post("/?action=quicksearch&datasource=test", data={"checksum": "CC"}))
    assert "Unknown checksum: CC" in page


def test_review_and_session(client, db_info):
    response = client.post(
        "/?action=upd_query&datasource=test&checksum=A1",
        data={
            "submit": "Review and Update Comments",
            "reviewed_by": "dba2",
            "reviewed_status": "needs-fix",
            "comments": "add an index",
        },
    )
    assert response.headers["Location"] == "/?action=show_query&datasource=test&checksum=A1"
    with connect(**db_info) as connection:
        row = connection.fetch_one("SELECT * FROM global_query_review WHERE checksum = 'A1'")
    assert (row["reviewed_by"], row["reviewed_status"], row["comments"]) == (
        "dba2",
        "needs-fix",
        "add an index",
    )
    assert re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", row["reviewed_on"])

    page = _text(client.get("/?action=show_query&datasource=test&checksum=A1"))
    assert '<option value="dba2"  SELECTED >dba2</option>' in page

    client.post("/?action=upd_query&datasource=test&checksum=A1", data={"submit": "Clear Review"})
    with connect(**db_info) as connection:
        row = connection.fetch_one(
            "SELECT reviewed_by FROM global_query_review WHERE checksum='A1'"
        )
    assert row["reviewed_by"] is None


def test_invalid_review_action(client):
    page = _text(
        client.post("/?action=upd_query&datasource=test&checksum=A1", data={"submit": "x"})
    )
    assert "<strong>Error</strong> Invalid form actionx" in page


def test_invalid_action_and_datasource(client):
    assert _text(client.get("/?action=nope")) == "Invalid action (nope)"
    response = client.get("/?action=report&datasource=missing")
    assert response.status_code == 500
    assert "Unknown datasource missing" in _text(response)
