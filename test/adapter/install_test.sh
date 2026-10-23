#!/usr/bin/env bash
# shellcheck disable=SC2016  # check() evals its single-quoted test
# scripts/install-adapter.sh with stub systemctl, usermod and pip
# (canopen-remote-adapter "Adapter server install script" and "Adapter server
# uninstall"): the PC tools once per version, the adapter-serve options,
# dialout for slcan, uninstall of one server and of all.
#
#   test/adapter/install_test.sh

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
cat > "$T/usermod" <<STUB
#!/bin/sh
echo "usermod \$*" >> "$T/calls"
STUB
# The stub pip makes a python that reports the version and a canworks-diag
# that logs its arguments and writes the unit adapter-serve would.
cat > "$T/pip" <<STUB
#!/bin/sh
echo "pip \$2" >> "$T/calls"
mkdir -p "\$1/bin"
printf '#!/bin/sh\necho %s\n' "\$2" > "\$1/bin/python"
cat > "\$1/bin/canworks-diag" <<'DIAG'
#!/bin/sh
echo "diag \$*" >> "$T/calls"
ch=\$(echo "\$3" | sed -e 's/^[^:]*://' -e 's/[^A-Za-z0-9_-][^A-Za-z0-9_-]*/-/g' -e 's/^-*//')
touch "$T/units/canworks-adapter-\$ch.service" "$T/avahi/canworks-adapter-\$ch.service"
DIAG
chmod +x "\$1/bin/python" "\$1/bin/canworks-diag"
STUB
chmod +x "$T/systemctl" "$T/usermod" "$T/pip"
mkdir -p "$T/units" "$T/avahi"
export CANWORKS_UNIT_DIR="$T/units" CANWORKS_AVAHI_DIR="$T/avahi" CANWORKS_SYSTEMCTL="$T/systemctl" \
    CANWORKS_USERMOD="$T/usermod" CANWORKS_ADAPTER_PIP="$T/pip"
ME=$(id -un)
[ "$ME" != root ] || ME=nobody   # a CI container may run as root
S="$REPO/scripts/install-adapter.sh"
echo "SCRAM-SHA-256\$4096:x\$y:z" > "$T/verifier"

"$S" --prefix "$T/opt" --version 1.2.3 --adapter socketcan:can0 --bitrate 500 --user "$ME" --allow-changes \
    --verifier-file "$T/verifier" > "$T/out"
check 'grep -qx "pip 1.2.3" "$T/calls"' "the PC tools of the release go into the venv"
check 'grep -qx "diag adapter-serve --adapter socketcan:can0 --bitrate 500 --port 7536 --install-service --service-user $ME --allow-changes --token-verifier-file $T/verifier" "$T/calls"' \
    "adapter-serve installs the service for the user with the verifier"
check 'grep -q "^::canworks-step 1/2 Installing the PC tools 1.2.3" "$T/out" && grep -q "^::canworks-step 2/2 Starting the adapter server on can0" "$T/out"' \
    "step lines"
check '! grep -qi "token:" "$T/out"' "no token is printed"
check '! grep -q usermod "$T/calls"' "no dialout for SocketCAN"

: > "$T/calls"
"$S" --prefix "$T/opt" --version 1.2.3 --adapter slcan:/dev/ttyACM0 --bitrate 250 --user "$ME" --port 7537 \
    --without-discovery > "$T/out"
check '! grep -q "^pip" "$T/calls"' "the same version is not installed again"
check 'grep -q "^::canworks-step 1/2 The PC tools 1.2.3 are installed" "$T/out"' "and the step says so"
if getent group dialout >/dev/null 2>&1; then
    check 'grep -qx "usermod -aG dialout $ME" "$T/calls"' "slcan: the user joins dialout"
fi
check 'grep -q -- "--port 7537 --install-service --service-user $ME --without-discovery$" "$T/calls"' \
    "read-only, own port, no advertisement"

: > "$T/calls"
"$S" --prefix "$T/opt" --version 1.2.4 --adapter socketcan:can0 --bitrate 500 --user "$ME" > "$T/out"
check 'grep -qx "pip 1.2.4" "$T/calls"' "another release updates the venv"
check '! grep -q -- "--token-verifier-file" "$T/calls"' "without a verifier the server keeps its token"

"$S" --prefix "$T/opt" --uninstall --adapter slcan:/dev/ttyACM0 > "$T/out"
check '[ ! -e "$T/units/canworks-adapter-dev-ttyACM0.service" ] && [ ! -e "$T/avahi/canworks-adapter-dev-ttyACM0.service" ]' \
    "uninstall removes that server and its advertisement"
check '[ -e "$T/units/canworks-adapter-can0.service" ] && [ -d "$T/opt" ]' "the other server and the venv stay"
"$S" --prefix "$T/opt" --uninstall > "$T/out"
check '[ ! -e "$T/units/canworks-adapter-can0.service" ] && [ ! -e "$T/opt" ]' "uninstall of all removes the venv"

for bad in "--adapter socketcan:can0 --user $ME" "--adapter socketcan:can0 --bitrate 500" \
           "--adapter socketcan:can0 --bitrate 500 --user root" "--adapter remote:x --bitrate 500 --user $ME"; do
    # shellcheck disable=SC2086
    if "$S" --prefix "$T/opt" --version 1.2.3 $bad > "$T/out" 2>&1; then
        echo "FAIL refused: $bad"; fail=1
    else
        echo "ok   refused: $bad"
    fi
done
exit $fail
