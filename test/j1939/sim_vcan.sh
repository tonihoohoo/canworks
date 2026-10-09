#!/usr/bin/env bash
# canworks-j1939-sim on a SocketCAN interface (vcan0 by default): two
# simulators against each other.
#
#   test/j1939/sim_vcan.sh [--iface vcan0] [--duration 3] [--dbc FILE]
#
# Runs the Engine node of the DBC (default examples/j1939/machine.dbc) at
# address 0, with a scenario that sends ComponentInfo (40 bytes, BAM) every
# second with Starts=42, and the PLC node at address 128, each with --log,
# for --duration seconds. Passes (exit 0) when both claimed their address,
# the PLC received Pressures (PGN 65280) and ComponentInfo (PGN 65282, Starts
# 42) from 0, and the Engine received Setpoints (PGN 65281) from 128.
# Creates IFACE as a vcan link with sudo when it is missing. SIM overrides
# the simulator command (default: python3 -m canworks.j1939.sim from
# tools/deploy). Exit 1: a check failed; 2: setup failed.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
IFACE=vcan0
DURATION=3
DBC="$ROOT/examples/j1939/machine.dbc"

while [ $# -gt 0 ]; do
    case "$1" in
        --iface) IFACE="$2"; shift ;;
        --duration) DURATION="$2"; shift ;;
        --dbc) DBC="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; shift ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

if ! ip link show "$IFACE" >/dev/null 2>&1; then
    { sudo modprobe vcan && sudo ip link add dev "$IFACE" type vcan; } || {
        echo "cannot create $IFACE; run: sudo modprobe vcan && sudo ip link add dev $IFACE type vcan" >&2; exit 2; }
fi
if ! ip link show "$IFACE" | grep -q "[<,]UP[,>]"; then
    sudo ip link set "$IFACE" up || { echo "cannot bring $IFACE up" >&2; exit 2; }
fi

read -ra SIM <<< "${SIM:-python3 -m canworks.j1939.sim}"
export PYTHONPATH="$ROOT/tools/deploy${PYTHONPATH:+:$PYTHONPATH}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cat > "$WORK/engine-scenario.json" <<'JSON'
{"messages": {"ComponentInfo": {"period_ms": 1000, "signals": {"Starts": 42}}}}
JSON

"${SIM[@]}" --dbc "$DBC" --node Engine --interface "$IFACE" --address 0 --scenario "$WORK/engine-scenario.json" \
    --log "$WORK/engine.jsonl" --duration "$DURATION" > "$WORK/engine.out" 2>&1 &
ENGINE=$!
"${SIM[@]}" --dbc "$DBC" --node PLC --interface "$IFACE" --address 128 \
    --log "$WORK/plc.jsonl" --duration "$DURATION" > "$WORK/plc.out" 2>&1 &
PLC=$!
wait "$ENGINE"; ENGINE_STATUS=$?
wait "$PLC"; PLC_STATUS=$?

python3 - "$WORK" "$ENGINE_STATUS" "$PLC_STATUS" <<'PY'
import json, os, sys

work, statuses = sys.argv[1], {"engine": int(sys.argv[2]), "plc": int(sys.argv[3])}


def records(who):
    path = os.path.join(work, who + ".jsonl")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def rx(recs, pgn, source):
    return [r for r in recs if r["event"] == "rx" and r["pgn"] == pgn and r["source"] == source and "signals" in r]


engine, plc = records("engine"), records("plc")
failed = []


def check(ok, what):
    print("%s %s" % ("ok  " if ok else "FAIL", what))
    if not ok:
        failed.append(what)


for who in ("engine", "plc"):
    check(statuses[who] == 0, "%s simulator exited with 0 (got %d)" % (who, statuses[who]))
check(any(r["event"] == "claimed" and r["address"] == 0 for r in engine), "Engine claimed address 0")
check(any(r["event"] == "claimed" and r["address"] == 128 for r in plc), "PLC claimed address 128")
check(len(rx(plc, 65280, 0)) >= 5, "PLC received Pressures from 0 (%d)" % len(rx(plc, 65280, 0)))
check(any(r["signals"].get("Starts") == 42 for r in rx(plc, 65282, 0)),
      "PLC received ComponentInfo (BAM, 40 bytes) from 0 with Starts=42 (%d)" % len(rx(plc, 65282, 0)))
check(len(rx(engine, 65281, 128)) >= 5, "Engine received Setpoints from 128 (%d)" % len(rx(engine, 65281, 128)))
if failed:
    for who in ("engine", "plc"):
        print("--- %s output" % who)
        with open(os.path.join(work, who + ".out")) as f:
            sys.stdout.write(f.read())
sys.exit(1 if failed else 0)
PY
