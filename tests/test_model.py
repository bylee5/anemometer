from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

from anemometer.config import AppConfig, Datasource, Plugins, load_config
from anemometer.db import connect
from anemometer.explain import ExplainError
from anemometer.model import AnemometerModel, ModelError, run_script
from tests.conftest import load_schema

SAMPLE = Path(__file__).parents[1] / "conf" / "config.sample.py"
SLOW_TABLES = {"global_query_review": "fact", "global_query_review_history": "dimension"}


def _config(**datasources: Datasource) -> AppConfig:
    sample = load_config(SAMPLE)
    return dataclasses.replace(sample, datasources={**sample.datasources, **datasources})


def _datasource(name, source_type, tables=SLOW_TABLES, **db):
    values = {"host": "h", "user": "u", "password": "", "db": "d", **db}
    return Datasource(name=name, tables=tables, source_type=source_type, **values)


@pytest.fixture
def model() -> AnemometerModel:
    return AnemometerModel(
        _config(
            ps=_datasource("ps", "performance_schema", {"events_summary": "fact"}),
            psh=_datasource(
                "psh", "performance_schema_history", {"es": "fact", "esh": "dimension"}
            ),
            untyped=_datasource("untyped", None),
        )
    )


# -- configuration (no database) --------------------------------------------


def test_configuration_lookups(model):
    assert model.default_report_action == "report"
    assert list(model.reviewers) == ["dba1", "dba2"]
    assert "needs-fix" in model.review_types
    assert model.datasource_names() == ["localhost", "ps", "psh", "untyped"]
    assert model.datasource("localhost").db == "slow_query_log"
    assert model.datasource("nope") is None


def test_set_datasource(model):
    assert model.source_type == "default"
    model.set_datasource("localhost")
    assert model.current_datasource.name == "localhost"
    assert model.source_type == "slow_query_log"
    assert (model.fact_table, model.dimension_table) == tuple(SLOW_TABLES)
    assert model.table_aliases() == SLOW_TABLES

    model.set_datasource("untyped")
    assert model.source_type == "default"

    with pytest.raises(ModelError, match="Unknown datasource nope"):
        model.set_datasource("nope")


@pytest.mark.parametrize(
    ("datasource", "expected"),
    [
        (None, {"time": "ts_min", "hostname": "hostname_max", "checksum": "checksum"}),
        ("localhost", {"time": "ts_min", "hostname": "hostname_max", "sample": "sample"}),
        ("untyped", {"fingerprint": "fingerprint", "checksum": "checksum"}),
        ("psh", {"time": "FIRST_SEEN", "checksum": "DIGEST", "hostname": "hostname"}),
        ("psh", {"fingerprint": "fingerprint", "sample": "DIGEST_TEXT"}),
    ],
)
def test_field_names(model, datasource, expected):
    if datasource:
        model.set_datasource(datasource)
    assert {kind: model.field_name(kind) for kind in expected} == expected


def test_report_defaults(model):
    with pytest.raises(ModelError, match="without a datasource"):
        model.report_defaults()
    model.set_datasource("localhost")
    assert model.report_defaults()["fact-group"] == "checksum"
    assert model.report_defaults("graph_defaults")["plot_field"] == "Query_time_sum"
    model.set_datasource("psh")
    assert model.report_defaults("graph_defaults")["plot_field"] == "SUM_TIMER_WAIT"
    assert model.report_defaults("history_defaults")["fact-group"] == "date"


def test_report_specs_and_callbacks(model):
    assert model.report_spec(None) is model.config.reports["slow_query_log"]
    assert "DIGEST" in model.form_fields("performance_schema")["fact"]
    with pytest.raises(ModelError):
        model.report_spec("default")
    assert set(model.callbacks("slow_query_log", "table")) == {"date", "checksum"}
    assert model.callbacks("slow_query_log", "json") is None
    assert model.callbacks("default", "table") is None


def test_database_requires_a_datasource(model):
    with pytest.raises(ModelError, match="No datasource selected"):
        model.connect()


def test_plugins_without_explainer(model):
    assert model.explain_for_sample() is None
    assert model.create_table() is None
    assert model.table_status() is None
    model.init_query_explainer(None)
    assert model.explainer is None


def test_query_advisor_missing_script(tmp_path):
    config = dataclasses.replace(
        _config(), plugins=Plugins(query_advisor=str(tmp_path / "pt-query-advisor"))
    )
    model = AnemometerModel(config)
    assert model.query_advisor("SELECT 1") == (
        f"can't find query advisor at {tmp_path / 'pt-query-advisor'}"
    )
    assert AnemometerModel(_config()).query_advisor("SELECT 1") is None


SCRIPT = (
    f'"{sys.executable}" -c "import sys; data = sys.stdin.read();'
    " print(data.upper()); print('warning', file=sys.stderr)\""
)


def test_run_script_returns_stdout_then_stderr():
    output = run_script(SCRIPT, "plan 한글")
    assert output.replace("\r\n", "\n") == "PLAN 한글\nwarning\n"


def test_visual_explain_runs_the_configured_script():
    model = AnemometerModel(dataclasses.replace(_config(), plugins=Plugins(visual_explain=SCRIPT)))
    assert model.visual_explain("x").startswith("X")
    assert (
        AnemometerModel(dataclasses.replace(_config(), plugins=Plugins())).visual_explain("x")
        is None
    )


# -- with a database ---------------------------------------------------------


@pytest.fixture
def db_model(mysql_db):
    with connect(**mysql_db) as connection:
        load_schema(connection)
        connection.execute(
            "INSERT INTO global_query_review (checksum, fingerprint, sample, reviewed_by)"
            " VALUES ('A', 'select ?', 'select 1', 'dba1'), ('B', 'select ?', 'select 2', NULL)"
        )
        for host, sample, ts in [
            ("h1", "select 1 /* old */", "2024-03-30 10:00:00"),
            ("h2", "select * from global_query_review /* new */", "2024-03-31 10:00:00"),
            ("h1", "select 1 /* oldest */", "2024-03-29 10:00:00"),
        ]:
            connection.execute(
                "INSERT INTO global_query_review_history"
                " (hostname_max, db_max, checksum, sample, ts_min, ts_max)"
                " VALUES (%s, 'app', 'A', %s, %s, %s)",
                [host, sample, ts, ts],
            )
    info = {k: mysql_db[k] for k in ("host", "port", "user", "password", "db")}
    datasource = _datasource("test", "slow_query_log", **info)
    plugins = Plugins(explain=lambda row: info, show_create=True, show_status=True)
    model = AnemometerModel(dataclasses.replace(_config(test=datasource), plugins=plugins))
    model.set_datasource("test")
    yield model
    model.close()


def test_checksum_exists(db_model):
    assert db_model.checksum_exists("A")
    assert not db_model.checksum_exists("Z")
    assert not db_model.checksum_exists(None)
    assert not db_model.checksum_exists("' OR '1'='1")


def test_query_by_checksum(db_model):
    row = db_model.query_by_checksum("A")
    assert row["fingerprint"] == "select ?"
    assert row["reviewed_by"] == "dba1"
    assert db_model.query_by_checksum("Z") is None


def test_query_samples(db_model):
    samples = db_model.query_samples("A", limit=2)
    assert [s["sample"] for s in samples] == [
        "select * from global_query_review /* new */",
        "select 1 /* old */",
    ]
    assert [s["sample"] for s in db_model.query_samples("A", 5, 2)] == ["select 1 /* oldest */"]


def test_update_query(db_model):
    db_model.update_query(
        "A", {"reviewed_by": "dba2", "reviewed_status": "good", "comments": 'it\'s "fine"'}
    )
    row = db_model.query_by_checksum("A")
    assert (row["reviewed_by"], row["reviewed_status"], row["comments"]) == (
        "dba2",
        "good",
        'it\'s "fine"',
    )

    db_model.update_query("A", {"reviewed_by": "NULL", "reviewed_on": "NULL", "comments": None})
    row = db_model.query_by_checksum("A")
    assert (row["reviewed_by"], row["reviewed_on"], row["comments"]) == (None, None, "")
    assert db_model.query_by_checksum("B")["comments"] is None


def test_explainer_plugins(db_model):
    sample = db_model.query_samples("A")[0]
    db_model.init_query_explainer(sample)
    assert "| global_query_review " in db_model.explain_for_sample()
    assert db_model.create_table().startswith("CREATE TABLE `global_query_review`")
    assert db_model.table_status().startswith("                Name : global_query_review")


def test_explainer_errors_propagate(db_model):
    model = AnemometerModel(
        dataclasses.replace(db_model.config, plugins=Plugins(explain=lambda row: None))
    )
    with pytest.raises(ExplainError, match="Missing field host"):
        model.init_query_explainer({"sample": "SELECT 1"})


def test_performance_schema_version_check(mysql_server):
    ps = _datasource("ps", "performance_schema", {"events": "fact"}, **mysql_server, db="mysql")
    model = AnemometerModel(_config(ps=ps))
    model.set_datasource("ps")  # the test server is 5.7
    model.close()

    class OldServer:
        server_version = "5.5.62-log"

        def close(self):
            pass

    model = AnemometerModel(_config(ps=ps), connect=lambda *a, **k: OldServer())
    with pytest.raises(ModelError, match="requires mysql version >= 5.6.  Found version: 5.5.62"):
        model.set_datasource("ps")

    newer = AnemometerModel(_config(ps=ps), connect=lambda *a, **k: OldServer())
    OldServer.server_version = "10.6.12-MariaDB"
    newer.set_datasource("ps")
