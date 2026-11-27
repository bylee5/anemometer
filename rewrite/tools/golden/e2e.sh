#!/usr/bin/env bash
# Record the original PHP application's responses for tests/test_e2e.py.
#
# Needs the test MySQL container (tools/test_mysql.sh start). Creates the
# database anemometer_e2e from install.sql + e2e_fixture.sql, runs every
# request in e2e_requests.json through index.php and writes
# tests/golden/e2e.json.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
mount="$(cd "$repo" && (pwd -W 2>/dev/null || pwd))"
container="${TEST_MYSQL_CONTAINER:-anemometer-test-mysql}"
image=anemometer-php-mysqli

docker build -q -t "$image" -f "$here/php-mysqli.Dockerfile" "$here" >/dev/null

{
    echo "DROP DATABASE IF EXISTS anemometer_e2e;"
    echo "CREATE DATABASE anemometer_e2e CHARACTER SET utf8mb4;"
    echo "USE anemometer_e2e;"
    grep -vE '^(DROP DATABASE|CREATE DATABASE|USE) ' "$repo/install.sql"
    cat "$here/e2e_fixture.sql"
} | docker exec -i "$container" mysql -uroot -ptest 2>/dev/null

echo "generating rewrite/tests/golden/e2e.json"
MSYS_NO_PATHCONV=1 docker run --rm --network "container:$container" -v "$mount:/app:ro" "$image" \
    php /app/rewrite/tools/golden/e2e_runner.php > "$here/../../tests/golden/e2e.json"
