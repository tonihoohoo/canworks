#!/usr/bin/env bash
# The local runtime end to end (canopen-local-runtime): canworks-local-runtime
# with upstream's runtime image and a bridge image, and the `local` target,
# with a real PLC program through the runtime's own Modbus master.
#
#   test/local-runtime/run.sh --image <bridge image> --strucpp <strucpp command> [--engine docker|podman]
#
# 1. `start` with the bridge image: both containers, first user, saved
#    credentials (mode 600)
# 2. `status`: the runtime answers, the PLC is empty, the bridge waits for a
#    config
# 3. the ping-pong config (a real vcan0 adapter in the file) as an OpenPLC
#    through Modbus config with online diagnostics, put on the bridge with
#    `canworks-deploy --bridge local`: the bridge log says simulation is
#    forced and node 2 is operational; the diagnostics channel through the
#    published port shows the forced simulated network
# 4. the program (program.py: canworks_in, ping = pong + 1, canworks_out;
#    compiled with STruC++ by build_program.mjs) uploaded with the editor's
#    conf/modbus_master.json: the PLC runs and the round trip moves 0x4000
# 5. `stop` and `start`, then `update`: the same certificate fingerprint and
#    credentials, the bridge keeps its config
# 6. `remove --data`: containers, volumes and credentials gone
# Needs the PC tools on PATH (pip install tools/deploy), the container engine,
# Node.js 22 and free ports 8443 and 7531. Leaves nothing behind.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/test/local-runtime"
IMAGE="" STRUCPP="" ENGINE=docker
while [ $# -gt 0 ]; do
    case "$1" in
        --image) IMAGE="$2"; shift ;;
        --strucpp) STRUCPP="$2"; shift ;;
        --engine) ENGINE="$2"; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done
[ -n "$IMAGE" ] && [ -n "$STRUCPP" ] || { sed -n '6p' "$0" >&2; exit 2; }

FAILS=0
ok() { echo "  ok   $*"; }
fail() { echo "  FAIL $*"; FAILS=$((FAILS + 1)); }

WORK=$(mktemp -d)
export CANWORKS_CONFIG_DIR="$WORK/settings"
export CANWORKS_ENGINE="$ENGINE"
SETTINGS="$CANWORKS_CONFIG_DIR/local-runtime.json"
RT=(canworks-local-runtime)
cleanup() {
    "${RT[@]}" remove --data >/dev/null 2>&1
    rm -rf "$WORK"
}
trap cleanup EXIT
saved() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$SETTINGS" "$1"; }
# Captured first: `grep -q` closing a pipe early fails the pipeline under pipefail.
logs() { local text; text=$("$ENGINE" logs canworks-local-bridge 2>&1); printf '%s\n' "$text"; }
in_logs() { local text; text=$(logs); grep -q "$1" <<<"$text"; }

echo "1. start"
if "${RT[@]}" start --image "$IMAGE" > "$WORK/start.log" 2>&1; then
    ok "started"
else
    cat "$WORK/start.log"; fail "start"; exit 1
fi
grep -q "address localhost:8443, user openplc" "$WORK/start.log" && ok "editor settings printed" ||
    fail "no editor settings in: $(cat "$WORK/start.log")"
[ -f "$SETTINGS" ] && ok "credentials saved" || fail "no $SETTINGS"
[ "$(stat -c %a "$SETTINGS" 2>/dev/null)" = 600 ] && ok "credentials file mode 600" || fail "mode $(stat -c %a "$SETTINGS")"
FP=$(saved fingerprint)

echo "2. status"
# Right after its first boot the runtime can report ERROR for a moment.
for _ in $(seq 1 15); do
    out=$("${RT[@]}" status 2>&1)
    grep -q "PLC: EMPTY" <<<"$out" && break
    sleep 1
done
grep -q "PLC: EMPTY" <<<"$out" && ok "runtime answers, PLC empty" || fail "status: $out"
grep -q "bridge: waiting for a config" <<<"$out" && ok "the bridge waits for a config" || fail "status: $out"

echo "3. the ping-pong config on the local bridge"
mkdir -p "$WORK/project" "$WORK/bundle"
python3 "$HERE/program.py" pingpong "$WORK/project" || fail "program.py pingpong"
if canworks-deploy --config "$WORK/project/canworks.json" --bridge local > "$WORK/deploy.log" 2>&1; then
    ok "deployed with --bridge local"
else
    cat "$WORK/deploy.log"; fail "deploy"
fi
grep -q "the local bridge runs the new config" "$WORK/deploy.log" && ok "deploy says it" || fail "no started notice"
for _ in $(seq 1 60); do
    in_logs "node 2 (pingpong) is operational" && break
    sleep 1
done
in_logs "simulation forced by the runtime environment" && ok "log: simulation forced" || fail "no forced log line"
in_logs "node 2 (pingpong) is operational" && ok "node 2 operational" ||
    { logs | grep CANWORKS | tail -20; fail "node 2 not operational"; }
export CANWORKS_TOKEN=local-runtime-test
st=$(canworks-diag --runtime local status 2>&1)
grep -q "simulation forced by the runtime" <<<"$st" && ok "diagnostics through the published port" ||
    fail "diag status: $st"

echo "4. the PLC program through the runtime's Modbus master"
node "$HERE/build_program.mjs" "$STRUCPP" "$WORK/project/project.st" "$WORK/bundle" \
    --lib "$ROOT/tools/deploy/canworks/library" >/dev/null || fail "build_program.mjs"
if python3 "$HERE/program.py" upload "$WORK/bundle" "$WORK/project/remote.json" > "$WORK/upload.log" 2>&1; then
    ok "uploaded, built and started"
else
    cat "$WORK/upload.log"; fail "upload"
fi
value() { canworks-diag --runtime local --json sim get 2 0x4000 2>/dev/null |
          python3 -c 'import json,sys; print(json.load(sys.stdin)["values"][0]["value"])' 2>/dev/null; }
v1=$(value); sleep 2; v2=$(value)
[ -n "$v1" ] && [ -n "$v2" ] && [ "$v2" -gt "$v1" ] && ok "the round trip runs ($v1 -> $v2)" ||
    fail "0x4000 does not move: '$v1' -> '$v2'"

echo "5. stop, start and update keep the certificate, the credentials and the bridge's config"
"${RT[@]}" stop >/dev/null 2>&1 && "${RT[@]}" start --image "$IMAGE" >/dev/null 2>&1 && ok "stop and start" ||
    fail "stop/start"
[ "$(saved fingerprint)" = "$FP" ] && ok "same fingerprint after start" || fail "fingerprint changed"
if "${RT[@]}" update --image "$IMAGE" > "$WORK/update.log" 2>&1; then ok "update"; else
    cat "$WORK/update.log"; fail "update"; fi
[ "$(saved fingerprint)" = "$FP" ] && ok "same fingerprint after update" || fail "fingerprint changed by update"
out=$("${RT[@]}" status 2>&1)
grep -q "^PLC: [A-Z]" <<<"$out" && ok "saved credentials log in ($(grep '^PLC:' <<<"$out"))" || fail "status after update: $out"
for _ in $(seq 1 60); do
    in_logs "node 2 (pingpong) is operational" && break
    sleep 1
done
in_logs "node 2 (pingpong) is operational" && ok "the new bridge container runs the kept config" ||
    fail "no config after update"

echo "6. remove --data"
"${RT[@]}" remove --data >/dev/null 2>&1
for c in canworks-local-runtime canworks-local-bridge; do
    "$ENGINE" container inspect "$c" >/dev/null 2>&1 && fail "container $c left" || ok "container $c gone"
done
for v in canworks-local-runtime-data canworks-local-bridge-config; do
    "$ENGINE" volume inspect "$v" >/dev/null 2>&1 && fail "volume $v left" || ok "volume $v gone"
done
[ -f "$SETTINGS" ] && fail "credentials left" || ok "credentials gone"

[ "$FAILS" -eq 0 ] && echo OK || echo "$FAILS failure(s)"
exit $((FAILS > 0))
