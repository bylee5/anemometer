# Anemometer Python 이식 계획

원본: PHP 5.3+ 웹 앱 (Box Anemometer 포크). `pt-query-digest`가 MySQL에 적재한 슬로우 쿼리 집계를 조회·그래프·리뷰하는 도구.
목표: 서버 측 PHP 코드(`index.php`, `lib/`, `views/`, `conf/`)를 Python으로 재작성한다. 프런트엔드 정적 자원(`js/`, `css/`, `img/`)과 DB 스키마(`*.sql`)는 그대로 재사용한다.

> 용어: Python에는 "크레이트"(Rust)라는 단위가 없으므로 이 문서에서는 PyPI **패키지** 기준으로 대응 관계를 적는다.

---

## 1. 현재 구조

### 1.1 이식 대상 범위

| 경로 | 줄 수 | 역할 | 이식 여부 |
|---|---:|---|---|
| `index.php` | 46 | 프런트 컨트롤러. `?action=` 값으로 `Anemometer`의 public 메서드를 호출 | 이식 (라우팅) |
| `lib/Anemometer.php` | 747 | 컨트롤러. 액션 9개(`index`, `report`, `api`, `graph_search`, `show_query`, `samples`, `quicksearch`, `upd_query`, `noconfig`) | 이식 |
| `lib/AnemometerModel.php` | 455 | 설정 조회, fact/dimension 테이블 조회·갱신, 외부 스크립트(pt-visual-explain) 실행 | 이식 |
| `lib/MySQLTableReport.php` | 1081 | 폼 값 → SQL 생성기(SELECT/JOIN/WHERE/GROUP/HAVING/ORDER/LIMIT, pivot, 날짜 범위) 및 실행 | 이식 (핵심) |
| `lib/QueryExplain.php` | 304 | 샘플 쿼리의 원본 DB에 접속해 `EXPLAIN`, `SHOW CREATE TABLE`, `SHOW TABLE STATUS` 실행, mysql CLI 형식 표 출력 | 이식 |
| `lib/QueryRewrite.php` | 118 | DML을 EXPLAIN 가능한 SELECT로 변환 (정규식 기반) | 이식 |
| `lib/QueryTableParser.php` | 118 | SQL 문자열에서 테이블 이름 추출 (토큰 기반) | 이식 |
| `lib/Helpers.php` | 146 | 전역 함수: `get_var`, `site_url`, `prettyprint`, `check_mysql_error`, `flatten_array`, `dec2hex`, `trim_left_zeros` | 이식 (분산) |
| `lib/Loader.php` | 49 | `views/{name}.php`를 `extract($data)` 후 include | Jinja2로 대체 |
| `lib/TestQueryRewrite.php` | 244 | PHPUnit 테스트 | pytest로 이식 |
| `views/*.php` | 1,808 (17개) | HTML/JSON 출력 템플릿. 인라인 JS(flot 그래프) 포함 | Jinja2 템플릿으로 이식 |
| `conf/config.inc.php`, `conf/sample.config.inc.php` | 457 / 444 | PHP 배열 설정. **클로저(콜백 함수)를 포함** | Python 설정 모듈로 이식 |
| `scripts/anemometer_collect.sh` | 158 | 수집 스크립트 (bash + mysql CLI + pt-query-digest) | 이식 불필요 (PHP와 무관) |
| `install.sql`, `mysql56-*.sql` | — | 저장소 DB 스키마 | 그대로 사용 |
| `js/`, `css/`, `img/` | — | jQuery 1.8, Bootstrap 2, flot, prettify | 그대로 사용 (static) |
| `docs/` | — | phpDocumentor 산출물 | 폐기 |
| `vagrant/` | — | 개발용 VM | 폐기 또는 docker-compose로 대체 |
| `.tar` | 2.9MB | 2019년 시점 배포본 스냅샷 (아래 1.4 참고) | 이식 대상 아님 |

### 1.2 모듈 의존 관계

```
index.php  (라우터, conf 로드)
 ├─ Helpers.php ─────────────────────────────────────┐ ($_GET/$_POST/$_SERVER 전역 의존)
 └─ Anemometer.php (컨트롤러)                         │
     ├─ Loader.php ──► views/*.php ──────────────────┤ (get_var, site_url, prettyprint, dec2hex, flatten_array)
     ├─ MySQLTableReport.php ──► mysqli ─────────────┤ (get_var)
     └─ AnemometerModel.php ──► mysqli, proc_open ───┤ (check_mysql_error)
         └─ QueryExplain.php ──► mysqli              │
             ├─ QueryTableParser.php   (의존 없음)    │
             └─ QueryRewrite.php       (의존 없음)    │
conf/config.inc.php ──► Helpers.dec2hex (콜백 안에서) ┘
```

의존 깊이(작을수록 먼저 이식 가능):

| 깊이 | 모듈 | 내부 의존 | 외부 의존 |
|---:|---|---|---|
| 0 | `QueryRewrite` | 없음 | PCRE |
| 0 | `QueryTableParser` | 없음 | PCRE |
| 0 | `Helpers` 중 순수 함수 (`dec2hex`, `trim_left_zeros`, `flatten_array`) | 없음 | — |
| 0 | `QueryExplain::result_as_table` / `make_row` / `make_rule` (static) | 없음 | — |
| 1 | `Helpers` 중 요청 함수 (`get_var`, `site_url`) | 요청 컨텍스트 | 슈퍼글로벌 |
| 1 | 설정 (`config.inc.php`) | `dec2hex` | PHP 클로저 |
| 2 | `QueryExplain` | `QueryRewrite`, `QueryTableParser` | mysqli |
| 2 | `MySQLTableReport` | `get_var` | mysqli, `strtotime`, `date` |
| 3 | `AnemometerModel` | `QueryExplain`, `check_mysql_error`, 설정 | mysqli, `proc_open` |
| 3 | `Loader` + `views/` | `Helpers` 전부 | `json_encode`, `strptime`, `mktime` |
| 4 | `Anemometer` | 위 전부 | 세션, `header()`, 시간대 |
| 5 | `index.php` | `Anemometer`, 설정 | — |

### 1.3 이식 시 구조적으로 주의할 점

1. **`$_GET`을 상태 저장소로 사용한다.** 컨트롤러가 `$_GET[...] = ...`로 값을 써 넣고, `MySQLTableReport`가 `get_var()`로 다시 읽는 방식으로 두 클래스가 통신한다 (`set_search_defaults`, `show_query`, `graph_search` 등 약 20곳). Python에서는 요청마다 **변경 가능한 `RequestVars` 객체**를 만들어 컨트롤러와 리포트에 명시적으로 넘긴다. Flask의 `request.args`는 불변이므로 그대로 쓰면 안 된다.
2. **설정 문자열로 메서드를 동적 호출한다.** `'clear|reldate|ge|where'` 같은 필터 체인을 `call_user_func_array(array($this, $func), ...)`로 실행한다. Python에서는 `getattr` 대신 **허용 목록 dict**(`{"clear": self.clear, ...}`)로 디스패치한다. `index.php`의 `?action=` 디스패치도 같은 방식으로 허용 목록을 쓴다.
3. **출력 순서에 의존하는 렌더링.** `header()` 출력 여부를 `header_printed` 플래그로 추적하고, 예외 발생 시 페이지 중간에 `alert()`를 `print`한다. `check_mysql_error`는 `die()`로 즉시 종료한다. Python에서는 요청당 출력 버퍼(조각 리스트)에 쌓은 뒤 한 번에 응답하고, `die()`는 예외 + 에러 핸들러로 바꾼다.
4. **리다이렉트가 출력 이후에 올 수 있다.** `header("Location: ...")` 호출 전에 이미 출력이 있을 수 있다. Python에서는 리다이렉트를 `Response` 반환으로 처리한다.
5. **설정에 클로저가 있다.** `plugins.explain`(샘플 행 → 접속 정보), `reports.*.callbacks.table.*`(셀 값 변환). YAML/TOML로는 표현할 수 없으므로 **설정을 Python 모듈(`config.py`)로** 둔다.
6. **PHP 느슨한 비교와 truthiness.** `get_var($key) == null`(빈 문자열도 참), `$expression == ''`(null도 참), `get_var('start') | 0`, `$row['@@version'] >= '5.6'`(문자열 비교) 등. 이 규칙을 `phpcompat.py`의 작은 헬퍼(`is_blank()` 등)로 모아 한 곳에서 처리한다. MySQL 버전 비교는 숫자 튜플 비교로 고친다.
7. **바이트 길이 기준 패딩.** `result_as_table`이 `strlen`(바이트)으로 열 너비를 계산하므로, 한글이 포함된 EXPLAIN 결과는 원본에서도 정렬이 어긋난다. Python에서는 `wcwidth`로 화면 폭 기준으로 계산한다 (의도적 동작 변경).
8. **정규식 차이.** PCRE는 `/u` 없이 쓰여 `\w`가 ASCII 기준이다. Python에서는 `re.ASCII`를 붙여 동일하게 맞춘다. `preg_split("/\|/")` 같은 단순 분할은 `str.split`으로 바꾼다.
9. **SQL 인젝션 표면.** `where` 값은 이스케이프 없이 `"..."`로 감싸고, `get_query_by_checksum`, `get_query_samples`, `SHOW TABLE STATUS LIKE '{$table}'`는 값을 그대로 끼워 넣는다. `fact-where`(raw_where), `group`/`order`/`having`/`limit`은 **설계상 원시 SQL 입력**이다 (`views/nav_sub.php`의 즐겨찾기 링크가 이 기능을 사용한다). 1차 이식은 동작 동등성을 우선하되, 값 바인딩이 가능한 곳(체크섬, WHERE 값, 테이블명)은 이식하면서 바로 매개변수 바인딩 또는 식별자 검증으로 바꾼다. 원시 SQL 입력 기능은 유지하고 접속 계정을 읽기 전용으로 제한할 것을 권장한다.

### 1.4 이 포크의 원본 대비 변경점 (이식 시 유지)

- `checksum` 컬럼이 `BIGINT UNSIGNED` → `CHAR(32)`로 바뀌었다 (`install.sql`, `Anemometer::translate_checksum` 주석, 2019-01-11). 그래서 16진수 → 10진수 변환(`bchexdec`, BCMath)은 더 이상 쓰이지 않는다. **BCMath 의존은 이식하지 않는다** (`index.php`의 BCMath 확인도 제거).
- `conf/config.inc.php`의 `checksum` 콜백은 `dec2hex`를 호출하지 않는다. 다만 `views/report_json2.php`는 숫자로만 된 열 이름에 여전히 `dec2hex`를 적용하므로, 체크섬이 우연히 숫자로만 이루어진 경우 그래프 레이블이 바뀌는 잠재 버그가 있다. 이식 시 이 변환은 제거하는 것을 권장한다.
- `QueryExplain::explain_query`는 EXPLAIN 전에 `/* ... */` 주석을 제거한다.
- `views/nav_sub.php`는 사내 즐겨찾기 리포트 링크 모음이다. `.tar` 안의 `nav_sub.php`(34KB)는 현재 파일과 내용이 다르므로, 어느 쪽이 최신인지 이식 전에 확인해야 한다.
- `conf/config.inc.php`에 **실제 비밀번호가 커밋되어 있다.** Python 설정에서는 비밀 값을 환경 변수로 분리하고, 설정 파일은 `.gitignore`에 넣는다.

---

## 2. PHP 기능 → Python 패키지 대응

| PHP 기능 / 라이브러리 | 사용 위치 | Python 대응 | 비고 |
|---|---|---|---|
| `mysqli` (접속, query, prepare/bind_param, real_escape_string, fetch_assoc) | Model, Report, Explain | **PyMySQL** (`DictCursor`) | 순수 Python이라 Windows/Linux 모두 설치가 쉽다. 성능이 필요하면 API가 거의 같은 `mysqlclient`로 교체 가능. SQL을 문자열로 직접 만드는 구조라 SQLAlchemy ORM은 이점이 적다 |
| `MYSQLI_OPT_CONNECT_TIMEOUT` | Report(5초), Explain(1초) | `pymysql.connect(connect_timeout=...)` | |
| `index.php` 라우팅, `$_GET`/`$_POST`/`$_SERVER`, `header("Location")` | 전역 | **Flask** (Werkzeug) | 동기식 서버 렌더링 + 단일 URL `?action=` 구조에 맞다. FastAPI는 비동기/JSON API 중심이라 이 앱에는 과하다 |
| `session_start()`, `$_SESSION` | 리뷰어 이름 기억 | Flask `session` (서명된 쿠키) | `SECRET_KEY` 필요 |
| `$_SERVER['PHP_AUTH_USER']` (.htaccess 인증) | `get_auth_user` | `request.authorization.username` 또는 리버스 프록시의 `REMOTE_USER` | 배포 방식에 따라 선택 |
| `Loader` + `views/*.php` (`extract` + include) | 모든 화면 | **Jinja2** (Flask 내장) | `extract($data)` → `render_template(name, **data)` |
| `json_encode` | `report_json*.php` | 표준 `json` | 원본은 `Content-Type: text/html`로 응답한다. 프런트 JS가 문제없는지 확인 후 `application/json`으로 바꾼다 |
| `preg_match` / `preg_replace` / `preg_split` | Rewrite, Parser, Report | 표준 `re` (`re.ASCII`) | |
| `proc_open` (pt-visual-explain, pt-query-advisor) | Model | 표준 `subprocess.run(input=..., cwd=..., timeout=...)` | 원본엔 타임아웃이 없다. 추가 권장 |
| `strtotime("-1 month")`, `date("Y-m-d H:i:s")` | `MySQLTableReport::reldate` | 표준 `datetime` (`anemometer.util.timeutil`) | 입력 형식이 `^\s*([+-])?(\d+)\s(\w+)$` 하나로 제한되어 있어 작은 파서로 충분하다. `relativedelta`는 월말 처리 규칙이 PHP와 달라(3/31 − 1개월: PHP 3/2, relativedelta 2/29) 쓰지 않는다. 요일 이름 등 비정형 표현은 해석하지 않고 그대로 둔다 |
| `strptime` / `mktime` (서버 로컬 시간) | `report_json2.php` | `datetime.strptime` + `.timestamp()` | 로컬 시간대 기준이어야 그래프가 원본과 같다 |
| `exec('date +%Z')`, `timezone_offset_get` | 컨트롤러 생성자 | 표준 `zoneinfo` + **tzlocal** | 셸 호출 제거. 시간대는 설정 값으로 받는 것을 권장 |
| `date('N', strtotime($x))` (주말 판정) | 설정 콜백 | `datetime.isoweekday()` | |
| BCMath (`bcadd`, `bcmul`) | `bchexdec` (사용 안 함) | 불필요 — Python `int`는 임의 정밀도 | `int(h, 16)` / `format(n, "X")` |
| `dec2hex` (문자열 기반 긴 나눗셈) | Helpers, 설정 콜백, `report_json2` | `format(int(s), "X")` | 한 줄로 대체 |
| `urlencode` | `get_search_uri` | `urllib.parse.quote_plus` | 공백 → `+` 동작 동일 |
| `str_pad` / `sprintf("%20s : %s")` | Explain 표 출력 | f-string + **wcwidth** | 1.3-7 참고 |
| `addslashes` | pivot의 `IF(col='값', ...)` | 직접 구현한 `sql_quote()` 또는 `pymysql.converters.escape_string` | |
| PHPUnit | `TestQueryRewrite.php` | **pytest** | |
| PHP 배열 설정 + 클로저 | `conf/` | `config.py` (Python 모듈, `importlib`로 로드) + 환경 변수 | 검증이 필요하면 `pydantic` 고려 (선택) |
| Apache + mod_php | 배포 | **gunicorn** (Linux) / **waitress** (Windows) | 정적 파일은 웹서버 또는 Flask `static` |
| — | 테스트 DB | **testcontainers** (MySQL) 또는 docker-compose | 통합 테스트용 (선택) |

최종 런타임 의존: `flask`, `pymysql`, (운영) `gunicorn` 또는 `waitress`. (`tzlocal`은 10단계에서 필요 여부 판단. 5절 결정 1에 따라 표 출력은 원본처럼 바이트 길이 기준으로 맞추므로 `wcwidth`는 쓰지 않는다.)
개발 의존: `pytest`, (선택) `testcontainers`.

---

## 3. 목표 패키지 구조

Python 코드는 전부 저장소의 `rewrite/` 폴더 아래에 둔다. 아래 경로는 `rewrite/` 기준이다.

```
pyproject.toml
tools/golden/           ← PHP 원본을 Docker에서 실행해 기준 데이터를 만드는 스크립트
anemometer/
  __init__.py
  sql/
    rewrite.py          ← QueryRewrite.php
    table_parser.py     ← QueryTableParser.php
  util/
    hexconv.py          ← Helpers::dec2hex, trim_left_zeros
    text_table.py       ← QueryExplain::result_as_table / make_row / make_rule
    timeutil.py         ← reldate 파서, 시간대 오프셋
    phpcompat.py        ← 느슨한 비교 헬퍼 (is_blank 등), flatten_array
  request_vars.py       ← get_var / $_GET 변경을 대체하는 요청 단위 상태 객체
  config.py             ← 설정 로더 (conf/config.py 로드 + 환경 변수 병합)
  db.py                 ← PyMySQL 접속 팩토리, 에러 → 예외 변환 (check_mysql_error 대체)
  report.py             ← MySQLTableReport.php
  explain.py            ← QueryExplain.php (DB 부분)
  model.py              ← AnemometerModel.php
  controller.py         ← Anemometer.php
  web.py                ← index.php (Flask 앱, ?action= 디스패치)
  templates/            ← views/*.php → *.html (Jinja2)
static/                 ← 기존 js/ css/ img/ 그대로 이동 또는 심볼릭 링크
conf/config.sample.py   ← sample.config.inc.php
tests/
```

URL 구조(`index.php?action=report&datasource=...&table_fields[]=...`)는 **그대로 유지**한다. `nav_sub.php`의 즐겨찾기 링크, 사용자 북마크, 프런트 JS의 AJAX URL이 모두 이 형식에 의존한다. Flask에서는 `/` 하나와 `/index.php`(호환용) 두 경로에 같은 디스패처를 연결한다.

---

## 4. 이식 순서

원칙: 의존이 없는 모듈부터 옮기고, 각 단계가 끝날 때마다 해당 모듈의 테스트가 통과해야 다음 단계로 간다. 단계 1~4는 DB 없이 단위 테스트만으로 검증할 수 있다.

### 단계 0. 기반 준비
- `pyproject.toml`, pytest 설정, 린터(ruff) 구성.
- **골든 데이터 수집:** 기존 PHP 앱을 docker(PHP 7 + MySQL)로 띄워 아래 출력을 파일로 저장한다. 이후 단계의 회귀 테스트 기준이 된다.
  - 대표 URL별 `MySQLTableReport::query()`가 생성한 SQL (`api` 액션에 `output=print_r` 또는 `debug=1`을 붙이면 확인 가능). `views/nav_sub.php`의 즐겨찾기 링크와 `report_defaults`/`graph_defaults`/`history_defaults`를 우선 수집.
  - `output=json`, `output=json2` 응답 본문.
  - 샘플 쿼리 몇 개에 대한 `EXPLAIN` 표 문자열.
- 완료 기준: 골든 파일 세트가 `tests/golden/`에 커밋됨.

### 단계 1. `sql/rewrite.py` ← `QueryRewrite.php` (의존 0)
- 상수(`SELECT`, `DELETE`, ... ) → `IntEnum`.
- `TestQueryRewrite.php`의 케이스를 전부 pytest로 옮긴다 (`@pytest.mark.parametrize`).
- 주의: `toSelect()`의 UPDATE 분기는 패턴이 맞지 않으면 PHP에서 notice와 함께 빈 문자열을 만든다. Python에서는 `None`을 반환하도록 하고 테스트로 고정한다.
- 완료 기준: 기존 PHPUnit 케이스 전부 통과.

### 단계 2. `sql/table_parser.py` ← `QueryTableParser.php` (의존 0)
- 공백 기준 토크나이저를 그대로 옮긴다 (원본의 한계—문자열 리터럴 안의 `from`, 백틱 안 공백—도 그대로 유지하고 테스트에 기록).
- 반환 순서는 처음 등장 순서 (`dict` 키 순서로 재현).
- 완료 기준: 쉼표 조인, `schema.table`, 백틱, `INSERT INTO`, `UPDATE` 케이스 테스트 통과.

### 단계 3. `util/*` ← Helpers 순수 함수 + Explain 표 출력 (의존 0)
- `hexconv.dec2hex` → `format(int(s), "X")`. 원본 PHP 구현과 0, 15, 16, 2^63, 2^64-1 등 경계값을 비교 테스트.
- `text_table.result_as_table(rows, columns)` — DB 결과 객체 대신 `list[dict]`를 받도록 바꿔 DB와 분리한다. 골든 EXPLAIN 표와 비교 (ASCII 범위에서는 바이트 단위까지 동일해야 함).
- `timeutil.reldate("now" | "-1 month" | "+3 days" ...)` — `strtotime` 동작 중 실제 쓰이는 형식만 구현.
- `phpcompat` — `is_blank`, `flatten_array`.
- 완료 기준: 단위 테스트 통과.

### 단계 4. `request_vars.py`, `config.py` (깊이 1)
- `RequestVars`: POST 우선 → GET 순서로 조회 (`get_var`와 동일), `set()`/`unset()` 지원, `table_fields[]` 같은 배열 파라미터는 리스트로 보관. Flask `request`에서 요청마다 복사해서 생성.
- `site_url()` → `request.script_root + request.path` 기반 함수.
- 설정: `conf/sample.config.inc.php`를 `conf/config.sample.py`로 옮긴다. 클로저는 일반 함수로 변환. 비밀번호는 `os.environ`에서 읽는다.
- 완료 기준: 샘플 설정 로드 테스트, `RequestVars` 단위 테스트.

### 단계 5. `db.py` (깊이 1)
- `connect(ds: dict, timeout: int) -> Connection` (DictCursor, `autocommit=True`, charset 명시).
- `query_all`, `query_one`, `execute` 헬퍼. 오류 시 `DatabaseError(errno, message)`를 던진다 (`check_mysql_error`의 `die()` 대체).
- 완료 기준: testcontainers 또는 로컬 MySQL로 접속·조회 통합 테스트.

### 단계 6. `report.py` ← `MySQLTableReport.php` (깊이 2, 가장 중요)
- 생성자에서 DB 접속을 분리한다: SQL 생성(`query()`)은 DB 없이 테스트할 수 있어야 한다. `get_table_fields`, `get_distinct_values`, `execute`만 연결을 사용.
- 필터 체인(`clear`, `reldate`, `date_range`, `ge`/`le`/`gt`/`lt`/`ne`, `like`, `where`, `group`, `order`, `having`, `limit`, `raw_where`, `pivot`, `select`)을 허용 목록 dict로 디스패치. 원본에서 `$this`를 반환해 체인을 끊는 동작(빈 리스트로 처리됨)을 그대로 재현.
- `get_column_aggregate_function`의 정규식·분기 순서, `remove_schema_name`, `get_search_uri`의 파라미터 순서를 원본과 동일하게 유지 (URL 문자열이 골든과 일치해야 함).
- `RequestVars`를 생성자 인자로 받는다 (전역 `get_var` 제거).
- 완료 기준: 단계 0에서 수집한 모든 URL에 대해 생성 SQL과 `get_search_uri()`가 골든과 **문자열 단위로 일치**.

### 단계 7. `explain.py` ← `QueryExplain.php` (깊이 2)
- 의존: 단계 1(rewrite), 2(table_parser), 3(text_table), 5(db).
- 접속 정보 콜백(`plugins.explain`)이 `None`을 반환하거나 필수 키가 없으면 예외 → 컨트롤러가 `explain_plan_error`로 표시하는 원본 흐름 유지.
- `SHOW TABLE STATUS LIKE %s`는 바인딩, `SHOW CREATE TABLE`은 식별자 검증 후 백틱으로 감싼다.
- 완료 기준: 테스트 DB에서 SELECT/UPDATE/DELETE 샘플의 EXPLAIN 표가 생성되고, 접속 실패 시 오류 메시지가 반환됨.

### 단계 8. `model.py` ← `AnemometerModel.php` (깊이 3)
- 의존: 단계 4(config), 5(db), 7(explain).
- `update_query`의 `'NULL'` 문자열 → SQL NULL 처리 규칙 유지. 체크섬 조건은 바인딩으로 변경.
- `exec_external_script` → `subprocess.run`, 실행 파일이 없으면 원본처럼 안내 문자열 반환, 타임아웃 추가.
- `performance_schema` 소스의 MySQL 버전 확인은 숫자 튜플 비교로 수정.
- 완료 기준: 테스트 DB에 `install.sql`을 적용하고 체크섬 존재 확인·조회·샘플 조회·리뷰 갱신 통합 테스트 통과.

### 단계 9. `templates/` ← `views/*.php` (깊이 3)
- 단순한 것부터: `footer` → `report_json`/`report_json2`/`report_printr` → `report_result` → `samples` → `index`/`noconfig` → `header`/`navbar`/`nav_sub` → `report`/`report-performance_schema` → `show_query`/`show_query_perf_schema` → `graph_search`/`graph_search-performance_schema_history`.
- `report_json2`의 데이터 가공(시계열 변환)은 템플릿이 아닌 Python 함수로 옮기고 단위 테스트한다.
- 인라인 JS 안의 PHP 값 출력은 Jinja2 `|tojson` 필터로 바꿔 이스케이프 문제를 없앤다.
- Jinja2 자동 이스케이프를 켠다. 원본은 대부분 이스케이프 없이 출력하므로 SQL 샘플 표시 등에서 화면 차이가 날 수 있다 — 의도된 수정으로 기록.
- 완료 기준: 각 템플릿 렌더링 스모크 테스트, JSON 출력은 골든과 일치.

### 단계 10. `controller.py` + `web.py` ← `Anemometer.php` + `index.php` (깊이 4~5)
- 액션 허용 목록: `index`, `report`, `api`, `graph_search`, `show_query`, `samples`, `quicksearch`, `upd_query`, `noconfig`.
- 출력 버퍼 방식으로 `header()`/`alert()`/`footer()`의 출력 순서를 재현하고, `noheader=1` 처리 유지.
- `upd_query`, `quicksearch`, 단일 데이터소스 `index`의 리다이렉트는 `redirect()` 응답으로.
- 세션(`current_review_user`), 인증 사용자 조회 연결.
- 완료 기준: 테스트 클라이언트(`app.test_client()`)로 모든 액션 200/302 확인, 골든 URL의 `api` 응답이 원본과 일치.

### 단계 11. 병행 운영과 전환
- PHP 앱과 Python 앱을 같은 저장소 DB에 붙여 병행 운영한다. 저장소 DB 스키마는 바꾸지 않으므로 두 앱이 동시에 동작할 수 있다.
- 주요 화면을 눈으로 비교하고, `api?output=json` 응답을 자동 비교하는 스크립트를 일정 기간 실행.
- 이상이 없으면 웹서버 라우팅을 Python 앱으로 전환하고, PHP 코드·`docs/`·`vagrant/`·`.tar`를 정리한다.

### 단계별 요약

| 단계 | 모듈 | 선행 단계 | DB 필요 | 검증 방식 |
|---:|---|---|---|---|
| 0 | 골든 데이터, 프로젝트 골격 | — | PHP 환경 | — |
| 1 | `sql/rewrite.py` | 0 | 아니오 | 기존 PHPUnit 케이스 |
| 2 | `sql/table_parser.py` | 0 | 아니오 | 단위 테스트 |
| 3 | `util/*` | 0 | 아니오 | 단위 테스트 + 골든 EXPLAIN 표 |
| 4 | `request_vars.py`, `config.py` | 3 | 아니오 | 단위 테스트 |
| 5 | `db.py` | 4 | 예 | 통합 테스트 |
| 6 | `report.py` | 3, 4, 5 | SQL 생성은 아니오 | 골든 SQL·URI 문자열 일치 |
| 7 | `explain.py` | 1, 2, 3, 5 | 예 | 통합 테스트 |
| 8 | `model.py` | 4, 5, 7 | 예 | 통합 테스트 |
| 9 | `templates/` | 4 | 아니오 | 렌더링 스모크 + 골든 JSON |
| 10 | `controller.py`, `web.py` | 6, 8, 9 | 예 | 테스트 클라이언트 + 골든 응답 |
| 11 | 병행 운영·전환 | 10 | 예 | 응답 비교 |

단계 1·2·3은 서로 독립이라 병렬로 진행할 수 있고, 단계 9(템플릿)는 단계 4 이후 단계 5~8과 병렬로 진행할 수 있다.

---

## 5. 착수 전에 결정할 사항

1. 똑같이 옮기고 나중에 고치기
2. **인증 방식:** 인증 없음
3. **`nav_sub.php`의 기준본:** 현재 파일
4. **Python 버전과 배포 환경:** Python 3.9 이상, Linux(gunicorn) 배포를 가정했다.
5. **`performance_schema` 데이터소스 사용 여부:** 그대로 이식
