#!/usr/bin/env bash
# canworks-sim end-to-end test on vcan0 and vcan1.
#
#   test/simulator/run.sh [--build-dir build]
#
# 1. Run mode: the standalone simulator simulates node 2 of the ping-pong
#    config (config/pingpong) on vcan0, with a simulation file that loops
#    0x4000 back to 0x4001; the real libcanworks_plugin.so in canopen_host
#    boots it and runs the ping-pong program. While it runs, the control
#    subcommands are checked against the plugin's view: status, get, source,
#    set and override (the PLC's answer comes back through the RPDO),
#    release, fault/clear emcy and heartbeat-stop (the plugin logs the EMCY
#    and the lost and resumed heartbeat), and the remote test mode
#    (test --runtime) against the simulator's control channel. SIGTERM must
#    stop the simulator cleanly.
# 2. Test mode: canworks-sim test with a passing and a failing
#    scenario next to the plugin; exit codes 1 and 0, and the JUnit file's
#    structure.
# 3. Real-bus checks on vcan1: an interface that is not vcan is refused
#    without --real-bus, and with it a node ID that is already on the bus
#    (node 23, held by a second simulator sending EMCY) is not simulated
#    while node 24 is. vcan1 counts as a real bus through the test-only
#    override CANWORKS_SIM_TREAT_AS_REAL=vcan1 (tools/sim/sim_run.cpp);
#    users never set it.
#
# 4. Simulated nodes in the plugin on a real interface (vcan0): a real
#    ping-pong node 2 (separate process) next to a node 5 the plugin
#    simulates; an outside listener sees node 5's heartbeat. Then node 2
#    marked simulated while another process holds node ID 2: not started,
#    conflict logged; and the plugin's node 5 powers off when another
#    process starts sending as node 5.
#
# Needs a build of this repo (cmake -B build -DOPENPLC_ROOT=... && cmake
# --build build) and vcan0 UP (sudo scripts/dev-setup.sh); vcan1 is created
# with sudo when missing.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build"

while [ $# -gt 0 ]; do
    case "$1" in
        --build-dir) BUILD="$(cd "$2" && pwd)"; shift ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

PLUGIN="$BUILD/plugins/libcanworks_plugin.so"
HOST="$BUILD/test/canopen_host"
SIM="$BUILD/bin/canworks-sim"
SLAVE="$BUILD/test/pingpong_slave"
for f in "$PLUGIN" "$HOST" "$SIM" "$SLAVE"; do
    [ -x "$f" ] || [ -f "$f" ] || { echo "missing $f; build the repo first" >&2; exit 2; }
done
if ! ip link show vcan0 2>/dev/null | grep -q "state UP\|,UP"; then
    echo "vcan0 is missing or down; run: sudo scripts/dev-setup.sh" >&2
    exit 2
fi
if ! ip link show vcan1 >/dev/null 2>&1; then
    sudo modprobe vcan 2>/dev/null
    sudo ip link add dev vcan1 type vcan || { echo "cannot create vcan1" >&2; exit 2; }
fi
sudo ip link set vcan1 up || { echo "cannot bring vcan1 up" >&2; exit 2; }

WORK="$(mktemp -d)"
PIDS=()
cleanup() {
    for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
    wait 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

FAILS=0
ok() { echo "ok:   $*"; }
fail() { echo "FAIL: $*" >&2; FAILS=$((FAILS + 1)); }
# The value `get` prints: "node 2 0x4000:0 = 451 (UNSIGNED32)".
value() { "$SIM" get "$@" | awk '{ print $5 }'; }
# Waits up to $2 s for $1 (a grep pattern) in file $3.
wait_for() {
    local i
    for i in $(seq 1 $(($2 * 10))); do
        grep -q "$1" "$3" 2>/dev/null && return 0
        sleep 0.1
    done
    return 1
}

CONFIG="$ROOT/config/pingpong"
cp "$CONFIG/cpp-slave.eds" "$WORK/"
cp "$CONFIG/canopen_config.json" "$WORK/"
# The tutorial slave's EDS has no EMCY producer; give the copy a 0x1014 so the
# EMCY faults have something to send with.
python3 - "$WORK/cpp-slave.eds" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
s = s.replace("[OptionalObjects]\nSupportedObjects=7\n", "[OptionalObjects]\nSupportedObjects=8\n8=0x1014\n", 1)
s += "\n[1014]\nParameterName=COB-ID EMCY\nDataType=0x0007\nAccessType=rw\nDefaultValue=$NODEID+0x80\nPDOMapping=0\n"
open(p, "w", encoding="utf-8").write(s)
PY
grep -q "^\[1014\]" "$WORK/cpp-slave.eds" || { echo "could not add 0x1014 to the EDS copy" >&2; exit 2; }
cat > "$WORK/simulation.json" <<'JSON'
{
  "schema_version": 1,
  "nodes": { "2": { "sources": { "0x4001": { "expr": "[0x4000]" } } } },
  "scenarios": {
    "counts": {
      "test": true,
      "steps": [
        { "wait": { "node": 2, "object": "0x4000", "gt": 10 }, "timeout_ms": 20000 },
        { "expect": { "expr": "[2/0x4001] >= 10" }, "within_ms": 1000 }
      ]
    },
    "never": {
      "test": true,
      "steps": [ { "expect": { "node": 2, "object": "0x4001", "eq": 4000000000 }, "within_ms": 300 } ]
    }
  }
}
JSON

echo "==> 1. Run mode on vcan0 next to the plugin"
"$SIM" "$WORK/canopen_config.json" --state-dir "$WORK/state" > "$WORK/sim.log" 2>&1 &
SIM_PID=$!
PIDS+=($SIM_PID)
wait_for "node 2: powered on" 10 "$WORK/sim.log" && ok "the simulator started node 2" || fail "the simulator did not start node 2"
"$HOST" "$PLUGIN" "$WORK/canopen_config.json" 30 > "$WORK/host.out" 2> "$WORK/host.log" &
HOST_PID=$!
PIDS+=($HOST_PID)

booted=0
for i in $(seq 1 150); do
    if "$SIM" status 2>/dev/null | grep -q "node 2 (pingpong): power on, operational"; then booted=1; break; fi
    sleep 0.1
done
[ $booted -eq 1 ] && ok "the plugin booted node 2 (status: operational)" || fail "node 2 did not become operational"
sleep 2
v1=$(value 2 0x4000); sleep 1; v2=$(value 2 0x4000)
[ -n "$v1" ] && [ -n "$v2" ] && [ "$v2" -gt "$v1" ] && ok "get: 0x4000 counts ($v1 -> $v2)" || fail "get: 0x4000 does not count ($v1 -> $v2)"

echo "==> remote test mode against the simulator's control channel"
if "$SIM" test --runtime 127.0.0.1:7532 --scenario counts --start-timeout 5 --timeout 20 > "$WORK/remote.out" 2>&1; then
    ok "test --runtime: scenario counts passed"
else
    fail "test --runtime: scenario counts did not pass: $(cat "$WORK/remote.out")"
fi

"$SIM" source 2 0x4001 none > /dev/null && ok "source none" || fail "source none"
"$SIM" set 2 0x4001 450 > /dev/null && ok "set" || fail "set"
[ "$(value 2 0x4001)" = 450 ] && ok "get after set: 0x4001 = 450" || fail "get after set: 0x4001 = $(value 2 0x4001)"
sleep 1
[ "$(value 2 0x4000)" = 451 ] && ok "the PLC answered 451 through the plugin (0x4000)" || fail "0x4000 = $(value 2 0x4000), not 451"
"$SIM" source 2 0x4001 '{"expr": "[0x4000] * 2"}' > /dev/null && ok "source expr" || fail "source expr"
"$SIM" override 2 0x4001 1500 > /dev/null && ok "override" || fail "override"
sleep 1
[ "$(value 2 0x4001)" = 1500 ] && ok "the override holds against the source" || fail "0x4001 = $(value 2 0x4001), not 1500"
[ "$(value 2 0x4000)" = 1501 ] && ok "the PLC answered 1501 (0x4000)" || fail "0x4000 = $(value 2 0x4000), not 1501"
"$SIM" release 2 0x4001 > /dev/null && ok "release" || fail "release"
"$SIM" source 2 0x4001 '{"expr": "[0x4000]"}' > /dev/null || fail "source expr (loopback)"
sleep 1
v=$(value 2 0x4000)
[ -n "$v" ] && [ "$v" -gt 1501 ] && ok "released: counting again ($v)" || fail "after release 0x4000 = $v"
if "$SIM" get 2 0x9999 > /dev/null 2>&1; then fail "get of a missing object exited 0"; else ok "get of a missing object exits 1"; fi

"$SIM" fault 2 emcy 0x5000 --register 1 --msef 0100000000 > /dev/null && ok "fault emcy" || fail "fault emcy"
wait_for "EMCY 0x5000" 3 "$WORK/host.log" && ok "the plugin logged EMCY 0x5000" || fail "the plugin did not log EMCY 0x5000"
"$SIM" clear 2 emcy > /dev/null && ok "clear emcy" || fail "clear emcy"
wait_for "EMCY error reset" 3 "$WORK/host.log" && ok "the plugin logged the EMCY error reset" || fail "no EMCY error reset in the plugin log"
"$SIM" fault 2 heartbeat-stop > /dev/null && ok "fault heartbeat-stop" || fail "fault heartbeat-stop"
wait_for "lost: no heartbeat" 3 "$WORK/host.log" && ok "the plugin lost node 2's heartbeat" || fail "the plugin did not lose node 2's heartbeat"
"$SIM" clear 2 heartbeat > /dev/null && ok "clear heartbeat" || fail "clear heartbeat"
wait_for "heartbeat resumed\|node 2 (pingpong).*boot" 5 "$WORK/host.log" && ok "the plugin saw the heartbeat again" || fail "the heartbeat did not come back"

# Every check is done: once node 2 is operational again, stop the host (it
# prints its result on SIGTERM) instead of waiting out its 30 s.
for i in $(seq 1 100); do
    "$SIM" status 2>/dev/null | grep -q "node 2 (pingpong): power on, operational" && break
    sleep 0.1
done
sleep 1
kill -TERM "$HOST_PID" 2>/dev/null
wait "$HOST_PID"
HOST_RC=$?
# The heartbeat fault makes the plugin boot node 2 again, which restarts the
# count, so only the status bit at the end is checked here.
grep -q "status bit TRUE" "$WORK/host.out" && ok "canopen_host: status bit TRUE at the end" \
    || fail "canopen_host exited $HOST_RC: $(tail -3 "$WORK/host.out")"
kill -TERM "$SIM_PID"
wait "$SIM_PID"
SIM_RC=$?
[ $SIM_RC -eq 0 ] && grep -q "stopped" "$WORK/sim.log" && ok "SIGTERM stopped the simulator cleanly" || fail "the simulator exited $SIM_RC on SIGTERM"

echo "==> 2. Test mode next to the plugin"
"$HOST" "$PLUGIN" "$WORK/canopen_config.json" 90 > "$WORK/host2.out" 2> "$WORK/host2.log" &
HOST_PID=$!
PIDS+=($HOST_PID)
"$SIM" test "$WORK/canopen_config.json" --junit "$WORK/junit.xml" --start-timeout 15 --timeout 40 > "$WORK/test.out" 2>&1
RC=$?
cat "$WORK/test.out" | grep -E "PASS|FAIL|passed"
[ $RC -eq 1 ] && ok "test mode with a failing scenario exits 1" || fail "test mode exited $RC, not 1"
grep -q "FAIL never.*value seen" "$WORK/test.out" && ok "the failure names the step, condition and value seen" || fail "no failure line with the value seen"
if python3 - "$WORK/junit.xml" <<'PY'
import sys, xml.etree.ElementTree as ET
suite = ET.parse(sys.argv[1]).getroot()
assert suite.tag == "testsuite" and suite.get("name") == "canworks-sim", suite.attrib
assert suite.get("tests") == "2" and suite.get("failures") == "1", suite.attrib
cases = {c.get("name"): c for c in suite.findall("testcase")}
assert set(cases) == {"counts", "never"}, cases
for c in cases.values():
    float(c.get("time"))
assert cases["counts"].find("failure") is None
f = cases["never"].find("failure")
assert f is not None and "value seen" in f.get("message"), f
PY
then ok "JUnit file: testsuite, two testcases with times, one failure with its message"; else fail "JUnit file structure"; fi
"$SIM" test "$WORK/canopen_config.json" --scenario counts --start-timeout 15 --timeout 40 --quiet > "$WORK/test2.out" 2>&1
RC=$?
[ $RC -eq 0 ] && ok "test mode with the passing scenario exits 0" || fail "test mode --scenario counts exited $RC: $(cat "$WORK/test2.out")"
"$SIM" test "$WORK/canopen_config.json" --scenario nosuch > /dev/null 2>&1
[ $? -eq 2 ] && ok "an unknown scenario exits 2" || fail "an unknown scenario did not exit 2"
kill "$HOST_PID" 2>/dev/null; wait "$HOST_PID" 2>/dev/null

echo "==> 3. Real-bus checks on vcan1"
cat > "$WORK/holder.json" <<'JSON'
{ "nodes": { "23": { "faults": [ { "emcy": { "code": "0x1000", "period_ms": 100 } } ] } } }
JSON
"$SIM" --eds "$WORK/cpp-slave.eds" --node 23 --iface vcan1 --sim "$WORK/holder.json" --port 7540 > "$WORK/holder.log" 2>&1 &
PIDS+=($!)
wait_for "node 23: powered on" 10 "$WORK/holder.log" || fail "the holder of node 23 did not start"
export CANWORKS_SIM_TREAT_AS_REAL=vcan1
"$SIM" --eds "$WORK/cpp-slave.eds" --node 24 --iface vcan1 --port 7541 > "$WORK/refused.log" 2>&1
RC=$?
[ $RC -eq 2 ] && grep -q -- "--real-bus is needed" "$WORK/refused.log" && ok "a real interface without --real-bus is refused" \
    || fail "not refused without --real-bus (exit $RC): $(cat "$WORK/refused.log")"
"$SIM" --eds "$WORK/cpp-slave.eds" --node 23 --eds "$WORK/cpp-slave.eds" --node 24 --iface vcan1 --real-bus --port 7541 \
    > "$WORK/real.log" 2>&1 &
REAL_PID=$!
PIDS+=($REAL_PID)
unset CANWORKS_SIM_TREAT_AS_REAL
wait_for "node 24: powered on" 10 "$WORK/real.log" && ok "--real-bus: node 24 started" || fail "--real-bus: node 24 did not start"
grep -q "node 23: node ID 23 is taken" "$WORK/real.log" && ok "--real-bus: node 23 refused, named in the log" || fail "node 23 was not refused"
"$SIM" status --sim 127.0.0.1:7541 > "$WORK/real-status.out"
grep -q "node 23.*NODE ID CONFLICT" "$WORK/real-status.out" && grep -q "node 24.*power on" "$WORK/real-status.out" \
    && ok "status: node 23 conflict, node 24 on" || fail "status: $(cat "$WORK/real-status.out")"
# Plain CAN devices only (a version 2 file without "networks"): no node ID
# check, and they send on the real bus.
cat > "$WORK/raw-only.json" <<'JSON'
{ "schema_version": 2,
  "raw_devices": [ { "name": "sensor", "send": [ { "id": 912, "dlc": 1, "period_ms": 50, "data": [7] } ] } ] }
JSON
CANWORKS_SIM_TREAT_AS_REAL=vcan1 "$SIM" --iface vcan1 --real-bus --sim "$WORK/raw-only.json" --port 7542 \
    > "$WORK/raw-only.log" 2>&1 &
PIDS+=($!)
python3 - > "$WORK/raw-only.out" 2>&1 <<'PY'
import socket, struct, time
s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
s.bind(("vcan1",))
s.settimeout(0.5)
end = time.time() + 5
while time.time() < end:
    try:
        f = s.recv(16)
    except socket.timeout:
        continue
    if struct.unpack("<I", f[:4])[0] == 912:
        print("seen 0x390")
        break
PY
grep -q "seen 0x390" "$WORK/raw-only.out" && ok "--real-bus: a file of raw devices only sends" \
    || fail "raw devices only on a real bus: $(cat "$WORK/raw-only.log")"

echo "==> 4. Simulated nodes in the plugin next to a real node on vcan0"
python3 - "$WORK/canopen_config.json" "$WORK/mixed.json" "$WORK/conflict.json" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1]))
node5 = {"node_id": 5, "name": "simulated", "eds": "cpp-slave.eds", "simulate": True,
         "heartbeat_ms": 100, "heartbeat_timeout_ms": 300, "status_location": "%IX10.1"}
mixed = dict(cfg, nodes=cfg["nodes"] + [node5])
json.dump(mixed, open(sys.argv[2], "w"), indent=2)
conflict = dict(cfg, nodes=[dict(cfg["nodes"][0], simulate=True)])
json.dump(conflict, open(sys.argv[3], "w"), indent=2)
PY
# Outside listener: node 5's heartbeat (0x705) on vcan0, from another socket.
python3 - > "$WORK/listen.out" 2>&1 <<'PY' &
import socket, struct, time
s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
s.bind(("vcan0",))
s.settimeout(1)
end = time.time() + 20
while time.time() < end:
    try:
        frame = s.recv(16)
    except socket.timeout:
        continue
    if struct.unpack("=I", frame[:4])[0] & 0x7FF == 0x705:
        print("seen 0x705"); break
PY
LISTEN_PID=$!
PIDS+=($LISTEN_PID)
"$SLAVE" vcan0 "$WORK/cpp-slave.eds" 2 > "$WORK/slave.log" 2>&1 &
SLAVE_PID=$!
PIDS+=($SLAVE_PID)
sleep 0.5
"$HOST" "$PLUGIN" "$WORK/mixed.json" 15 > "$WORK/host4.out" 2> "$WORK/host4.log"
RC=$?
[ $RC -eq 0 ] && ok "mixed: real node 2 runs the ping-pong program" || fail "mixed: canopen_host exited $RC"
grep -q "node 5.*powered on" "$WORK/host4.log" && ok "mixed: the plugin started simulated node 5" || fail "mixed: node 5 was not started"
grep -q "node 5 (simulated) is operational" "$WORK/host4.log" && ok "mixed: the plugin booted simulated node 5" || fail "mixed: node 5 was not booted"
wait "$LISTEN_PID"
grep -q "seen 0x705" "$WORK/listen.out" && ok "mixed: an outside listener on vcan0 sees node 5's heartbeat" || fail "mixed: no 0x705 on vcan0"
kill "$SLAVE_PID" 2>/dev/null; wait "$SLAVE_PID" 2>/dev/null

# Another process holds node 2 (a simulator sending EMCY so the 1 s listen sees it).
cat > "$WORK/holder2.json" <<'JSON'
{ "nodes": { "2": { "faults": [ { "emcy": { "code": "0x1000", "period_ms": 100 } } ] } } }
JSON
"$SIM" --eds "$WORK/cpp-slave.eds" --node 2 --sim "$WORK/holder2.json" --port 7542 > "$WORK/holder2.log" 2>&1 &
HOLDER_PID=$!
PIDS+=($HOLDER_PID)
wait_for "node 2: powered on" 10 "$WORK/holder2.log" || fail "the holder of node 2 did not start"
"$HOST" "$PLUGIN" "$WORK/conflict.json" 5 > "$WORK/host5.out" 2> "$WORK/host5.log"
grep -q "node 2.*is taken by a device on vcan0" "$WORK/host5.log" && ok "conflict: simulated node 2 not started, conflict logged" \
    || fail "conflict: no conflict for node 2: $(grep -i 'node 2' "$WORK/host5.log" | head -5)"
kill "$HOLDER_PID" 2>/dev/null; wait "$HOLDER_PID" 2>/dev/null

# The running guard: the plugin's node 5 powers off when another process sends as node 5.
"$SLAVE" vcan0 "$WORK/cpp-slave.eds" 2 > "$WORK/slave2.log" 2>&1 &
SLAVE_PID=$!
PIDS+=($SLAVE_PID)
"$HOST" "$PLUGIN" "$WORK/mixed.json" 12 > "$WORK/host6.out" 2> "$WORK/host6.log" &
HOST_PID=$!
PIDS+=($HOST_PID)
wait_for "node 5 (simulated) is operational" 8 "$WORK/host6.log" || fail "guard: node 5 was not booted"
"$SIM" --eds "$WORK/cpp-slave.eds" --node 5 --port 7543 > "$WORK/intruder.log" 2>&1 &
PIDS+=($!)
wait_for "another device sends with node ID 5" 6 "$WORK/host6.log" && ok "guard: simulated node 5 powered off for another device" \
    || fail "guard: node 5 kept running next to another node 5"
kill "$HOST_PID" "$SLAVE_PID" 2>/dev/null; wait "$HOST_PID" "$SLAVE_PID" 2>/dev/null

if [ $FAILS -ne 0 ]; then
    echo "==> $FAILS check(s) failed; simulator log:" >&2
    cat "$WORK/sim.log" >&2
    exit 1
fi
echo "==> PASS"
exit 0
