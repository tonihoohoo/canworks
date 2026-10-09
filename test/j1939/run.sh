#!/usr/bin/env bash
# The plugin's J1939 ECU against canworks-j1939-sim on a SocketCAN interface
# (vcan0 by default), with the example of examples/j1939.
#
#   test/j1939/run.sh [--build-dir build] [--iface vcan0]
#
# Loads the real libcanworks_plugin.so through canopen_host (program j1939)
# and runs the simulator as the Engine node at address 0, sending
# ComponentInfo (40 bytes, BAM) every second with Starts=42. At 5 s it stops
# the simulator and takes the interface down and up (sudo), then starts it
# again; at 10 s it stops it for good, and a contender with a lower NAME
# claims 128. Passes (exit 0) when the plugin's checks pass (claimed, no
# bus, claimed again, moved to 129; Pressures values and the timeout bit;
# Starts=42), the contender saw the plugin claim 129, and the simulator
# received Setpoints (Run=1) and Command (PDU1 to address 0, Mode=3) from
# 128 and the plugin's request for ComponentInfo. Needs the kernel module
# can-j1939 (loaded with sudo when it is missing). Exit 1: a check failed;
# 2: setup failed.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build"
IFACE=vcan0

while [ $# -gt 0 ]; do
    case "$1" in
        --build-dir) BUILD="$(cd "$2" && pwd)"; shift ;;
        --iface) IFACE="$2"; shift ;;
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
if [ ! -d /sys/module/can_j1939 ]; then
    sudo modprobe can-j1939 || { echo "the kernel module can-j1939 is missing (linux-modules-extra)" >&2; exit 2; }
fi
if ! ip link show "$IFACE" >/dev/null 2>&1; then
    { sudo modprobe vcan && sudo ip link add dev "$IFACE" type vcan; } || {
        echo "cannot create $IFACE" >&2; exit 2; }
fi
if ! ip link show "$IFACE" | grep -q "[<,]UP[,>]"; then
    sudo ip link set "$IFACE" up || { echo "cannot bring $IFACE up" >&2; exit 2; }
fi

read -ra SIM <<< "${SIM:-python3 -m canworks.j1939.sim}"
export PYTHONPATH="$ROOT/tools/deploy${PYTHONPATH:+:$PYTHONPATH}"
WORK="$(mktemp -d)"
HOST_PID=
SIM_PID=
cleanup() {
    [ -n "$HOST_PID" ] && kill "$HOST_PID" 2>/dev/null
    [ -n "$SIM_PID" ] && kill "$SIM_PID" 2>/dev/null
    sudo ip link set "$IFACE" up 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

cp "$ROOT/examples/j1939/machine.dbc" "$WORK/"
python3 - "$ROOT/examples/j1939/canworks.json" "$WORK/canworks.json" "$IFACE" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1]))
cfg["networks"][0]["adapter"]["interface"] = sys.argv[3]
json.dump(cfg, open(sys.argv[2], "w"), indent=2)
PY
cat > "$WORK/engine-scenario.json" <<'JSON'
{"messages": {"ComponentInfo": {"period_ms": 1000, "signals": {"Starts": 42}}}}
JSON

start_sim() {
    "${SIM[@]}" --dbc "$WORK/machine.dbc" --node Engine --interface "$IFACE" --address 0 \
        --scenario "$WORK/engine-scenario.json" --ramp-period 2 --log "$WORK/engine-$1.jsonl" \
        > "$WORK/engine-$1.out" 2>&1 &
    SIM_PID=$!
}
stop_sim() {
    kill "$SIM_PID" 2>/dev/null
    wait "$SIM_PID" 2>/dev/null
    SIM_PID=
}

echo "==> The plugin's J1939 ECU and the simulated engine on $IFACE"
start_sim 1
"$HOST" "$PLUGIN" "$WORK/canworks.json" 14 j1939 > "$WORK/host.out" 2> "$WORK/host.log" &
HOST_PID=$!
sleep 5
stop_sim
echo "==> Interface $IFACE down and up"
sudo ip link set "$IFACE" down
sleep 1
sudo ip link set "$IFACE" up
start_sim 2
sleep 4
stop_sim
echo "==> A lower NAME takes address 128"
"${SIM[@]}" --contend 128 --name-value 0x10 --interface "$IFACE" --log "$WORK/contend.log.jsonl" \
    > "$WORK/contend.out" 2>&1 &
SIM_PID=$!
sleep 2
stop_sim
wait "$HOST_PID"
RC=$?
HOST_PID=
cat "$WORK/host.out"
grep -E "\[CANWORKS\]" "$WORK/host.log" | head -40

python3 - "$WORK" <<'PY' || RC=1
import glob, json, os, sys

work = sys.argv[1]
recs = []
for path in sorted(glob.glob(os.path.join(work, "engine-*.jsonl"))):
    with open(path) as f:
        recs += [json.loads(line) for line in f if line.strip()]
failed = []


def check(ok, what):
    print("%s %s" % ("ok  " if ok else "FAIL", what))
    if not ok:
        failed.append(what)


def rx(pgn):
    return [r for r in recs if r["event"] == "rx" and r["pgn"] == pgn and r["source"] == 128 and "signals" in r]


with open(os.path.join(work, "contend.log.jsonl")) as f:
    contend = [json.loads(line) for line in f if line.strip()]
check(any(r["event"] == "claim_seen" and r.get("address") == 129 for r in contend),
      "the contender took 128 and saw the plugin claim 129")
check(sum(1 for r in recs if r["event"] == "claimed") == 2, "the simulator claimed address 0 in both runs")
check(sum(1 for r in rx(65281) if r["signals"].get("Run") == 1) >= 10,
      "Setpoints with Run=1 from 128 (%d)" % len(rx(65281)))
check(any(r["signals"].get("Mode") == 3 for r in rx(61184)), "Command (PDU1 to 0) with Mode=3 from 128")
check(any(r["event"] == "request" and r.get("pgn") == 65282 and r.get("source") == 128 for r in recs),
      "the plugin's request for ComponentInfo")
if failed:
    for path in sorted(glob.glob(os.path.join(work, "*.out"))):
        print("--- " + os.path.basename(path))
        with open(path) as f:
            sys.stdout.write(f.read())
sys.exit(1 if failed else 0)
PY
if [ "$RC" -ne 0 ]; then
    echo "--- plugin log" >&2
    cat "$WORK/host.log" >&2
fi
exit $RC
