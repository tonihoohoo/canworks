#!/usr/bin/env bash
# scripts/install-bridge.sh with a stub systemctl and a prebuilt binary
# (modbus-bridge "Packaging"): the unit, the binary, uninstall and purge.
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
check 'grep -q "^RuntimeDirectory=canworks$" "$T/units/canworks-bridge@.service"' "the unit keeps the lock folder"
check 'grep -qx "daemon-reload" "$T/calls"' "systemd reloads the units"
check '[ -d "$T/etc" ]' "the config folder exists"
check 'grep -qx can-j1939 "$T/modules/canworks-j1939.conf"' "can-j1939 loads at boot"
check 'grep -q "systemctl enable --now canworks-bridge@NAME" "$T/out"' "the next steps are printed"
check '"$T/opt/bin/canworks-bridge" --version | grep -q "^canworks-bridge "' "the installed binary runs"

mkdir -p "$T/etc/line1"
echo '{}' > "$T/etc/line1/canworks.json"
"$REPO/scripts/install-bridge.sh" --prefix "$T/opt" --uninstall > "$T/out"
check 'grep -qx "disable --now canworks-bridge@line1.service" "$T/calls"' "uninstall stops every instance"
check '[ ! -e "$T/units/canworks-bridge@.service" ] && [ ! -e "$T/opt/bin/canworks-bridge" ]' "uninstall removes the unit and binary"
check '[ -f "$T/etc/line1/canworks.json" ]' "uninstall keeps the configs"
"$REPO/scripts/install-bridge.sh" --prefix "$T/opt" --uninstall --purge > "$T/out"
check '[ ! -e "$T/etc" ]' "--purge removes the configs"
exit $fail
