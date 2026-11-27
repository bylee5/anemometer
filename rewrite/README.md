# Anemometer (Python)

Python port of the PHP application in the repository root. The plan and the
decisions behind it are in [../PORTING_PLAN.md](../PORTING_PLAN.md).

The port reproduces the original behaviour, including its rough edges: values
are printed into HTML without escaping and search fields are interpolated into
SQL as before (see "Known issues" below). Those are to be fixed after the
switch-over.

## Run

```sh
python -m venv .venv
.venv/bin/pip install -e ".[dev]"          # Windows: .venv\Scripts\pip
cp conf/config.sample.py conf/config.py    # then edit it
export ANEMOMETER_SECRET_KEY=...           # signs the session cookie
.venv/bin/flask --app "anemometer.web:create_app()" run
```

In production use a WSGI server, e.g.
`gunicorn "anemometer.web:create_app()"` (Linux) or
`waitress-serve --call anemometer.web:create_app` (Windows).

The web assets (`js/`, `css/`, `img/`) are served from the repository root by
default; set `ANEMOMETER_STATIC_DIR` to use another location. Other settings:
`ANEMOMETER_CONFIG` (configuration file) and `ANEMOMETER_TIMEZONE` (time zone
for graphs, default: server local time).

URLs are unchanged (`/index.php?action=report&datasource=...`), so existing
bookmarks keep working.

## Test

```sh
.venv/bin/pytest                           # unit tests; MySQL tests are skipped
tools/test_mysql.sh start                  # throwaway MySQL 5.7 in Docker
export ANEMOMETER_TEST_MYSQL=root:test@127.0.0.1:33306
.venv/bin/pytest                           # everything
tools/test_mysql.sh stop
```

Most tests compare against output recorded from the original PHP code
(`tests/golden/*.json`). To re-record (needs Docker):

```sh
tools/golden/run.sh            # module-level cases (PHP 7.4 CLI, no database)
tools/golden/e2e.sh            # whole application against the test MySQL server
```

## Layout

| Module | Ported from |
|---|---|
| `anemometer/sql/rewrite.py` | `lib/QueryRewrite.php` |
| `anemometer/sql/table_parser.py` | `lib/QueryTableParser.php` |
| `anemometer/util/` | `lib/Helpers.php`, parts of `QueryExplain.php` and `MySQLTableReport.php` |
| `anemometer/request_vars.py` | `get_var()` and the `$_GET` writes |
| `anemometer/config.py`, `conf/config.sample.py` | `conf/sample.config.inc.php` |
| `anemometer/db.py` | mysqli usage |
| `anemometer/report.py` | `lib/MySQLTableReport.php` |
| `anemometer/explain.py` | `lib/QueryExplain.php` |
| `anemometer/model.py` | `lib/AnemometerModel.php` |
| `anemometer/views.py`, `anemometer/templates/` | `lib/Loader.php`, `views/*.php` |
| `anemometer/controller.py` | `lib/Anemometer.php` |
| `anemometer/web.py` | `index.php` |

## Differences from the PHP version

Intentional, everything else matches the recorded PHP output:

- Configuration is a Python module; per-source-type defaults are
  `{"default": {...}, "<source type>": {...}}`, and time-relative defaults use
  `relative_time("-1 day")` so they are evaluated per request.
- The sample config shows checksums as they are (`CHAR(32)` hex, like the
  production config) instead of converting them with `dec2hex`.
- Relative dates accept `now` and `[+-]N unit` with sec/min/hour/day/week/
  fortnight/month/year; other free-form `strtotime()` input is left as typed.
- Checksum lookups, review updates and `SHOW TABLE STATUS` use bound
  parameters; the generated SQL text is otherwise the same.
- The MySQL version check for performance_schema compares numerically.
- `upd_query` with an unknown form action shows an alert (the original called
  an undefined function and died).
- Uncaught errors show an alert with the message and return HTTP 500.

## Known issues (inherited, to fix later)

- No HTML escaping in templates (XSS).
- Search form values are interpolated into SQL (`where`, `group`, `order`,
  `having`, `limit` are raw SQL by design). Use a read-only database account.
- `conf/config.inc.php` in the repository root contains a real password.
