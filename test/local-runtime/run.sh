#!/usr/bin/env bash
# The local simulator runtime end to end (canopen-local-runtime): the image,
# openplc-canopen-runtime and the `local` target, with a real PLC program.
#
#   test/local-runtime/run.sh --image <image> --strucpp <strucpp command> [--engine docker|podman]
#
# 1. `start` with the image: container, first user, saved credentials (mode 600)
# 2. `status`: the runtime answers and the PLC is empty
# 3. the ping-pong config (a real vcan0 adapter in the file) with online
#    diagnostics and pingpong.st (compiled with STruC++ by build_program.mjs)
#    deployed with `--runtime local`: the PLC runs, the log says simulation is
#    forced, node 2 is operational, and the diagnostics channel through the
#    published port shows the forced simulated network and a moving value
# 4. `stop` and `start`, then `update`: the same certificate fingerprint and
#    credentials
# 5. `remove --data`: container, volume and credentials gone
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
[ -n "$IMAGE" ] && [ -n "$STRUCPP" ] || { sed -n '4,5p' "$0" >&2; exit 2; }

FAILS=0
ok() { echo "  ok   $*"; }
fail() { echo "  FAIL $*"; FAILS=$((FAILS + 1)); }

WORK=$(mktemp -d)
export OPENPLC_CANOPEN_CONFIG_DIR="$WORK/settings"
export OPENPLC_CANOPEN_ENGINE="$ENGINE"
SETTINGS="$OPENPLC_CANOPEN_CONFIG_DIR/local-runtime.json"
RT=(openplc-canopen-runtime)
cleanup() {
    "${RT[@]}" remove --data >/dev/null 2>&1
    rm -rf "$WORK"
}
trap cleanup EXIT
saved() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$SETTINGS" "$1"; }
# Captured first: `grep -q` closing a pipe early fails the pipeline under pipefail.
logs() { local text; text=$("$ENGINE" logs openplc-canopen-runtime 2>&1); printf '%s\n' "$text"; }
in_logs() { local text; text=$(logs); grep -q "$1" <<<"$text"; }

echo "1. start"
if "${RT[@]}" start --image "$IMAGE" > "$WORK/start.log" 2>&1; then
    ok "started"
else
    cat "$WORK/start.log"; fail "start"; exit 1
fi
grep -q "address localhost:8443, user openplc, password " "$WORK/start.log" && ok "editor settings printed" ||
    fail "no editor settings in: $(cat "$WORK/start.log")"
[ -f "$SETTINGS" ] && ok "credentials saved" || fail "no $SETTINGS"
[ "$(stat -c %a "$SETTINGS" 2>/dev/null)" = 600 ] && ok "credentials file mode 600" || fail "mode $(stat -c %a "$SETTINGS")"
FP=$(saved fingerprint)

echo "2. status"
out=$("${RT[@]}" status 2>&1)
grep -q "PLC: EMPTY" <<<"$out" && ok "runtime answers, PLC empty" || fail "status: $out"

echo "3. a PLC program with the ping-pong config, deployed to local"
mkdir -p "$WORK/project" "$WORK/bundle"
cp "$ROOT/config/pingpong/cpp-slave.eds" "$ROOT/config/pingpong/simulation.json" "$WORK/project/"
python3 - "$ROOT/config/pingpong/canopen_config.json" "$WORK/project/canopen_config.json" <<'PY'
import hashlib, json, sys
cfg = json.load(open(sys.argv[1]))
assert not cfg["adapter"].get("simulate"), "the test needs a config with a real adapter"
cfg["master"]["diagnostics"] = {"token_sha256": hashlib.sha256(b"local-runtime-test").hexdigest()}
json.dump(cfg, open(sys.argv[2], "w"), indent=2)
PY
node "$HERE/build_program.mjs" "$STRUCPP" "$HERE/pingpong.st" "$WORK/bundle" >/dev/null || fail "build_program.mjs"
if openplc-canopen-deploy --bundle "$WORK/bundle" --config "$WORK/project/canopen_config.json" --runtime local \
        > "$WORK/deploy.log" 2>&1; then
    ok "deployed with --runtime local"
else
    cat "$WORK/deploy.log"; fail "deploy"
fi
grep -q "local simulator runtime: every network runs simulated" "$WORK/deploy.log" && ok "deploy says it" ||
    fail "no local runtime notice"
grep -q "the PLC is running" "$WORK/deploy.log" && ok "PLC running" || fail "PLC not running"
for _ in $(seq 1 60); do
    in_logs "node 2 (pingpong) is operational" && break
    sleep 1
done
in_logs "simulation forced by the runtime environment" && ok "log: simulation forced" || fail "no forced log line"
in_logs "node 2 (pingpong) is operational" && ok "node 2 operational" ||
    { logs | grep CANOPEN | tail -20; fail "node 2 not operational"; }
export OPENPLC_CANOPEN_TOKEN=local-runtime-test
st=$(openplc-canopen-diag --runtime local status 2>&1)
grep -q "simulation forced by the runtime" <<<"$st" && ok "diagnostics through the published port" ||
    fail "diag status: $st"
value() { openplc-canopen-diag --runtime local --json sim get 2 0x4000 2>/dev/null |
          python3 -c 'import json,sys; print(json.load(sys.stdin)["values"][0]["value"])' 2>/dev/null; }
v1=$(value); sleep 2; v2=$(value)
[ -n "$v1" ] && [ -n "$v2" ] && [ "$v2" -gt "$v1" ] && ok "the round trip runs ($v1 -> $v2)" ||
    fail "0x4000 does not move: '$v1' -> '$v2'"

echo "4. stop, start and update keep the certificate and the credentials"
"${RT[@]}" stop >/dev/null 2>&1 && "${RT[@]}" start >/dev/null 2>&1 && ok "stop and start" || fail "stop/start"
[ "$(saved fingerprint)" = "$FP" ] && ok "same fingerprint after start" || fail "fingerprint changed"
if "${RT[@]}" update --image "$IMAGE" > "$WORK/update.log" 2>&1; then ok "update"; else
    cat "$WORK/update.log"; fail "update"; fi
[ "$(saved fingerprint)" = "$FP" ] && ok "same fingerprint after update" || fail "fingerprint changed by update"
out=$("${RT[@]}" status 2>&1)
grep -q "^PLC: [A-Z]" <<<"$out" && ok "saved credentials log in ($(grep '^PLC:' <<<"$out"))" || fail "status after update: $out"

echo "5. remove --data"
"${RT[@]}" remove --data >/dev/null 2>&1
"$ENGINE" container inspect openplc-canopen-runtime >/dev/null 2>&1 && fail "container left" || ok "container gone"
"$ENGINE" volume inspect openplc-canopen-runtime-data >/dev/null 2>&1 && fail "volume left" || ok "volume gone"
[ -f "$SETTINGS" ] && fail "credentials left" || ok "credentials gone"

[ "$FAILS" -eq 0 ] && echo OK || echo "$FAILS failure(s)"
exit $((FAILS > 0))
