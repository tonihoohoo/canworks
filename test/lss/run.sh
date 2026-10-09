#!/usr/bin/env bash
# LSS node ID assignment end-to-end test on a SocketCAN interface (vcan0 by
# default).
#
#   test/lss/run.sh [--build-dir build] [--iface vcan0] [--seconds 10]
#
# Starts the tutorial ping-pong slave as an LSS device without a node ID
# (test/lss/lss_slave, EDS test/fixtures/eds/lss-slave.eds with serial
# number 0x00001234), then loads the real libcanworks_plugin.so through
# canopen_host with the ping-pong program and node 2 configured with
# "serial_number" and "lss": { "assign": true }. Passes (exit 0) when the
# plugin logs that it assigned node ID 2, the ping-pong runs on node 2
# (status bit %IX10.0 TRUE, %ID100 counting) and, with candump, no LSS
# "store configuration" (0x7E5 17) was sent.
#
# Needs a build of this repo and an UP interface (sudo scripts/dev-setup.sh).

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build"
IFACE=vcan0
SECONDS_RUN=10

while [ $# -gt 0 ]; do
    case "$1" in
        --build-dir) BUILD="$(cd "$2" && pwd)"; shift ;;
        --iface) IFACE="$2"; shift ;;
        --seconds) SECONDS_RUN="$2"; shift ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

PLUGIN="$BUILD/plugins/libcanworks_plugin.so"
HOST="$BUILD/test/canopen_host"
SLAVE="$BUILD/test/lss_slave"
for f in "$PLUGIN" "$HOST" "$SLAVE"; do
    [ -x "$f" ] || [ -f "$f" ] || { echo "missing $f; build the repo first" >&2; exit 2; }
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

# The fixture EDS with serial number 0x00001234 (the DefaultValue of [1018sub4]).
awk '/^\[/ { sec = $0 } sec == "[1018sub4]" && /^DefaultValue=/ { $0 = "DefaultValue=0x00001234" } { print }' \
    "$ROOT/test/fixtures/eds/lss-slave.eds" > "$WORK/lss-slave.eds"
cat > "$WORK/canopen_config.json" <<JSON
{
  "schema_version": 1,
  "adapter": { "type": "socketcan", "interface": "$IFACE", "bitrate": 125000, "configure_link": false },
  "master": { "node_id": 1, "sync_period_us": 100000 },
  "nodes": [
    {
      "node_id": 2,
      "name": "pingpong",
      "eds": "lss-slave.eds",
      "serial_number": "0x00001234",
      "lss": { "assign": true },
      "heartbeat_ms": 100,
      "heartbeat_timeout_ms": 300,
      "status_location": "%IX10.0",
      "tx_pdos": [
        { "entries": [ { "index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID100" } ] }
      ],
      "rx_pdos": [
        { "entries": [ { "index": "0x4000", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%QD100" } ] }
      ]
    }
  ]
}
JSON

if command -v candump >/dev/null; then
    candump -L "$IFACE" > "$WORK/candump.log" 2>/dev/null &
    PIDS+=($!)
fi
"$SLAVE" "$IFACE" "$WORK/lss-slave.eds" > "$WORK/slave.log" 2>&1 &
PIDS+=($!)
sleep 0.5

echo "==> Running the plugin on $IFACE for ${SECONDS_RUN}s (LSS slave without a node ID, assigned node ID 2)"
"$HOST" "$PLUGIN" "$WORK/canopen_config.json" "$SECONDS_RUN" 2>&1 | tee "$WORK/host.log"
RC=${PIPESTATUS[0]}
echo "==> Slave:"
cat "$WORK/slave.log"

if ! grep -q "node 2 (pingpong): LSS assigned node ID 2 (previous: none)" "$WORK/host.log"; then
    echo "FAIL: the plugin did not log the LSS assignment of node ID 2" >&2
    RC=1
fi
if [ -f "$WORK/candump.log" ]; then
    sleep 0.2
    count() { grep -c " $IFACE $1" "$WORK/candump.log" || true; }
    echo "==> Traffic on $IFACE: LSS requests $(count 7E5#), LSS answers $(count 7E4#)," \
         "configure node ID $(count 7E5#11), store $(count 7E5#17), TPDO1 from node 2 $(count 182#)"
    if [ "$(count 7E5#11)" -lt 1 ]; then
        echo "FAIL: no LSS configure node ID request was sent" >&2
        RC=1
    fi
    if [ "$(count 7E5#17)" -ne 0 ]; then
        echo "FAIL: LSS store configuration was sent although lss.store is off" >&2
        RC=1
    fi
fi
exit $RC
