#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2034  # check() evals its single-quoted test (F is used there)
# scripts/install-adapter.sh with stub systemctl, usermod, python3, openssl and
# download (canopen-remote-adapter "Adapter server install script" and
# "Adapter server uninstall"): the file once per version, an uploaded file
# without a download, the old venv removed, the adapter-serve options, dialout
# for slcan, the Python and openssl checks, uninstall of one server and of all.
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
# A fake adapter server file is one line, "canworks-diag X". The stub python
# answers the version check from $T/pyver, -V, FILE --version from the file's
# line, and FILE adapter-serve by logging it and writing the unit it would.
echo 3.11 > "$T/pyver"
cat > "$T/python3" <<STUB
#!/bin/sh
case "\$1" in
    -c) [ "\$(cat "$T/pyver")" != 3.9 ] ;;
    -V) echo "Python \$(cat "$T/pyver")" ;;
    -I) shift 2
        f=\$1; shift
        case "\$1" in
            --version) grep '^canworks-diag ' "\$f" ;;
            adapter-serve)
                echo "diag \$f \$*" >> "$T/calls"
                ch=\$(echo "\$3" | sed -e 's/^[^:]*://' -e 's/[^A-Za-z0-9_-][^A-Za-z0-9_-]*/-/g' -e 's/^-*//')
                touch "$T/units/canworks-adapter-\$ch.service" "$T/avahi/canworks-adapter-\$ch.service" ;;
        esac ;;
esac
STUB
cat > "$T/download" <<STUB
#!/bin/sh
echo "download \$1" >> "$T/calls"
v=\$(echo "\$1" | sed 's|.*/canworks-adapter-\(.*\)\.pyz\$|\1|')
echo "canworks-diag \$v" > "\$2"
STUB
printf '#!/bin/sh\n' > "$T/openssl"
chmod +x "$T/systemctl" "$T/usermod" "$T/python3" "$T/download" "$T/openssl"
mkdir -p "$T/units" "$T/avahi"
export CANWORKS_UNIT_DIR="$T/units" CANWORKS_AVAHI_DIR="$T/avahi" CANWORKS_SYSTEMCTL="$T/systemctl" \
    CANWORKS_USERMOD="$T/usermod" CANWORKS_PYTHON="$T/python3" CANWORKS_OPENSSL="$T/openssl" \
    CANWORKS_ADAPTER_DOWNLOAD="$T/download"
ME=$(id -un)
[ "$ME" != root ] || ME=nobody   # a CI container may run as root
S="$REPO/scripts/install-adapter.sh"
F="$T/opt/canworks-adapter.pyz"
echo "SCRAM-SHA-256\$4096:x\$y:z" > "$T/verifier"
mkdir -p "$T/opt/venv/bin"   # what an older install left

"$S" --prefix "$T/opt" --version 1.2.3 --adapter socketcan:can0 --bitrate 500 --user "$ME" --allow-changes \
    --verifier-file "$T/verifier" > "$T/out"
check 'grep -qx "download https://github.com/tonihoohoo/canworks/releases/download/deploy-v1.2.3/canworks-adapter-1.2.3.pyz" "$T/calls"' \
    "the release's file is downloaded"
check 'grep -qx "canworks-diag 1.2.3" "$F" && [ ! -e "$T/opt/venv" ]' "it is installed and the old venv is gone"
check 'grep -qx "diag $F adapter-serve --adapter socketcan:can0 --bitrate 500 --port 7536 --install-service --service-user $ME --allow-changes --token-verifier-file $T/verifier" "$T/calls"' \
    "the installed file installs the service for the user with the verifier"
check 'grep -q "^::canworks-step 1/2 Installing the adapter server 1.2.3" "$T/out" && grep -q "^::canworks-step 2/2 Starting the adapter server on can0" "$T/out"' \
    "step lines"
check '! grep -qi "token:" "$T/out"' "no token is printed"
check '! grep -q usermod "$T/calls"' "no dialout for SocketCAN"
check '! grep -q pip "$T/calls"' "no pip"

: > "$T/calls"
"$S" --prefix "$T/opt" --version 1.2.3 --adapter slcan:/dev/ttyACM0 --bitrate 250 --user "$ME" --port 7537 \
    --without-discovery > "$T/out"
check '! grep -q "^download" "$T/calls"' "the same version is not downloaded again"
check 'grep -q "^::canworks-step 1/2 The adapter server 1.2.3 is installed" "$T/out"' "and the step says so"
if getent group dialout >/dev/null 2>&1; then
    check 'grep -qx "usermod -aG dialout $ME" "$T/calls"' "slcan: the user joins dialout"
fi
check 'grep -q -- "--port 7537 --install-service --service-user $ME --without-discovery$" "$T/calls"' \
    "read-only, own port, no advertisement"

: > "$T/calls"
echo "canworks-diag 1.2.4" > "$T/canworks-adapter-1.2.4.pyz"
"$S" --prefix "$T/opt" --version 1.2.4 --file "$T/canworks-adapter-1.2.4.pyz" --adapter socketcan:can0 \
    --bitrate 500 --user "$ME" > "$T/out"
check '! grep -q "^download" "$T/calls" && grep -qx "canworks-diag 1.2.4" "$F"' "an uploaded file: nothing downloaded"
check '! grep -q -- "--token-verifier-file" "$T/calls"' "without a verifier the server keeps its token"

: > "$T/calls"
echo "canworks-diag 1.2.5" > "$T/up.pyz"
"$S" --prefix "$T/opt" --file "$T/up.pyz" --adapter socketcan:can0 --bitrate 500 --user "$ME" > "$T/out"
check 'grep -qx "canworks-diag 1.2.5" "$F" && ! grep -q "^download" "$T/calls"' "the version comes from --file"
echo "canworks-diag 1.2.6" > "$T/wrong.pyz"
if "$S" --prefix "$T/opt" --version 1.2.7 --file "$T/wrong.pyz" --adapter socketcan:can0 --bitrate 500 \
        --user "$ME" > "$T/out" 2>&1; then
    echo "FAIL a file of another version is refused"; fail=1
else
    check 'grep -q "is version 1.2.6, not 1.2.7" "$T/out" && grep -qx "canworks-diag 1.2.5" "$F"' \
        "a file of another version is refused and the installed one stays"
fi

echo 3.9 > "$T/pyver"
if "$S" --prefix "$T/opt" --version 1.2.8 --adapter socketcan:can0 --bitrate 500 --user "$ME" > "$T/out" 2>&1; then
    echo "FAIL Python 3.9 is refused"; fail=1
else
    check 'grep -q "needs Python 3.11 or newer; this device has Python 3.9" "$T/out" && grep -qx "canworks-diag 1.2.5" "$F"' \
        "Python 3.9 is refused before anything changes"
fi
echo 3.11 > "$T/pyver"
if CANWORKS_OPENSSL=/nonexistent/openssl "$S" --prefix "$T/opt" --version 1.2.8 --adapter socketcan:can0 \
        --bitrate 500 --user "$ME" > "$T/out" 2>&1; then
    echo "FAIL no openssl is refused"; fail=1
else
    check 'grep -q "needs the openssl command" "$T/out" && grep -qx "canworks-diag 1.2.5" "$F"' \
        "no openssl command is refused before anything changes"
fi

"$S" --prefix "$T/opt" --uninstall --adapter slcan:/dev/ttyACM0 > "$T/out"
check '[ ! -e "$T/units/canworks-adapter-dev-ttyACM0.service" ] && [ ! -e "$T/avahi/canworks-adapter-dev-ttyACM0.service" ]' \
    "uninstall removes that server and its advertisement"
check '[ -e "$T/units/canworks-adapter-can0.service" ] && [ -f "$F" ]' "the other server and the file stay"
"$S" --prefix "$T/opt" --uninstall > "$T/out"
check '[ ! -e "$T/units/canworks-adapter-can0.service" ] && [ ! -e "$T/opt" ]' "uninstall of all removes the file"

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
