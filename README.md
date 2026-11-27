Anemometer
==========

A web UI for MySQL slow query logs: it shows the query digests that
[pt-query-digest](https://docs.percona.com/percona-toolkit/pt-query-digest.html)
stores in MySQL, as searchable tables and graphs, and lets you review queries.

This is a Python port of [Box Anemometer](https://github.com/box/Anemometer)
(PHP). How it was ported and verified is described in
[PORTING_RESULT.md](PORTING_RESULT.md).

## How it fits together

```
slow query log --(pt-query-digest)--> MySQL "slow_query_log" DB --> Anemometer
```

Anemometer only reads (and annotates) the digests; collecting them is done by
`pt-query-digest`, for example from cron.

## Setup

### 1. Storage database

```sh
mysql -h db.example.com < install.sql
mysql -h db.example.com -e "CREATE USER 'anemometer'@'%' IDENTIFIED BY '...';
  GRANT ALL ON slow_query_log.* TO 'anemometer'@'%';"
```

Checksums are stored as `CHAR(32)` (Percona Toolkit 3.x). For MySQL 5.6
`performance_schema` sources see `mysql56-install.sql`.

### 2. Collect slow query digests

```sh
pt-query-digest --user=anemometer --password=... \
  --review  h=db.example.com,D=slow_query_log,t=global_query_review \
  --history h=db.example.com,D=slow_query_log,t=global_query_review_history \
  --no-report --limit=0% \
  --filter=" \$event->{Bytes} = length(\$event->{arg}) and \$event->{hostname}=\"$HOSTNAME\"" \
  /var/lib/mysql/db.example.com-slow.log
```

`scripts/anemometer_collect.sh` wraps this for cron: it turns the slow log on
for an interval, digests it and turns it off again (see the script's header).

### 3. Run the web application

```sh
python -m venv .venv
.venv/bin/pip install -e .                 # Windows: .venv\Scripts\pip
cp conf/config.sample.py conf/config.py    # then edit it
export ANEMOMETER_SECRET_KEY=...           # signs the session cookie
.venv/bin/flask --app "anemometer.web:create_app()" run
```

In production use a WSGI server, e.g. `gunicorn "anemometer.web:create_app()"`
(Linux) or `waitress-serve --call anemometer.web:create_app` (Windows).

Settings (environment variables):

| Variable | Meaning |
|---|---|
| `ANEMOMETER_CONFIG` | configuration file (default `conf/config.py`) |
| `ANEMOMETER_SECRET_KEY` | session signing key |
| `ANEMOMETER_TIMEZONE` | time zone for graphs (default: server local time) |
| `ANEMOMETER_STATIC_DIR` | directory with `js/`, `css/`, `img/` (default: this repository) |

URLs look like `/index.php?action=report&datasource=...`, the same as the PHP
version, so existing bookmarks keep working.

## Development

```sh
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                           # MySQL tests are skipped
tools/test_mysql.sh start                  # throwaway MySQL 5.7 in Docker
export ANEMOMETER_TEST_MYSQL=root:test@127.0.0.1:33306
.venv/bin/pytest                           # everything
tools/test_mysql.sh stop                   # removes the container and its data
```

`tools/load_demo_data.py` fills the test server with a week of made-up digests
for trying the UI (point `conf/config.py` at port 33306).

Many tests compare against output recorded from the original PHP code
(`tests/golden/*.json`), including whole pages of the PHP application
(`tests/test_e2e.py`).

### Layout

| Path | Contents |
|---|---|
| `anemometer/web.py` | Flask app, routing (`?action=`) |
| `anemometer/controller.py` | the actions: report, graph search, query details, review |
| `anemometer/report.py` | builds the aggregate SQL from search form values |
| `anemometer/model.py` | datasource settings, review table access, plugins |
| `anemometer/explain.py` | EXPLAIN / SHOW CREATE TABLE on the query's own server |
| `anemometer/views.py`, `anemometer/templates/` | page rendering |
| `anemometer/config.py`, `conf/config.sample.py` | configuration |
| `anemometer/db.py`, `anemometer/request_vars.py`, `anemometer/sql/`, `anemometer/util/` | helpers |
| `js/`, `css/`, `img/` | front-end assets (unchanged from the PHP version) |

## Known issues

Inherited from the PHP version and kept on purpose during the port:

- Templates print values without HTML escaping (XSS).
- Search form values are interpolated into SQL; the `where`, `group`, `order`,
  `having` and `limit` fields are raw SQL by design. Use a read-only database
  account where possible.

## License

Apache 2.0, see [LICENSE](LICENSE).
