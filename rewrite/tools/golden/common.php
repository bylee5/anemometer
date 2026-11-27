<?php
// Shared helpers for the golden data generators. Not a generator itself
// (run.sh skips files starting with "common").

error_reporting(E_ALL & ~E_NOTICE);

function emit_golden(array $cases)
{
    print json_encode($cases, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    print "\n";
}
