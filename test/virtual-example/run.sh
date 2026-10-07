#!/usr/bin/env bash
# The virtual example (examples/virtual-plant, docs/tour.md) end to end on the
# local simulator runtime, the command-line steps of the tour:
#
#   test/virtual-example/run.sh --image <image> --strucpp <strucpp command> [--engine docker|podman]
#
# 1. the generated files are up to date: dio16.eds from make_dio16_eds.py,
#    cell.eds from cell_eds.json (slave-eds --gateway)
# 2. the deploy tool's check with no warning beyond the simulation notice,
#    and the exports: HTML network document, DCF files, DBC file
# 3. the program compiles with STruC++ and the openplc_canopen library
# 4. `openplc-canopen-sim-runtime start`, the example deployed with
#    `--runtime local`: every configured node OPERATIONAL (node 20 on host
#    included), node 7 given its node ID by LSS, the gateway started by the
#    stand-in master
# 5. the diagnostics channel with the example's token: the gateway status
#    and the extra device found by an LSS fastscan
# 6. the test scenarios of networks io and motion (sim test, JUnit reports
#    in $JUNIT_DIR when set)
# The runtime's program is built by test/local-runtime/build_program.mjs,
# which cannot build the editor's C/C++ blocks: test/virtual-example/
# ci_program.py leaves the program's SDO blocks section out (the editor
# builds them; the SDO blocks have their own tests).
# Needs the PC tools on PATH (pip install tools/deploy), the container engine,
# Node.js 22 and free ports 8443 and 7531. Leaves nothing behind.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EXAMPLE="$ROOT/examples/virtual-plant"
IMAGE="" STRUCPP="" ENGINE=docker
while [ $# -gt 0 ]; do
    case "$1" in
        --image) IMAGE="$2"; shift ;;
        --strucpp) STRUCPP="$2"; shift ;;
        --engine) ENGINE="$2"; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done
[ -n "$IMAGE" ] && [ -n "$STRUCPP" ] || { sed -n '5p' "$0" >&2; exit 2; }

FAILS=0
ok() { echo "  ok   $*"; }
fail() { echo "  FAIL $*"; FAILS=$((FAILS + 1)); }

WORK=$(mktemp -d)
export OPENPLC_CANOPEN_CONFIG_DIR="$WORK/settings"
export OPENPLC_CANOPEN_ENGINE="$ENGINE"
export OPENPLC_CANOPEN_TOKEN=virtual-plant-demo  # the example's documented demo token
RT=(openplc-canopen-sim-runtime)
cleanup() {
    "${RT[@]}" remove --data >/dev/null 2>&1
    rm -rf "$WORK"
}
trap cleanup EXIT
logs() { local text; text=$("$ENGINE" logs openplc-canopen-sim-runtime 2>&1); printf '%s\n' "$text"; }
in_logs() { local text; text=$(logs); grep -q "$1" <<<"$text"; }
CONFIG="$EXAMPLE/canopen/canopen.json"

echo "1. generated files are up to date"
python3 "$EXAMPLE/make_dio16_eds.py" > "$WORK/dio16.eds"
cmp -s "$WORK/dio16.eds" "$EXAMPLE/canopen/dio16.eds" && ok "dio16.eds" ||
    fail "dio16.eds differs from make_dio16_eds.py's output"
cp "$EXAMPLE/canopen/"* "$WORK/" && mkdir -p "$WORK/gen"
if openplc-canopen-deploy slave-eds "$EXAMPLE/canopen/cell_eds.json" -o "$WORK/gen/cell.eds" \
        --gateway "$CONFIG" > "$WORK/slave-eds.log" 2>&1; then
    cmp -s "$WORK/gen/cell.eds" "$EXAMPLE/canopen/cell.eds" && ok "cell.eds" ||
        fail "cell.eds differs from slave-eds --gateway's output"
else
    cat "$WORK/slave-eds.log"; fail "slave-eds"
fi

echo "2. check and exports"
mkdir -p "$WORK/dcf"
if openplc-canopen-deploy --export-html "$WORK/network.html" --config "$CONFIG" > "$WORK/html.log" 2>&1; then
    ok "HTML network document ($(wc -c < "$WORK/network.html") bytes)"
else
    cat "$WORK/html.log"; fail "export HTML"
fi
# The checks print one warning for a simulated config; anything else is new.
warnings=$(grep "^warning:" "$WORK/html.log" | grep -v "this config simulates devices")
[ -z "$warnings" ] && ok "no warning beyond the simulation notice" || fail "warnings: $warnings"
openplc-canopen-deploy --export-dcf "$WORK/dcf" --config "$CONFIG" > "$WORK/dcf.log" 2>&1 &&
    ok "DCF files: $(cd "$WORK/dcf" && ls | tr '\n' ' ')" || { cat "$WORK/dcf.log"; fail "export DCF"; }
openplc-canopen-deploy --export-dbc "$WORK/plant.dbc" --config "$CONFIG" > "$WORK/dbc.log" 2>&1 &&
    ok "DBC file" || { cat "$WORK/dbc.log"; fail "export DBC"; }

echo "3. the program compiles"
LIBRARY="$ROOT/tools/deploy/openplc_canopen_deploy/library"
if "$STRUCPP" "$EXAMPLE/pous/programs/main.st" -L "$LIBRARY" -o "$WORK/main.cpp" > "$WORK/strucpp.log" 2>&1; then
    ok "main.st with STruC++"
else
    tail -20 "$WORK/strucpp.log"; fail "STruC++"
fi
mkdir -p "$WORK/bundle"
python3 "$ROOT/test/virtual-example/ci_program.py" "$EXAMPLE" "$WORK/program.st" &&
    node "$ROOT/test/local-runtime/build_program.mjs" "$STRUCPP" "$WORK/program.st" "$WORK/bundle" --lib "$LIBRARY" \
        >/dev/null && ok "runtime bundle (SDO blocks left out)" || fail "build_program.mjs"

echo "4. deploy to the local simulator runtime"
if "${RT[@]}" start --image "$IMAGE" > "$WORK/start.log" 2>&1; then ok "started"; else
    cat "$WORK/start.log"; fail "start"; exit 1; fi
for _ in $(seq 1 15); do
    "${RT[@]}" status 2>&1 | grep -q "PLC: EMPTY" && break
    sleep 1
done
if openplc-canopen-deploy --bundle "$WORK/bundle" --config "$CONFIG" --runtime local > "$WORK/deploy.log" 2>&1; then
    ok "deployed with --runtime local"
else
    cat "$WORK/deploy.log"; fail "deploy"
fi
grep -q "the PLC is running" "$WORK/deploy.log" && ok "PLC running" || fail "PLC not running"
NODES=("io: node 5 (rtd) is operational" "io: node 6 (dio) is operational" "io: node 7 (new_io) is operational"
       "motion: node 4 (drive) is operational" "host: node 20 (cell) is operational")
for _ in $(seq 1 60); do
    text=$(logs)
    all=1
    for n in "${NODES[@]}"; do grep -q "$n" <<<"$text" || all=0; done
    [ $all = 1 ] && break
    sleep 1
done
for n in "${NODES[@]}"; do in_logs "$n" && ok "$n" || fail "not in the log: $n"; done
in_logs "node 7 (new_io): LSS assigned node ID 7" && ok "LSS gave node 7 its node ID" || fail "no LSS assignment"
in_logs "gateway: the upper master started this node; routes run" && ok "gateway started by host" ||
    fail "gateway not started"
in_logs "ERROR" && { logs | grep ERROR | head; fail "errors in the log"; } || ok "no error in the log"

echo "5. diagnostics"
st=$(openplc-canopen-diag --runtime local status 2>&1)
grep -qi "gateway" <<<"$st" && ok "status shows the gateway" || fail "diag status: $st"
grep -q "upper master present" <<<"$st" && ok "the gateway sees its upper master" || fail "diag status: $st"
found=$(openplc-canopen-diag --runtime local lss-find --network io 2>&1)
grep -q "serial 0x00001BBB" <<<"$found" && ok "LSS fastscan finds the spare device" || fail "lss-find: $found"

echo "6. test scenarios"
for net in io motion; do
    junit=()
    [ -n "${JUNIT_DIR:-}" ] && mkdir -p "$JUNIT_DIR" && junit=(--junit "$JUNIT_DIR/virtual-example-$net.xml")
    if openplc-canopen-diag --runtime local sim test --network "$net" --timeout 120 "${junit[@]}" \
            > "$WORK/test-$net.log" 2>&1; then
        ok "network $net: $(tr '\n' ' ' < "$WORK/test-$net.log")"
    else
        cat "$WORK/test-$net.log"; fail "scenarios of network $net"
    fi
done

"${RT[@]}" remove --data >/dev/null 2>&1
[ "$FAILS" -eq 0 ] && echo OK || echo "$FAILS failure(s)"
exit $((FAILS > 0))
