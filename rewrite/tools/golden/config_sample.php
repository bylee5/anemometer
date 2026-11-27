<?php
// Records conf/sample.config.inc.php so the Python sample config can be checked
// against it. Closures are replaced by "<callable>" and their results are
// recorded separately. Timestamps computed with strtotime() are recorded as a
// day offset from now ("-7 day") because the real values depend on the clock.
require __DIR__ . '/common.php';
require 'lib/Helpers.php';

date_default_timezone_set('Asia/Seoul');
$now = time();
$conf = array();
require 'conf/sample.config.inc.php';

function describe($value, $now)
{
    if ($value instanceof Closure) {
        return '<callable>';
    }
    if (is_array($value)) {
        $out = array();
        foreach ($value as $k => $v) {
            $out[$k] = describe($v, $now);
        }
        return $out;
    }
    if (is_string($value) && preg_match('/^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/', $value)) {
        return sprintf('%+d day', round((strtotime($value) - $now) / 86400));
    }
    return $value;
}

$date_callback = $conf['reports']['slow_query_log']['callbacks']['table']['date'];
$checksum_callback = $conf['reports']['slow_query_log']['callbacks']['table']['checksum'];
$explain = $conf['plugins']['explain'];

$cases = array();
$cases[] = array('input' => 'conf', 'expected' => describe($conf, $now));
foreach (array('2024-03-29', '2024-03-30', '2024-03-31', '2024-04-01', '2024-03-30 23:59:59') as $d) {
    $cases[] = array('input' => array('callback' => 'date', 'value' => $d), 'expected' => $date_callback($d));
}
foreach (array('0', '255', '18446744073709551615') as $n) {
    $cases[] = array('input' => array('callback' => 'checksum', 'value' => $n), 'expected' => $checksum_callback($n));
}
$samples = array(
    array('hostname_max' => 'db1.example.com', 'db_max' => 'app'),
    array('hostname_max' => 'db1.example.com:3307', 'db_max' => ''),
    array('hostname_max' => 'db1', 'db_max' => 'app'),
    array('hostname_max' => '10.0.0.1:3306:x', 'db_max' => 'app'),
    array('db_max' => 'app'),
);
foreach ($samples as $s) {
    $cases[] = array('input' => array('callback' => 'explain', 'value' => $s), 'expected' => $explain($s));
}
emit_golden($cases);
