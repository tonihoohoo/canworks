#!/usr/bin/env bash
# Device parameter backup and restore on a SocketCAN interface (vcan0 by default).
#
#   test/params/run.sh [--build-dir build] [--iface vcan0]
#
# Runs the simulated RTD module (config/rtd-sensor, node 5) and the real
# libcanworks_plugin.so through canopen_host with the diagnostics channel on
# 127.0.0.1 (changes allowed). Then, with canworks-diag: backs node 5
# up, changes three of its parameters by hand, checks that compare finds the
# three, restores the backup, and checks that compare finds no difference.
# With candump it also checks that nothing was written to 0x1010 (store).

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build"
IFACE=vcan0

while [ $# -gt 0 ]; do
    case "$1" in
        --build-dir) BUILD="$(cd "$2" && pwd)"; shift ;;
        --iface) IFACE="$2"; shift ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

PLUGIN="$BUILD/plugins/libcanworks_plugin.so"
HOST="$BUILD/test/canopen_host"
SLAVE="$BUILD/test/sensor_slave"
for f in "$PLUGIN" "$HOST" "$SLAVE"; do
    [ -f "$f" ] || { echo "missing $f; build the repo first" >&2; exit 2; }
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

export PYTHONPATH="$ROOT/tools/deploy${PYTHONPATH:+:$PYTHONPATH}"
export CANWORKS_TOKEN=params-test-token
PORT=7539
DIAG=(python3 -m canworks.diag --runtime "127.0.0.1:$PORT")

cp "$ROOT/config/rtd-sensor/rtd8.eds" "$WORK/"
python3 - "$ROOT/config/rtd-sensor/canopen_config.json" "$WORK/canopen_config.json" "$IFACE" "$PORT" <<'PY'
import json, os, sys
def verifier(token):  # diag.token_verifier: SCRAM-SHA-256 (docs/diagnostics.md)
    import base64, hashlib, hmac, os
    salt = os.urandom(16)
    sp = hashlib.pbkdf2_hmac("sha256", token.encode(), salt, 4096)
    key = lambda name: hmac.new(sp, name, hashlib.sha256).digest()
    b = lambda x: base64.b64encode(x).decode()
    return "SCRAM-SHA-256$4096:%s$%s:%s" % (b(salt), b(hashlib.sha256(key(b"Client Key")).digest()), b(key(b"Server Key")))
cfg = json.load(open(sys.argv[1]))
cfg["adapter"]["interface"] = sys.argv[3]
cfg["master"]["diagnostics"] = {
    "token_verifier": verifier(os.environ["CANWORKS_TOKEN"]),
    "port": int(sys.argv[4]), "bind": "127.0.0.1", "allow_changes": True}
json.dump(cfg, open(sys.argv[2], "w"), indent=2)
PY

if command -v candump >/dev/null; then
    candump -L "$IFACE,605:7FF" > "$WORK/sdo.log" 2>/dev/null &
    PIDS+=($!)
fi
"$SLAVE" "$IFACE" "$WORK/rtd8.eds" 5 \
    --signal 0x7130:1=200..260 --signal 0x7130:2=300..360 \
    --signal 0x7130:3=400..460 --signal 0x7130:4=-100..-40 > "$WORK/slave.log" 2>&1 &
PIDS+=($!)
sleep 0.5
"$HOST" "$PLUGIN" "$WORK/canopen_config.json" 60 rtd > "$WORK/host.log" 2>&1 &
PIDS+=($!)

fail() {
    echo "FAIL: $*" >&2
    echo "--- host log (tail)" >&2
    tail -30 "$WORK/host.log" >&2
    exit 1
}

echo "==> Waiting for node 5 to boot"
for _ in $(seq 1 40); do
    if "${DIAG[@]}" --json status 2>/dev/null |
            python3 -c 'import json,sys; s=json.load(sys.stdin); sys.exit(0 if any(n["node_id"]==5 and n["booted"] for n in s["nodes"]) else 1)' 2>/dev/null; then
        break
    fi
    sleep 0.5
done
"${DIAG[@]}" status || fail "no status from the diagnostics channel"

cd "$WORK" || exit 2
echo "==> Backup"
"${DIAG[@]}" backup 5 -o backup.dcf --config canopen_config.json || fail "backup failed"
grep -q "^NodeID=5" backup.dcf || fail "backup has no NodeID=5"

echo "==> Changing three parameters by hand"
"${DIAG[@]}" sdo-write 5 0x6112 1 1 --type UNSIGNED8 || fail "sdo-write 0x6112:1"
"${DIAG[@]}" sdo-write 5 0x2000 2 1000 --type UNSIGNED16 || fail "sdo-write 0x2000:2"
"${DIAG[@]}" sdo-write 5 0x6126 1 2.5 --type REAL32 || fail "sdo-write 0x6126:1"

"${DIAG[@]}" compare 5 --with backup.dcf --config canopen_config.json > compare1.txt || { cat compare1.txt; fail "compare failed"; }
cat compare1.txt
grep -q "3 different" compare1.txt || fail "compare did not find the three changes"

echo "==> Restore"
"${DIAG[@]}" restore 5 backup.dcf --config canopen_config.json --yes > restore.txt || { cat restore.txt; fail "restore failed"; }
cat restore.txt
grep -q "3 written, 0 failed" restore.txt || fail "restore did not write the three values"

"${DIAG[@]}" compare 5 --with backup.dcf --config canopen_config.json > compare2.txt || { cat compare2.txt; fail "compare after restore failed"; }
cat compare2.txt
grep -q " 0 different" compare2.txt || fail "values still differ after the restore"

if [ -f "$WORK/sdo.log" ]; then
    sleep 0.2
    # An SDO download initiate to 0x1010 is 2x 10 10 (command, index LE).
    if grep -E " $IFACE 605#2[0-9A-F]1010" "$WORK/sdo.log"; then
        fail "something wrote 0x1010 (store) on node 5"
    fi
    echo "==> No SDO write to 0x1010"
fi
echo "==> Backup, compare and restore passed"
