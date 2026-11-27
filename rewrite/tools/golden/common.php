<?php
// Shared helpers for the golden data generators. Not a generator itself
// (run.sh skips files starting with "common").

// Notices and warnings from the original code must not end up in the JSON on stdout.
error_reporting(E_ALL & ~E_NOTICE);
ini_set('display_errors', 'stderr');

function emit_golden(array $cases)
{
    print json_encode($cases, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    print "\n";
}
