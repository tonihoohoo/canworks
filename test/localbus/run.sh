#!/usr/bin/env bash
# PC-direct commissioning (canopen-local-bus) on a SocketCAN interface
# (vcan0 by default): canworks-diag --adapter socketcan:vcan0, no
# runtime.
#
#   test/localbus/run.sh [--build-dir build] [--iface vcan0]
#
# 1. No PLC on the bus: the simulated RTD module (config/rtd-sensor, node 5)
#    and an LSS device without a node ID (test/lss/lss_slave, serial number
#    0x00005678). Through the adapter: status, scan (node 5 found), sdo-read,
#    a write refused without --allow-changes and done with it, backup and
#    compare (one difference after a write), restore, lss-find and
#    lss-set-id (the device gets node ID 7, no LSS store sent), and a trace
#    exported to pcapng.
# 2. The real libcanworks_plugin.so in canopen_host on the same bus with the
#    diagnostics channel: scan and sdo-read through the plugin and through
#    the adapter give the same identity fields (parity), the adapter's status
#    shows another master (the plugin's SYNC), and lss-find is refused
#    without --force.
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
SENSOR="$BUILD/test/sensor_slave"
LSS="$BUILD/test/lss_slave"
for f in "$PLUGIN" "$HOST" "$SENSOR" "$LSS"; do
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
export CANWORKS_TOKEN=localbus-test-token
PORT=7541
LOCAL=(python3 -m canworks.diag --adapter "socketcan:$IFACE" --bitrate 125)
CHANGE=(python3 -m canworks.diag --adapter "socketcan:$IFACE" --bitrate 125 --allow-changes)
REMOTE=(python3 -m canworks.diag --runtime "127.0.0.1:$PORT")

fail() {
    echo "FAIL: $*" >&2
    [ -f "$WORK/host.log" ] && { echo "--- host log (tail)" >&2; tail -30 "$WORK/host.log" >&2; }
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
    "port": int(sys.argv[4]), "bind": "127.0.0.1"}
json.dump(cfg, open(sys.argv[2], "w"), indent=2)
PY
awk '/^\[/ { sec = $0 } sec == "[1018sub4]" && /^DefaultValue=/ { $0 = "DefaultValue=0x00005678" } { print }' \
    "$ROOT/test/fixtures/eds/lss-slave.eds" > "$WORK/lss-slave.eds"

if command -v candump >/dev/null; then
    candump -L "$IFACE,7E5:7FF" > "$WORK/lss.log" 2>/dev/null &
    PIDS+=($!)
fi
"$SENSOR" "$IFACE" "$WORK/rtd8.eds" 5 --signal 0x7130:1=200..260 > "$WORK/sensor.log" 2>&1 &
PIDS+=($!)
"$LSS" "$IFACE" "$WORK/lss-slave.eds" > "$WORK/lss-slave.log" 2>&1 &
PIDS+=($!)
sleep 1
cd "$WORK" || exit 2

echo "==> 1. No PLC: the adapter alone"
"${LOCAL[@]}" status | tee status.txt || fail "status"
grep -q "adapter socketcan:$IFACE, 125 kbit/s, read-only" status.txt || fail "status line"
"${LOCAL[@]}" scan --config canopen_config.json | tee scan.txt || fail "scan"
grep -q "node   5" scan.txt || fail "scan did not find node 5"
grep -q "configured" scan.txt || fail "scan did not compare node 5 with the config"
"${LOCAL[@]}" sdo-read 5 0x1018 1 --type UNSIGNED32 || fail "sdo-read"
if "${LOCAL[@]}" sdo-write 5 0x2000 2 1000 --type UNSIGNED16 2> refused.txt; then
    fail "sdo-write without --allow-changes was not refused"
fi
grep -q "changes not allowed" refused.txt || fail "refusal reason"
"${LOCAL[@]}" backup 5 -o backup.dcf --config canopen_config.json || fail "backup"
grep -q "^NodeID=5" backup.dcf || fail "backup has no NodeID=5"
"${CHANGE[@]}" sdo-write 5 0x2000 2 1000 --type UNSIGNED16 || fail "sdo-write with --allow-changes"
"${LOCAL[@]}" compare 5 --with backup.dcf --config canopen_config.json > compare1.txt; cat compare1.txt
grep -q "1 different" compare1.txt || fail "compare did not find the change"
"${CHANGE[@]}" restore 5 backup.dcf --config canopen_config.json --yes > restore.txt || { cat restore.txt; fail "restore"; }
"${LOCAL[@]}" compare 5 --with backup.dcf --config canopen_config.json > compare2.txt; cat compare2.txt
grep -q " 0 different" compare2.txt || fail "values still differ after the restore"

"${CHANGE[@]}" lss-find | tee find.txt || fail "lss-find"
grep -q "serial 0x00005678" find.txt || fail "lss-find did not find the LSS device"
VENDOR=$(sed -n 's/.*vendor \(0x[0-9A-F]*\).*/\1/p' find.txt)
PRODUCT=$(sed -n 's/.*product \(0x[0-9A-F]*\).*/\1/p' find.txt)
REVISION=$(sed -n 's/.*revision \(0x[0-9A-F]*\).*/\1/p' find.txt)
"${CHANGE[@]}" lss-set-id "$VENDOR" "$PRODUCT" "$REVISION" 0x5678 7 | tee setid.txt || fail "lss-set-id"
grep -q "node ID 7 set" setid.txt || fail "lss-set-id output"
"${LOCAL[@]}" sdo-read 7 0x1018 4 --type UNSIGNED32 | tee serial.txt || fail "node 7 does not answer after LSS"
grep -q "22136" serial.txt || fail "node 7 is not the LSS device"   # 0x5678

"${LOCAL[@]}" trace -o bus.pcapng --duration 2 || fail "trace"
[ -s bus.pcapng ] || fail "empty trace"

if [ -f "$WORK/lss.log" ]; then
    grep -q "7E5#11" "$WORK/lss.log" || fail "no LSS configure node ID was sent"
    if grep -q "7E5#17" "$WORK/lss.log"; then fail "LSS store was sent without --store"; fi
fi

echo "==> 2. With the plugin as master on the same bus"
"$HOST" "$PLUGIN" "$WORK/canopen_config.json" 60 rtd > "$WORK/host.log" 2>&1 &
PIDS+=($!)
for _ in $(seq 1 40); do
    if "${REMOTE[@]}" --json status 2>/dev/null |
            python3 -c 'import json,sys; s=json.load(sys.stdin); sys.exit(0 if any(n["node_id"]==5 and n["booted"] for n in s["nodes"]) else 1)' 2>/dev/null; then
        break
    fi
    sleep 0.5
done
"${REMOTE[@]}" --json scan > scan-plugin.json || fail "scan through the plugin"
"${LOCAL[@]}" --json scan --config canopen_config.json > scan-local.json || fail "scan through the adapter"
python3 - <<'PY' || fail "scan results differ"
import json
keys = ("vendor_id", "product_code", "revision_number", "serial_number", "device_type", "device_name", "match")
plugin = {n["node_id"]: n for n in json.load(open("scan-plugin.json"))["nodes"]}
local = {n["node_id"]: n for n in json.load(open("scan-local.json"))["nodes"]}
for nid in (5, 7):
    a, b = plugin.get(nid), local.get(nid)
    assert a and b, "node %d missing (plugin %s, adapter %s)" % (nid, bool(a), bool(b))
    for k in keys:
        assert a.get(k) == b.get(k), "node %d %s: plugin %r, adapter %r" % (nid, k, a.get(k), b.get(k))
print("scan parity: nodes 5 and 7 identical")
PY
"${REMOTE[@]}" --json sdo-read 5 0x1018 2 > read-plugin.json || fail "sdo-read through the plugin"
"${LOCAL[@]}" --json sdo-read 5 0x1018 2 > read-local.json || fail "sdo-read through the adapter"
python3 -c 'import json; a, b = (json.load(open(f)) for f in ("read-plugin.json", "read-local.json")); assert (a["data"], a["size"]) == (b["data"], b["size"]), (a, b); print("sdo-read parity")' \
    || fail "sdo-read results differ"
"${LOCAL[@]}" status | tee status2.txt
grep -q "another master is active on this bus" status2.txt || fail "the plugin's SYNC was not seen as another master"
if "${CHANGE[@]}" lss-find 2> refused2.txt; then fail "lss-find ran while another master is active"; fi
grep -q "another master is active" refused2.txt || fail "lss-find refusal reason"
echo "PASS"
