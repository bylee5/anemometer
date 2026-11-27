<?php
// Runs tools/golden/e2e_requests.json through the original application and
// prints the responses as golden data. Started by e2e.sh inside a container
// that shares the network of the test MySQL server.
require __DIR__ . '/common.php';

// index.php expects lib/, views/ and conf/config.inc.php in the working directory.
$work = '/tmp/anemometer';
@mkdir("$work/conf", 0777, true);
@symlink('/app/lib', "$work/lib");
@symlink('/app/views', "$work/views");
file_put_contents("$work/conf/config.inc.php", <<<'PHP'
<?php
require '/app/conf/sample.config.inc.php';
$conf['datasources'] = array('test' => array(
    'host' => '127.0.0.1', 'port' => 3306, 'db' => 'anemometer_e2e', 'user' => 'root', 'password' => 'test',
    'tables' => array('global_query_review' => 'fact', 'global_query_review_history' => 'dimension'),
    'source_type' => 'slow_query_log',
));
$conf['plugins'] = array(
    'show_create' => true,
    'show_status' => false,
    'explain' => function ($sample) {
        return array('host' => '127.0.0.1', 'port' => 3306, 'db' => 'anemometer_e2e', 'user' => 'root', 'password' => 'test');
    },
);
// checksums are CHAR(32) hex in this schema; the site config shows them as they are
$conf['reports']['slow_query_log']['callbacks']['table']['checksum'] = function ($x) { return array($x); };
PHP
);

$requests = json_decode(file_get_contents(__DIR__ . '/e2e_requests.json'), true);
$golden = array();
foreach ($requests as $request) {
    $command = sprintf(
        'cd %s && php %s %s %s 2>/dev/null',
        escapeshellarg($work),
        escapeshellarg(__DIR__ . '/e2e_request.php'),
        escapeshellarg($request['query']),
        escapeshellarg(isset($request['post']) ? $request['post'] : '')
    );
    $golden[] = array('input' => $request, 'expected' => shell_exec($command));
}
emit_golden($golden);
