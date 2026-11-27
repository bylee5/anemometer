"""Application configuration.

The configuration is a Python module (see ``conf/config.sample.py``) with
upper-case settings. It is a module rather than YAML/TOML because some settings
are functions: the EXPLAIN connection callback and per-column display callbacks.

Search form defaults may contain callables; they are evaluated every time the
defaults are read, so ``relative_time("-1 day")`` always means "one day before
this request".
"""

from __future__ import annotations

import copy
import importlib.util
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from anemometer.util.timeutil import resolve_relative_date

__all__ = [
    "AppConfig",
    "ConfigError",
    "Datasource",
    "DEFAULTS_KINDS",
    "Plugins",
    "ReportSpec",
    "load_config",
    "relative_time",
]

DEFAULT_SOURCE_TYPE = "default"
DEFAULTS_KINDS = ("report_defaults", "history_defaults", "graph_defaults")

ExplainCallback = Callable[[Mapping[str, Any]], "Mapping[str, Any] | None"]
CellCallback = Callable[[Any], Sequence[Any]]


class ConfigError(ValueError):
    """The configuration module is missing settings or has invalid values."""


def relative_time(expression: str) -> Callable[[], str]:
    """A search default resolved at request time, e.g. ``relative_time("-7 day")``."""

    def resolve() -> str:
        return resolve_relative_date(expression)

    resolve.__qualname__ = f"relative_time({expression!r})"
    return resolve


@dataclass(frozen=True)
class Datasource:
    """A database holding pt-query-digest review tables."""

    name: str
    host: str
    db: str
    user: str
    password: str
    # real table name -> alias; exactly one alias must be "fact".
    tables: Mapping[str, str]
    port: int = 3306
    source_type: str | None = None

    def table_for(self, alias: str) -> str | None:
        return next((table for table, a in self.tables.items() if a == alias), None)


@dataclass(frozen=True)
class ReportSpec:
    """How search form fields map onto SQL for one source type.

    ``fields`` maps a table alias to ``{field: "filter|filter|..."}``; see
    :mod:`anemometer.report` for the available filters.
    """

    fields: Mapping[str, Mapping[str, str]]
    join: Mapping[str, str] = field(default_factory=dict)
    custom_fields: Mapping[str, str] = field(default_factory=dict)
    special_field_names: Mapping[str, str] = field(default_factory=dict)
    # output format -> column -> callback returning (value, css_class)
    callbacks: Mapping[str, Mapping[str, CellCallback]] = field(default_factory=dict)


@dataclass(frozen=True)
class Plugins:
    explain: ExplainCallback | None = None
    visual_explain: str | None = None
    query_advisor: str | None = None
    show_create: bool = False
    show_status: bool = False


@dataclass(frozen=True)
class AppConfig:
    datasources: Mapping[str, Datasource]
    reports: Mapping[str, ReportSpec]
    report_defaults: Mapping[str, Mapping[str, Any]]
    history_defaults: Mapping[str, Mapping[str, Any]]
    graph_defaults: Mapping[str, Mapping[str, Any]]
    default_report_action: str = "report"
    reviewers: Sequence[str] = ()
    review_types: Sequence[str] = ()
    plugins: Plugins = field(default_factory=Plugins)
    time_columns: Sequence[str] = ()

    def defaults(self, kind: str, source_type: str | None) -> dict[str, Any]:
        """Search form defaults of ``kind`` for a source type, with callables evaluated.

        Falls back to the ``"default"`` entry when the source type has none.
        """
        if kind not in DEFAULTS_KINDS:
            raise ValueError(f"unknown defaults kind: {kind!r}")
        by_source: Mapping[str, Mapping[str, Any]] = getattr(self, kind)
        chosen = by_source.get(source_type or DEFAULT_SOURCE_TYPE)
        if chosen is None:
            chosen = by_source.get(DEFAULT_SOURCE_TYPE, {})
        # Copies, so that request handling can't modify the configuration.
        return {
            key: value() if callable(value) else copy.deepcopy(value)
            for key, value in chosen.items()
        }


def _require(settings: Mapping[str, Any], name: str, where: str) -> Any:
    try:
        return settings[name]
    except KeyError:
        raise ConfigError(f"{where}: missing setting {name!r}") from None


def _build(cls: type, values: Mapping[str, Any], where: str, **extra: Any) -> Any:
    try:
        return cls(**values, **extra)
    except TypeError as exc:
        raise ConfigError(f"{where}: {exc}") from None


def _datasource(name: str, values: Mapping[str, Any]) -> Datasource:
    datasource = _build(Datasource, values, f"DATASOURCES[{name!r}]", name=name)
    if "fact" not in datasource.tables.values():
        raise ConfigError(f"DATASOURCES[{name!r}]: one table must have the alias 'fact'")
    return datasource


def _from_module(module: ModuleType) -> AppConfig:
    settings = {key.lower(): value for key, value in vars(module).items() if key.isupper()}
    known = {f for f in AppConfig.__dataclass_fields__}
    unknown = sorted(set(settings) - known)
    if unknown:
        raise ConfigError(f"unknown settings: {', '.join(s.upper() for s in unknown)}")

    datasources = {
        name: _datasource(name, values)
        for name, values in _require(settings, "datasources", "config").items()
    }
    reports = {
        name: _build(ReportSpec, values, f"REPORTS[{name!r}]")
        for name, values in _require(settings, "reports", "config").items()
    }
    for kind in DEFAULTS_KINDS:
        _require(settings, kind, "config")
    plugins = _build(Plugins, settings.get("plugins", {}), "PLUGINS")

    return AppConfig(
        **{**settings, "datasources": datasources, "reports": reports, "plugins": plugins}
    )


def load_config(path: str | Path) -> AppConfig | None:
    """Load a configuration module from ``path``; ``None`` if the file doesn't exist."""
    path = Path(path)
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("anemometer_site_config", path)
    if spec is None or spec.loader is None:
        raise ConfigError(f"cannot load configuration from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return _from_module(module)
