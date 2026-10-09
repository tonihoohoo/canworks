#!/usr/bin/env bash
# Raw frames and bit rate detection end-to-end on a SocketCAN interface
# (vcan0 by default) and on the simulated bus.
#
#   test/rawframes/run.sh [--build-dir build] [--iface vcan0]
#
# Runs the ping-pong (tutorial slave, node 2) with the real plugin through
# canopen_host and diagnostics with allow_changes on 127.0.0.1. Passes (exit 0)
# when:
#   - a frame sent with send_frame arrives on a second CAN_RAW socket and shows
#     in a trace marked Tx;
#   - an identifier the network uses (RPDO1 0x202) and any frame while node 2
#     is OPERATIONAL are refused without force, and sent with it;
#   - a cyclic job with a count sends exactly that many frames, and a job ends
#     when its client disconnects;
#   - detect_bitrate on vcan is refused and the session goes on;
#   - `canworks-diag send` and `detect-bitrate` behave the same;
#   - on a simulated network, a forced SDO upload request to node 2 sent by
#     hand gets the simulated device's answer, both in the trace;
#   - raw config messages next to the CANopen network (add-raw-can): the sent
#     message goes out every 50 ms, a received one counts, the plugin
#     confirms its own frames by their echo, and a replay plays three frames.
#
# Needs a build of this repo and an UP interface (sudo scripts/dev-setup.sh).

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build"
IFACE=vcan0

while [ $# -gt 0 ]; do
    case "$1" in
        --build-dir) BUILD="$(cd "$2" && pwd)"; shift ;;
        --iface) IFACE="$2"; shift ;;
        -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
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
if ! ip link show "$IFACE" 2>/dev/null | grep -q "state UP\|,UP"; then
    echo "$IFACE is missing or down; run: sudo scripts/dev-setup.sh" >&2
    exit 2
fi
PY="${PYTHON:-python3}"
export PYTHONPATH="$ROOT/tools/deploy${PYTHONPATH:+:$PYTHONPATH}"
export CANWORKS_TOKEN=raw-test
PORT=7541
DIAG=("$PY" -m canworks.diag --runtime "127.0.0.1:$PORT")

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
VERIFIER="$("$PY" -c 'from canworks.diag import token_verifier; print(token_verifier("raw-test"))')"
DIAGCFG="\"diagnostics\": { \"token_verifier\": \"$VERIFIER\", \"port\": $PORT, \"bind\": \"127.0.0.1\", \"allow_changes\": true }"
sed -e "s/\"vcan0\"/\"$IFACE\"/" \
    -e "s|\"sync_period_us\": 100000 }|\"sync_period_us\": 100000, $DIAGCFG }|" \
    "$CONFIG/canopen_config.json" > "$WORK/canopen_config.json"
grep -q token_verifier "$WORK/canopen_config.json" || { echo "FAIL: could not add diagnostics to the config" >&2; exit 1; }
# Raw messages next to the CANopen network: one sent, one received (version 2).
"$PY" - "$WORK/canopen_config.json" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    cfg = json.load(f)
cfg["raw"] = {"tx": [{"name": "Beat", "id": 0x3F0, "dlc": 2, "period_ms": 50,
                      "signals": [{"name": "v", "start_bit": 0, "length": 16, "iec_location": "%QW400"}]}],
              "rx": [{"name": "Remote", "id": 0x3F1, "timeout_ms": 500, "status_location": "%IX400.0",
                      "signals": [{"name": "v", "start_bit": 0, "length": 16, "iec_location": "%IW400"}]}]}
# raw needs schema_version 2: the network moves into networks[].
diagnostics = cfg["master"].pop("diagnostics")
raw = cfg.pop("raw")
cfg = {"schema_version": 2, "diagnostics": diagnostics,
       "networks": [{"name": "pingpong", "adapter": cfg["adapter"], "master": cfg["master"], "nodes": cfg["nodes"],
                     "raw": raw}]}
with open(sys.argv[1], "w") as f:
    json.dump(cfg, f)
PY

"$SLAVE" "$IFACE" "$WORK/cpp-slave.eds" 2 > "$WORK/slave.log" 2>&1 &
PIDS+=($!)
sleep 0.5

echo "==> Running the plugin on $IFACE for 40 s with diagnostics (allow_changes) on 127.0.0.1:$PORT"
"$HOST" "$PLUGIN" "$WORK/canopen_config.json" 40 > "$WORK/host.log" 2>&1 &
HOST_PID=$!
sleep 4

RC=0
fail() { echo "FAIL: $*" >&2; RC=1; }

echo "==> send_frame, guards and cyclic jobs through the protocol"
"$PY" - "$IFACE" "$PORT" <<'PY' || fail "protocol checks failed"
import base64, socket, struct, sys, time
from canworks import diag

iface, port = sys.argv[1], int(sys.argv[2])
rx = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
rx.bind((iface,))
rx.settimeout(0.05)

def drain(seconds):
    got = []
    end = time.time() + seconds
    while time.time() < end:
        try:
            frame = rx.recv(16)
        except socket.timeout:
            continue
        can_id, dlc = struct.unpack("=IB3x", frame[:8])
        got.append((can_id & 0x1FFFFFFF, frame[8:8 + dlc]))
    return got

def refused(c, why, **fields):
    try:
        c.request("send_frame", **fields)
    except diag.DiagError as e:
        assert why in str(e), "expected %r, got %r" % (why, str(e))
        return
    raise SystemExit("send_frame %r was not refused" % fields)

c = diag.Client("127.0.0.1", port, "raw-test")
c.connect()
st = c.status()
nodes = {n["node_id"]: n for n in st["nodes"]}
assert nodes[2]["state"] == 5, "node 2 is not OPERATIONAL: %r" % nodes[2]
t = c.trace_start()
drain(0.2)

# Node 2 runs: every frame needs force; 0x202 is its RPDO1 anyway.
refused(c, "is OPERATIONAL; force needed", can_id=0x60A, data="40 18 10 01 00 00 00 00")
refused(c, "0x202 is RPDO1 of node 2", can_id=0x202, data="01 00 00 00")
assert c.request("send_frame", can_id=0x60A, data="40 18 10 01 00 00 00 00", force=True) == {"sent": True}
got = [f for f in drain(0.3) if f[0] == 0x60A]
assert got == [(0x60A, bytes.fromhex("4018100100000000"))], got
print("    single frame: received on a second socket")

# The trace shows it as sent from this host.
f = c.trace_fetch(t["next"], 4000)
raw = base64.b64decode(f["frames"])
tx = [r for r in (raw[i:i + 24] for i in range(0, len(raw), 24))
      if struct.unpack_from("<I", r, 8)[0] & 0x1FFFFFFF == 0x60A]
assert tx and all(r[13] & 1 for r in tx), "0x60A not in the trace as Tx"
c.trace_stop()
print("    single frame: in the trace, marked Tx")

job = c.request("send_frame", can_id=0x123, data="AA 55", period_ms=20, count=5, force=True)["job"]
got = [x for x in drain(0.6) if x[0] == 0x123]
assert len(got) == 5, "cyclic job with count 5 sent %d frames" % len(got)
stopped = c.request("send_frame_stop")["stopped"]
assert any(s["job"] == job and s["sent"] == 5 and s["reason"] == "count reached" for s in stopped), stopped
print("    cyclic job: exactly 5 frames")

other = diag.Client("127.0.0.1", port, "raw-test")
other.connect()
other.request("send_frame", can_id=0x124, period_ms=20, force=True)
assert [x for x in drain(0.3) if x[0] == 0x124], "endless job sends nothing"
other.close()
time.sleep(0.2)
drain(0.1)
assert not [x for x in drain(0.3) if x[0] == 0x124], "the job went on after its client disconnected"
print("    cyclic job: ends with its client")

try:
    c.request("detect_bitrate", force=True)
    raise SystemExit("detect_bitrate on vcan was not refused")
except diag.DiagError as e:
    assert "no bit rate on a virtual bus" in str(e), e
assert c.status()["session"], "the session ended after a refused detection"
print("    detect_bitrate: refused on vcan, session goes on")

# Raw config messages (add-raw-can).
beats = [x for x in drain(1.0) if x[0] == 0x3F0]
assert 15 <= len(beats) <= 25, "raw message 0x3F0 every 50 ms: %d frames in 1 s" % len(beats)
rx.send(struct.pack("=IB3x8s", 0x3F1, 2, bytes.fromhex("3412") + bytes(6)))
time.sleep(0.2)
raw = c.status()["raw"]
assert raw["confirm"] == "echo", raw
remote = [m for m in raw["rx"] if m["message"].startswith("Remote")][0]
assert remote["count"] == 1 and remote["last_data"] == "34 12", remote
assert [m for m in raw["tx"] if m["message"].startswith("Beat")][0]["count"] >= 15, raw["tx"]
print("    raw messages: 0x3F0 every 50 ms, 0x3F1 received, echo confirmation")
frames = [{"t_us": i * 20000, "id": 0x3F2, "dlc": 1, "data": "%02X" % i} for i in range(3)]
c.replay(frames, force=True)
got = [x for x in drain(0.5) if x[0] == 0x3F2]
assert [g[1] for g in got] == [b"\x00", b"\x01", b"\x02"], got
print("    replay: three frames in order")
PY

echo "==> canworks-diag send and detect-bitrate"
out="$("${DIAG[@]}" send 0x60A "40 18 10 01" 2>&1)"
[ $? -eq 1 ] || fail "send without --force while node 2 runs should exit 1: $out"
echo "$out" | grep -q "force" || fail "send without --force does not say force is needed: $out"
"${DIAG[@]}" send 0x60A "40 18 10 01" --force > "$WORK/send.out" 2>&1 || fail "send --force failed: $(cat "$WORK/send.out")"
"${DIAG[@]}" send 0x125 AA --period-ms 20 --count 3 --force > "$WORK/cyclic.out" 2>&1 || fail "cyclic send failed: $(cat "$WORK/cyclic.out")"
grep -q "3" "$WORK/cyclic.out" || fail "cyclic send does not report 3 frames: $(cat "$WORK/cyclic.out")"
out="$("${DIAG[@]}" detect-bitrate --force 2>&1)"
[ $? -eq 1 ] || fail "detect-bitrate on vcan should exit 1: $out"
echo "$out" | grep -q "virtual bus" || fail "detect-bitrate does not say why: $out"

# Every request is done: stop the host (a clean exit on SIGTERM) instead of
# waiting out its 40 s.
kill -TERM "$HOST_PID" 2>/dev/null
wait "$HOST_PID"
grep -q "frame 0x60A \[8\] 40 18 10 01 00 00 00 00 sent by 127.0.0.1 (forced: node 2 (pingpong) is OPERATIONAL)" "$WORK/host.log" \
    || fail "the forced frame is not logged with the client's address"
grep -q "(job .*) of 127.0.0.1 ended: client disconnected" "$WORK/host.log" || fail "the disconnected job is not logged"

echo "==> Simulated network: a hand-sent SDO request to the simulated node 2"
SIMPORT=$((PORT + 1))
sed -e "s/\"port\": $PORT/\"port\": $SIMPORT/" \
    -e "s/\"interface\": \"$IFACE\"/\"interface\": \"$IFACE\", \"simulate\": true/" \
    "$WORK/canopen_config.json" > "$WORK/sim_config.json"
grep -q '"simulate": true' "$WORK/sim_config.json" || fail "could not make the config simulated"
"$HOST" "$PLUGIN" "$WORK/sim_config.json" 12 > "$WORK/sim_host.log" 2>&1 &
SIM_PID=$!
sleep 4
"$PY" - "$SIMPORT" <<'PY' || fail "simulated network check failed"
import base64, struct, sys, time
from canworks import diag
c = diag.Client("127.0.0.1", int(sys.argv[1]), "raw-test")
c.connect()
t = c.trace_start()
c.request("send_frame", can_id=0x602, data="40 18 10 01 00 00 00 00", force=True)
time.sleep(0.5)
f = c.trace_fetch(t["next"], 4000)
raw = base64.b64decode(f["frames"])
recs = [raw[i:i + 24] for i in range(0, len(raw), 24)]
req = [r for r in recs if struct.unpack_from("<I", r, 8)[0] == 0x602 and r[16:24] == bytes.fromhex("4018100100000000")]
ans = [r for r in recs if struct.unpack_from("<I", r, 8)[0] == 0x582 and r[16] == 0x43 and r[17:20] == bytes.fromhex("181001")]
assert req and req[0][13] & 1, "the hand-sent request is not in the trace as Tx"
assert ans, "no SDO answer from the simulated node 2"
print("    simulated: request Tx, answer 0x582 %s" % ans[0][16:24].hex(" "))
PY
wait "$SIM_PID"

if [ "$RC" -ne 0 ]; then
    echo "---- plugin log (vcan) ----"; tail -n 60 "$WORK/host.log"
    echo "---- plugin log (simulated) ----"; tail -n 40 "$WORK/sim_host.log"
    echo "---- slave log ----"; tail -n 20 "$WORK/slave.log"
    exit 1
fi
echo "PASS: raw frames and bit rate detection"
