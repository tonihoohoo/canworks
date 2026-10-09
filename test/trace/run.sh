#!/usr/bin/env bash
# Bus trace end-to-end test on a SocketCAN interface (vcan0 by default).
#
#   test/trace/run.sh [--build-dir build] [--iface vcan0]
#
# Runs the ping-pong (tutorial slave, node 2) with the real plugin through
# canopen_host and read-only diagnostics on 127.0.0.1, then records traces
# with `canworks-diag trace` (this checkout's deploy tool). Passes
# (exit 0) when:
#   - the trace holds the master's SYNC (080) and RPDO1 (202) and the slave's
#     TPDO1 (182) and heartbeat (702), all marked T: Tx means "sent from the
#     PLC's computer", and on vcan the slave runs on the same computer (frames
#     from other devices, marked R, are checked on real hardware);
#   - a trace with --filter 0x180/0x780 holds only identifiers 0x180-0x1FF;
#   - the same frames come out as pcapng and ASC (convert);
#   - a client that stops fetching has its trace ended after 10 s (plugin log);
#   - the ping-pong itself passes (status bit and counter, as test/pingpong).
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
        -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
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
DIAG=("$PY" -m canworks.diag --runtime 127.0.0.1:7539 --token trace-test)

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
python3 - "$CONFIG/canopen_config.json" "$WORK/canopen_config.json" "$IFACE" <<'PY'
import json, sys
def verifier(token):  # diag.token_verifier: SCRAM-SHA-256 (docs/diagnostics.md)
    import base64, hashlib, hmac, os
    salt = os.urandom(16)
    sp = hashlib.pbkdf2_hmac("sha256", token.encode(), salt, 4096)
    key = lambda name: hmac.new(sp, name, hashlib.sha256).digest()
    b = lambda x: base64.b64encode(x).decode()
    return "SCRAM-SHA-256$4096:%s$%s:%s" % (b(salt), b(hashlib.sha256(key(b"Client Key")).digest()), b(key(b"Server Key")))
cfg = json.load(open(sys.argv[1]))
cfg["adapter"]["interface"] = sys.argv[3]
cfg["master"]["diagnostics"] = {"token_verifier": verifier("trace-test"), "port": 7539, "bind": "127.0.0.1"}
json.dump(cfg, open(sys.argv[2], "w"), indent=2)
PY
grep -q token_verifier "$WORK/canopen_config.json" || { echo "FAIL: could not add diagnostics to the config" >&2; exit 1; }

"$SLAVE" "$IFACE" "$WORK/cpp-slave.eds" 2 > "$WORK/slave.log" 2>&1 &
PIDS+=($!)
sleep 0.5

echo "==> Running the plugin on $IFACE for 30 s with read-only diagnostics on 127.0.0.1:7539"
"$HOST" "$PLUGIN" "$WORK/canopen_config.json" 30 > "$WORK/host.log" 2>&1 &
HOST_PID=$!
sleep 3

RC=0
fail() { echo "FAIL: $*" >&2; RC=1; }

echo "==> Trace for 4 s"
"${DIAG[@]}" trace -o "$WORK/all.log" --duration 4 --config "$WORK/canopen_config.json" || fail "trace failed"
dir_of() { awk -v id="$1" '$3 ~ "^"id"#" { print $NF }' "$WORK/all.log" | sort -u | tr '\n' ' '; }
for want in "080 T" "202 T" "182 T" "702 T"; do
    set -- $want
    got="$(dir_of "$1")"
    echo "    $1: $(grep -c " $1#" "$WORK/all.log" || true) frames, direction $got"
    [ "$(grep -c " $1#" "$WORK/all.log" || true)" -gt 0 ] || fail "no $1 frames in the trace"
    [ "$got" = "$2 " ] || fail "$1 frames should all be marked $2, got '$got'"
done

echo "==> Trace for 2 s with --filter 0x180/0x780"
"${DIAG[@]}" trace -o "$WORK/tpdo.log" --duration 2 --filter 0x180/0x780 || fail "filtered trace failed"
other="$("$PY" -c 'import sys
ids = {l.split()[2].split("#")[0] for l in open(sys.argv[1]) if l.strip()}
print(" ".join(sorted(i for i in ids if not 0x180 <= int(i, 16) <= 0x1FF)))' "$WORK/tpdo.log")"
[ -s "$WORK/tpdo.log" ] || fail "the filtered trace is empty"
[ -z "$other" ] || fail "the filtered trace holds other identifiers: $other"

echo "==> Convert to pcapng and ASC and back"
"${DIAG[@]}" convert "$WORK/all.log" "$WORK/all.pcapng" || fail "convert to pcapng failed"
"${DIAG[@]}" convert "$WORK/all.pcapng" "$WORK/back.log" || fail "convert back failed"
"${DIAG[@]}" convert "$WORK/all.log" "$WORK/all.asc" || fail "convert to ASC failed"
cmp -s "$WORK/all.log" "$WORK/back.log" || fail "candump -> pcapng -> candump changed the frames"
[ "$(grep -c ' d \| r ' "$WORK/all.asc" || true)" = "$(wc -l < "$WORK/all.log")" ] || fail "the ASC file has a different frame count"

echo "==> A client that stops fetching"
"$PY" - <<'PY' || fail "idle trace client check failed"
import time
from canworks import diag
c = diag.Client("127.0.0.1", 7539, "trace-test")
c.connect()
r = c.trace_start()
time.sleep(11.5)
try:
    c.trace_fetch(r["next"])
    raise SystemExit("the trace still ran after 11.5 s without a fetch")
except diag.DiagError as e:
    assert "no trace running" in str(e), e
PY

wait "$HOST_PID"
HOST_RC=$?
echo "==> Plugin log (trace lines):"
grep -i "trace" "$WORK/host.log" || true
grep -q "trace of 127.0.0.1 ended: no fetch" "$WORK/host.log" || fail "the plugin did not log the ended idle trace"
[ "$HOST_RC" -eq 0 ] || { tail -20 "$WORK/host.log"; fail "the ping-pong failed while tracing (exit $HOST_RC)"; }
exit $RC
