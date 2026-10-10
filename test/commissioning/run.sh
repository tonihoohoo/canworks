#!/usr/bin/env bash
# Writing a configuration to one device from the PC
# (canopen-device-commissioning) on a SocketCAN interface (vcan0 by default):
# canworks-diag --adapter socketcan:vcan0, no runtime.
#
#   test/commissioning/run.sh [--build-dir build] [--iface vcan0]
#
# 1. The standalone simulator simulates the RTD module's EDS
#    (config/rtd-sensor, node 5) with a state folder, so what it stores
#    outlives a power cycle. Through the adapter: a dry run writes nothing;
#    configure from the config's node 5 (its TPDO1 remapped to two entries)
#    writes the PDO sequence and reads it back; --verify-only passes, and
#    fails after a power cycle without store. Then the config's exported DCF
#    with --store survives a power cycle, restore-defaults --reset brings the
#    EDS values back, a DCF of another product and one for another node ID
#    are refused, and a PDO test with SYNC from the PC receives TPDO1.
# 2. The real libcanworks_plugin.so in canopen_host as master of node 5:
#    configure through the plugin's diagnostics channel is refused, because
#    the plugin writes node 5's configuration at every boot.
#
# Needs a build of this repo and an UP interface (sudo scripts/dev-setup.sh),
# and python-can for the deploy tool package.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build"
IFACE=vcan0

while [ $# -gt 0 ]; do
    case "$1" in
        --build-dir) BUILD="$(cd "$2" && pwd)"; shift ;;
        --iface) IFACE="$2"; shift ;;
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

PLUGIN="$BUILD/plugins/libcanworks_plugin.so"
HOST="$BUILD/test/canopen_host"
SIM="$BUILD/bin/canworks-sim"
for f in "$PLUGIN" "$HOST" "$SIM"; do
    [ -f "$f" ] || { echo "missing $f; build the repo first" >&2; exit 2; }
done
if ! ip link show "$IFACE" 2>/dev/null | grep -q "state UP\|,UP"; then
    echo "$IFACE is missing or down; run: sudo scripts/dev-setup.sh" >&2
    exit 2
fi

WORK="$(mktemp -d)"
PIDS=()
cleanup() {
    for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
    wait 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

export PYTHONPATH="$ROOT/tools/deploy${PYTHONPATH:+:$PYTHONPATH}"
export CANWORKS_TOKEN=commissioning-test-token
PORT=7543
SIMPORT=7544
LOCAL=(python3 -m canworks.diag --adapter "socketcan:$IFACE" --bitrate 125)
CHANGE=(python3 -m canworks.diag --adapter "socketcan:$IFACE" --bitrate 125 --allow-changes)
REMOTE=(python3 -m canworks.diag --runtime "127.0.0.1:$PORT")

fail() {
    echo "FAIL: $*" >&2
    for log in sim host; do
        [ -f "$WORK/$log.log" ] && { echo "--- $log log (tail)" >&2; tail -30 "$WORK/$log.log" >&2; }
    done
    exit 1
}

cp "$ROOT/config/rtd-sensor/rtd8.eds" "$WORK/"
python3 - "$ROOT/config/rtd-sensor/canopen_config.json" "$WORK/canopen_config.json" "$IFACE" "$PORT" <<'PY'
import json, os, sys
from canworks.diag import token_verifier
cfg = json.load(open(sys.argv[1]))
cfg["adapter"]["interface"] = sys.argv[3]
cfg["adapter"]["configure_link"] = False
cfg["master"]["diagnostics"] = {
    "token_verifier": token_verifier(os.environ["CANWORKS_TOKEN"]),
    "port": int(sys.argv[4]), "bind": "127.0.0.1", "allow_changes": True}
# A remap: TPDO1 with two of its four entries.
cfg["nodes"][0]["tx_pdos"][0]["entries"] = cfg["nodes"][0]["tx_pdos"][0]["entries"][:2]
json.dump(cfg, open(sys.argv[2], "w"), indent=2)
PY
python3 -c 'import sys; from canworks import cli; sys.exit(cli.main(sys.argv[1:]))' \
    --config "$WORK/canopen_config.json" --export-dcf "$WORK/dcf" > "$WORK/export.log" 2>&1 \
    || { cat "$WORK/export.log"; fail "DCF export"; }
DCF="$WORK/dcf/node_5.dcf"
[ -f "$DCF" ] || fail "no $DCF"

"$SIM" --eds "$WORK/rtd8.eds" --node 5 --name rtd --no-sim-file --iface "$IFACE" --state-dir "$WORK/state" \
    --port "$SIMPORT" > "$WORK/sim.log" 2>&1 &
PIDS+=($!)
simcmd() { "$SIM" "$@" --sim "127.0.0.1:$SIMPORT"; }
cd "$WORK" || exit 2

ready() {
    for _ in $(seq 1 40); do
        "${LOCAL[@]}" sdo-read 5 0x1000 0 > /dev/null 2>&1 && return 0
        sleep 0.25
    done
    fail "node 5 does not answer"
}
power_cycle() {
    simcmd fault 5 power cycle --off-ms 300 > /dev/null || fail "power cycle"
    sleep 0.6
    ready
}
count() { "${LOCAL[@]}" --json sdo-read 5 "$1" "$2" | python3 -c 'import json,sys; print(int(json.load(sys.stdin)["data"].replace(" ", "")[:2], 16))'; }
ready

echo "==> 1. One device on the bench, through the adapter"
ORIG=$(count 0x1A00 0)
[ "$ORIG" = 4 ] || fail "the simulated module maps $ORIG entries in TPDO1, not 4"
"${CHANGE[@]}" configure 5 --from-node 5 --config canopen_config.json --dry-run | tee dry.txt || fail "dry run"
grep -q "to write" dry.txt || fail "dry run printed no plan"
grep -q "off   0x1800 sub 1" dry.txt || fail "the plan does not switch TPDO1 off first"
[ "$(count 0x1A00 0)" = 4 ] || fail "the dry run wrote"
if "${LOCAL[@]}" configure 5 --from-node 5 --config canopen_config.json --yes 2> refused.txt; then
    fail "configure without --allow-changes was not refused"
fi
grep -q "changes not allowed" refused.txt || { cat refused.txt; fail "refusal reason"; }

"${CHANGE[@]}" configure 5 --from-node 5 --config canopen_config.json --yes | tee configure.txt || fail "configure"
grep -q "verified" configure.txt || fail "the read-back was not verified"
grep -q "not stored on the device" configure.txt || fail "no note that nothing was stored"
[ "$(count 0x1A00 0)" = 2 ] || fail "TPDO1 was not remapped"
"${LOCAL[@]}" configure 5 --from-node 5 --config canopen_config.json --verify-only | tee verify1.txt || fail "verify after configure"
grep -q "no difference" verify1.txt || fail "verify output"

power_cycle
if "${LOCAL[@]}" configure 5 --from-node 5 --config canopen_config.json --verify-only > verify2.txt 2>&1; then
    cat verify2.txt; fail "verify passed after a power cycle without store"
fi
grep -q "differ" verify2.txt || { cat verify2.txt; fail "verify after the power cycle"; }

"${CHANGE[@]}" configure 5 --dcf "$DCF" --store --yes | tee store.txt || fail "configure from the DCF with --store"
grep -q "node 5: stored (0x1010 sub 1)" store.txt || fail "not stored"
power_cycle
"${LOCAL[@]}" configure 5 --dcf "$DCF" --verify-only | tee verify3.txt || fail "verify after a power cycle with store"
[ "$(count 0x1A00 0)" = 2 ] || fail "the stored mapping did not survive the power cycle"

# The stored heartbeat makes node 5 heard OPERATIONAL after the power cycle,
# so the load and the reset need --force.
"${CHANGE[@]}" --force restore-defaults 5 --config canopen_config.json --reset --yes | tee defaults.txt || fail "restore-defaults"
grep -q "defaults restored" defaults.txt || fail "restore-defaults output"
ready
[ "$(count 0x1A00 0)" = 4 ] || fail "the defaults did not come back"

# Another product, and a DCF for another node ID: refused, nothing written.
awk '/^\[/ { sec = $0 } /^ProductNumber=/ { $0 = "ProductNumber=0x00000999" }
     sec == "[1018sub2]" && /^(DefaultValue|ParameterValue)=/ { sub(/=.*/, "=0x00000999") } { print }' "$DCF" > other.dcf
if "${CHANGE[@]}" configure 5 --dcf other.dcf --yes > other.txt 2>&1; then fail "a DCF of another product was written"; fi
grep -q "product code differs" other.txt || { cat other.txt; fail "identity refusal reason"; }
sed 's/^NodeID=.*/NodeID=7/' "$DCF" > node7.dcf
if "${CHANGE[@]}" configure 5 --dcf node7.dcf --yes > node7.txt 2>&1; then fail "a DCF for node 7 was written to node 5"; fi
grep -q "the source is for node 7 and the device is node 5" node7.txt || { cat node7.txt; fail "node ID refusal reason"; }
[ "$(count 0x1A00 0)" = 4 ] || fail "a refused configure wrote"

# The PDO test: the configuration's layout, SYNC from the PC, TPDO1 received.
"${CHANGE[@]}" configure 5 --from-node 5 --config canopen_config.json --yes > /dev/null || fail "configure again"
"${CHANGE[@]}" pdo-test 5 --config canopen_config.json --start --sync 50 --duration 2 | tee pdo.txt || fail "pdo-test"
grep -Eq "TPDO1 0x185: [1-9][0-9]* received" pdo.txt || fail "no TPDO1 in the PDO test"
grep -q "SYNC every 50 ms" pdo.txt || fail "no SYNC in the PDO test"

echo "==> 2. With the plugin as master: refused, the plugin configures node 5"
simcmd fault 5 reset node > /dev/null 2>&1
"$HOST" "$PLUGIN" "$WORK/canopen_config.json" 60 rtd > "$WORK/host.log" 2>&1 &
PIDS+=($!)
for _ in $(seq 1 40); do
    if "${REMOTE[@]}" --json status 2>/dev/null |
            python3 -c 'import json,sys; s=json.load(sys.stdin); sys.exit(0 if any(n["node_id"]==5 for n in s["nodes"]) else 1)' 2>/dev/null; then
        break
    fi
    sleep 0.5
done
if "${REMOTE[@]}" configure 5 --from-node 5 --config canopen_config.json --yes > runtime.txt 2>&1; then
    fail "configure through the plugin was not refused"
fi
grep -q "writes node 5's configuration at every boot" runtime.txt || { cat runtime.txt; fail "runtime refusal reason"; }
echo "PASS"
