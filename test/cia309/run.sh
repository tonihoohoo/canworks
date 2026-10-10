#!/usr/bin/env bash
# The CiA 309-3 gateway end to end (canopen-cia309-gateway): the real plugin
# through canopen_host and canworks-bridge, both on a simulated bus (no CAN
# interface needed), with the Python client of the deploy tool over the
# loopback port and through canworks-diag gateway. See client_test.py.
#
#   test/cia309/run.sh [--build-dir build]

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build"

while [ $# -gt 0 ]; do
    case "$1" in
        --build-dir) BUILD="$(cd "$2" && pwd)"; shift ;;
        -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

for f in "$BUILD/plugins/libcanworks_plugin.so" "$BUILD/test/canopen_host" "$BUILD/bin/canworks-bridge"; do
    [ -f "$f" ] || { echo "missing $f; build the repo first" >&2; exit 2; }
done

export PYTHONPATH="$ROOT/tools/deploy${PYTHONPATH:+:$PYTHONPATH}"
export CANWORKS_EDSLINT="${CANWORKS_EDSLINT:-python3}"
exec python3 "$HERE/client_test.py" "$BUILD" "$ROOT"
