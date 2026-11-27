<?php
require __DIR__ . '/common.php';
set_include_path(get_include_path() . PATH_SEPARATOR . 'lib');
require 'lib/QueryExplain.php';

/** Minimal stand-in for mysqli_result: only fetch_assoc() is used. */
class FakeResult
{
    private $rows;

    function __construct(array $rows)
    {
        $this->rows = $rows;
    }

    function fetch_assoc()
    {
        return array_shift($this->rows);
    }
}

$explain_row = array(
    'id' => '1', 'select_type' => 'SIMPLE', 'table' => 't', 'partitions' => null,
    'type' => 'ALL', 'possible_keys' => null, 'key' => null, 'key_len' => null,
    'ref' => null, 'rows' => '1000', 'filtered' => '10.00', 'Extra' => 'Using where',
);

$inputs = array(
    array(),
    array(array('a' => '1')),
    array($explain_row),
    array($explain_row, array_merge($explain_row, array('id' => '2', 'table' => 'a_much_longer_table_name', 'Extra' => null))),
    array(array('x' => ''), array('x' => 'longer value')),
    array(array('a' => '1', 'b' => '2'), array('a' => '3', 'c' => 'only in second row')),
    array(array('table' => '한글테이블', 'Extra' => 'Using index; 메모')),
    array(array('long_column_name' => 'v')),
);

$explainer = (new ReflectionClass('QueryExplain'))->newInstanceWithoutConstructor();
$cases = array();
foreach ($inputs as $rows) {
    $cases[] = array('input' => $rows, 'expected' => $explainer->result_as_table(new FakeResult($rows)));
}
emit_golden($cases);
