"""Anemometer configuration.

Copy this file to ``conf/config.py`` (or point ANEMOMETER_CONFIG at another
path) and adjust it. All environment specific settings live here.

Keep secrets out of this file where possible; the samples below read
passwords from environment variables.
"""

import os
from datetime import date, datetime

from anemometer.config import relative_time
from anemometer.util.hexconv import dec2hex

# ---------------------------------------------------------------------------
# Datasources
#
# A datasource is a database server, a database name and the tables used for
# reporting. You can add as many as you like; with only one, the index page
# goes straight to its report.
#
# ``tables`` maps the real table names to aliases. The review table must have
# the alias "fact" and the review history table the alias "dimension".
# ---------------------------------------------------------------------------
DATASOURCES = {
    "localhost": {
        "host": "localhost",
        "port": 3306,
        "db": "slow_query_log",
        "user": "root",
        "password": os.environ.get("ANEMOMETER_DB_PASSWORD", ""),
        "tables": {
            "global_query_review": "fact",
            "global_query_review_history": "dimension",
        },
        "source_type": "slow_query_log",
    },
    # If you're using Anemometer with MySQL 5.6's performance schema:
    #
    # "mysql56": {
    #     "host": "localhost",
    #     "port": 3306,
    #     "db": "performance_schema",
    #     "user": "root",
    #     "password": os.environ.get("ANEMOMETER_DB_PASSWORD", ""),
    #     "tables": {"events_statements_summary_by_digest": "fact"},
    #     "source_type": "performance_schema",
    # },
    #
    # If you save performance schema history into a table structure similar to
    # pt-query-digest's, this datasource gives you graphs and query details:
    #
    # "localhost_history": {
    #     "host": "localhost",
    #     "port": 3306,
    #     "db": "slow_query_log",
    #     "user": "root",
    #     "password": os.environ.get("ANEMOMETER_DB_PASSWORD", ""),
    #     "tables": {
    #         "events_statements": "fact",
    #         "events_statements_history": "dimension",
    #     },
    #     "source_type": "performance_schema_history",
    # },
}

# Which page opens first for a datasource: "report" (search form with an HTML
# table) or "graph_search" (interactive graph with a table of the selection).
DEFAULT_REPORT_ACTION = "report"

# People who review queries, and the statuses a query can be given.
REVIEWERS = ["dba1", "dba2"]
REVIEW_TYPES = [
    "good",
    "bad",
    "ticket-created",
    "needs-fix",
    "fixed",
    "needs-analysis",
    "review-again",
]

# ---------------------------------------------------------------------------
# Search form defaults
#
# report_defaults: the basic HTML table search.
# history_defaults: the query history at the bottom of the query details page.
# graph_defaults: the interactive graph search page.
#
# Each is keyed by datasource source_type; "default" is used when a source
# type has no entry of its own. relative_time() values are evaluated per
# request.
# ---------------------------------------------------------------------------
HISTORY_DEFAULTS = {
    "default": {
        "output": "table",
        "fact-group": "date",
        "fact-order": "date DESC",
        "fact-limit": "90",
        "dimension-ts_min_start": relative_time("-90 day"),
        "dimension-ts_min_end": relative_time("now"),
        "table_fields": [
            "date", "index_ratio", "query_time_avg", "rows_sent_avg", "ts_cnt",
            "Query_time_sum", "Lock_time_sum", "Rows_sent_sum", "Rows_examined_sum",
            "Tmp_table_sum", "Filesort_sum", "Full_scan_sum",
        ],
    },
    "performance_schema": {
        "fact-order": "SUM_TIMER_WAIT DESC",
        "fact-limit": "20",
        "fact-group": "DIGEST",
        "table_fields": [
            "DIGEST", "index_ratio", "COUNT_STAR", "SUM_LOCK_TIME", "SUM_ROWS_AFFECTED",
            "SUM_ROWS_SENT", "SUM_ROWS_EXAMINED", "SUM_CREATED_TMP_TABLES", "SUM_SORT_SCAN",
            "SUM_NO_INDEX_USED",
        ],
    },
    "performance_schema_history": {
        "output": "table",
        "fact-group": "date",
        "fact-order": "date DESC",
        "fact-limit": "90",
        "dimension-FIRST_SEEN_start": relative_time("-90 day"),
        "dimension-FIRST_SEEN_end": relative_time("now"),
        "table_fields": [
            "date", "snippet", "index_ratio", "COUNT_STAR", "SUM_LOCK_TIME",
            "SUM_ROWS_AFFECTED", "SUM_ROWS_SENT", "SUM_ROWS_EXAMINED",
            "SUM_CREATED_TMP_TABLES", "SUM_SORT_SCAN", "SUM_NO_INDEX_USED",
        ],
    },
}  # fmt: skip

REPORT_DEFAULTS = {
    "default": {
        "fact-group": "checksum",
        "fact-order": "Query_time_sum DESC",
        "fact-limit": "20",
        "dimension-ts_min_start": relative_time("-1 day"),
        "dimension-ts_min_end": relative_time("now"),
        "table_fields": [
            "checksum", "snippet", "index_ratio", "query_time_avg", "rows_sent_avg",
            "ts_cnt", "Query_time_sum", "Lock_time_sum", "Rows_sent_sum",
            "Rows_examined_sum", "Tmp_table_sum", "Filesort_sum", "Full_scan_sum",
        ],
        "dimension-pivot-hostname_max": None,
    },
    "performance_schema": {
        "fact-order": "SUM_TIMER_WAIT DESC",
        "fact-limit": "20",
        "fact-group": "DIGEST",
        "table_fields": [
            "DIGEST", "snippet", "index_ratio", "COUNT_STAR", "SUM_TIMER_WAIT",
            "SUM_LOCK_TIME", "SUM_ROWS_AFFECTED", "SUM_ROWS_SENT", "SUM_ROWS_EXAMINED",
            "SUM_CREATED_TMP_TABLES", "SUM_SORT_SCAN", "SUM_NO_INDEX_USED",
        ],
    },
    "performance_schema_history": {
        "fact-group": "DIGEST",
        "fact-order": "SUM_TIMER_WAIT DESC",
        "fact-limit": "20",
        "dimension-FIRST_SEEN_start": relative_time("-1 day"),
        "dimension-FIRST_SEEN_end": relative_time("now"),
        "table_fields": [
            "DIGEST", "snippet", "index_ratio", "COUNT_STAR", "SUM_LOCK_TIME",
            "SUM_ROWS_AFFECTED", "SUM_ROWS_SENT", "SUM_ROWS_EXAMINED",
            "SUM_CREATED_TMP_TABLES", "SUM_SORT_SCAN", "SUM_NO_INDEX_USED",
        ],
    },
}  # fmt: skip

GRAPH_DEFAULTS = {
    "default": {
        "fact-group": "minute_ts",
        "fact-order": "minute_ts",
        "fact-limit": "",
        "dimension-ts_min_start": relative_time("-7 day"),
        "dimension-ts_min_end": relative_time("now"),
        "table_fields": ["minute_ts"],
        # hack ... fix is to make query builder select the group and order
        # fields, then table fields only has to contain the plot_field
        "plot_field": "Query_time_sum",
    },
    "performance_schema_history": {
        "fact-group": "minute_ts",
        "fact-order": "minute_ts",
        "fact-limit": "",
        "dimension-FIRST_SEEN_start": relative_time("-7 day"),
        "dimension-FIRST_SEEN_end": relative_time("now"),
        "table_fields": ["minute_ts"],
        "plot_field": "SUM_TIMER_WAIT",
        "dimension-pivot-hostname_max": None,
    },
}


# ---------------------------------------------------------------------------
# Plugins
#
# explain: called with the query's history row (the sample plus columns such
#   as hostname_max) and must return connection details for the server the
#   query ran on: {"host", "port", "db", "user", "password"}. Return None if
#   they can't be determined; the EXPLAIN plan is then not shown.
#
# visual_explain / query_advisor: full paths to the Percona Toolkit scripts.
#
# show_create / show_status: show SHOW CREATE TABLE and SHOW TABLE STATUS for
#   the tables in the query, using the connection returned by explain.
# ---------------------------------------------------------------------------
def explain_connection(sample):
    hostname = sample.get("hostname_max")
    if hostname is None or len(hostname) < 5:
        return None

    if ":" in hostname:
        host, port = hostname.split(":")[:2]
    else:
        host, port = hostname, 3306

    return {
        "host": host,
        "port": int(port),
        "db": sample.get("db_max") or "mysql",
        "user": "root",
        "password": os.environ.get("ANEMOMETER_EXPLAIN_PASSWORD", ""),
    }


PLUGINS = {
    "visual_explain": "/usr/bin/pt-visual-explain",
    # percona toolkit has removed query advisor
    # "query_advisor": "/usr/bin/pt-query-advisor",
    "show_create": True,
    "show_status": True,
    "explain": explain_connection,
}


# ---------------------------------------------------------------------------
# Reports: how SQL queries are built from the search form. It shouldn't be
# necessary to change these, and you can break reporting by doing so. See
# anemometer.report for the meaning of the filters ("clear|where" etc.).
# ---------------------------------------------------------------------------
def weekend_marker(value):
    """Table cell callback: flag Saturdays and Sundays with the "weekend" class."""
    if isinstance(value, date):
        day = value
    else:
        try:
            day = datetime.strptime(str(value)[:10], "%Y-%m-%d")
        except ValueError:
            return value, ""
    return value, "weekend" if day.isoweekday() >= 6 else ""


REPORTS = {
    "slow_query_log": {
        "join": {
            "dimension": "USING (`checksum`)",
        },
        # Form fields, defined by table *alias*; the real names come from the
        # datasource.
        "fields": {
            "fact": {
                "group": "group",
                "order": "order",
                "having": "having",
                "limit": "limit",
                "first_seen": "clear|reldate|ge|where",
                "where": "raw_where",
                "sample": "clear|like|where",
                "checksum": "clear|where",
                "reviewed_status": "clear|where",
            },
            "dimension": {
                "extra_fields": "where",
                "hostname_max": "clear|where",
                "ts_min": "date_range|reldate|clear|where",
                "pivot-hostname_max": "clear|pivot|select",
                "pivot-checksum": "clear|pivot|select",
            },
        },
        "custom_fields": {
            "checksum": "checksum",
            "date": "DATE(ts_min)",
            "hour": "substring(ts_min,1,13)",
            "hour_ts": "round(unix_timestamp(substring(ts_min,1,13)))",
            "minute_ts": "round(unix_timestamp(substring(ts_min,1,16)))",
            "minute": "substring(ts_min,1,16)",
            "snippet": "LEFT(dimension.sample,20)",
            "index_ratio": "ROUND(SUM(Rows_examined_sum)/SUM(rows_sent_sum),2)",
            "query_time_avg": "SUM(Query_time_sum) / SUM(ts_cnt)",
            "rows_sent_avg": "ROUND(SUM(Rows_sent_sum)/SUM(ts_cnt),0)",
        },
        "callbacks": {
            "table": {
                "date": weekend_marker,
                "checksum": lambda value: (dec2hex(value), ""),
            },
        },
    },
    "performance_schema": {
        "fields": {
            "fact": {
                "order": "order",
                "having": "having",
                "limit": "limit",
                "first_seen": "date_range|reldate|clear|where",
                "where": "raw_where",
                "DIGEST": "clear|where",
                "DIGEST_TEXT": "clear|like|where",
                "group": "group",
            },
        },
        "custom_fields": {
            "snippet": "LEFT(fact.DIGEST_TEXT,20)",
            "index_ratio": "ROUND(SUM_ROWS_EXAMINED/SUM_ROWS_SENT,2)",
            "rows_sent_avg": "ROUND(SUM_ROWS_SENT/COUNT_STAR,0)",
        },
        "special_field_names": {
            "time": "FIRST_SEEN",
            "checksum": "DIGEST",
            "sample": "DIGEST_TEXT",
            "fingerprint": "DIGEST_TEXT",
        },
    },
    "performance_schema_history": {
        "join": {
            "dimension": "USING (`DIGEST`)",
        },
        "fields": {
            "fact": {
                "group": "group",
                "order": "order",
                "having": "having",
                "limit": "limit",
                "first_seen": "clear|reldate|ge|where",
                "where": "raw_where",
                "DIGEST_TEXT": "clear|like|where",
                "DIGEST": "clear|where",
                "reviewed_status": "clear|where",
            },
            "dimension": {
                "extra_fields": "where",
                "hostname": "clear|where",
                "FIRST_SEEN": "date_range|reldate|clear|where",
                "pivot-hostname": "clear|pivot|select",
            },
        },
        "custom_fields": {
            "date": "DATE(fact.FIRST_SEEN)",
            "snippet": "LEFT(fact.DIGEST_TEXT,20)",
            "index_ratio": "ROUND(SUM_ROWS_EXAMINED/SUM_ROWS_SENT,2)",
            "rows_sent_avg": "ROUND(SUM_ROWS_SENT/COUNT_STAR,0)",
            "hour": "substring(dimension.FIRST_SEEN,1,13)",
            "hour_ts": "round(unix_timestamp(substring(dimension.FIRST_SEEN,1,13)))",
            "minute_ts": "round(unix_timestamp(substring(dimension.FIRST_SEEN,1,16)))",
            "minute": "substring(dimension.FIRST_SEEN,1,16)",
        },
        "special_field_names": {
            "time": "FIRST_SEEN",
            "checksum": "DIGEST",
            "hostname": "hostname",
            "sample": "DIGEST_TEXT",
        },
    },
}
