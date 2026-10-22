#!/usr/bin/env bash
# ST tests of OpenPLC through Modbus with STruC++ (the editor's compiler,
# fetched by scripts/fetch-strucpp.sh) and the packaged canworks library
# (library/build.sh):
#   - the blocks over the bridge (library/modbus) against a model of the
#     bridge's control block and SDO registers (bridge_model.st);
#   - the generated canworks_in and canworks_out for canworks.json here
#     (make_programs.py): conversions both ways, canworks.ok, the header;
#   - the whole generated project (list, programs, configuration with the
#     three instances in one task) compiles.
#
#   test/plc_modbus/run.sh [--strucpp PATH]
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
STRUCPP=""
while [ $# -gt 0 ]; do
    case "$1" in
        --strucpp) STRUCPP="$2"; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done
[ -n "$STRUCPP" ] || STRUCPP="$("$REPO/scripts/fetch-strucpp.sh")"
PYTHON="${PYTHON:-python3}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
"$PYTHON" "$HERE/make_programs.py" "$WORK"
LIBRARY=(-L "$REPO/tools/deploy/canworks/library")

status=0
check() {
    local name="$1" log="$WORK/$1.log"
    shift
    echo "== $name"
    if "$STRUCPP" "$@" >"$log" 2>&1; then
        grep -E '\[(PASS|FAIL)\]|tests?, |Compilation successful' "$log" || true
        if grep -q '\[FAIL\]' "$log"; then
            grep -E 'failed:' "$log"
            status=1
        fi
    else
        grep -vE 'c\+\+17|inline CONSTANTS|^\s*\||\^~|In file included|not debuggable' "$log" | tail -40
        status=1
    fi
}
check blocks "$HERE/bridge_model.st" "${LIBRARY[@]}" -o "$WORK/blocks.cpp" --test "$HERE/test_blocks.st"
check programs "$WORK/programs.st" "${LIBRARY[@]}" -o "$WORK/programs.cpp" --test "$HERE/test_programs.st"
check project "$WORK/project.st" "${LIBRARY[@]}" -o "$WORK/project.cpp"
# The C++ of the whole project compiles (types in an order g++ takes).
RUNTIME="$(cd "$(dirname "$(readlink -f "$STRUCPP")")/../.." && pwd)/src/runtime/include"
if g++ -std=c++17 -fsyntax-only -I"$RUNTIME" "$WORK/project.cpp" 2>"$WORK/gxx.log"; then
    echo "project C++ compiles"
else
    grep -E 'error' "$WORK/gxx.log" | head -20
    status=1
fi
exit $status
