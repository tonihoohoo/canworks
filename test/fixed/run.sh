#!/usr/bin/env bash
# Fixed PDO mapping end-to-end test on a SocketCAN interface (vcan0 by default).
#
#   test/fixed/run.sh [--build-dir build] [--iface vcan0] [--seconds 8]
#
# Starts a simulated digital I/O module as node 4, driven by
# test/fixtures/eds/fixed-io.eds: its PDO mappings, PDO COB-IDs and
# transmission types are read-only, so Lely's SDO server aborts any write to
# them, as a real fixed-mapping device does. Input 0x6000:2 moves through
# 10-50. Then loads the real libcanopen_plugin.so through canopen_host with
# the `fixed` program, which uses only 0x6000:2 of TPDO 1 (%IB40) and only
# 0x6200:1 of RPDO 1 (%QB40 := %IB40). Passes (exit 0) when the node status
# bit %IX10.0 is TRUE and %IB40 follows the module, the plugin logs no SDO
# abort, and (with candump) no SDO writes a PDO object of node 4, the node
# answers no SDO with an abort, TPDO 1 carries 2 bytes, the unused TPDO 2
# (COB-ID 0x384, fixed) keeps running and RPDO 1 goes out with 2 bytes.
# Then checks that the same config with "mapping": "config" is refused at load.
#
# Needs a build of this repo and an UP interface (sudo scripts/dev-setup.sh).

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build"
IFACE=vcan0
SECONDS_RUN=8

while [ $# -gt 0 ]; do
    case "$1" in
        --build-dir) BUILD="$(cd "$2" && pwd)"; shift ;;
        --iface) IFACE="$2"; shift ;;
        --seconds) SECONDS_RUN="$2"; shift ;;
        -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

PLUGIN="$BUILD/plugins/libcanopen_plugin.so"
HOST="$BUILD/test/canopen_host"
SLAVE="$BUILD/test/sensor_slave"
CHECK="$BUILD/canopen_check"
for f in "$PLUGIN" "$HOST" "$SLAVE" "$CHECK"; do
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

cp "$ROOT/test/fixtures/eds/fixed-io.eds" "$WORK/"
config() {
    cat <<JSON
{
  "schema_version": 1,
  "adapter": { "type": "socketcan", "interface": "$IFACE", "bitrate": 125000, "configure_link": false },
  "master": { "node_id": 1, "sync_period_us": 50000 },
  "nodes": [
    {
      "node_id": 4, "name": "io", "eds": "fixed-io.eds",
      "heartbeat_ms": 100,
      "status_location": "%IX10.0",
      "tx_pdos": [ { $1"entries": [ { "index": "0x6000", "subindex": 2, "type": "UNSIGNED8", "iec_location": "%IB40" } ] } ],
      "rx_pdos": [ { "entries": [ { "index": "0x6200", "subindex": 1, "type": "UNSIGNED8", "iec_location": "%QB40" } ] } ]
    }
  ]
}
JSON
}
config "" > "$WORK/canopen_config.json"

if command -v candump >/dev/null; then
    candump -L "$IFACE" > "$WORK/candump.log" 2>/dev/null &
    PIDS+=($!)
fi
"$SLAVE" "$IFACE" "$WORK/fixed-io.eds" 4 --signal 0x6000:2=10..50 > "$WORK/slave.log" 2>&1 &
PIDS+=($!)
sleep 0.5

echo "==> Running the plugin on $IFACE for ${SECONDS_RUN}s against the fixed-mapping I/O module"
"$HOST" "$PLUGIN" "$WORK/canopen_config.json" "$SECONDS_RUN" fixed 2>&1 | tee "$WORK/host.log"
RC=${PIPESTATUS[0]}
if grep -q "aborted" "$WORK/host.log"; then
    echo "FAIL: the plugin logged an SDO abort" >&2
    RC=1
fi
if [ $RC -eq 0 ] && ! grep -q "node 4 (io): TPDO 1 uses the device mapping from fixed-io.eds" "$WORK/host.log"; then
    echo "FAIL: the plugin did not log the device mapping of TPDO 1" >&2
    RC=1
fi

if [ -f "$WORK/candump.log" ]; then
    sleep 0.2
    LOG="$WORK/candump.log"
    count() { grep -c " $IFACE $1#" "$LOG" || true; }
    echo "==> Traffic on $IFACE: SYNC $(count 080), SDO to node 4 $(count 604), SDO from node 4 $(count 584)," \
         "TPDO1 $(count 184), TPDO2 $(count 384), RPDO1 $(count 204)"
    if [ $RC -eq 0 ]; then
        check=$(awk -v ifc="$IFACE" '
            function hex(h,   i, v) { v = 0; for (i = 1; i <= length(h); i++) v = v * 16 + index("0123456789ABCDEF", toupper(substr(h, i, 1))) - 1; return v }
            $2 != ifc { next }
            $3 ~ /^604#/ { d = substr($3, 5); cs = hex(substr(d, 1, 2)); idx = hex(substr(d, 5, 2) substr(d, 3, 2))
                           if (int(cs / 32) == 1 && idx >= 5120 && idx <= 7167) bad = bad " SDO-write:" sprintf("%04X", idx) }
            $3 ~ /^584#80/ { bad = bad " abort:" substr($3, 5) }
            $3 ~ /^184#/ { n1++; if (length(substr($3, 5)) != 4) bad = bad " TPDO1-length" }
            $3 ~ /^384#/ { n2++ }
            $3 ~ /^204#/ { n3++; if (length(substr($3, 5)) != 4) bad = bad " RPDO1-length" }
            END { if (!n1) bad = bad " no-TPDO1"; if (!n2) bad = bad " no-TPDO2"; if (!n3) bad = bad " no-RPDO1"; print bad }' "$LOG" \
            | tr ' ' '\n' | sort -u | head -5 | tr '\n' ' ')
        if [ -z "${check// /}" ]; then
            echo "==> No SDO wrote a PDO object, no abort; TPDO 1 has 2 bytes, TPDO 2 runs, RPDO 1 has 2 bytes"
        else
            echo "FAIL: bus traffic:$check" >&2
            RC=1
        fi
    fi
fi

config '"mapping": "config", ' > "$WORK/forced.json"
if "$CHECK" --no-dcfgen "$WORK/forced.json" > "$WORK/forced.log" 2>&1; then
    echo "FAIL: \"mapping\": \"config\" on the fixed TPDO 1 was accepted" >&2
    RC=1
elif grep -q "'mapping' is \"config\", but fixed-io.eds fixes the mapping" "$WORK/forced.log"; then
    echo "==> \"mapping\": \"config\" on the fixed TPDO 1 is refused at load"
else
    echo "FAIL: unexpected canopen_check output:" >&2
    cat "$WORK/forced.log" >&2
    RC=1
fi

[ $RC -eq 0 ] || { echo "--- slave log"; cat "$WORK/slave.log"; } >&2
exit $RC
