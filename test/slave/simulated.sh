#!/usr/bin/env bash
# The plugin's master and the plugin's own slave on one simulated bus: a
# master network and a slave network (node 10, config/slave's EDS) that both
# have adapter.simulate and interface "sim0", in one config. No CAN interface.
#
#   test/slave/simulated.sh <build dir> [seconds]
#
# Runs canopen_host with the program `%QW10 := %IW10 + 1` (master) and
# `%QW300 := %IW300` (slave echo). Passes when the master boots node 10, the
# slave reports communication OK and the counter keeps counting through both
# networks.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD="$(cd "${1:?usage: $0 <build dir> [seconds]}" && pwd)"
SECONDS_RUN="${2:-6}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cp "$ROOT/config/slave/openplc-slave.eds" "$WORK/"
cat > "$WORK/canopen_config.json" <<'JSON'
{
  "schema_version": 2,
  "networks": [
    { "name": "plc", "adapter": { "type": "socketcan", "interface": "sim0", "bitrate": 250000, "simulate": true },
      "master": { "node_id": 1, "heartbeat_ms": 100 },
      "nodes": [ { "node_id": 10, "name": "openplc", "eds": "openplc-slave.eds", "simulate": false,
        "heartbeat_ms": 100, "heartbeat_timeout_ms": 300, "status_location": "%IX10.0",
        "tx_pdos": [ { "number": 1, "entries": [
          { "index": "0x2100", "subindex": 1, "type": "UNSIGNED16", "iec_location": "%IW10" } ] } ],
        "rx_pdos": [ { "number": 1, "entries": [
          { "index": "0x2000", "subindex": 1, "type": "UNSIGNED16", "iec_location": "%QW10" } ] } ] } ] },
    { "name": "line", "role": "slave",
      "adapter": { "type": "socketcan", "interface": "sim0", "bitrate": 250000, "simulate": true },
      "slave": { "node_id": 10, "eds": "openplc-slave.eds",
        "objects": [
          { "index": "0x2000", "subindex": 1, "iec_location": "%IW300" },
          { "index": "0x2100", "subindex": 1, "iec_location": "%QW300" } ],
        "state_location": "%IB301", "comm_ok_location": "%IX300.0" } }
  ]
}
JSON
export CANOPEN_STATE_DIR="$WORK/state"

RC=0
"$BUILD/test/canopen_host" "$BUILD/plugins/libcanworks_plugin.so" "$WORK/canopen_config.json" "$SECONDS_RUN" slave \
    2> "$WORK/host.log" || RC=1
grep -E "\[CANWORKS\]" "$WORK/host.log" | head -30
for line in "line: .*opened simulated bus sim0, starting the CANopen slave (node ID 10)" \
            "line: .*NMT state OPERATIONAL (node ID 10)" \
            "plc: node 10 (openplc) is operational"; do
    if grep -q -- "\[CANWORKS\] $line" "$WORK/host.log"; then
        echo "==> log: $line"
    else
        echo "FAIL: no log line with '$line'" >&2
        RC=1
    fi
done
if grep -q "\[CANWORKS\].*\(ERROR\|error\)" "$WORK/host.log"; then
    echo "FAIL: errors in the log" >&2
    RC=1
fi
exit $RC
