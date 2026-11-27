#!/usr/bin/env bash
# Start (or stop) a throwaway MySQL server in Docker for the integration tests.
#
#   tools/test_mysql.sh start   # prints the ANEMOMETER_TEST_MYSQL value to export
#   tools/test_mysql.sh stop
#
# Tests that need MySQL are skipped unless ANEMOMETER_TEST_MYSQL is set, e.g.
#   export ANEMOMETER_TEST_MYSQL=root:test@127.0.0.1:33306
set -euo pipefail

name="${TEST_MYSQL_CONTAINER:-anemometer-test-mysql}"
image="${TEST_MYSQL_IMAGE:-mysql:5.7}"
port="${TEST_MYSQL_PORT:-33306}"
password=test

case "${1:-start}" in
start)
    if ! docker ps --format '{{.Names}}' | grep -qx "$name"; then
        docker rm -f "$name" >/dev/null 2>&1 || true
        # install.sql uses '0000-00-00' defaults, so run without strict/zero-date modes.
        docker run -d --name "$name" -p "$port:3306" \
            -e MYSQL_ROOT_PASSWORD="$password" \
            "$image" --sql-mode="" --character-set-server=utf8mb4 >/dev/null
    fi
    for _ in $(seq 60); do
        if docker exec "$name" mysql -uroot -p"$password" -e 'SELECT 1' >/dev/null 2>&1; then
            echo "ANEMOMETER_TEST_MYSQL=root:$password@127.0.0.1:$port"
            exit 0
        fi
        sleep 2
    done
    echo "MySQL did not become ready" >&2
    exit 1
    ;;
stop)
    docker rm -f "$name" >/dev/null
    ;;
*)
    echo "usage: $0 start|stop" >&2
    exit 2
    ;;
esac
