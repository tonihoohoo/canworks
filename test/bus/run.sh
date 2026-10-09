#!/usr/bin/env bash
# Bus state byte on a SocketCAN interface (vcan0 by default).
#
#   test/bus/run.sh [--build-dir build] [--iface vcan0]
#
# Loads the real libcanworks_plugin.so through canopen_host with the ping-pong
# config plus master.bus_state_location %IB110, then takes the interface down
# and brings it up again (sudo). Passes (exit 0) when %IB110 reads 1 while
# the bus runs, 0 while the interface is down, and 1 again after it is back.
# Run it as a user without CAP_NET_ADMIN, so the plugin cannot bring the
# interface up itself.
# The config also has master.time_period_ms 60000: with candump, the test
# checks that a TIME message (COB-ID 0x100) went out when the bus came up and
# again at once after the interface came back, not only after the period.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build"
IFACE=vcan0

while [ $# -gt 0 ]; do
    case "$1" in
        --build-dir) BUILD="$(cd "$2" && pwd)"; shift ;;
        --iface) IFACE="$2"; shift ;;
        -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

PLUGIN="$BUILD/plugins/libcanworks_plugin.so"
HOST="$BUILD/test/canopen_host"
for f in "$PLUGIN" "$HOST"; do
    [ -f "$f" ] || { echo "missing $f; build the repo first" >&2; exit 2; }
done
if ! ip link show "$IFACE" 2>/dev/null | grep -q "state UP\|,UP"; then
    echo "$IFACE is missing or down; run: sudo scripts/dev-setup.sh" >&2
    exit 2
fi

WORK="$(mktemp -d)"
HOST_PID=
DUMP_PID=
cleanup() {
    [ -n "$HOST_PID" ] && kill "$HOST_PID" 2>/dev/null
    [ -n "$DUMP_PID" ] && kill "$DUMP_PID" 2>/dev/null
    sudo ip link set "$IFACE" up 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

CONFIG="$ROOT/config/pingpong"
cp "$CONFIG/cpp-slave.eds" "$WORK/"
python3 - "$CONFIG/canopen_config.json" "$WORK/canopen_config.json" "$IFACE" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1]))
cfg["adapter"]["interface"] = sys.argv[3]
cfg["master"]["bus_state_location"] = "%IB110"
cfg["master"]["time_period_ms"] = 60000
json.dump(cfg, open(sys.argv[2], "w"), indent=2)
PY

if command -v candump >/dev/null; then
    candump -L "$IFACE,100:7FF" > "$WORK/time.log" 2>/dev/null &
    DUMP_PID=$!
fi
echo "==> Running the plugin on $IFACE; taking it down at 3 s and up again at 5 s"
"$HOST" "$PLUGIN" "$WORK/canopen_config.json" 9 bus &
HOST_PID=$!
sleep 3
sudo ip link set "$IFACE" down
sleep 2
sudo ip link set "$IFACE" up
if [ -n "$DUMP_PID" ]; then
    # candump stops reading when the interface goes down: listen again for the TIME
    # the plugin sends once it has reopened the interface.
    kill "$DUMP_PID" 2>/dev/null; wait "$DUMP_PID" 2>/dev/null
    candump -L "$IFACE,100:7FF" >> "$WORK/time.log" 2>/dev/null &
    DUMP_PID=$!
fi
wait "$HOST_PID"
RC=$?
HOST_PID=
if [ -n "$DUMP_PID" ]; then
    sleep 0.2
    kill "$DUMP_PID" 2>/dev/null
    wait "$DUMP_PID" 2>/dev/null
    DUMP_PID=
    n=$(grep -c " $IFACE 100#[0-9A-F]\{12\}$" "$WORK/time.log" || true)
    if [ "$n" -ge 2 ]; then
        echo "==> $n TIME messages: at bus start and again after the interface came back"
    else
        echo "FAIL: $n TIME messages; expected one at start and one after the interface came back" >&2
        cat "$WORK/time.log" >&2
        RC=1
    fi
fi
exit $RC
