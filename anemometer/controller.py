"""Request handling: one :class:`Anemometer` instance per request.

Each public action (``index``, ``report``, ``api``, ...) corresponds to an
``?action=`` value. Actions write HTML into an output buffer, in order, the way
the original PHP controller printed it: the page header is emitted lazily the
first time something needs it, an error alert can appear in the middle of a
page, and a redirect only happens when nothing has been written yet.

Search settings are passed to the report builder by *writing into the request
parameters* (``self.params.set(...)``) -- the report reads its form values from
there. This mirrors the original design, where the controller wrote to $_GET.
"""

from __future__ import annotations

import re
from collections.abc import Callable, MutableMapping, Sequence
from datetime import datetime, tzinfo
from typing import Any

from jinja2 import Environment

from anemometer.config import AppConfig
from anemometer.db import Connection, connect
from anemometer.explain import ExplainError
from anemometer.model import AnemometerModel
from anemometer.report import TableReport
from anemometer.request_vars import RequestVars
from anemometer.views import php_truthy, report_json, report_json2, report_printr

__all__ = ["ACTIONS", "Anemometer", "ControllerError"]

ACTIONS = (
    "index",
    "report",
    "api",
    "graph_search",
    "show_query",
    "samples",
    "quicksearch",
    "upd_query",
    "noconfig",
)

REVIEW_ACTIONS = ("Review", "Review and Update Comments", "Update Comments", "Clear Review")
# column names which appear in both fact and dimension tables
EXCEPTION_SELECT_FIELDS = ("checksum", "sample", "DIGEST")

_DIGITS = re.compile(r"^[0-9]+$")
_HEX = re.compile(r"^[0-9A-Fa-f]+$")
_INT_PREFIX = re.compile(r"^\s*[+-]?\d+")


class ControllerError(Exception):
    """A request can't be served (bad checksum, no datasource, ...)."""


def _php_int(value: Any) -> int:
    """PHP's integer conversion of a request value ("20" -> 20, null/"abc" -> 0)."""
    if isinstance(value, int):
        return value
    match = _INT_PREFIX.match(value) if isinstance(value, str) else None
    return int(match.group()) if match else 0


def _is_unset(value: Any) -> bool:
    """``$value == null`` in PHP."""
    return value is None or value == "" or value == [] or value == {}


class Anemometer:
    def __init__(
        self,
        config: AppConfig | None,
        params: RequestVars,
        *,
        env: Environment,
        site_url: str,
        session: MutableMapping[str, Any],
        auth_user: str | None = None,
        now: Callable[[], datetime] = datetime.now,
        tz: tzinfo | None = None,
        connect: Callable[..., Connection] = connect,
    ) -> None:
        self.params = params
        self.env = env
        self.site_url = site_url
        self.session = session
        self.auth_user = auth_user
        self.now = now
        self.tz = tz
        self.redirect_to: str | None = None
        self._output: list[str] = []
        self._header_printed = False
        self.model: AnemometerModel | None = None
        self.table_report: TableReport | None = None
        if config is None:
            return

        offset = (now().replace(tzinfo=tz) if tz else now().astimezone()).utcoffset()
        self.timezone_offset = int(offset.total_seconds()) if offset else 0
        self.model = AnemometerModel(config, connect=connect)
        self.time_columns: Sequence[str] = list(config.time_columns)

        datasource = self.params.get("datasource")
        if datasource is not None:
            self.model.set_datasource(datasource)
            self.model.connect()
        self._init_report()

    # -- output ------------------------------------------------------------

    @property
    def body(self) -> str:
        return "".join(self._output)

    def write(self, text: str) -> None:
        self._output.append(text)

    def view(self, name: str, **data: Any) -> None:
        template = self.env.get_template(f"{name}.html")
        self.write(template.render(**data, get_var=self.params.get, site_url=self.site_url))

    def redirect(self, url: str) -> None:
        # Like PHP's header("Location: ..."), this only works before any output.
        if not self._output:
            self.redirect_to = url

    def close(self) -> None:
        if self.model is not None:
            self.model.close()

    def run(self, action: str) -> None:
        if action not in ACTIONS:
            self.write(f"Invalid action ({action})")
            return
        getattr(self, action)()

    # -- actions -------------------------------------------------------------

    def api(self) -> None:
        """Run the report query and print it as a table, JSON, graph data or print_r."""
        model, report = self._require_model(), self._require_report()
        checksum_field = model.field_name("checksum")
        hostname_field = model.field_name("hostname")
        dimension_table = report.table_for_alias("dimension")

        # optional pivot on hostname (graph each host as a series) or on checksums
        if not _is_unset(self.params.get(f"dimension-pivot-{hostname_field}")):
            hosts = report.distinct_values(dimension_table, hostname_field)
            report.set_pivot_values(f"dimension-pivot-{hostname_field}", hosts)
        elif not _is_unset(self.params.get(f"dimension-pivot-{checksum_field}")) and not _is_unset(
            self.params.get(f"dimension-pivot-{checksum_field}-use-values")
        ):
            values = str(self.params.get(f"dimension-pivot-{checksum_field}-use-values")).split("|")
            report.set_pivot_values(
                f"dimension-pivot-{checksum_field}", [self._translate_checksum(v) for v in values]
            )

        checksum = self._translate_checksum(self.params.get(f"fact-{checksum_field}"))
        if checksum is not None:
            self.params.set(f"fact-{checksum_field}", checksum)

        datasource = self.params.get("datasource")
        data: dict[str, Any] = {"datasource": datasource}
        try:
            data["sql"] = report.query()
            data["result"] = report.execute()
        except Exception as exc:  # shown inline, like the original
            self._alert(str(exc), "alert-error")
            self.write(f'<pre class="prettyprint">{data.get("sql") or ""}</pre>')
        data["columns"] = report.column_names()
        search = report.search_uri()
        data["permalink"] = f"{self.site_url}?action=report&datasource={datasource}&{search}"
        data["jsonlink"] = (
            f"{self.site_url}?action=api&output=json&datasource={datasource}&{search}"
        )

        output = self.params.get("output")
        if output not in ("json", "json2", "print_r", "table"):
            output = "table"
        data["callbacks"] = model.callbacks(model.source_type, output)

        if output == "json":
            self.write(report_json(data["columns"], data.get("result")))
        elif output == "json2":
            debug = php_truthy(self.params.get("debug"))
            self.write(
                report_json2(
                    data["columns"],
                    data.get("result") or [],
                    self.params.get("fact-group"),
                    debug_sql=data.get("sql") if debug else None,
                    tz=self.tz,
                )
            )
        elif output == "print_r":
            self.write(report_printr(data["columns"], data.get("result") or []))
        else:
            self.view("report_result", **data)

    def graph_search(self) -> None:
        """Search with an interactive graph and a table of the selected time range."""
        self._header()
        self._set_search_defaults("graph_defaults")
        data = self._setup_data_for_graph_search()
        self.view("graph_search", **data)
        self._footer()

    def index(self) -> None:
        """Choose a datasource; with only one, go straight to its default report."""
        model = self._require_model()
        datasources = model.datasource_names()
        if not datasources:
            self._alert("No Datasources defined.  Edit conf/config.py", "alert-error")
            return
        if len(datasources) == 1:
            action = model.default_report_action
            self.redirect(f"{self.site_url}?action={action}&datasource={datasources[0]}")
            return
        self._header()
        self.view("index", datasources=datasources, datasource=self.params.get("datasource"))
        self._footer()

    def noconfig(self) -> None:
        self._header()
        self.view("noconfig")
        self._footer()

    def quicksearch(self) -> None:
        """Jump to a query by checksum."""
        datasource = self.params.get("datasource")
        checksum = self._translate_checksum(self.params.get("checksum"))
        if not self._require_model().checksum_exists(checksum):
            self._alert(f"Unknown checksum: {checksum or ''}")
            return
        self.redirect(
            f"{self.site_url}?action=show_query&datasource={datasource}&checksum={checksum}"
        )

    def report(self) -> None:
        """The search form plus the report results as an HTML table."""
        model, report = self._require_model(), self._require_report()
        self._header()
        self._set_search_defaults("report_defaults")

        if self.params.get("hide_search_form") is None:
            data: dict[str, Any] = {
                "datasource": self.params.get("datasource"),
                "tables": report.tables,
            }
            if model.source_type != "performance_schema":
                field = model.field_name("hostname")
                tables = report.tables
                data["hosts"] = report.distinct_values(tables[1] if len(tables) > 1 else "", field)
                data[field] = self.params.get(f"dimension-{field}")
                report.set_pivot_values(f"dimension-pivot-{field}", data["hosts"])

            data["table_fields"] = {table: report.table_fields(table) for table in report.tables}
            data["table_aliases"] = model.table_aliases()
            data["custom_fields"] = report.custom_fields()
            data["table_fields_selected"] = self.params.get("table_fields")
            data["exception_select_fields"] = list(EXCEPTION_SELECT_FIELDS)
            data["review_types"] = list(model.review_types)
            data["reviewers"] = list(model.reviewers)
            self._display_report_form(data)

        self.api()
        self._footer()

    def samples(self) -> None:
        """Page through the samples of one query."""
        model = self._require_model()
        self._header()
        checksum = self._translate_checksum(self.params.get("checksum"))
        start = _php_int(self.params.get("start"))
        rpp = self.params.get("rpp")
        samples = model.query_samples(checksum, _php_int(rpp) + 1, start)
        self.view(
            "samples",
            datasource=self.params.get("datasource"),
            checksum=checksum,
            start=start,
            rpp=rpp,
            rpp_number=_php_int(rpp),
            samples=samples,
            num_rows=len(samples),
        )
        self._footer()

    def show_query(self) -> None:
        """Details of one query: sample, table info, review form, graph and history."""
        model, report = self._require_model(), self._require_report()
        self._header()
        checksum = self._translate_checksum(self.params.get("checksum"))
        if not model.checksum_exists(checksum):
            self._alert(f"Unknown checksum: {checksum or ''}")
            return

        data: dict[str, Any] = {"datasource": self.params.get("datasource")}
        sample_field = model.field_name("sample")
        checksum_field = model.field_name("checksum")
        hostname_field = model.field_name("hostname")
        fingerprint_field = model.field_name("fingerprint")
        source_type = model.source_type
        data["source_type"] = source_type

        row = dict(model.query_by_checksum(checksum) or {})
        for column, callback in (model.callbacks(source_type, "table") or {}).items():
            if column in row:
                row[column] = callback(row[column])[0]
        data["checksum"] = row.get(checksum_field)
        self.params.set("checksum", row.get(checksum_field))
        data["row"] = row

        samples = model.query_samples(checksum, 1)
        data["sample"] = samples[0] if samples else None
        sample = (data["sample"] or {}).get(sample_field)
        data["review_types"] = list(model.review_types)
        data["reviewers"] = list(model.reviewers)
        data["current_auth_user"] = self._auth_user()

        data["show_samples"] = True
        if source_type == "performance_schema_history":
            data["show_samples"] = False
            data["row"]["fingerprint"] = sample
        else:
            try:
                model.init_query_explainer(data["sample"])
            except ExplainError as exc:
                data["explain_plan_error"] = str(exc)
            data["query_advisor"] = model.query_advisor(sample or "")
            data["create_table"] = model.create_table()
            data["table_status"] = model.table_status()

        data["time_field_name"] = model.field_name("time")
        data["hostname_field_name"] = hostname_field
        data["checksum_field_name"] = checksum_field
        data["timezone_offset"] = self.timezone_offset
        data["tables"] = report.tables
        if source_type == "slow_query_log":
            dimension_table = report.table_for_alias("dimension")
            data["hosts"] = report.distinct_values(dimension_table, hostname_field)
            data[hostname_field] = self.params.get(hostname_field)
            report.set_pivot_values(f"dimension-pivot-{hostname_field}", data["hosts"])
        data["table_fields"] = {table: report.table_fields(table) for table in report.tables}
        data["custom_fields"] = report.custom_fields()

        self._set_search_defaults("graph_defaults")
        report.process_form_data()
        plot_field = self.params.get("plot_field")
        self.params.append("table_fields", plot_field)
        if php_truthy(self.params.get(f"dimension-pivot-{hostname_field}")):
            self.params.set(f"dimension-pivot-{hostname_field}", plot_field)
            data["dimension_pivot_hostname_max"] = plot_field
        if php_truthy(self.params.get(f"dimension-pivot-{checksum_field}")):
            self.params.set(f"dimension-pivot-{checksum_field}", plot_field)
            data["dimension_pivot_checksum"] = plot_field
        self.params.append("table_fields", plot_field)
        self.params.set("fact-checksum", self.params.get("checksum"))
        self.params.set("fact-DIGEST", self.params.get("checksum"))
        data["ajax_request_url"] = (
            f"{self.site_url}?action=api&output=json2&noheader=1"
            f"&datasource={data['datasource']}&{report.search_uri()}"
        )
        data["sample_field_name"] = sample_field
        data["fingerprint_field_name"] = fingerprint_field

        view = "show_query_perf_schema" if source_type == "performance_schema" else "show_query"
        self.view(view, **data)

        # the query's history: a report on this checksum
        self._init_report()
        self._clear_all_time_values()
        self._set_search_defaults("history_defaults", override=[])
        self.params.set("fact-checksum", checksum)
        self.api()
        self._footer()

    def upd_query(self) -> None:
        """Save a review and/or comments for a query, then show it again."""
        model = self._require_model()
        checksum = self._translate_checksum(self.params.get("checksum"))
        submit = self.params.get("submit")
        if submit not in REVIEW_ACTIONS:
            # The original called an undefined function here and died.
            self._alert(f"<strong>Error</strong> Invalid form action{submit or ''}", "alert-error")
            return

        fields: dict[str, Any] = {}
        if submit in ("Review", "Review and Update Comments"):
            fields["reviewed_by"] = self.params.get("reviewed_by")
            fields["reviewed_on"] = self.now().strftime("%Y-%m-%d %H:%M:%S")
            fields["reviewed_status"] = self.params.get("reviewed_status")
            self.session["current_review_user"] = self.params.get("reviewed_by")
        if submit in ("Review and Update Comments", "Update Comments"):
            fields["comments"] = self.params.get("comments")
        if submit == "Clear Review":
            fields.update(reviewed_by="NULL", reviewed_on="NULL", reviewed_status="NULL")

        model.update_query(checksum, fields)
        datasource = self.params.get("datasource")
        self.redirect(
            f"{self.site_url}?action=show_query&datasource={datasource}&checksum={checksum}"
        )

    # -- helpers -------------------------------------------------------------

    def _require_model(self) -> AnemometerModel:
        if self.model is None:
            raise ControllerError("No configuration loaded")
        return self.model

    def _require_report(self) -> TableReport:
        if self.table_report is None:
            raise ControllerError("No datasource defined")
        return self.table_report

    def _init_report(self) -> None:
        """(Re)create the report builder for the selected datasource."""
        model = self._require_model()
        datasource = model.current_datasource
        if self.params.get("datasource") is None or datasource is None:
            return
        self.table_report = TableReport(
            datasource.tables,
            model.report_spec(datasource.source_type),
            self.params,
            connection=model.connection,
            schema=datasource.db,
            now=self.now,
        )
        self.table_report.set_non_aggregate_columns(self.time_columns)

    def _translate_checksum(self, checksum: Any) -> Any:
        """Validate a checksum (hex since checksums are CHAR(32)); '' and None -> None."""
        if self._require_model().source_type not in ("slow_query_log", "default"):
            return checksum
        if not isinstance(checksum, str) or checksum == "":
            return None
        if _DIGITS.match(checksum) or _HEX.match(checksum):
            return checksum
        raise ControllerError("Invalid query checksum")

    def _set_search_defaults(
        self, kind: str = "report_defaults", override: Sequence[str] | None = None
    ) -> None:
        """Fill in default search values; with ``override``, defaults not listed there win."""
        for key, value in self._require_model().report_defaults(kind).items():
            if _is_unset(self.params.get(key)) or (override is not None and key not in override):
                self.params.set(key, value)

    def _clear_all_time_values(self) -> None:
        for column in self.time_columns:
            self.params.discard(f"dimension-{column}_start")
            self.params.discard(f"dimension-{column}_end")

    def _time_field_from_report_defaults(self, kind: str) -> str | None:
        defaults = self._require_model().report_defaults(kind)
        for column in self.time_columns:
            if f"dimension-{column}_start" in defaults or f"dimension-{column}_end" in defaults:
                return column
        return None

    def _setup_data_for_graph_search(self) -> dict[str, Any]:
        model, report = self._require_model(), self._require_report()
        datasource = self.params.get("datasource")
        data: dict[str, Any] = {"datasource": datasource}

        # older config files don't say which column is the time column
        time = self._time_field_from_report_defaults("graph_defaults") or model.field_name("time")
        hostname_field = model.field_name("hostname")
        checksum_field = model.field_name("checksum")
        data["time_field_name"] = time
        data["hostname_field_name"] = hostname_field
        data["checksum_field_name"] = checksum_field

        data["tables"] = report.tables
        dimension_table = report.table_for_alias("dimension")
        data["hosts"] = report.distinct_values(dimension_table, hostname_field)
        data[hostname_field] = self.params.get(hostname_field)
        report.set_pivot_values(f"dimension-pivot-{hostname_field}", data["hosts"])
        data["table_fields"] = {table: report.table_fields(table) for table in report.tables}
        data["custom_fields"] = report.custom_fields()

        report.process_form_data()
        plot_field = self.params.get("plot_field")
        self.params.append("table_fields", plot_field)
        if php_truthy(self.params.get(f"dimension-pivot-{hostname_field}")):
            self.params.set(f"dimension-pivot-{hostname_field}", plot_field)
            data["dimension_pivot_hostname_max"] = plot_field
        if php_truthy(self.params.get(f"dimension-pivot-{checksum_field}")):
            self.params.set(f"dimension-pivot-{checksum_field}", plot_field)
            data["dimension_pivot_checksum"] = plot_field

        graph_search = report.search_uri([f"dimension-{time}"])
        data["ajax_request_url"] = (
            f"{self.site_url}?action=api&output=json2&noheader=1"
            f"&datasource={datasource}&{graph_search}"
        )
        data["graph_permalink"] = (
            f"{self.site_url}?action=graph_search&datasource={datasource}"
            f"&plot_field={plot_field or ''}&{graph_search}"
        )
        data["show_query_base_url"] = f"{self.site_url}?action=show_query&datasource={datasource}"

        # now the URL for the table of results below the graph
        self._init_report()
        report = self._require_report()
        self._set_search_defaults(
            "report_defaults",
            override=[f"dimension-{time}_start", f"dimension-{time}_end", checksum_field],
        )
        self.params.set("fact-order", f"{plot_field or ''} DESC")
        table_search = report.search_uri([f"dimension-{time}", "dimension-ts_min"])
        data["ajax_table_request_url_base"] = (
            f"{self.site_url}?action=api&output=table&noheader=1"
            f"&datasource={datasource}&{table_search}"
        )
        data["table_url_time_start_param"] = f"dimension-{time}_start"
        data["table_url_time_end_param"] = f"dimension-{time}_end"
        data["timezone_offset"] = self.timezone_offset
        return data

    def _display_report_form(self, data: dict[str, Any]) -> None:
        model = self._require_model()
        data["hostname_field_name"] = model.field_name("hostname")
        data["checksum_field_name"] = model.field_name("checksum")
        data["time_field_name"] = model.field_name("time")
        data["sample_field_name"] = model.field_name("sample")
        if model.source_type == "performance_schema":
            self.view("report-performance_schema", **data)
        else:
            self.view("report", **data)

    def _auth_user(self) -> str | None:
        """The web server's authenticated user, else the last reviewer from the session."""
        return self.auth_user or self.session.get("current_review_user")

    def _alert(self, message: str, level: str = "alert-warning") -> None:
        self._header()
        self.write(f'<div class="alert {level}">{message}</div>')

    def _header(self) -> None:
        if self._header_printed:
            return
        datasources = datasource = source_type = None
        if self.model is not None:
            datasources = self.model.datasource_names()
            datasource = self.params.get("datasource")
            source_type = self.model.source_type
        if not php_truthy(self.params.get("noheader")):
            self.view("header")
            self.view(
                "navbar", datasources=datasources, datasource=datasource, source_type=source_type
            )
        self._header_printed = True

    def _footer(self) -> None:
        self.view("footer")
