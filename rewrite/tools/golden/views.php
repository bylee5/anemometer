<?php
// Renders every view in views/ with fixed data through the original Loader.
// Callables (table callbacks) and the mysqli result used by samples.php can't
// travel through JSON, so cases name them and both sides construct them.
require __DIR__ . '/common.php';
require 'lib/Helpers.php';
require 'lib/Loader.php';

date_default_timezone_set('Asia/Seoul');
$_SERVER['SCRIPT_NAME'] = '/anemometer/index.php';

class FakeResult
{
    private $rows;
    public $num_rows;

    function __construct(array $rows)
    {
        $this->rows = $rows;
        $this->num_rows = count($rows);
    }

    function fetch_assoc()
    {
        return array_shift($this->rows);
    }
}

$callback_sets = array(
    'sample' => array(
        'date' => function ($x) { $type = ''; if (date('N', strtotime($x)) >= 6) { $type = 'weekend'; } return array($x, $type); },
        'checksum' => function ($x) { return array(dec2hex($x), ''); },
    ),
    'site' => array(
        'date' => function ($x) { $type = ''; if (date('N', strtotime($x)) >= 6) { $type = 'weekend'; } return array($x, $type); },
        'checksum' => function ($x) { return array($x); },
    ),
);

$tables = array(
    'global_query_review' => array('checksum', 'fingerprint', 'sample', 'first_seen', 'last_seen', 'reviewed_by'),
    'global_query_review_history' => array('hostname_max', 'checksum', 'sample', 'ts_min', 'ts_cnt', 'Query_time_sum'),
);
$custom_fields = array('checksum', 'date', 'snippet', 'index_ratio', 'query_time_avg');
$hosts = array('db1.example.com', 'db2.example.com', '');
$names = array(
    'hostname_field_name' => 'hostname_max', 'checksum_field_name' => 'checksum',
    'time_field_name' => 'ts_min', 'sample_field_name' => 'sample',
);
$query_row = array(
    'checksum' => '0123456789ABCDEF0123456789ABCDEF', 'fingerprint' => 'select * from t where id = ?',
    'sample' => 'select * from t where id = 1', 'first_seen' => '2024-03-01 00:00:00',
    'last_seen' => '2024-03-31 10:00:00', 'reviewed_by' => 'dba1', 'reviewed_on' => '2024-03-31 11:00:00',
    'reviewed_status' => 'needs-fix', 'comments' => "line 1\nline <2>",
);
$sample_row = array(
    'hostname_max' => 'db1.example.com', 'ts_min' => '2024-03-31 10:00:00', 'ts_max' => '2024-03-31 10:05:00',
    'sample' => 'select * from t where id = 1', 'checksum' => '0123456789ABCDEF0123456789ABCDEF',
);
$show_query_common = array_merge($names, array(
    'datasource' => 'localhost', 'checksum' => '0123456789ABCDEF0123456789ABCDEF', 'row' => $query_row,
    'sample' => $sample_row, 'review_types' => array('good', 'needs-fix'), 'reviewers' => array('dba1', 'dba2'),
    'show_samples' => true, 'tables' => array_keys($tables), 'hosts' => $hosts, 'table_fields' => $tables,
    'custom_fields' => $custom_fields, 'ajax_request_url' => '/anemometer/index.php?action=api&output=json2&x=1',
    'timezone_offset' => 32400, 'fingerprint_field_name' => 'fingerprint', 'source_type' => 'slow_query_log',
));
$graph_common = array_merge($names, array(
    'datasource' => 'localhost', 'tables' => array_keys($tables), 'hosts' => $hosts, 'table_fields' => $tables,
    'custom_fields' => $custom_fields, 'ajax_request_url' => '/anemometer/index.php?action=api&output=json2',
    'graph_permalink' => '/anemometer/index.php?action=graph_search&plot_field=Query_time_sum',
    'show_query_base_url' => '/anemometer/index.php?action=show_query&datasource=localhost',
    'ajax_table_request_url_base' => '/anemometer/index.php?action=api&output=table&noheader=1',
    'table_url_time_start_param' => 'dimension-ts_min_start', 'table_url_time_end_param' => 'dimension-ts_min_end',
    'timezone_offset' => 32400,
));
$report_form = array_merge($names, array(
    'datasource' => 'localhost', 'tables' => array_keys($tables), 'hosts' => $hosts, 'table_fields' => $tables,
    'table_aliases' => array('global_query_review' => 'fact', 'global_query_review_history' => 'dimension'),
    'custom_fields' => $custom_fields,
    'table_fields_selected' => array('checksum', 'snippet', 'dimension.hostname_max', 'ts_cnt', 'sample'),
    'exception_select_fields' => array('checksum', 'sample', 'DIGEST'),
    'review_types' => array('good', 'needs-fix'), 'reviewers' => array('dba1', 'dba2'),
));
$report_get = array(
    'dimension-ts_min_start' => '-1 day', 'dimension-ts_min_end' => 'now', 'fact-first_seen' => '',
    'dimension-hostname_max' => 'db2.example.com', 'fact-group' => 'checksum', 'fact-order' => 'Query_time_sum DESC',
    'fact-having' => '', 'fact-limit' => '20', 'fact-where' => "db_max = 'app'", 'fact-sample' => 'select',
    'fact-reviewed_status' => 'needs-fix', 'fact-checksum' => '',
);
$results = array(
    array('checksum' => 'AAA', 'date' => '2024-03-30', 'ts_cnt' => '10'),
    array('checksum' => 'BBB', 'date' => '2024-04-01', 'ts_cnt' => null),
);
$samples = array();
for ($i = 0; $i < 21; $i++) {
    $samples[] = array_merge($sample_row, array('ts_max' => sprintf('2024-03-31 10:%02d:00', 59 - $i), 'sample' => "select $i"));
}

$cases = array(
    array('view' => 'footer'),
    array('view' => 'header'),
    array('view' => 'nav_sub'),
    array('view' => 'noconfig'),
    array('view' => 'navbar', 'data' => array('datasources' => array('localhost', 'other'), 'datasource' => 'localhost', 'source_type' => 'slow_query_log')),
    array('view' => 'navbar', 'data' => array('datasources' => array('ps'), 'datasource' => 'ps', 'source_type' => 'performance_schema')),
    array('view' => 'navbar', 'data' => array('datasources' => null, 'datasource' => null, 'source_type' => null)),
    array('view' => 'index', 'data' => array('datasources' => array('a', 'b'), 'datasource' => 'b')),
    array('view' => 'report', 'data' => $report_form, 'get' => $report_get),
    array('view' => 'report', 'data' => array_merge($report_form, array('table_fields_selected' => null)), 'get' => array()),
    array('view' => 'report-performance_schema', 'data' => array_merge($report_form, array(
        'table_fields' => array('events_statements_summary_by_digest' => array('DIGEST', 'COUNT_STAR')),
        'table_fields_selected' => array('DIGEST', 'snippet'))),
        'get' => array('fact-DIGEST' => 'abc', 'fact-DIGEST_TEXT' => 'select', 'fact-group' => 'DIGEST')),
    array('view' => 'report_result', 'data' => array('datasource' => 'localhost', 'columns' => array('checksum', 'date', 'ts_cnt'),
        'result' => $results, 'sql' => "SELECT 1\n FROM t", 'permalink' => '/p?x=1', 'jsonlink' => '/j?x=1', 'callbacks' => 'site')),
    array('view' => 'report_result', 'data' => array('datasource' => 'localhost', 'columns' => array('checksum', 'date', 'ts_cnt'),
        'result' => array(array('checksum' => '255', 'date' => '2024-03-31', 'ts_cnt' => '1')), 'sql' => 'SELECT 1',
        'permalink' => '/p', 'jsonlink' => '/j', 'callbacks' => 'sample')),
    array('view' => 'report_result', 'data' => array('datasource' => 'ps', 'columns' => array('DIGEST', 'COUNT_STAR'),
        'result' => array(array('DIGEST' => 'abc', 'COUNT_STAR' => '3')), 'sql' => 'SELECT 1', 'permalink' => '/p', 'jsonlink' => '/j')),
    array('view' => 'report_result', 'data' => array('datasource' => 'x', 'columns' => array(), 'result' => array(), 'sql' => null, 'permalink' => '', 'jsonlink' => '')),
    array('view' => 'samples', 'data' => array('datasource' => 'localhost', 'checksum' => 'AAA', 'start' => 0, 'rpp' => '20', 'samples' => $samples, 'num_rows' => 21)),
    array('view' => 'samples', 'data' => array('datasource' => 'localhost', 'checksum' => 'AAA', 'start' => 20, 'rpp' => '20', 'samples' => array_slice($samples, 0, 3), 'num_rows' => 3)),
    array('view' => 'samples', 'data' => array('datasource' => 'localhost', 'checksum' => 'AAA', 'start' => 0, 'rpp' => null, 'samples' => array_slice($samples, 0, 1), 'num_rows' => 1)),
    array('view' => 'show_query', 'data' => array_merge($show_query_common, array(
        'explain_plan_error' => 'Missing field host', 'create_table' => 'CREATE TABLE t (id int)', 'table_status' => '', 'query_advisor' => null,
        'current_auth_user' => 'dba2', 'dimension_pivot_hostname_max' => 'Query_time_sum')),
        'get' => array('dimension-ts_min_start' => '2024-03-01 00:00:00', 'plot_field' => 'ts_cnt', 'dimension-hostname_max' => 'db1.example.com', 'show_form' => '1')),
    array('view' => 'show_query', 'data' => array_merge($show_query_common, array(
        'row' => array_merge($query_row, array('reviewed_by' => null, 'reviewed_status' => null, 'comments' => null)),
        'show_samples' => false, 'explain_plan' => "+---+\n| a |\n+---+\n", 'visual_explain' => 'tree', 'query_advisor' => 'advice',
        'table_status' => '       Name : t')),
        'get' => array('show_form' => '0')),
    array('view' => 'show_query_perf_schema', 'data' => array_merge($show_query_common, array(
        'row' => array('DIGEST' => 'abc', 'FIRST_SEEN' => '2024-01-01', 'last_seen' => '2024-02-02', 'DIGEST_TEXT' => 'SELECT ?'),
        'fingerprint_field_name' => 'DIGEST_TEXT', 'source_type' => 'performance_schema', 'create_table' => 'CREATE TABLE x', 'table_status' => 'status')),
        'get' => array()),
    array('view' => 'show_query_perf_schema', 'data' => array_merge($show_query_common, array(
        'row' => array('first_seen' => '2024-01-01', 'LAST_SEEN' => '2024-02-02', 'fingerprint' => 'SELECT ?'),
        'source_type' => 'performance_schema_history')), 'get' => array('show_form' => '1')),
    array('view' => 'graph_search', 'data' => array_merge($graph_common, array('dimension_pivot_hostname_max' => 'Query_time_sum')),
        'get' => array('dimension-ts_min_start' => '2024-03-24 10:00:00', 'dimension-ts_min_end' => '2024-03-31 10:00:00',
            'plot_field' => 'Query_time_sum', 'dimension-hostname_max' => 'db2.example.com', 'fact-checksum' => 'AAA')),
    array('view' => 'graph_search', 'data' => array_merge($graph_common, array('dimension_pivot_checksum' => 'Query_time_sum')), 'get' => array()),
    array('view' => 'graph_search-performance_schema_history', 'data' => array_merge($graph_common, array('hostname_max' => 'db1.example.com')),
        'get' => array('dimension-ts_min_start' => '2024-03-24 10:00:00', 'plot_field' => 'SUM_TIMER_WAIT')),

    // JSON / debug outputs of the report API (compared byte for byte)
    array('view' => 'report_json', 'data' => array('columns' => array('checksum', 'sample'),
        'result' => array(array('checksum' => 'A/B', 'sample' => "select '한글' <x>\n\t\"q\""), array('checksum' => 'C', 'sample' => null)))),
    array('view' => 'report_json', 'data' => array('columns' => array(), 'result' => array())),
    array('view' => 'report_printr', 'data' => array('columns' => array('a', 'b'),
        'result' => array(array('a' => '1', 'b' => null), array('a' => '2', 'b' => 'x')))),
    array('view' => 'report_json2', 'data' => array('columns' => array('minute_ts', 'Query_time_sum', 'db1.example.com'),
        'result' => array(array('minute_ts' => '1711843200', 'Query_time_sum' => '1.5', 'db1.example.com' => '0'),
                          array('minute_ts' => '1711843260', 'Query_time_sum' => '2', 'db1.example.com' => null))),
        'get' => array('fact-group' => 'minute_ts')),
    array('view' => 'report_json2', 'data' => array('columns' => array('date', 'ts_cnt', '255', '00042', '1.5', 'ABC123'),
        'result' => array(array('date' => '2024-03-31 10:00:00', 'ts_cnt' => '3', '255' => '1', '00042' => '2', '1.5' => '0', 'ABC123' => '4'),
                          array('date' => '2024-03-31', 'ts_cnt' => '4', '255' => '0', '00042' => '0', '1.5' => '0', 'ABC123' => '1'))),
        'get' => array('fact-group' => 'date', 'debug' => '1'), 'sql' => 'SELECT 1'),
    array('view' => 'report_json2', 'data' => array('columns' => array('minute_ts', 'x'), 'result' => array()),
        'get' => array('fact-group' => 'minute_ts')),
    array('view' => 'report_json2', 'data' => array('columns' => array('minute_ts'), 'result' => array()),
        'get' => array('fact-group' => 'minute_ts')),
);

$loader = new Loader();
$golden = array();
foreach ($cases as $case) {
    $data = isset($case['data']) ? $case['data'] : array();
    $_GET = isset($case['get']) ? $case['get'] : array();
    $_POST = array();
    if (isset($data['callbacks'])) {
        $data['callbacks'] = $callback_sets[$data['callbacks']];
    }
    if ($case['view'] == 'samples') {
        $data['samples'] = new FakeResult($data['samples']);
    }
    if (isset($case['sql'])) {
        $data['sql'] = $case['sql'];
    }
    ob_start();
    $loader->view($case['view'], $data);
    $golden[] = array('input' => $case, 'expected' => ob_get_clean());
}
emit_golden($golden);
