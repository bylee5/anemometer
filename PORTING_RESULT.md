# Anemometer Python 이식 결과

PHP로 작성된 Box Anemometer 포크를 Python(Flask)으로 다시 작성했다. 계획과 단계별 결정은 [PORTING_PLAN.md](PORTING_PLAN.md)에 있다.

## 요약

- 서버 측 PHP 코드(`index.php`, `lib/` 8개 클래스, `views/` 17개 화면, 설정)를 모두 Python으로 옮겼다. 프런트엔드(`js/`, `css/`, `img/`)와 DB 스키마(`install.sql`)는 그대로 쓴다.
- URL 형식(`/index.php?action=...`)은 바꾸지 않았다. 기존 즐겨찾기와 북마크를 그대로 쓸 수 있다.
- 원본 동작을 그대로 재현하는 것을 원칙으로 했다(계획서 5절 결정 1). 바꾼 부분은 아래 "PHP 버전과 다른 점"에 모두 적었다.
- PHP 원본은 저장소에서 지웠다. 필요하면 정리 직전 커밋(`8fbfb89`)에서 볼 수 있다.

## 구성

| Python | 원본 PHP | 역할 |
|---|---|---|
| `anemometer/web.py` | `index.php` | Flask 앱, `?action=` 라우팅, 정적 파일 |
| `anemometer/controller.py` | `lib/Anemometer.php` | 액션 9개 (리포트, 그래프 검색, 쿼리 상세, 샘플, 리뷰 저장 등) |
| `anemometer/report.py` | `lib/MySQLTableReport.php` | 검색 폼 값 → 집계 SQL 생성·실행 |
| `anemometer/model.py` | `lib/AnemometerModel.php` | 데이터소스 설정, 리뷰 테이블 조회·갱신, 플러그인 |
| `anemometer/explain.py` | `lib/QueryExplain.php` | 원본 서버에서 EXPLAIN, SHOW CREATE TABLE 실행 |
| `anemometer/sql/` | `lib/QueryRewrite.php`, `lib/QueryTableParser.php` | DML → SELECT 변환, 테이블 이름 추출 |
| `anemometer/views.py`, `anemometer/templates/` | `lib/Loader.php`, `views/*.php` | Jinja2 템플릿, JSON 출력 |
| `anemometer/config.py`, `conf/config.sample.py` | `conf/sample.config.inc.php` | 설정 (Python 모듈) |
| `anemometer/db.py`, `anemometer/request_vars.py`, `anemometer/util/` | mysqli 사용부, `lib/Helpers.php` | DB 접속, 요청 파라미터, 보조 함수 |

런타임 의존 패키지는 `flask`, `pymysql` 두 개다.

## 검증

PHP 원본을 Docker(PHP 7.4)에서 실행해 같은 입력에 대한 출력을 기록하고(`tests/golden/*.json`), Python 출력과 비교했다.

| 대상 | 비교 방식 | 건수 |
|---|---|---:|
| SQL 변환, 테이블 추출, 16진수 변환, 표 출력, 상대 날짜, 파라미터 파싱 | 결과 값 일치 | 약 300 |
| 리포트 SQL 생성 (즐겨찾기 링크, pivot, 날짜 범위 등) | SQL·컬럼명·검색 URL 문자열 일치 | 19 |
| 화면 템플릿 / JSON 출력 | 공백 정규화 후 일치 / 바이트 일치 | 25 / 7 |
| 앱 전체 (원본 `index.php`와 같은 DB, 같은 요청) | 공백·현재 시각만 정규화 후 일치 | 18 |

이 밖에 실제 MySQL 5.7을 쓰는 통합 테스트를 포함해 전체 521건이 통과한다. 기준 데이터 생성 도구는 PHP 원본과 함께 지웠으므로, 앞으로는 이미 기록한 데이터로만 비교한다.

## PHP 버전과 다른 점

모두 의도한 변경이고, 해당 테스트에 표시해 두었다.

- **설정 형식**: PHP 배열 → Python 모듈. 데이터소스 유형별 기본값은 `{"default": ..., "<유형>": ...}` 구조로 분리했다. "최근 1일" 같은 기본값은 `relative_time("-1 day")`로 적고 요청마다 계산한다.
- **체크섬 표시**: 샘플 설정의 체크섬 콜백이 `dec2hex` 변환 대신 값을 그대로 보여 준다. 이 포크의 스키마는 체크섬이 `CHAR(32)` 16진수이고, 운영 설정도 원래 그렇게 쓰고 있었다.
- **상대 날짜**: `now`와 `[+-]N 단위`(초·분·시·일·주·fortnight·월·년)만 해석한다. `strtotime`의 비정형 해석(`-1 foo`, `+1 monday` 등)은 입력을 그대로 둔다.
- **매개변수 바인딩**: 체크섬 조회, 리뷰 저장, `SHOW TABLE STATUS`에 값을 SQL에 직접 넣지 않는다. 생성되는 SQL 문장은 같다.
- **버전 확인**: performance_schema용 MySQL 버전 확인을 숫자로 비교한다. 원본은 문자열 비교라 10.x를 5.6 미만으로 판단했다.
- **오류 처리**: 리뷰 폼의 잘못된 액션은 경고를 보여 준다(원본은 없는 함수를 호출해 중단됐다). 처리 중 예외는 오류 알림과 HTTP 500으로 응답한다.
- **안내 문구**: 설정 없음 화면과 데이터소스 없음 경고가 Python 설정 파일 이름(`conf/config.py`)을 안내한다.
- **외부 스크립트**: pt-visual-explain 실행에 타임아웃(60초)을 두었다.

## 고치지 않은 문제

결정 1("똑같이 옮기고 나중에 고치기")에 따라 원본의 문제를 그대로 옮겼다.

- 템플릿이 값을 HTML 이스케이프 없이 출력한다(XSS).
- 검색 폼 값을 SQL에 그대로 넣는다. `where`, `group`, `order`, `having`, `limit` 칸은 설계상 원시 SQL 입력이다. 앱의 DB 계정을 읽기 전용(리뷰 컬럼만 UPDATE 허용)으로 제한하기를 권장한다.

## 남은 일

1. **운영 설정 이전**: 운영 설정(`conf/config.inc.php`, 정리 전 커밋에 있음)을 `conf/config.py`로 옮긴다. 비밀번호는 환경 변수로 빼고, 즐겨찾기 메뉴(`nav_sub`)도 운영 내용으로 채운다.
2. **비밀 정보 정리**: 운영 DB 비밀번호가 git 이력에 남아 있다. `conf/config.inc.php`와 2019년 배포본 `.tar` 안의 설정 백업 파일들이다. 비밀번호를 바꾸고, 저장소를 공개한다면 이력에서도 지워야 한다.
3. **병행 운영과 전환**(계획서 11단계): Python 앱을 운영 DB에 붙여 PHP 앱과 함께 띄우고, 화면을 비교한 뒤 전환한다.
4. **전환 후 보안 수정**: 위 "고치지 않은 문제" 두 가지를 고친다.

데이터 수집(`pt-query-digest`, `scripts/anemometer_collect.sh`)은 이 앱 밖에서 하며, 이번 이식과 무관하게 그대로 쓴다.
