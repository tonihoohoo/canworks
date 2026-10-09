#!/usr/bin/env bash
# Two CANopen networks on two SocketCAN interfaces (vcan0 and vcan1 by
# default), one ping-pong slave (node 2) on each.
#
#   test/networks/run.sh [--build-dir build] [--seconds 12]
#
# Loads the real libcanworks_plugin.so through canopen_host with
# config/two-networks and the program `%QD100 := %ID100 + 1`,
# `%QD101 := %ID101 + 1`. Passes (exit 0) when both status bits are TRUE and
# both counters keep counting, the log names each network in its lines, and
# each network generated its device configuration in its own folder. Then
# runs again with the second slave stopped halfway: the first network must
# keep counting while the second reports its node lost.
#
# Needs a build of this repo and both interfaces UP.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build"
SECONDS_RUN=12

while [ $# -gt 0 ]; do
    case "$1" in
        --build-dir) BUILD="$(cd "$2" && pwd)"; shift ;;
        --seconds) SECONDS_RUN="$2"; shift ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

PLUGIN="$BUILD/plugins/libcanworks_plugin.so"
HOST="$BUILD/test/canopen_host"
SLAVE="$BUILD/test/pingpong_slave"
for f in "$PLUGIN" "$HOST" "$SLAVE"; do
    [ -x "$f" ] || [ -f "$f" ] || { echo "missing $f; build the repo first" >&2; exit 2; }
done
for i in vcan0 vcan1; do
    if ! ip link show "$i" 2>/dev/null | grep -q "state UP\|,UP"; then
        echo "$i is missing or down" >&2
        exit 2
    fi
done

WORK="$(mktemp -d)"
PIDS=()
cleanup() {
    for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
    wait 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

cp "$ROOT/config/two-networks/cpp-slave.eds" "$ROOT/config/two-networks/canopen_config.json" "$WORK/"

"$SLAVE" vcan0 "$WORK/cpp-slave.eds" 2 > "$WORK/slave0.log" 2>&1 &
PIDS+=($!)
"$SLAVE" vcan1 "$WORK/cpp-slave.eds" 2 > "$WORK/slave1.log" 2>&1 &
SLAVE1=$!
PIDS+=($SLAVE1)
sleep 0.5

RC=0
echo "==> Running the plugin on vcan0 and vcan1 for ${SECONDS_RUN}s"
"$HOST" "$PLUGIN" "$WORK/canopen_config.json" "$SECONDS_RUN" two 2> "$WORK/host.log" || RC=1
grep -E "\[CANWORKS\]" "$WORK/host.log" | head -40

check_log() {
    if grep -q -- "$1" "$WORK/host.log"; then
        echo "==> log: $1"
    else
        echo "FAIL: no log line with '$1'" >&2
        RC=1
    fi
}
check_log "\[CANWORKS\] io: loaded .* vcan0, 125000 bit/s"
check_log "\[CANWORKS\] drives: loaded .* vcan1, 125000 bit/s"
check_log "\[CANWORKS\] drives: node 2 (pingpong) is operational"
for d in io drives; do
    if [ -f "$WORK/.canworks/$d/master.dcf" ]; then
        echo "==> .canworks/$d/master.dcf generated"
    else
        echo "FAIL: no .canworks/$d/master.dcf" >&2
        RC=1
    fi
done

echo "==> Again, with the drives slave stopped after 3 s: io must keep counting"
( sleep 3; kill "$SLAVE1" 2>/dev/null ) &
PIDS+=($!)
"$HOST" "$PLUGIN" "$WORK/canopen_config.json" 8 pingpong 2> "$WORK/host2.log"
if [ $? -ne 0 ]; then
    echo "FAIL: network io stopped counting while drives lost its node" >&2
    RC=1
fi
if grep -q "\[CANWORKS\] drives: node 2 (pingpong)" "$WORK/host2.log" && \
   grep -E "\[CANWORKS\] drives: node 2 \(pingpong\).*(lost|heartbeat|not operational|no answer)" "$WORK/host2.log" >/dev/null; then
    echo "==> drives reported its node lost"
else
    echo "FAIL: drives did not report node 2 lost" >&2
    grep -E "drives:" "$WORK/host2.log" | tail -10 >&2
    RC=1
fi
exit $RC
