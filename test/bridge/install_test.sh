#!/usr/bin/env bash
# scripts/install-bridge.sh with a stub systemctl and a prebuilt binary
# (modbus-bridge "Packaging"): the unit, the binary, uninstall and purge, a
# prefix whose venv the runtime's Docker container made, and the runtime
# archive's sha256 check (local archives, nothing is built).
#
#   test/bridge/install_test.sh CANWORKS_BRIDGE

set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN_SRC="$1"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
fail=0
check() { if eval "$1"; then echo "ok   $2"; else echo "FAIL $2"; fail=1; fi; }

cat > "$T/systemctl" <<STUB
#!/bin/sh
echo "\$*" >> "$T/calls"
[ "\$1" = list-units ] && echo "canworks-bridge@line1.service loaded active running canworks Modbus TCP bridge (line1)"
exit 0
STUB
chmod +x "$T/systemctl"
export CANWORKS_UNIT_DIR="$T/units" CANWORKS_BRIDGE_CONF_DIR="$T/etc" CANWORKS_SYSTEMCTL="$T/systemctl" \
    CANWORKS_MODULES_LOAD_DIR="$T/modules" CANWORKS_MODPROBE=true

"$REPO/scripts/install-bridge.sh" --prefix "$T/opt" --no-deps --without-canopen --binary "$BIN_SRC" > "$T/out"
check '[ -x "$T/opt/bin/canworks-bridge" ]' "the binary is installed"
check 'grep -q "^ExecStart=$T/opt/bin/canworks-bridge --config $T/etc/%i/canworks.json$" "$T/units/canworks-bridge@.service"' \
    "the unit runs one config per instance"
check 'grep -qx "MemoryMax=256M" "$T/units/canworks-bridge@.service" && grep -qx "TasksMax=64" "$T/units/canworks-bridge@.service"' \
    "the unit limits memory and tasks"
check 'grep -qx "daemon-reload" "$T/calls"' "systemd reloads the units"
check '[ -d "$T/etc" ]' "the config folder exists"
check 'grep -qx can-j1939 "$T/modules/canworks-j1939.conf"' "can-j1939 loads at boot"
check 'grep -q "systemctl enable --now canworks-bridge@NAME" "$T/out"' "the next steps are printed"
check '"$T/opt/bin/canworks-bridge" --version | grep -q "^canworks-bridge "' "the installed binary runs"
check '[ -s "$T/opt/VERSION" ]' "the installed version is written next to the binary"
check '[ "$(grep -c "^::canworks-step " "$T/out")" -eq 2 ] && grep -qx "::canworks-step 1/2 Building canworks-bridge" "$T/out" &&
       grep -q "^::canworks-step 2/2 " "$T/out"' "each step prints its progress line"

mkdir -p "$T/etc/line1"
echo '{}' > "$T/etc/line1/canworks.json"
"$REPO/scripts/install-bridge.sh" --prefix "$T/opt" --uninstall > "$T/out"
check 'grep -qx "disable --now canworks-bridge@line1.service" "$T/calls"' "uninstall stops every instance"
check '[ ! -e "$T/units/canworks-bridge@.service" ] && [ ! -e "$T/opt/bin/canworks-bridge" ] && [ ! -e "$T/opt/VERSION" ]' \
    "uninstall removes the unit, binary and version file"
check '[ -f "$T/etc/line1/canworks.json" ]' "uninstall keeps the configs"
"$REPO/scripts/install-bridge.sh" --prefix "$T/opt" --uninstall --purge > "$T/out"
check '[ ! -e "$T/etc" ]' "--purge removes the configs"

# A prefix shared with the canworks plugin: uninstalling the bridge keeps the
# plugin's VERSION and its can-j1939 boot entry.
mkdir -p "$T/shared/lib"
: > "$T/shared/lib/libcanworks_plugin.so"
echo 0.98.1 > "$T/shared/VERSION"
CANWORKS_DEFAULT_PREFIX="$T/shared" "$REPO/scripts/install-bridge.sh" --prefix "$T/shared" --no-deps --without-canopen \
    --binary "$BIN_SRC" > "$T/out"
echo 0.98.1 > "$T/shared/VERSION"
CANWORKS_DEFAULT_PREFIX="$T/shared" "$REPO/scripts/install-bridge.sh" --prefix "$T/shared" --uninstall > "$T/out"
check '[ ! -e "$T/shared/bin/canworks-bridge" ] && grep -qx 0.98.1 "$T/shared/VERSION" &&
       grep -qx can-j1939 "$T/modules/canworks-j1939.conf"' "uninstall beside the plugin keeps the plugin's files"
rm -rf "$T/shared"

# A prefix whose venv another Python made (the runtime's Docker container).
mkdir -p "$T/docker/venv/bin"
printf 'home = /usr/local/bin\nversion = 3.0.1\n' > "$T/docker/venv/pyvenv.cfg"
ln -s "$(command -v python3)" "$T/docker/venv/bin/python"
if "$REPO/scripts/install-bridge.sh" --prefix "$T/docker" --no-deps --without-canopen --binary "$BIN_SRC" > "$T/out" 2>&1; then
    check false "a container's venv is refused"
else
    check 'grep -q "made by another Python" "$T/out" && grep -q -- "--prefix /opt/canworks-bridge" "$T/out"' \
        "a container's venv is refused with the way out"
fi

# The runtime archive: the pinned release's sha256, or the one given with
# --runtime-ref; a mismatch stops before anything is unpacked.
mkdir -p "$T/archive/openplc-runtime-x" "$T/plain"
echo "not a runtime" > "$T/archive/openplc-runtime-x/README"
PIN=$(cat "$REPO/docker/local-runtime/runtime-version")
tar czf "$T/plain/$PIN.tar.gz" -C "$T/archive" openplc-runtime-x
cp "$T/plain/$PIN.tar.gz" "$T/plain/other.tar.gz"
export CANWORKS_RUNTIME_URL="file://$T/plain"
if "$REPO/scripts/install-bridge.sh" --prefix "$T/fetch" --no-deps --without-canopen > "$T/out" 2>&1; then
    check false "a runtime archive with another sha256 is refused"
else
    check 'grep -q "archive $PIN has sha256 .*, expected $(cat "$REPO/docker/local-runtime/runtime-sha256")" "$T/out" &&
           [ ! -e "$T/fetch/src/openplc-runtime" ]' "a runtime archive with another sha256 is refused"
fi
"$REPO/scripts/install-bridge.sh" --prefix "$T/fetch" --no-deps --without-canopen --runtime-ref other > "$T/out" 2>&1 || true
check 'grep -q -- "--runtime-ref other needs the sha256" "$T/out"' "another --runtime-ref needs its sha256"
sum=$(sha256sum "$T/plain/other.tar.gz" | cut -d" " -f1)
"$REPO/scripts/install-bridge.sh" --prefix "$T/fetch" --no-deps --without-canopen --runtime-ref other \
    --runtime-sha256 "$sum" > "$T/out" 2>&1 || true
check 'grep -q "is not an OpenPLC runtime v4 checkout" "$T/out" && [ -f "$T/fetch/src/openplc-runtime/README" ]' \
    "an archive with the given sha256 is unpacked"
exit $fail
