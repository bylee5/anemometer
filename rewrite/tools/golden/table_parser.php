<?php
require __DIR__ . '/common.php';
require 'lib/QueryTableParser.php';

$queries = array(
    'SELECT * FROM t',
    'select * from t1 join t2 using (id)',
    'SELECT a FROM db.t1 AS x JOIN `db`.`t2` y ON x.id = y.id LEFT JOIN t3 ON 1',
    'SELECT * FROM t1, t2, t3 WHERE t1.a = t2.a',
    'SELECT * FROM t1 ,t2 WHERE 1',
    'SELECT * FROM t1,t2,t3',
    'SELECT * FROM t1, t2 , t3',
    "SELECT *\n  FROM\tt1\n\n  JOIN   t2 ON 1",
    'UPDATE t SET a = 1 WHERE b = 2',
    'INSERT INTO t (a) VALUES (1)',
    'INSERT INTO t SELECT * FROM s',
    'DELETE FROM t WHERE 1',
    'SELECT * FROM t WHERE x IN (SELECT y FROM u)',
    'SELECT * FROM (SELECT 1) AS d',
    "SELECT 'from x' FROM t",
    'SELECT * FROM `my table`',
    'SELECT * FROM t1 JOIN t1 ON 1',
    'SELECT * FROM 한글테이블',
    'SELECT * FROM 123',
    ' SELECT * FROM leading_space',
    'SELECT * FROM trailing,',
    'SELECT * FROM a, b,',
    'SELECT * FROM',
    'SELECT 1',
    '',
    'FROM',
    'SELECT * FROM t1 STRAIGHT_JOIN t2',
    'SELECT * FROM t INTO OUTFILE "/tmp/x"',
    'SELECT * FROM `db`.`t`, `db`.`u`',
);

$cases = array();
foreach ($queries as $sql) {
    $parser = new QueryTableParser();
    // array_keys() turns numeric table names into integers; normalise to strings.
    $cases[] = array('input' => $sql, 'expected' => array_map('strval', $parser->parse($sql)));
}
emit_golden($cases);
