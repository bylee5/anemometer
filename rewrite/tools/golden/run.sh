#!/usr/bin/env bash
# Regenerate rewrite/tests/golden/*.json by running the original PHP code in Docker.
#
# Each rewrite/tools/golden/<name>.php script runs a fixed set of inputs through
# the PHP implementation (lib/ at the repository root) and prints a JSON list of
# {"input": ..., "expected": ...}. The Python test suite replays the same inputs
# and compares the results.
#
# Usage: rewrite/tools/golden/run.sh [name ...]
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
# Docker Desktop on Windows needs a native path (D:/...) for bind mounts.
mount="$(cd "$repo" && (pwd -W 2>/dev/null || pwd))"
image="${PHP_IMAGE:-php:7.4-cli}"
out="$here/../../tests/golden"

if [ "$#" -eq 0 ]; then
    set -- $(cd "$here" && ls *.php | grep -v '^common' | sed 's/\.php$//')
fi

mkdir -p "$out"
for name in "$@"; do
    echo "generating rewrite/tests/golden/$name.json"
    MSYS_NO_PATHCONV=1 docker run --rm -v "$mount:/app:ro" -w /app "$image" \
        php "rewrite/tools/golden/$name.php" > "$out/$name.json"
done
