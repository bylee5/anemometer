<?php
require __DIR__ . '/common.php';
require 'lib/QueryRewrite.php';

$queries = array(
    // cases from lib/TestQueryRewrite.php
    'SELECT 123',
    '/* 123 * 456 */ SELECT 123 #214241*/',
    "\t\t    SELECT       \t\t\t   123\t\t\t    \t\t\t\n",
    "/* Script : /home/site/XXXXXXXXXX.php Utilisateur : prod_outils */ SELECT SQL_SMALL_RESULT DISTINCT ID_CLIENT\nFROM DB.CLIENT CL\nWHERE CL.TELEPHONE = '0000000000'\nLIMIT 1\n",
    "SELECT id FROM ips WHERE ip='192.168.0.1' AND type=1 LIMIT 1",
    "INSERT INTO tbl_old(\nSELECT * \nFROM tbl\nWHERE id =123 )",
    'DELETE FROM table WHERE id = 123',
    'INSERT INTO table (col1, col2, col3) VALUES (1, 2, 3), (4, 5, 6)',
    'INSERT INTO table SELECT * FROM table2',
    'INSERT INTO table (SELECT * FROM table2)',
    'UPDATE table SET col1 = 123 WHERE id = 456',
    'ALTER TABLE MODIFY col1 INT NOT NULL DEFAULT 0',
    'DROP TABLE table',
    'CREATE TABLE table (id INT)',
    'DELETE table1 FROM table1 JOIN table2 ON table1.id = table2.id WHERE table1.col1 = 123 AND table2.col2 = 456 ',
    '(SELECT 123) UNION (SELECT 456)',

    // additional edge cases
    'select lower_case from t',
    'UPDATE t SET a = 1',
    "UPDATE t SET a = 1\nWHERE b = 2\r\n",
    'insert into t (select * from s)',
    'insert into t select * from s',
    'INSERT INTO `db`.`t` SELECT 1',
    'DELETE `db`.`t1` FROM t1 WHERE 1',
    "SELECT 1 -- trailing comment",
    "SELECT 1 # hash\nFROM dual",
    "SELECT 1\n-- not last line\nFROM dual",
    "SELECT /* inline */ a, /* two */ b FROM t",
    "SELECT * FROM 한글테이블 WHERE 이름 = '값'",
    "SHOW TABLES",
    "",
    "   ",
    "SELECT\x0b1\x00",
    "REPLACE INTO t VALUES (1)",
    "SELECT a FROM t WHERE x IN (SELECT y FROM u UNION SELECT z FROM v)",
    "WITH cte AS (SELECT 1) SELECT * FROM cte UNION SELECT 2",
);

$cases = array();
foreach ($queries as $sql) {
    $q = new QueryRewrite($sql);
    $cases[] = array(
        'input' => $sql,
        'expected' => array(
            'normalized' => $q->sql,
            'type' => $q->getType(),
            'select' => $q->toSelect(),
            'explain' => $q->asExplain(),
            'extended_explain' => $q->asExtendedExplain(),
        ),
    );
}
$cases[] = array(
    'input' => null,
    'expected' => array(
        'normalized' => null,
        'type' => (new QueryRewrite(null))->getType(),
        'select' => (new QueryRewrite(null))->toSelect(),
        'explain' => (new QueryRewrite(null))->asExplain(),
        'extended_explain' => (new QueryRewrite(null))->asExtendedExplain(),
    ),
);
emit_golden($cases);
