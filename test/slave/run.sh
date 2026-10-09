#!/usr/bin/env bash
# The plugin's master against the plugin's own slave over SocketCAN: a master
# network on vcan0 and a slave network (node 10, config/slave's EDS) on
# vcan1, joined by two cangw routes, in one config.
#
#   test/slave/run.sh [--build-dir build] [--seconds 12]
#
# Loads the real libcanworks_plugin.so through canopen_host with the program
# `%QW10 := %IW10 + 1` (master) and `%QW300 := %IW300` (slave echo). Passes
# (exit 0) when the master boots node 10, the slave reports communication OK
# and the counter keeps counting through both networks, and the log shows the
# slave's NMT states. Then takes the vcan1 -> vcan0 route away: the master
# must report node 10 lost, and the counter must run again once the route is
# back.
#
# Needs a build of this repo, vcan0 and vcan1 UP, and cangw (can-utils) with
# the can-gw kernel module; run as root (cangw).

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build"
SECONDS_RUN=12

while [ $# -gt 0 ]; do
    case "$1" in
        --build-dir) BUILD="$(cd "$2" && pwd)"; shift ;;
        --seconds) SECONDS_RUN="$2"; shift ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

PLUGIN="$BUILD/plugins/libcanworks_plugin.so"
HOST="$BUILD/test/canopen_host"
for f in "$PLUGIN" "$HOST"; do
    [ -f "$f" ] || { echo "missing $f; build the repo first" >&2; exit 2; }
done
for i in vcan0 vcan1; do
    if ! ip link show "$i" 2>/dev/null | grep -q "state UP\|,UP"; then
        echo "$i is missing or down" >&2
        exit 2
    fi
done
command -v cangw >/dev/null || { echo "cangw not found (can-utils)" >&2; exit 2; }

WORK="$(mktemp -d)"
cleanup() {
    cangw -F 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

cp "$ROOT/config/slave/openplc-slave.eds" "$WORK/"
cat > "$WORK/canopen_config.json" <<'JSON'
{
  "schema_version": 2,
  "networks": [
    { "name": "plc", "adapter": { "type": "socketcan", "interface": "vcan0", "bitrate": 250000 },
      "master": { "node_id": 1, "heartbeat_ms": 100 },
      "nodes": [ { "node_id": 10, "name": "openplc", "eds": "openplc-slave.eds", "heartbeat_ms": 100,
        "heartbeat_timeout_ms": 300, "status_location": "%IX10.0",
        "tx_pdos": [ { "number": 1, "entries": [
          { "index": "0x2100", "subindex": 1, "type": "UNSIGNED16", "iec_location": "%IW10" } ] } ],
        "rx_pdos": [ { "number": 1, "entries": [
          { "index": "0x2000", "subindex": 1, "type": "UNSIGNED16", "iec_location": "%QW10" } ] } ] } ] },
    { "name": "line", "role": "slave", "adapter": { "type": "socketcan", "interface": "vcan1", "bitrate": 250000 },
      "slave": { "node_id": 10, "eds": "openplc-slave.eds",
        "objects": [
          { "index": "0x2000", "subindex": 1, "iec_location": "%IW300" },
          { "index": "0x2100", "subindex": 1, "iec_location": "%QW300" } ],
        "state_location": "%IB301", "comm_ok_location": "%IX300.0" } }
  ]
}
JSON
export CANOPEN_STATE_DIR="$WORK/state"
# The slave's EDS goes through the deploy tool's lint, as on an install.
export CANOPEN_EDSLINT="${CANOPEN_EDSLINT:-python3}"
export PYTHONPATH="$ROOT/tools/deploy${PYTHONPATH:+:$PYTHONPATH}"

cangw -F
cangw -A -s vcan0 -d vcan1 -e
cangw -A -s vcan1 -d vcan0 -e

RC=0
echo "==> Running the master on vcan0 and the slave on vcan1 for ${SECONDS_RUN}s"
"$BUILD/test/canopen_host" "$PLUGIN" "$WORK/canopen_config.json" "$SECONDS_RUN" slave 2> "$WORK/host.log" || RC=1
grep -E "\[CANWORKS\]" "$WORK/host.log" | head -40

check_log() {
    if grep -q -- "$1" "$WORK/host.log"; then
        echo "==> log: $1"
    else
        echo "FAIL: no log line with '$1'" >&2
        RC=1
    fi
}
check_log "\[CANWORKS\] line: .*NMT state PRE-OPERATIONAL (node ID 10)"
check_log "\[CANWORKS\] line: .*NMT state OPERATIONAL (node ID 10)"
check_log "\[CANWORKS\] plc: node 10 (openplc) is operational"

echo "==> Again, with the vcan1 -> vcan0 route removed for 3 s halfway"
(
    sleep 4
    cangw -D -s vcan1 -d vcan0 -e
    sleep 3
    cangw -A -s vcan1 -d vcan0 -e
) &
"$BUILD/test/canopen_host" "$PLUGIN" "$WORK/canopen_config.json" 16 slave 2> "$WORK/host2.log"
if [ $? -ne 0 ]; then
    echo "FAIL: the counter did not run again after the route came back" >&2
    RC=1
fi
wait
if grep -E "\[CANWORKS\] plc: node 10 \(openplc\).*(lost|heartbeat|not operational)" "$WORK/host2.log" >/dev/null; then
    echo "==> the master reported node 10 lost"
else
    echo "FAIL: the master did not report node 10 lost" >&2
    grep -E "plc:|line:" "$WORK/host2.log" | tail -10 >&2
    RC=1
fi
exit $RC
