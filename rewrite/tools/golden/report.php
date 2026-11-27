<?php
// Records what MySQLTableReport builds (SQL, column names, search URIs) for a
// range of request parameters. No database is needed: the report object is
// created without a datasource, which skips the connection.
require __DIR__ . '/common.php';
require 'lib/Helpers.php';
require 'lib/MySQLTableReport.php';

date_default_timezone_set('Asia/Seoul');
$conf = array();
require 'conf/sample.config.inc.php';

$reports = $conf['reports'];
// The site's production config differs from the sample in a few report settings.
$reports['slow_query_log_site'] = $reports['slow_query_log'];
$reports['slow_query_log_site']['join']['dimension'] = 'USE INDEX (idx_ts_min_01) USING (`checksum`)';
$reports['slow_query_log_site']['custom_fields']['snippet'] = 'LEFT(dimension.sample,100)';
$reports['slow_query_log_site']['custom_fields']['rows_examined_avg'] = 'ROUND(SUM(Rows_examined_sum)/SUM(ts_cnt),0)';
$reports['slow_query_log_site']['custom_fields']['rows_examined/sent_avg'] = 'ROUND(SUM(Rows_examined_sum)/SUM(Rows_sent_sum)/SUM(ts_cnt),0)';

$slow_tables = array('global_query_review' => 'fact', 'global_query_review_history' => 'dimension');
$ps_tables = array('events_statements_summary_by_digest' => 'fact');
$psh_tables = array('events_statements' => 'fact', 'events_statements_history' => 'dimension');

function qs($query_string)
{
    parse_str($query_string, $out);
    return $out;
}

$default_fields = array('checksum', 'snippet', 'index_ratio', 'query_time_avg', 'rows_sent_avg', 'ts_cnt', 'Query_time_sum', 'Lock_time_sum', 'Rows_sent_sum', 'Rows_examined_sum', 'Tmp_table_sum', 'Filesort_sum', 'Full_scan_sum');
$report_defaults = array(
    'fact-group' => 'checksum',
    'fact-order' => 'Query_time_sum DESC',
    'fact-limit' => '20',
    'dimension-ts_min_start' => '2024-03-30 10:00:00',
    'dimension-ts_min_end' => '2024-03-31 10:00:00',
    'table_fields' => $default_fields,
    'dimension-pivot-hostname_max' => null,
);
$hosts = array('db1.example.com', 'db2.example.com', "o'neil\\host", null, '');

// views/nav_sub.php favourites
$nav = array(
    'action=report&datasource=localhost&dimension-ts_min_start=-1+month&dimension-ts_min_end=now&fact-first_seen=&table_fields%5B%5D=checksum&table_fields%5B%5D=snippet&table_fields%5B%5D=query_time_avg&table_fields%5B%5D=fact.first_seen&table_fields%5B%5D=fact.last_seen&table_fields%5B%5D=fact.reviewed_by&table_fields%5B%5D=fact.reviewed_on&table_fields%5B%5D=fact.reviewed_status&table_fields%5B%5D=dimension.hostname_max&table_fields%5B%5D=dimension.db_max&table_fields%5B%5D=dimension.user_max&table_fields%5B%5D=dimension.ip_max&table_fields%5B%5D=dimension.ts_cnt&table_fields%5B%5D=dimension.Query_time_sum&table_fields%5B%5D=dimension.Rows_examined_max&dimension-hostname_max=&fact-group=checksum&fact-order=ts_cnt+DESC%2C+query_time_avg+DESC%2C+Rows_examined_max+DESC&fact-having=last_seen+%3E%3D+DATE_SUB%28DATE_FORMAT%28NOW%28%29%2C+%27%25Y-%25m-%25d+00%3A00%3A00%27%29%2C+INTERVAL+1+MONTH%29&fact-limit=100&submit=Search&fact-where=%28%0D%0Ahostname_max+%3D+%27%ED%98%B8%EC%8A%A4%ED%8A%B8%EB%84%A4%EC%9E%841%27%0D%0Aor+hostname_max+%3D+%27%ED%98%B8%EC%8A%A4%ED%8A%B8%EB%84%A4%EC%9E%842%27%0D%0A%29%0D%0Aand+user_max+not+in%28%0D%0A%27dba%27%0D%0A%29&fact-sample=&fact-reviewed_status=&fact-checksum=',
    'action=report&datasource=localhost&dimension-ts_min_start=-1+month&dimension-ts_min_end=now&fact-first_seen=&table_fields%5B%5D=checksum&table_fields%5B%5D=snippet&table_fields%5B%5D=index_ratio&table_fields%5B%5D=query_time_avg&table_fields%5B%5D=dimension.ts_cnt&table_fields%5B%5D=dimension.Query_time_sum&table_fields%5B%5D=rows_examined_avg&table_fields%5B%5D=rows_sent_avg&table_fields%5B%5D=rows_examined%2Fsent_avg&table_fields%5B%5D=fact.first_seen&table_fields%5B%5D=fact.last_seen&table_fields%5B%5D=dimension.hostname_max&table_fields%5B%5D=dimension.db_max&table_fields%5B%5D=dimension.user_max&table_fields%5B%5D=dimension.ip_max&table_fields%5B%5D=fact.reviewed_by&table_fields%5B%5D=fact.reviewed_on&table_fields%5B%5D=fact.reviewed_status&dimension-hostname_max=&fact-group=checksum&fact-order=%60rows_examined%2Fsent_avg%60+DESC%2C+ts_cnt+DESC%2C+query_time_avg+DESC%2C+Rows_examined_max+DESC&fact-having=last_seen+%3E%3D+DATE_SUB%28DATE_FORMAT%28NOW%28%29%2C+%27%25Y-%25m-%25d+00%3A00%3A00%27%29%2C+INTERVAL+3+MONTH%29+and+%28%60rows_examined%2Fsent_avg%60+%3E+10+or+%60rows_examined%2Fsent_avg%60+is+null+or+query_time_avg+%3E+10++or+ts_cnt+%3E+1000%29&fact-limit=500&submit=Search&fact-where=hostname_max+in+%28%0D%0A%27db1.example.com%27%0D%0A%29&fact-sample=&fact-reviewed_status=&fact-checksum=',
);

$cases = array(
    'report defaults' => array('report' => 'slow_query_log', 'tables' => $slow_tables, 'get' => $report_defaults),
    'nav favourite 1' => array('report' => 'slow_query_log_site', 'tables' => $slow_tables, 'get' => qs($nav[0])),
    'nav favourite 2' => array('report' => 'slow_query_log_site', 'tables' => $slow_tables, 'get' => qs($nav[1])),
    'nav favourite 2 sample report' => array('report' => 'slow_query_log', 'tables' => $slow_tables, 'get' => qs($nav[1])),
    'history defaults' => array('report' => 'slow_query_log', 'tables' => $slow_tables, 'get' => array(
        'output' => 'table', 'fact-group' => 'date', 'fact-order' => 'date DESC', 'fact-limit' => '90',
        'fact-checksum' => '0123456789ABCDEF0123456789ABCDEF',
        'table_fields' => array('date', 'index_ratio', 'query_time_avg', 'rows_sent_avg', 'ts_cnt', 'Query_time_sum', 'Lock_time_sum', 'Rows_sent_sum', 'Rows_examined_sum', 'Tmp_table_sum', 'Filesort_sum', 'Full_scan_sum'),
    )),
    'graph with host pivot' => array('report' => 'slow_query_log', 'tables' => $slow_tables,
        'get' => array('fact-group' => 'minute_ts', 'fact-order' => 'minute_ts', 'fact-limit' => '',
            'dimension-ts_min_start' => '2024-03-24 10:00:00', 'dimension-ts_min_end' => '2024-03-31 10:00:00',
            'table_fields' => array('minute_ts', 'Query_time_sum'), 'plot_field' => 'Query_time_sum',
            'dimension-pivot-hostname_max' => 'Query_time_sum'),
        'pivot' => array('dimension-pivot-hostname_max' => $hosts),
        'uri_exceptions' => array('dimension-ts_min')),
    'checksum pivot on custom field' => array('report' => 'slow_query_log', 'tables' => $slow_tables,
        'get' => array('fact-group' => 'hour_ts', 'table_fields' => array('hour_ts'),
            'dimension-pivot-checksum' => 'query_time_avg', 'fact-checksum' => ''),
        'pivot' => array('dimension-pivot-checksum' => array('AAA', 'B$1\\2', null))),
    'custom pivot without aggregate' => array('report' => 'slow_query_log', 'tables' => $slow_tables,
        'get' => array('table_fields' => array('hour'), 'dimension-pivot-hostname_max' => 'snippet'),
        'pivot' => array('dimension-pivot-hostname_max' => array('h1'))),
    'pivot without values' => array('report' => 'slow_query_log', 'tables' => $slow_tables,
        'get' => array('table_fields' => array('hour'), 'dimension-pivot-hostname_max' => 'ts_cnt')),
    'filters' => array('report' => 'slow_query_log', 'tables' => $slow_tables, 'get' => array(
        'table_fields' => array('checksum', 'fact.sample', 'dimension.hostname_max', 'ts_min', 'Query_time_pct_95', 'Query_time_median', 'Query_time_stddev', 'Rows_sent_min', 'COUNT_STAR', 'LAST_SEEN_x', 'FIRST_y_z', 'nounderscore', 'a.b.c', 'checksum'),
        'fact-sample' => 'SELECT ~ "x" & y', 'fact-first_seen' => '2024-01-01', 'fact-checksum' => '0',
        'fact-reviewed_status' => 'needs-fix', 'dimension-hostname_max' => '한글.example.com',
        'dimension-extra_fields' => '', 'fact-where' => 'db_max = "app"', 'fact-having' => 'ts_cnt > 1',
        'fact-limit' => '0', 'fact-order' => '', 'fact-group' => 'checksum',
    ), 'uri_exceptions' => array('fact-sample', 'dimension-ts_min')),
    'blank and array values' => array('report' => 'slow_query_log', 'tables' => $slow_tables, 'get' => array(
        'table_fields' => array('checksum'), 'dimension-hostname_max' => array('a', 'b'),
        'fact-reviewed_status' => '', 'dimension-ts_min_start' => '', 'dimension-ts_min_end' => 'yesterday',
        'fact-where' => '0',
    )),
    'relative dates' => array('report' => 'slow_query_log', 'tables' => $slow_tables, 'get' => array(
        'table_fields' => array('checksum'), 'dimension-ts_min_start' => '-1 month',
        'dimension-ts_min_end' => 'now', 'fact-first_seen' => '-7 day',
    )),
    'non aggregate columns' => array('report' => 'slow_query_log', 'tables' => $slow_tables,
        'get' => array('table_fields' => array('dimension.ts_min', 'ts_max', 'Query_time_sum')),
        'non_aggregate' => array('ts_min', 'ts_max')),
    'no fields selected' => array('report' => 'slow_query_log', 'tables' => $slow_tables, 'get' => array('fact-group' => 'checksum')),
    'empty field list' => array('report' => 'slow_query_log', 'tables' => $slow_tables, 'get' => array('table_fields' => array())),
    'post overrides get' => array('report' => 'slow_query_log', 'tables' => $slow_tables,
        'get' => array('table_fields' => array('checksum'), 'fact-limit' => '10'),
        'post' => array('fact-limit' => '5', 'fact-reviewed_status' => 'good')),
    'performance schema' => array('report' => 'performance_schema', 'tables' => $ps_tables, 'get' => array(
        'fact-order' => 'SUM_TIMER_WAIT DESC', 'fact-limit' => '20', 'fact-group' => 'DIGEST',
        'table_fields' => array('DIGEST', 'snippet', 'index_ratio', 'COUNT_STAR', 'SUM_TIMER_WAIT', 'SUM_LOCK_TIME', 'SUM_ROWS_AFFECTED', 'SUM_ROWS_SENT', 'SUM_ROWS_EXAMINED', 'SUM_CREATED_TMP_TABLES', 'SUM_SORT_SCAN', 'SUM_NO_INDEX_USED'),
        'fact-first_seen_start' => '2024-03-01 00:00:00', 'fact-DIGEST_TEXT' => 'select',
    )),
    'performance schema history graph' => array('report' => 'performance_schema_history', 'tables' => $psh_tables,
        'get' => array('fact-group' => 'minute_ts', 'fact-order' => 'minute_ts', 'fact-limit' => '',
            'dimension-FIRST_SEEN_start' => '2024-03-24 10:00:00', 'dimension-FIRST_SEEN_end' => '2024-03-31 10:00:00',
            'table_fields' => array('minute_ts', 'SUM_TIMER_WAIT'), 'plot_field' => 'SUM_TIMER_WAIT',
            'dimension-pivot-hostname' => 'SUM_TIMER_WAIT'),
        'pivot' => array('dimension-pivot-hostname' => array('h1', 'h2')),
        'uri_exceptions' => array('dimension-FIRST_SEEN')),
    'unknown join alias' => array('report' => 'performance_schema', 'tables' => $psh_tables,
        'get' => array('table_fields' => array('DIGEST'))),
);

function run_case(array $c, array $reports)
{
    $_GET = $c['get'];
    $_POST = isset($c['post']) ? $c['post'] : array();
    $out = array();
    try {
        $report = new MySQLTableReport(null, $c['tables'], $reports[$c['report']]);
        if (isset($c['non_aggregate'])) {
            $report->set_non_aggregate_columns($c['non_aggregate']);
        }
        if (isset($c['pivot'])) {
            foreach ($c['pivot'] as $name => $values) {
                $report->set_pivot_values($name, $values);
            }
        }
        $out['form_fields'] = $report->get_form_fields();
        $out['custom_fields'] = $report->get_custom_fields();
        $out['sql'] = $report->query();
        $out['columns'] = $report->get_column_names();
        $out['search_uri'] = $report->get_search_uri();
        $exceptions = isset($c['uri_exceptions']) ? $c['uri_exceptions'] : array('dimension-ts_min');
        $out['search_uri_except'] = $report->get_search_uri($exceptions);
    } catch (Exception $e) {
        $out['error'] = $e->getMessage();
    }
    return $out;
}

$golden = array();
foreach ($cases as $name => $c) {
    // reldate() reads the clock; retry until a case runs within one second.
    do {
        $now = time();
        $out = run_case($c, $reports);
    } while (time() != $now);
    $c['name'] = $name;
    $c['now'] = date('Y-m-d H:i:s', $now);
    $golden[] = array('input' => $c, 'expected' => $out);
}
emit_golden($golden);
