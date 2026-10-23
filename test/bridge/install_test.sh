#!/usr/bin/env bash
# scripts/install-bridge.sh with a stub systemctl and a prebuilt binary
# (modbus-bridge "Packaging"): the unit, the binary, uninstall and purge, and
# a remote link of another config (nothing is built).
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

# A remote link that serves another config is not repointed at a bridge.
mkdir -p "$T/units" "$T/link"
: > "$T/units/canworks-link.service"
echo '{"config": "/opt/canworks/lib/canworks.json"}' > "$T/link/link.json"
CANWORKS_LINK_DIR="$T/link" "$REPO/scripts/install-bridge.sh" --prefix "$T/opt" --no-deps --without-canopen \
    --binary "$BIN_SRC" --with-link line1 > "$T/out"
check 'grep -q "The remote link serves another config and stays; --with-link line1 is skipped" "$T/out" &&
       ! grep -q "Setting up discovery and the remote link" "$T/out" &&
       grep -q "/opt/canworks/lib/canworks.json" "$T/link/link.json"' "another config's remote link stays"
rm -f "$T/units/canworks-link.service"
"$REPO/scripts/install-bridge.sh" --prefix "$T/opt" --uninstall > "$T/out"

exit $fail
