#!/usr/bin/env bash
# scripts/install-link.sh with stub systemctl and pip (remote-access
# "Link and discovery install options"): the unit, link.json, the command, the
# Avahi advertisement with and without the link, uninstall and purge.
#
#   test/link/install_test.sh

set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
fail=0
check() { if eval "$1"; then echo "ok   $2"; else echo "FAIL $2"; fail=1; fi; }

cat > "$T/systemctl" <<STUB
#!/bin/sh
echo "\$*" >> "$T/calls"
exit 0
STUB
# The stub pip puts a canworks-link that only answers "id" into the venv.
cat > "$T/pip" <<'STUB'
#!/bin/sh
mkdir -p "$1/bin"
printf '#!/bin/sh\necho 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n' > "$1/bin/canworks-link"
chmod +x "$1/bin/canworks-link"
echo "$2 $3" > "$1/installed"
STUB
chmod +x "$T/systemctl" "$T/pip"
mkdir -p "$T/avahi"
export CANWORKS_UNIT_DIR="$T/units" CANWORKS_LINK_DIR="$T/etc" CANWORKS_AVAHI_DIR="$T/avahi/services" \
    CANWORKS_BIN_DIR="$T/bin" CANWORKS_SYSTEMCTL="$T/systemctl" CANWORKS_LINK_PIP="$T/pip"

"$REPO/scripts/install-link.sh" --prefix "$T/opt" --config /opt/canworks/lib/canworks.json > "$T/out"
check 'grep -q "iroh>=1.1,<1.2" "$T/opt/venv/installed"' "the venv gets the package and iroh"
check '[ -L "$T/bin/canworks-link" ]' "canworks-link is on the PATH"
check 'grep -q "\"config\": \"/opt/canworks/lib/canworks.json\"" "$T/etc/link.json" && grep -q "\"runtime_port\": 8443" "$T/etc/link.json"' \
    "link.json names the deployed config and the runtime port"
check '[ "$(stat -c %a "$T/etc")" = 700 ]' "the settings folder is private"
check 'grep -q "^ExecStart=$T/opt/venv/bin/canworks-link --dir $T/etc run$" "$T/units/canworks-link.service"' \
    "the unit runs the service"
check 'grep -qx "enable canworks-link.service" "$T/calls" && grep -qx "restart canworks-link.service" "$T/calls"' \
    "the service is enabled and (re)started"
check 'grep -q "<txt-record>id=0123456789abcdef" "$T/avahi/services/canworks.service" && grep -q "<txt-record>link=7533</txt-record>" "$T/avahi/services/canworks.service"' \
    "the advertisement carries the link ID"
check 'grep -q "<type>_canworks._tcp</type>" "$T/avahi/services/canworks.service" && grep -q "<txt-record>runtime=8443</txt-record>" "$T/avahi/services/canworks.service"' \
    "the advertisement names the ports"
check 'grep -q "internet access off" "$T/out"' "the output says internet access is off"

"$REPO/scripts/install-link.sh" --prefix "$T/opt" --uninstall > "$T/out"
check 'grep -qx "disable --now canworks-link.service" "$T/calls"' "uninstall stops the service"
check '[ ! -e "$T/units/canworks-link.service" ] && [ ! -e "$T/bin/canworks-link" ] && [ ! -e "$T/opt" ] && [ ! -e "$T/avahi/services/canworks.service" ]' \
    "uninstall removes the unit, the command, the venv and the advertisement"
check '[ -f "$T/etc/link.json" ]' "uninstall keeps the key and paired PCs"
"$REPO/scripts/install-link.sh" --prefix "$T/opt" --uninstall --purge > "$T/out"
check '[ ! -e "$T/etc" ]' "--purge removes them"

# Discovery only (a bridge, no link): no venv, no runtime port, no ID.
"$REPO/scripts/install-link.sh" --prefix "$T/opt" --without-link --runtime-port none --config /x.json > "$T/out"
check '[ ! -e "$T/opt" ] && [ ! -e "$T/units/canworks-link.service" ]' "--without-link installs no service"
check '! grep -q "runtime=" "$T/avahi/services/canworks.service" && ! grep -q "id=" "$T/avahi/services/canworks.service"' \
    "the advertisement has no runtime port or link ID"

if "$REPO/scripts/install-link.sh" --prefix "$T/opt" > "$T/out" 2>&1; then
    check false "--config is required"
else
    check 'grep -q -- "--config" "$T/out"' "--config is required"
fi
exit $fail
