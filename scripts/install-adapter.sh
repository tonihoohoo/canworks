#!/usr/bin/env bash
# Installs the adapter server (canworks-diag adapter-serve, docs/pc-adapter.md)
# on a Linux device as a service, so PCs on the network commission through the
# device's CAN adapter. The configurator's Devices page runs it to turn the
# remote CAN adapter on, change it and turn it off.
#
#   sudo scripts/install-adapter.sh --adapter socketcan:can0 --bitrate 500 --user USER
#                                   [--port 7536] [--allow-changes] [--without-discovery]
#                                   [--verifier-file FILE] [--version X] [--prefix /opt/canworks-adapter]
#   sudo scripts/install-adapter.sh --uninstall [--adapter socketcan:can0] [--prefix ...]
#
# Install: the PC tools of release X (the newest without --version) in
# <prefix>/venv with the release's locked dependency versions, unless that
# version is there already (no Lely, no build); USER joins the dialout group
# for a serial (slcan) adapter; then `canworks-diag adapter-serve
# --install-service --service-user USER` writes and (re)starts
# canworks-adapter-<channel>.service running as USER, and its Avahi file
# unless --without-discovery. --verifier-file is the token's verifier, made
# where the token is kept: the token itself never comes to the device and is
# never printed. Without it a reinstall keeps the server's token.
#
# Uninstall: stops and removes the server of --adapter (every server without
# it) and its Avahi file; <prefix> goes with the last one.

set -euo pipefail

PREFIX=/opt/canworks-adapter
ADAPTER=""
BITRATE=""
SERVICE_USER=""
PORT=7536
ALLOW_CHANGES=0
WITH_DISCOVERY=1
VERIFIER_FILE=""
VERSION=""
UNINSTALL=0
GITHUB=${CANWORKS_REPO:-https://github.com/tonihoohoo/canworks}
# Overridable for the tests.
UNIT_DIR=${CANWORKS_UNIT_DIR:-/etc/systemd/system}
AVAHI_DIR=${CANWORKS_AVAHI_DIR:-/etc/avahi/services}
SYSTEMCTL=${CANWORKS_SYSTEMCTL:-systemctl}
USERMOD=${CANWORKS_USERMOD:-usermod}
PIP=${CANWORKS_ADAPTER_PIP:-}

usage() {
    if [ -f "${BASH_SOURCE[0]:-}" ]; then
        awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]:-}"
    else
        echo "see $GITHUB/blob/main/scripts/install-adapter.sh"
    fi
}

die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --adapter) [ $# -ge 2 ] || die "--adapter needs TYPE:CHANNEL"; ADAPTER="$2"; shift ;;
        --bitrate) [ $# -ge 2 ] || die "--bitrate needs KBIT"; BITRATE="$2"; shift ;;
        --user) [ $# -ge 2 ] || die "--user needs a user name"; SERVICE_USER="$2"; shift ;;
        --port) [ $# -ge 2 ] || die "--port needs a port"; PORT="$2"; shift ;;
        --allow-changes) ALLOW_CHANGES=1 ;;
        --without-discovery) WITH_DISCOVERY=0 ;;
        --verifier-file) [ $# -ge 2 ] || die "--verifier-file needs a file"; VERIFIER_FILE="$2"; shift ;;
        --version) [ $# -ge 2 ] || die "--version needs a version"; VERSION=${2#deploy-v}; VERSION=${VERSION#v}; shift ;;
        --prefix) [ $# -ge 2 ] || die "--prefix needs a folder"; PREFIX="$2"; shift ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

# canworks-adapter-<channel>.service, as localbus/serve.py unit_name() names it.
unit_name() {
    local channel=${1#*:} name
    name=$(printf '%s' "$channel" | sed -e 's/[^A-Za-z0-9_-][^A-Za-z0-9_-]*/-/g' -e 's/^-*//' -e 's/-*$//')
    [ -n "$name" ] || name=${1%%:*}
    echo "canworks-adapter-$name.service"
}

remove_unit() {
    local name=$1
    "$SYSTEMCTL" disable --now "$name" >/dev/null 2>&1 || true
    rm -f "$UNIT_DIR/$name" "$AVAHI_DIR/$name"
    say "Removed $name"
}

if [ "$UNINSTALL" -eq 1 ]; then
    if [ -n "$ADAPTER" ]; then
        echo "::canworks-step 1/1 Removing the adapter server of $ADAPTER"
        remove_unit "$(unit_name "$ADAPTER")"
    else
        echo "::canworks-step 1/1 Removing the adapter servers"
        for f in "$UNIT_DIR"/canworks-adapter-*.service; do
            [ -f "$f" ] && remove_unit "$(basename "$f")"
        done
    fi
    "$SYSTEMCTL" daemon-reload || true
    left=0
    for f in "$UNIT_DIR"/canworks-adapter-*.service; do [ -f "$f" ] && left=1; done
    if [ "$left" -eq 0 ] && [ -d "$PREFIX" ]; then
        rm -rf "${PREFIX:?}"
        say "Removed $PREFIX (no adapter server left)"
    fi
    exit 0
fi

[ -n "$ADAPTER" ] || die "give --adapter TYPE:CHANNEL, e.g. socketcan:can0 (see --help)"
case "$ADAPTER" in socketcan:?*|slcan:?*|gs_usb:?*) ;; *) die "--adapter is socketcan:IF, slcan:PORT or gs_usb:N" ;; esac
case "$BITRATE" in ''|*[!0-9]*) die "give the bus's bit rate with --bitrate KBIT; it is never guessed" ;; esac
case "$PORT" in ''|*[!0-9]*) die "--port is a port number" ;; esac
[ -n "$SERVICE_USER" ] || die "give --user, the user the server runs as"
[ "$SERVICE_USER" != root ] || die "the server does not run as root: give a normal user with --user"
id "$SERVICE_USER" >/dev/null 2>&1 || die "no user $SERVICE_USER on this device"
[ -z "$VERIFIER_FILE" ] || [ -f "$VERIFIER_FILE" ] || die "no such verifier file: $VERIFIER_FILE"
[ "$(id -u)" = 0 ] || [ -n "$PIP" ] || die "run it as root (sudo)"

latest_version() {
    local url tag
    command -v curl >/dev/null 2>&1 || die "curl is needed"
    url=$(curl -fsSL -o /dev/null -w '%{url_effective}' "$GITHUB/releases/latest") ||
        die "could not reach $GITHUB/releases/latest"
    tag=${url##*/}
    [[ $tag == deploy-v* ]] || die "could not find the newest release at $GITHUB/releases"
    echo "${tag#deploy-v}"
}

# --- The PC tools, in their own venv ----------------------------------------------

[ -n "$VERSION" ] || VERSION=$(latest_version)
DIAG="$PREFIX/venv/bin/canworks-diag"
have=""
if [ -x "$PREFIX/venv/bin/python" ]; then
    have=$("$PREFIX/venv/bin/python" -c 'import importlib.metadata as m; print(m.version("canworks"))' 2>/dev/null) || have=""
fi
if [ "$have" = "$VERSION" ] && [ -x "$DIAG" ]; then
    echo "::canworks-step 1/2 The PC tools $VERSION are installed"
else
    echo "::canworks-step 1/2 Installing the PC tools $VERSION"
    if [ -n "$PIP" ]; then
        "$PIP" "$PREFIX/venv" "$VERSION"   # the tests' stub fills the venv
    else
        command -v python3 >/dev/null 2>&1 || die "python3 is needed for the adapter server"
        if [ ! -x "$PREFIX/venv/bin/python" ]; then
            if ! python3 -m venv "$PREFIX/venv" 2>/dev/null; then
                command -v apt-get >/dev/null 2>&1 || die "python3 -m venv failed: install python3-venv"
                say "Installing python3-venv"
                DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv >/dev/null
                rm -rf "${PREFIX:?}/venv"
                python3 -m venv "$PREFIX/venv" || die "python3 -m venv failed"
            fi
        fi
        rel="$GITHUB/releases/download/deploy-v$VERSION"
        "$PREFIX/venv/bin/python" -m pip install -q --upgrade \
            -c "$rel/canworks-$VERSION-constraints.txt" "canworks @ $rel/canworks-$VERSION-py3-none-any.whl" ||
            die "could not install the PC tools $VERSION into $PREFIX/venv"
    fi
    [ -x "$DIAG" ] || die "the PC tools installed no canworks-diag in $PREFIX/venv"
fi

# --- The service ----------------------------------------------------------------------

echo "::canworks-step 2/2 Starting the adapter server on ${ADAPTER#*:}"
if [ "${ADAPTER%%:*}" = slcan ] && getent group dialout >/dev/null 2>&1; then
    "$USERMOD" -aG dialout "$SERVICE_USER" || die "could not add $SERVICE_USER to the dialout group"
fi
opts=(--adapter "$ADAPTER" --bitrate "$BITRATE" --port "$PORT" --install-service --service-user "$SERVICE_USER")
[ "$ALLOW_CHANGES" -eq 0 ] || opts+=(--allow-changes)
[ -z "$VERIFIER_FILE" ] || opts+=(--token-verifier-file "$VERIFIER_FILE")
[ "$WITH_DISCOVERY" -eq 1 ] || opts+=(--without-discovery)
"$DIAG" adapter-serve "${opts[@]}"
say "Adapter server on $ADAPTER at $BITRATE kbit/s, port $PORT, $( [ "$ALLOW_CHANGES" -eq 1 ] && echo "changes allowed" || echo "read-only")"
