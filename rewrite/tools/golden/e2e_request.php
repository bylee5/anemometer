<?php
// Serves one request through the original index.php (run by e2e_runner.php).
// argv[1]: query string, argv[2]: url-encoded POST body.
ini_set('display_errors', 'stderr');
ini_set('session.save_path', '/tmp');
parse_str($argv[1], $_GET);
parse_str(isset($argv[2]) ? $argv[2] : '', $_POST);
$_SERVER['SCRIPT_NAME'] = '/index.php';
$_SERVER['REQUEST_METHOD'] = $_POST ? 'POST' : 'GET';
include '/app/index.php';
