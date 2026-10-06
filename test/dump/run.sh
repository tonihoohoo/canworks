#!/usr/bin/env bash
# canopen_check --dump-writes on a copy of an example config, compared with
# the checked-in list (ctest dump_writes_pingpong).
#
#   test/dump/run.sh <canopen_check> <config dir> <expected file> <work dir>

set -euo pipefail

CHECK=$1 SRC=$2 EXPECTED=$3 WORK=$4
rm -rf "$WORK"
mkdir -p "$WORK"
cp "$SRC"/* "$WORK"/
"$CHECK" --dump-writes "$WORK/canopen_config.json" > "$WORK/out.txt"
grep -E '^(write|step) ' "$WORK/out.txt" | diff -u "$EXPECTED" -
echo "dump-writes matches $EXPECTED"
