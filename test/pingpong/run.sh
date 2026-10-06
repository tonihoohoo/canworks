#!/usr/bin/env bash
# Ping-pong end-to-end test on a SocketCAN interface (vcan0 by default).
#
#   test/pingpong/run.sh [--build-dir build] [--iface vcan0] [--seconds 10] [--no-slave] [--plc-cycle]
#
# Starts the tutorial ping-pong slave (node 2), then loads the real
# libcanopen_plugin.so through canopen_host, which drives it with the PLC
# program %QD100 := %ID100 + 1. Passes (exit 0) when the node status bit
# %IX10.0 is TRUE and %ID100 keeps counting up, and (with candump) the
# config's startup SDO (0x1017 := 100) is the last SDO download to node 2
# before the NMT start. --no-slave runs the same test without the slave and
# is expected to fail (exit 1). --plc-cycle sends SYNC from the stand-in
# PLC cycle (10 ms) instead of the 100 ms timer and also checks, with
# candump, one SYNC per cycle and its spacing.
#
# Needs a build of this repo (cmake -B build -DOPENPLC_ROOT=... && cmake
# --build build) and an UP interface (sudo scripts/dev-setup.sh). candump from
# can-utils is used for a traffic summary when installed.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build"
IFACE=vcan0
SECONDS_RUN=10
WITH_SLAVE=1
PLC_CYCLE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --build-dir) BUILD="$(cd "$2" && pwd)"; shift ;;
        --iface) IFACE="$2"; shift ;;
        --seconds) SECONDS_RUN="$2"; shift ;;
        --no-slave) WITH_SLAVE=0 ;;
        --plc-cycle) PLC_CYCLE=1 ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

PLUGIN="$BUILD/plugins/libcanopen_plugin.so"
HOST="$BUILD/test/canopen_host"
SLAVE="$BUILD/test/pingpong_slave"
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

CONFIG="$ROOT/config/pingpong"
cp "$CONFIG/cpp-slave.eds" "$WORK/"
sed "s/\"vcan0\"/\"$IFACE\"/" "$CONFIG/canopen_config.json" > "$WORK/canopen_config.json"
if [ "$PLC_CYCLE" -eq 1 ]; then
    sed -i 's/"sync_period_us": 100000/"sync_source": "plc_cycle"/' "$WORK/canopen_config.json"
    grep -q '"plc_cycle"' "$WORK/canopen_config.json" || { echo "cannot switch the config to PLC-cycle SYNC" >&2; exit 2; }
fi

if command -v candump >/dev/null; then
    candump -L "$IFACE" > "$WORK/candump.log" 2>/dev/null &
    PIDS+=($!)
fi
if [ "$WITH_SLAVE" -eq 1 ]; then
    "$SLAVE" "$IFACE" "$WORK/cpp-slave.eds" 2 > "$WORK/slave.log" 2>&1 &
    PIDS+=($!)
    sleep 0.5
fi

echo "==> Running the plugin on $IFACE for ${SECONDS_RUN}s ($([ "$WITH_SLAVE" -eq 1 ] && echo with || echo without) the slave)"
"$HOST" "$PLUGIN" "$WORK/canopen_config.json" "$SECONDS_RUN"
RC=$?

if [ -f "$WORK/candump.log" ]; then
    sleep 0.2
    count() { grep -c " $IFACE $1#" "$WORK/candump.log" || true; }
    echo "==> Traffic on $IFACE: SYNC $(count 080), NMT $(count 000), SDO to node 2 $(count 602)," \
         "TPDO1 from node 2 $(count 182), RPDO1 to node 2 $(count 202), heartbeat $(count 702)"
    if [ "$WITH_SLAVE" -eq 1 ] && [ $RC -eq 0 ]; then
        # Startup SDOs go after the PDO parameters, right before NMT start
        # (node 2: 000#0102, or all nodes: 000#0100). 0x1017:00 := 100 is an
        # expedited 2-byte download: 602#2B17100064000000.
        last_sdo=$(awk -v ifc="$IFACE" '$2 == ifc && $3 ~ /^000#01(02|00)/ { exit } $2 == ifc && $3 ~ /^602#/ { s = $3 } END { print s }' "$WORK/candump.log")
        if [ "$last_sdo" = "602#2B17100064000000" ]; then
            echo "==> Startup SDO 0x1017:00 := 100 sent to node 2 after the PDO parameters, before NMT start"
        else
            echo "FAIL: the last SDO download before NMT start was '$last_sdo', not the startup SDO 602#2B17100064000000" >&2
            RC=1
        fi
    fi
fi
if [ "$PLC_CYCLE" -eq 1 ] && [ $RC -eq 0 ]; then
    if [ ! -f "$WORK/candump.log" ]; then
        echo "FAIL: --plc-cycle needs candump (can-utils)" >&2
        RC=1
    else
        # One SYNC per 10 ms cycle while the plugin ran, evenly spaced.
        read -r n mean lo hi <<< "$(awk -v ifc="$IFACE" '$2 == ifc && $3 ~ /^080#/ {
                t = substr($1, 2, length($1) - 2) + 0
                if (n) { d = (t - p) * 1000; s += d; if (!lo || d < lo) lo = d; if (d > hi) hi = d }
                p = t; n++ }
            END { printf "%d %.2f %.2f %.2f\n", n, (n > 1 ? s / (n - 1) : 0), lo, hi }' "$WORK/candump.log")"
        expect=$((SECONDS_RUN * 100))
        echo "==> PLC-cycle SYNC: $n frames (about $expect expected), interval mean $mean ms, min $lo ms, max $hi ms"
        if [ "$n" -lt $((expect * 9 / 10)) ] || [ "$n" -gt $((expect * 11 / 10)) ]; then
            echo "FAIL: $n SYNC frames for about $expect PLC cycles" >&2
            RC=1
        elif ! awk -v m="$mean" 'BEGIN { exit !(m > 9 && m < 11) }'; then
            echo "FAIL: mean SYNC interval $mean ms, not the 10 ms PLC cycle" >&2
            RC=1
        fi
    fi
fi
exit $RC
