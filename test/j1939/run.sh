#!/usr/bin/env bash
# The plugin's J1939 ECU against canworks-j1939-sim on a SocketCAN interface
# (vcan0 by default), with the example of examples/j1939.
#
#   test/j1939/run.sh [--build-dir build] [--iface vcan0]
#
# Loads the real libcanworks_plugin.so through canopen_host (program j1939)
# and runs the simulator as the Engine node at address 0, sending
# ComponentInfo (40 bytes, BAM) every second with Starts=42. At 3 s it stops
# the simulator and takes the interface down and up (sudo), then starts it
# again; at 7 s it stops it for good, and a contender with a lower NAME
# claims 128. Passes (exit 0) when the plugin's checks pass (claimed, no
# bus, claimed again, moved to 129; Pressures values and the timeout bit;
# Starts=42), the contender saw the plugin claim 129 and received Setpoints
# from 129, and the simulator received Setpoints (Run=1) and Command (PDU1
# to address 0, Mode=3) from 128 and the plugin's request for ComponentInfo.
#
# Diagnostic messages (j1939-diagnostics) in the same run: the simulator
# raises six trouble codes (one ends at 1 s, so five go out by BAM), and
# at 1.5 s a diagnostics client on 127.0.0.1 checks the status's DM1 store
# and watched entry, reads the simulator's DM2 through the plugin
# (j1939_dm_read), is refused a clear without force and clears it with DM11
# (j1939_dm_clear, ACK). The simulator's log must show the plugin's own DM1
# (no code active) every second and the DM11 it acknowledged.
# Needs the kernel module can-j1939 (loaded with sudo when it is missing).
# Exit 1: a check failed; 2: setup failed.

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
PORT=7548
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
python3 - "$ROOT/examples/j1939/canworks.json" "$WORK/canworks.json" "$IFACE" "$PORT" <<'PY'
import json, sys
from canworks.diag import token_verifier
cfg = json.load(open(sys.argv[1]))
cfg["networks"][0]["adapter"]["interface"] = sys.argv[3]
cfg["diagnostics"] = {"token_verifier": token_verifier("j1939-test"), "port": int(sys.argv[4]), "bind": "127.0.0.1"}
json.dump(cfg, open(sys.argv[2], "w"), indent=2)
PY
# Six codes from the start; SPN 520205 ends at 1 s (previously active).
cat > "$WORK/engine-scenario.json" <<'JSON'
{"messages": {"ComponentInfo": {"period_ms": 1000, "signals": {"Starts": 42}}},
 "dtcs": [{"spn": 520200, "fmi": 0, "lamps": ["amber"]},
          {"spn": 520201, "fmi": 5, "lamps": ["red"], "flash": "slow"},
          {"spn": 520202, "fmi": 3},
          {"spn": 520203, "fmi": 4},
          {"spn": 520204, "fmi": 31},
          {"spn": 520205, "fmi": 2, "to_s": 1}]}
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
"$HOST" "$PLUGIN" "$WORK/canworks.json" 10 j1939 > "$WORK/host.out" 2> "$WORK/host.log" &
HOST_PID=$!
sleep 1.5
echo "==> Trouble codes through the diagnostics channel"
python3 - "$PORT" > "$WORK/dm-client.out" 2>&1 <<'PY' &
import json, sys, time
from canworks.diag import Client, DiagError

c = Client("127.0.0.1", int(sys.argv[1]), token="j1939-test", timeout=5.0)
c.connect()
out = {"status": c.status()}
try:
    c.request("j1939_dm_clear", address=0, previous=False)
    out["unforced"] = "accepted"
except DiagError as e:
    out["unforced"] = str(e)
out["read"] = c.request("j1939_dm_read", address=0, timeout_ms=1000)
out["clear"] = c.request("j1939_dm_clear", address=0, previous=False, force=True)
c.close()
print(json.dumps(out))
PY
CLIENT_PID=$!
sleep 1.5
stop_sim
wait "$CLIENT_PID"
echo "==> Interface $IFACE down and up"
sudo ip link set "$IFACE" down
sleep 1
sudo ip link set "$IFACE" up
start_sim 2
sleep 3
stop_sim
echo "==> A lower NAME takes address 128"
"${SIM[@]}" --contend 128 --name-value 0x10 --dbc "$WORK/machine.dbc" --interface "$IFACE" --log "$WORK/contend.log.jsonl" \
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
moved = [r for r in contend if r["event"] == "rx" and r["pgn"] == 65281 and r["source"] == 129 and "signals" in r]
check(len(moved) >= 5, "Setpoints from 129 after the move (%d)" % len(moved))
check(sum(1 for r in recs if r["event"] == "claimed") == 2, "the simulator claimed address 0 in both runs")
check(sum(1 for r in rx(65281) if r["signals"].get("Run") == 1) >= 10,
      "Setpoints with Run=1 from 128 (%d)" % len(rx(65281)))
check(any(r["signals"].get("Mode") == 3 for r in rx(61184)), "Command (PDU1 to 0) with Mode=3 from 128")
check(any(r["event"] == "request" and r.get("pgn") == 65282 and r.get("source") == 128 for r in recs),
      "the plugin's request for ComponentInfo")

# Diagnostic messages.
own = [r for r in recs if r["event"] == "dm" and r.get("dm") == "DM1" and r.get("source") == 128]
check(len(own) >= 4 and all(r.get("lamps") == 0 and r.get("dtcs") == [] for r in own),
      "the plugin's own DM1, lamps off and no code, every second (%d)" % len(own))
check(any(r["event"] == "dm_clear" and r.get("dm") == "DM11" and r.get("from") == 128 and r.get("result") == "ack"
          for r in recs), "the simulator acknowledged the plugin's DM11")
try:
    with open(os.path.join(work, "dm-client.out")) as f:
        lines = f.read().strip().splitlines()
    dm = json.loads(lines[-1])
except (OSError, ValueError, IndexError):
    dm = {}
    check(False, "the diagnostics client's answers")
if dm:
    status = dm["status"]["j1939"]["dm"]
    src = [s for s in status["sources"] if s["address"] == 0]
    codes = src[0]["dtcs"] if src else []
    check(bool(src) and src[0]["count"] == 5 and src[0]["truncated"] == 0 and
          [d["spn"] for d in codes] == [520200, 520201, 520202, 520203, 520204] and src[0]["lamps"] & 0x14 == 0x14,
          "status: ECU 0's DM1 with five codes by BAM (%s)" % json.dumps(src))
    check(status["watched"] and status["watched"][0]["source"] == 0 and not status["watched"][0]["timed_out"],
          "status: the watched ECU 0 not timed out")
    check(status["own"] is not None and status["own"]["active"] == [] and status["own"]["dm1_sent"] >= 1 and
          not status["own"]["suspended"], "status: the own DM1, nothing active, sent")
    check(dm["unforced"] == "clearing trouble codes acts on another ECU: repeat with force",
          "a clear without force is refused (%s)" % dm["unforced"])
    rd = dm["read"]
    check(rd.get("address") == 0 and rd.get("count") == 1 and rd["dtcs"][0]["spn"] == 520205,
          "j1939_dm_read: ECU 0's DM2 with SPN 520205 (%s)" % json.dumps(rd))
    check(dm["clear"] == {"address": 0, "result": "ack"}, "j1939_dm_clear: ACK from 0 (%s)" % json.dumps(dm["clear"]))
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
