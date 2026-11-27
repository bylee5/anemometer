# 작업 규칙

이 저장소는 PHP로 된 Anemometer를 Python으로 다시 쓴 프로젝트다. PHP 원본은 정리되어 git 이력에만 남아 있다. 이식 과정과 결과는 [PORTING_PLAN.md](PORTING_PLAN.md), [PORTING_RESULT.md](PORTING_RESULT.md)에 있다.

- **git 커밋을 자주 한다.** 의미 있는 작업 단위 하나가 끝날 때마다 커밋한다.
- **딱 맞는 대체재가 없으면 비슷한 것을 쓴다.** 필요한 라이브러리와 정확히 같은 Python 패키지가 없으면, 가장 가까운 것을 고르거나 표준 라이브러리로 직접 구현한다.
- **Python 개발자가 처음부터 쓴 것처럼 작성한다.** Python 관례(PEP 8, 타입 힌트, dataclass, 예외 처리, 표준 라이브러리)를 따른다. Python 3.9 이상에서 동작해야 한다.
- **테스트로 동작을 확인한다.** `tests/golden/*.json`은 PHP 원본에서 기록한 기준 데이터다. 동작을 의도적으로 바꿀 때는 해당 테스트에 "알려진 차이"로 명시한다.
- **변경하면 테스트까지 통과시킨다.** DB 테스트는 `tools/test_mysql.sh start` 후 `ANEMOMETER_TEST_MYSQL`을 설정해 함께 돌린다.
