"""Data access for the web application.

:class:`AnemometerModel` answers configuration questions for the selected
datasource (field names, defaults, review settings) and reads and updates the
query review tables written by pt-query-digest:

* the *fact* table (``global_query_review``): one row per query checksum, with
  review status and comments;
* the *dimension* table (``global_query_review_history``): samples and metrics
  per time interval.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from anemometer.config import AppConfig, Datasource, ReportSpec
from anemometer.db import Connection, Row, connect
from anemometer.explain import QueryExplainer

__all__ = ["AnemometerModel", "ModelError", "run_script"]

SCRIPT_TIMEOUT = 60  # seconds

# Field names used when a report has no special_field_names entry.
_DEFAULT_FIELD_NAMES = {
    "time": "ts_min",
    "hostname": "hostname_max",
    "fingerprint": "fingerprint",
}


class ModelError(Exception):
    """Invalid datasource selection or configuration."""


def run_script(command: str, input_text: str, *, timeout: float = SCRIPT_TIMEOUT) -> str | None:
    """Run ``command`` through the shell with ``input_text`` on stdin.

    Returns stdout followed by stderr, or ``None`` if it could not be started.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            input=input_text.encode("utf-8"),
            capture_output=True,
            cwd=tempfile.gettempdir(),
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (result.stdout + result.stderr).decode("utf-8", errors="replace")


def _checksum_param(checksum: str | None) -> str:
    # The original interpolated the value into the SQL, so None compared as ''.
    return "" if checksum is None else checksum


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version)[:3])


class AnemometerModel:
    def __init__(self, config: AppConfig, *, connect: Callable[..., Connection] = connect) -> None:
        self.config = config
        self._connect = connect
        self._datasource: Datasource | None = None
        self._connection: Connection | None = None
        self.fact_table: str | None = None
        self.dimension_table: str | None = None
        self.explainer: QueryExplainer | None = None

    # -- configuration ---------------------------------------------------

    @property
    def default_report_action(self) -> str:
        return self.config.default_report_action

    @property
    def review_types(self) -> Sequence[str]:
        return self.config.review_types

    @property
    def reviewers(self) -> Sequence[str]:
        return self.config.reviewers

    def datasource_names(self) -> list[str]:
        return list(self.config.datasources)

    def datasource(self, name: str) -> Datasource | None:
        return self.config.datasources.get(name)

    @property
    def current_datasource(self) -> Datasource | None:
        return self._datasource

    @property
    def source_type(self) -> str:
        """The selected datasource's source type ("default" if none is set)."""
        if self._datasource is not None and self._datasource.source_type is not None:
            return self._datasource.source_type
        return "default"

    def set_datasource(self, name: str) -> None:
        """Select a datasource; performance_schema sources must be MySQL >= 5.6."""
        datasource = self.config.datasources.get(name)
        if datasource is None:
            raise ModelError(f"Unknown datasource {name}")
        self._datasource = datasource
        for table, alias in datasource.tables.items():
            if alias == "fact":
                self.fact_table = table
            elif alias == "dimension":
                self.dimension_table = table

        if datasource.source_type == "performance_schema":
            version = self.connect().server_version
            if _version_tuple(version) < (5, 6):
                raise ModelError(
                    f"Datasource {name} has a source_type of performance_schema which "
                    f"requires mysql version >= 5.6.  Found version: {version}"
                )

    def set_tables(self, fact: str, dimension: str | None) -> None:
        self.fact_table = fact
        self.dimension_table = dimension

    def table_aliases(self) -> dict[str, str]:
        aliases = {self.fact_table: "fact", self.dimension_table: "dimension"}
        return {table: alias for table, alias in aliases.items() if table is not None}

    def report_defaults(self, kind: str = "report_defaults") -> dict[str, Any]:
        """Search form defaults for the selected datasource (see AppConfig.defaults)."""
        if self._datasource is None:
            raise ModelError("Cannot get report default values without a datasource defined")
        return self.config.defaults(kind, self._datasource.source_type)

    def report_spec(self, source_type: str | None) -> ReportSpec:
        """The report definition for a source type (slow_query_log if not given)."""
        name = source_type if source_type is not None else "slow_query_log"
        try:
            return self.config.reports[name]
        except KeyError:
            raise ModelError(f"No report configured for source type {name!r}") from None

    def form_fields(self, source_type: str) -> Mapping[str, Mapping[str, str]]:
        return self.report_spec(source_type).fields

    def field_name(self, kind: str) -> str:
        """Column used for a role ("time", "hostname", "checksum", "sample", ...)."""
        spec = self.config.reports.get(self.source_type)
        if spec is not None and kind in spec.special_field_names:
            return spec.special_field_names[kind]
        return _DEFAULT_FIELD_NAMES.get(kind, kind)

    def callbacks(self, source_type: str, output: str) -> Mapping[str, Callable] | None:
        spec = self.config.reports.get(source_type)
        if spec is None:
            return None
        return spec.callbacks.get(output)

    # -- database --------------------------------------------------------

    def connect(self) -> Connection:
        """Connect to the selected datasource (reusing an open connection)."""
        if self._datasource is None:
            raise ModelError("No datasource selected")
        if self._connection is None:
            ds = self._datasource
            self._connection = self._connect(ds.host, ds.user, ds.password, ds.db, port=ds.port)
        return self._connection

    @property
    def connection(self) -> Connection:
        return self.connect()

    def close(self) -> None:
        for resource in (self._connection, self.explainer):
            if resource is not None:
                resource.close()
        self._connection = None
        self.explainer = None

    def checksum_exists(self, checksum: str | None) -> bool:
        column = self.field_name("checksum")
        row = self.connection.fetch_one(
            f"SELECT `{column}` FROM `{self.fact_table}` WHERE `{column}`=%s",
            [_checksum_param(checksum)],
        )
        return row is not None

    def update_query(self, checksum: str | None, fields: Mapping[str, Any]) -> None:
        """Update review columns of a query; the string "NULL" sets a column to NULL."""
        assignments, params = [], []
        for name, value in fields.items():
            if value == "NULL":
                assignments.append(f"{name} = NULL")
            else:
                assignments.append(f"`{name}` = %s")
                params.append("" if value is None else value)
        column = self.field_name("checksum")
        self.connection.execute(
            f"UPDATE `{self.fact_table}` SET {','.join(assignments)} WHERE `{column}`=%s",
            [*params, _checksum_param(checksum)],
        )

    def query_by_checksum(self, checksum: str | None) -> Row | None:
        """The fact table row of a query."""
        column = self.field_name("checksum")
        return self.connection.fetch_one(
            f"SELECT * FROM `{self.fact_table}` WHERE `{column}`=%s", [_checksum_param(checksum)]
        )

    def query_samples(self, checksum: str | None, limit: int = 1, offset: int = 0) -> list[Row]:
        """History rows of a query, most recent first."""
        table = (
            self.fact_table if self.source_type == "performance_schema" else self.dimension_table
        )
        checksum_column = self.field_name("checksum")
        time_column = self.field_name("time")
        return self.connection.fetch_all(
            f"SELECT * FROM `{table}` WHERE `{checksum_column}`=%s"
            f" ORDER BY `{time_column}` DESC LIMIT {int(limit)} OFFSET {int(offset)}",
            [_checksum_param(checksum)],
        )

    # -- plugins ---------------------------------------------------------

    def init_query_explainer(self, sample: Mapping[str, Any] | None) -> None:
        """Connect to the server a sample came from (see PLUGINS["explain"]).

        :raises anemometer.explain.ExplainError: if that isn't possible.
        """
        if not isinstance(sample, Mapping) or self.config.plugins.explain is None:
            return
        self.explainer = QueryExplainer.for_sample(self.config.plugins.explain, sample)

    def explain_for_sample(self) -> str | None:
        return self.explainer.explain() if self.explainer is not None else None

    def visual_explain(self, explain_plan: str) -> str | None:
        """Output of pt-visual-explain for an EXPLAIN plan."""
        command = self.config.plugins.visual_explain
        if command is None:
            return None
        return run_script(command, explain_plan)

    def query_advisor(self, query: str) -> str | None:
        """Output of pt-query-advisor for a query."""
        command = self.config.plugins.query_advisor
        if command is None:
            return None
        if not os.path.exists(command):
            return f"can't find query advisor at {command}"
        return run_script(command, query)

    def create_table(self) -> str | None:
        if not self.config.plugins.show_create or self.explainer is None:
            return None
        return self.explainer.create_statements()

    def table_status(self) -> str | None:
        if not self.config.plugins.show_status or self.explainer is None:
            return None
        return self.explainer.table_status()
