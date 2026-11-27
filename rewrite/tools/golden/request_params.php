<?php
// How PHP turns a query string into $_GET (parse_str uses the same rules).
require __DIR__ . '/common.php';

$query_strings = array(
    'action=report&datasource=localhost',
    'table_fields%5B%5D=checksum&table_fields%5B%5D=snippet&table_fields[]=fact.first_seen',
    'a=1&a=2',
    'a=1&a[]=2',
    'a[]=1&a=2',
    'a[x]=1&a[y]=2',
    'a[]=1&a[x]=2&a[]=3',
    'a[0]=x&a[1]=y',
    'a[1]=x&a[0]=y',
    'a[2]=x&a[]=y',
    'a[b][c]=1&a[b][d]=2',
    'a[b][]=1&a[b][]=2',
    'a[]=x&a[][]=y',
    'my.name=1&my name=2&+lead=3',
    'a.b[c.d]=1',
    'a[b=1',
    'a]b=1',
    'a[b]c=1',
    'a[b]c]=1',
    '=1&[x]=2',
    'empty=&noval&plus=a+b&pct=a%20b%2Bc',
    'k=%ED%95%9C%EA%B8%80',
    'fact-where=%28%0D%0Ahostname_max+%3D+%27h1%27%0D%0A%29&fact-limit=100',
    'x=1;y=2',
    'a[ b ]=1',
    'a[-1]=x&a[]=y',
    'a[07]=x&a[7]=y',
    'a[ 5]=x',
    '',
);

$cases = array();
foreach ($query_strings as $qs) {
    parse_str($qs, $out);
    $cases[] = array('input' => $qs, 'expected' => (object) $out);
}
emit_golden($cases);
