#!/usr/bin/env bash
# The Docker route end to end with a real runtime image (canopen-docker-install).
#
#   sudo test/docker/run.sh [--image ghcr.io/autonomy-logic/openplc-runtime:latest]
#                           [--prefix /opt/canworks-docker] [--iface vcan0]
#
# 1. scripts/install-stock.sh --docker-image builds in the image into <prefix>.
# 2. The installed library loads in the image (no missing libraries).
# 3. Ping-pong on <iface> from a container run with the managed install's flags
#    (--privileged --network host -v /dev:/dev), using the installed library.
# 4. A runtime container with the CANopen bind and PYTHONPATH: the editor hook
#    is active, adds a disabled canworks line to plugins.conf at start, and
#    dcfgen still runs with the PYTHONPATH set.
# 5. The same container started as another runtime version: the line stays
#    disabled and the log names both versions.
# Needs Docker, root, and an existing <iface> (vcan0: modprobe vcan; ip link add).

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE=ghcr.io/autonomy-logic/openplc-runtime:latest
PREFIX=/opt/canworks-docker
IFACE=vcan0
NAME=canopen-docker-test

while [ $# -gt 0 ]; do
    case "$1" in
        --image) IMAGE="$2"; shift ;;
        --prefix) PREFIX="$2"; shift ;;
        --iface) IFACE="$2"; shift ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

FAILS=0
ok() { echo "    ok   $*"; }
fail() { echo "    FAIL $*"; FAILS=$((FAILS + 1)); }
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1; }
trap cleanup EXIT

BIND="$PREFIX:/opt/canworks"
PYPATH="PYTHONPATH=/opt/canworks/lib/sitecustomize"
LINE_DISABLED="canworks,/opt/canworks/lib/libcanworks_plugin.so,0,1,/opt/canworks/lib/canworks.json,"

echo "1. build in $IMAGE"
if ! "$ROOT/scripts/install-stock.sh" --prefix "$PREFIX" --docker-image "$IMAGE"; then
    echo "FAIL: the in-image build failed"; exit 1
fi
VERSION=$(sed -n 1p "$PREFIX/lib/runtime-version")
[ -n "$VERSION" ] && ok "stamped for runtime $VERSION" || fail "no runtime-version stamp"

echo "2. the library loads in the image"
out=$(docker run --rm -v "$BIND" --entrypoint ldd "$IMAGE" /opt/canworks/lib/libcanworks_plugin.so 2>&1)
if [ $? -eq 0 ] && ! grep -q "not found" <<<"$out"; then ok "ldd: all libraries found"; else echo "$out"; fail "ldd"; fi
sim=$(docker run --rm -v "$BIND" --entrypoint /opt/canworks/lib/canworks-sim "$IMAGE" --version 2>&1)
if grep -q "^canworks-sim [^ ]" <<<"$sim"; then
    ok "$sim runs in the image"
else
    fail "canworks-sim --version in the image: '$sim'"
fi

echo "3. ping-pong on $IFACE in a container with the managed flags"
ip link set "$IFACE" up 2>/dev/null || true
SRC=$(mktemp -d)
cp -a "$ROOT/." "$SRC/"
rm -rf "$SRC/build"
if docker run --rm --privileged --network host -v /dev:/dev -v "$BIND" -v "$SRC:/src" -e "$PYPATH" \
    --entrypoint bash "$IMAGE" -c '
        set -e
        command -v ip >/dev/null || { apt-get update -qq && apt-get install -y -qq iproute2 >/dev/null; }
        # The test programs build against OpenSSL, which the runtime image has
        # only as a library.
        pkg-config --exists openssl 2>/dev/null || { apt-get update -qq && apt-get install -y -qq libssl-dev >/dev/null; }
        git config --global --add safe.directory "*"
        cmake -S /src -B /tmp/b -DOPENPLC_ROOT=/workdir -DLELY_PREFIX=/opt/canworks/lely >/dev/null
        cmake --build /tmp/b --target canopen_host pingpong_slave -j"$(nproc)" >/dev/null
        mkdir -p /tmp/b/plugins
        cp /opt/canworks/lib/libcanworks_plugin.so /tmp/b/plugins/
        /src/test/pingpong/run.sh --build-dir /tmp/b --iface '"$IFACE"' --seconds 10'; then
    ok "ping-pong with the installed library"
else
    fail "ping-pong in the container"
fi
rm -rf "$SRC"

# Starts the runtime container like the bootloader does; $1: extra docker args.
start_runtime() {
    docker rm -f "$NAME" >/dev/null 2>&1
    docker run -d --name "$NAME" --privileged --network host -v /dev:/dev -v "$BIND" -e "$PYPATH" "$@" \
        "$IMAGE" >/dev/null || return 1
    for _ in $(seq 1 120); do
        grep -q "canworks editor hook\] \(INFO\|ERROR\): \(added\|restored\|the CANopen\|RUNTIME\)" \
            <<<"$(docker logs "$NAME" 2>&1)" && return 0
        sleep 1
    done
    return 1
}
plugins_line() { docker exec "$NAME" grep '^canworks,' /workdir/plugins.conf 2>/dev/null; }

echo "4. runtime container: hook active, canworks line added at start"
if start_runtime; then
    logs=$(docker logs "$NAME" 2>&1)
    [ "$(plugins_line)" = "$LINE_DISABLED" ] && ok "plugins.conf: $LINE_DISABLED" ||
        fail "plugins.conf canworks line: '$(plugins_line)'"
    grep -q "added a disabled canworks line" <<<"$logs" && ok "log says the line was added" || fail "no 'added' log line"
    # The webserver imports plcapp_management at start; the hook patches it.
    # (Logs are captured first: grep -q closing a pipe early fails it under pipefail.)
    for _ in $(seq 1 30); do
        logs=$(docker logs "$NAME" 2>&1)
        grep -q "editor hook\] INFO: active" <<<"$logs" && break
        sleep 1
    done
    if grep -q "editor hook\] INFO: active" <<<"$logs"; then ok "hook active"; else
        grep "editor hook" <<<"$logs"; fail "hook not active"; fi
    docker exec "$NAME" /opt/canworks/venv/bin/dcfgen --help >/dev/null 2>&1 &&
        ok "dcfgen runs with the PYTHONPATH set" || fail "dcfgen with the PYTHONPATH set"
else
    docker logs "$NAME" 2>&1 | tail -30
    fail "runtime container did not start or the hook said nothing"
fi

echo "5. runtime container as another version: CANopen stays off"
if start_runtime -e RUNTIME_VERSION=v0.0.0-other; then
    logs=$(docker logs "$NAME" 2>&1)
    [ "$(plugins_line)" = "$LINE_DISABLED" ] && ok "canworks disabled" || fail "canworks line: '$(plugins_line)'"
    grep -q "built for runtime $VERSION but the runtime is v0.0.0-other" <<<"$logs" &&
        ok "log names both versions" || { grep "editor hook" <<<"$logs"; fail "no version error"; }
else
    docker logs "$NAME" 2>&1 | tail -30
    fail "runtime container did not start"
fi

[ "$FAILS" -eq 0 ] && echo OK || echo "$FAILS failure(s)"
exit $((FAILS > 0))
