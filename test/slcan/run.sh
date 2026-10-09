#!/usr/bin/env bash
# The slcan adapter type against a fake CANable on a pseudo-terminal.
#
#   test/slcan/run.sh [--build-dir build] [--bridge vcan1] [--iface canslc0]
#
# Runs the ping-pong slave on the bridge vcan and test/slcan/fake_slcan.py,
# which plays a CANable with slcan firmware on a pty and bridges its frames to
# the vcan. The real plugin (through canopen_host, as root: attaching the
# slcan driver needs CAP_NET_ADMIN) uses adapter type slcan on that pty and
# must create the interface itself. Passes (exit 0) when:
#   1. the slave becomes operational and ping-pong counts, the interface runs
#      at the config's bit rate with txqueuelen 1000, and it is gone after the
#      PLC stops;
#   2. after the fake adapter is "unplugged" (killed) and "plugged in" again
#      mid-run, the plugin recreates the interface and ping-pong counts again;
#   3. with a foreign interface of the same name present, the plugin leaves
#      it alone and logs the name-taken error.
# Skips (exit 0 with a notice) when the kernel has no slcan module or one
# older than Linux 6.0 (no bit rate over netlink).

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build"
BRIDGE=vcan1
IFACE=canslc0

while [ $# -gt 0 ]; do
    case "$1" in
        --build-dir) BUILD="$(cd "$2" && pwd)"; shift ;;
        --bridge) BRIDGE="$2"; shift ;;
        --iface) IFACE="$2"; shift ;;
        -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

PLUGIN="$BUILD/plugins/libcanworks_plugin.so"
HOST="$BUILD/test/canopen_host"
SLAVE="$BUILD/test/pingpong_slave"
for f in "$PLUGIN" "$HOST" "$SLAVE"; do
    [ -f "$f" ] || { echo "missing $f; build the repo first" >&2; exit 2; }
done

skip() { echo "::notice::slcan test skipped: $1"; echo "SKIP: $1"; exit 0; }
sudo modprobe slcan 2>/dev/null || skip "the kernel has no slcan module"
KMAJ=$(uname -r | cut -d. -f1)
[ "$KMAJ" -ge 6 ] || skip "kernel $(uname -r) is older than 6.0"
if ! ip link show "$BRIDGE" >/dev/null 2>&1; then
    sudo modprobe vcan && sudo ip link add dev "$BRIDGE" type vcan || { echo "cannot create $BRIDGE" >&2; exit 2; }
fi
sudo ip link set "$BRIDGE" up

WORK="$(mktemp -d)"
chmod 755 "$WORK"
PIDS=()
FAKE_PID=
cleanup() {
    [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null
    for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
    wait 2>/dev/null
    sudo ip link del "$IFACE" 2>/dev/null
    sudo rm -rf "$WORK"
}
trap cleanup EXIT

DEV="$WORK/ttyCANable"
start_fake() {
    python3 "$HERE/fake_slcan.py" "$DEV" "$BRIDGE" >> "$WORK/fake.log" 2>&1 &
    FAKE_PID=$!
    for _ in $(seq 50); do [ -e "$DEV" ] && return 0; sleep 0.1; done
    echo "fake adapter did not start:" >&2; cat "$WORK/fake.log" >&2; exit 2
}
stop_fake() { kill "$FAKE_PID" 2>/dev/null; wait "$FAKE_PID" 2>/dev/null; FAKE_PID=; }

CONFIG="$ROOT/config/pingpong"
cp "$CONFIG/cpp-slave.eds" "$WORK/"
python3 - "$CONFIG/canopen_config.json" "$WORK/canopen_config.json" "$DEV" "$IFACE" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1]))
cfg["adapter"] = {"type": "slcan", "device": sys.argv[3], "interface": sys.argv[4], "bitrate": 125000}
cfg["master"]["bus_state_location"] = "%IB110"
json.dump(cfg, open(sys.argv[2], "w"), indent=2)
PY

"$SLAVE" "$BRIDGE" "$WORK/cpp-slave.eds" 2 > "$WORK/slave.log" 2>&1 &
PIDS+=($!)
sleep 0.5

FAIL=0
fail() { echo "FAIL: $*" >&2; FAIL=1; }
expect_log() { grep -qF "$2" "$1" || fail "log $(basename "$1") lacks: $2"; }

echo "==> 1. Plugin creates $IFACE from the fake adapter"
start_fake
sudo "$HOST" "$PLUGIN" "$WORK/canopen_config.json" 10 > "$WORK/run1.out" 2> "$WORK/run1.log" &
HOST_PID=$!
sleep 6
ip -details link show "$IFACE" > "$WORK/link.txt" 2>&1
wait "$HOST_PID" || fail "ping-pong over slcan did not count (see below)"
cat "$WORK/run1.out"
grep -q "bitrate 125000" "$WORK/link.txt" || fail "$IFACE does not run at 125000 bit/s: $(cat "$WORK/link.txt")"
grep -q "qlen 1000" "$WORK/link.txt" || fail "$IFACE txqueuelen is not 1000: $(cat "$WORK/link.txt")"
expect_log "$WORK/run1.log" "attached the slcan driver to $DEV as CAN interface $IFACE"
expect_log "$WORK/run1.log" "slcan adapter on $IFACE does not report the CAN error state"
expect_log "$WORK/run1.log" "released $DEV; CAN interface $IFACE removed"
if ip link show "$IFACE" >/dev/null 2>&1; then fail "$IFACE still exists after the PLC stopped"; fi

echo "==> 2. Unplug the adapter at 3 s, plug it in again at 5 s"
sudo "$HOST" "$PLUGIN" "$WORK/canopen_config.json" 16 > "$WORK/run2.out" 2> "$WORK/run2.log" &
HOST_PID=$!
sleep 3
stop_fake
sleep 2
start_fake
wait "$HOST_PID" || fail "ping-pong did not recover after the replug (see below)"
cat "$WORK/run2.out"
expect_log "$WORK/run2.log" "CAN interface $IFACE (slcan on $DEV) is gone; reopening the serial device"
expect_log "$WORK/run2.log" "serial device $DEV is missing"
[ "$(grep -c "attached the slcan driver" "$WORK/run2.log")" -ge 2 ] || fail "the interface was not recreated"

echo "==> 3. A foreign $IFACE (as from an old slcand service) is left alone"
sudo ip link add dev "$IFACE" type vcan
sudo "$HOST" "$PLUGIN" "$WORK/canopen_config.json" 3 > "$WORK/run3.out" 2> "$WORK/run3.log"
expect_log "$WORK/run3.log" "CAN interface $IFACE already exists and was not created by the plugin"
ip -details link show "$IFACE" | grep -q "vcan" || fail "the foreign $IFACE was changed or removed"
sudo ip link del "$IFACE"

if [ "$FAIL" -ne 0 ]; then
    for f in run1.log run2.log run3.log fake.log; do echo "--- $f"; cat "$WORK/$f"; done
    exit 1
fi
echo "PASS: slcan adapter created, released, recovered after replug, and a foreign interface left alone"
