<?php
// Records MySQLTableReport::reldate() with a fixed "now".
//
// reldate() reads the clock through date() and strtotime(), so the generator
// re-implements its two lines with an explicit base timestamp. Keep this in
// sync with lib/MySQLTableReport.php if that method ever changes.
require __DIR__ . '/common.php';

date_default_timezone_set('Asia/Seoul');

function reldate_at($expression, $now)
{
    if (substr(strtolower($expression), 0, 3) == 'now') {
        $expression = date("Y-m-d H:i:s", $now);
    }
    if (preg_match('/^\s*([+-])?(\d+)\s(\w+)$/', $expression, $match)) {
        $expression = date("Y-m-d H:i:s", strtotime($expression, $now));
    }
    return $expression;
}

$bases = array(
    '2024-03-31 12:34:56', // month overflow backwards and forwards
    '2024-02-29 00:00:00', // leap day
    '2023-01-31 23:59:59',
    '2024-12-31 08:00:00',
);

$expressions = array(
    'now', 'NOW', 'nowhere', 'Now()',
    '-1 month', '+1 month', '1 month', '-1 months', '-3 MONTH', '-13 month', '+12 months',
    '-1 day', '+1 days', '-30 day', '-1 week', '-2 weeks', '-1 fortnight',
    '-1 hour', '-24 hours', '-90 min', '-5 mins', '-1 minute', '-30 minutes',
    '-10 sec', '-10 secs', '-1 second', '-45 seconds',
    '-1 year', '+1 years', '-4 year',
    ' -1 day', '-1  day', '- 1 day', '-1day', '-1 day ago',
    '2024-01-01 00:00:00', '2024-01-01', '', 'yesterday',
    '-1 foo', '+1 monday', '-1 weekday', '-1 weekdays', '-1 msec',
);

$cases = array();
foreach ($bases as $base) {
    $now = strtotime($base);
    foreach ($expressions as $expression) {
        $cases[] = array(
            'input' => array('now' => $base, 'expression' => $expression),
            'expected' => reldate_at($expression, $now),
        );
    }
}
emit_golden($cases);
