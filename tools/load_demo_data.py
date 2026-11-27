"""Fill a MySQL server with demo data for trying out Anemometer.

Creates (dropping them first!) two databases:

* ``slow_query_log`` -- the review tables from install.sql, with a week of
  hourly digests for a handful of queries on two hosts, ending now;
* ``demo_app`` -- the application tables the sample queries use, so the
  EXPLAIN plan and CREATE TABLE sections have something to show.

Usage::

    python tools/load_demo_data.py [user:password@host:port]

The default target is the test server started by tools/test_mysql.sh.
"""

from __future__ import annotations

import hashlib
import random
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anemometer.db import connect  # noqa: E402

INSTALL_SQL = Path(__file__).resolve().parents[1] / "install.sql"
HOSTS = ["db1.example.com", "db2.example.com"]

APP_TABLES = [
    """CREATE TABLE users (
        id INT PRIMARY KEY AUTO_INCREMENT,
        email VARCHAR(100) NOT NULL,
        name VARCHAR(50) NOT NULL,
        created_at DATETIME NOT NULL,
        UNIQUE KEY uk_email (email)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE products (
        id INT PRIMARY KEY AUTO_INCREMENT,
        name VARCHAR(100) NOT NULL,
        category VARCHAR(30) NOT NULL,
        price DECIMAL(10,2) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE orders (
        id INT PRIMARY KEY AUTO_INCREMENT,
        user_id INT NOT NULL,
        product_id INT NOT NULL,
        status VARCHAR(20) NOT NULL,
        amount DECIMAL(10,2) NOT NULL,
        created_at DATETIME NOT NULL,
        KEY idx_user (user_id),
        KEY idx_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]

# fingerprint, sample, (avg query time, rows examined, rows sent, executions per hour), user
QUERIES = [
    (
        "select * from orders where status = ? order by created_at desc",
        "SELECT * FROM orders WHERE status = 'pending' ORDER BY created_at DESC",
        (2.4, 180000, 120, 30),
        "web",
    ),
    (
        "select o.id, u.email from orders o join users u on u.id = o.user_id"
        " where o.created_at > ?",
        "SELECT o.id, u.email FROM orders o JOIN users u ON u.id = o.user_id "
        "WHERE o.created_at > '2024-03-01 00:00:00'",
        (1.1, 90000, 5000, 12),
        "report",
    ),
    (
        "select * from products where name like ?",
        "SELECT * FROM products WHERE name LIKE '%키보드%'",
        (0.8, 50000, 20, 60),
        "web",
    ),
    (
        "select count(*) from orders where user_id = ?",
        "SELECT COUNT(*) FROM orders WHERE user_id = 42",
        (0.12, 300, 1, 400),
        "api",
    ),
    (
        "update orders set status = ? where created_at < ? and status = ?",
        "UPDATE orders SET status = 'expired'"
        " WHERE created_at < '2024-01-01' AND status = 'pending'",
        (5.6, 400000, 0, 2),
        "batch",
    ),
    (
        "delete from orders where status = ? and created_at < ?",
        "DELETE FROM orders WHERE status = 'cancelled' AND created_at < '2023-01-01'",
        (3.2, 250000, 0, 1),
        "batch",
    ),
    (
        "select p.category, sum(o.amount) from orders o join products p on p.id = o.product_id "
        "group by p.category",
        "SELECT p.category, SUM(o.amount) FROM orders o JOIN products p ON p.id = o.product_id "
        "GROUP BY p.category",
        (4.1, 600000, 12, 4),
        "report",
    ),
    (
        "select * from users where email = ?",
        "SELECT * FROM users WHERE email = 'kim@example.com'",
        (0.05, 1, 1, 900),
        "api",
    ),
]


def checksum(fingerprint: str) -> str:
    return hashlib.md5(fingerprint.encode()).hexdigest().upper()


def create_tables(connection) -> None:
    lines = INSTALL_SQL.read_text(encoding="utf-8").splitlines()
    sql = "\n".join(line for line in lines if not line.lstrip().startswith("--"))
    for statement in sql.split(";"):
        if statement.strip().upper().startswith("CREATE TABLE"):
            connection.execute(statement)


def main(target: str) -> None:
    match = re.fullmatch(r"([^:@]+):([^@]*)@([^:]+):(\d+)", target)
    if not match:
        raise SystemExit(f"bad target {target!r}, expected user:password@host:port")
    user, password, host, port = match.groups()
    server = {"host": host, "port": int(port), "user": user, "password": password}
    rng = random.Random(42)

    with connect(**server, db="") as admin:
        for name in ("slow_query_log", "demo_app"):
            admin.execute(f"DROP DATABASE IF EXISTS `{name}`")
            admin.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4")

    with connect(**server, db="demo_app") as app:
        for statement in APP_TABLES:
            app.execute(statement)
        app.execute(
            "INSERT INTO users (email, name, created_at)"
            " VALUES ('kim@example.com', '김철수', NOW()), ('lee@example.com', '이영희', NOW())"
        )

    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=7)
    with connect(**server, db="slow_query_log") as db:
        create_tables(db)
        for fingerprint, sample, (seconds, examined, sent, per_hour), user in QUERIES:
            digest = checksum(fingerprint)
            db.execute(
                "INSERT INTO global_query_review (checksum, fingerprint, sample, first_seen,"
                " last_seen) VALUES (%s, %s, %s, %s, %s)",
                [digest, fingerprint, sample, start, now],
            )
            rows = []
            hour = start
            while hour <= now:
                # busier during the day, quieter at night
                load = 1.0 if 9 <= hour.hour <= 18 else 0.3
                for host in HOSTS:
                    count = max(1, int(per_hour * load * rng.uniform(0.5, 1.5)))
                    query_time = seconds * rng.uniform(0.6, 1.6)
                    rows.append(
                        [host, "demo_app", user, f"10.0.0.{HOSTS.index(host) + 11}", digest,
                         sample, hour, hour + timedelta(minutes=59), count,
                         query_time * count, query_time * 0.5, query_time * 2,
                         query_time * 1.8, query_time * 1.1,
                         0.001 * count, 0.0005, 0.01,
                         sent * count, sent, examined * count, examined,
                         int(count * 0.3), int(count * 0.2), count if examined > 10000 else 0,
                         len(sample) * count]
                    )  # fmt: skip
                hour += timedelta(hours=1)
            for batch in range(0, len(rows), 200):
                chunk = rows[batch : batch + 200]
                db.execute(
                    "INSERT INTO global_query_review_history (hostname_max, db_max, user_max,"
                    " ip_max, checksum, sample, ts_min, ts_max, ts_cnt, Query_time_sum,"
                    " Query_time_min, Query_time_max, Query_time_pct_95, Query_time_median,"
                    " Lock_time_sum, Lock_time_min, Lock_time_max, Rows_sent_sum, Rows_sent_max,"
                    " Rows_examined_sum, Rows_examined_max, Tmp_table_sum, Filesort_sum,"
                    " Full_scan_sum, Bytes_sum) VALUES "
                    + ",".join(["(" + ",".join(["%s"] * 25) + ")"] * len(chunk)),
                    [value for row in chunk for value in row],
                )
            print(f"{digest}  {len(rows):4d} rows  {fingerprint[:60]}")

        # one reviewed query
        db.execute(
            "UPDATE global_query_review SET reviewed_by = 'dba1', reviewed_on = NOW(),"
            " reviewed_status = 'needs-fix', comments = 'status 컬럼에 인덱스 필요'"
            " WHERE checksum = %s",
            [checksum(QUERIES[0][0])],
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "root:test@127.0.0.1:33306")
