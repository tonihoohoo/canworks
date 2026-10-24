#!/usr/bin/env bash
# Installs the adapter server (canworks-diag adapter-serve, docs/pc-adapter.md)
# on a Linux device as a service, so PCs on the network commission through the
# device's CAN adapter. The configurator's Devices page runs it to turn the
# remote CAN adapter on, change it and turn it off.
#
#   sudo scripts/install-adapter.sh --adapter socketcan:can0 --bitrate 500 --user USER
#                                   [--port 7536] [--allow-changes] [--without-discovery]
#                                   [--verifier-file FILE] [--version X] [--file canworks-adapter-X.pyz]
#                                   [--prefix /opt/canworks-adapter]
#   sudo scripts/install-adapter.sh --uninstall [--adapter socketcan:can0] [--prefix ...]
#
# Install: the adapter server file of release X (the newest without --version
# or --file), canworks-adapter-X.pyz, as <prefix>/canworks-adapter.pyz unless
# that version is there already; --file takes one already on the device, so
# nothing is downloaded. The device needs python3 3.11 or newer and the
# openssl command, and nothing else: no pip, no venv, no packages. A venv an
# older install left in <prefix> is removed. USER joins the dialout group for
# a serial (slcan) adapter; then `adapter-serve --install-service
# --service-user USER` writes and (re)starts canworks-adapter-<channel>.service
# running the file as USER, and its Avahi file unless --without-discovery.
# --verifier-file is the token's verifier, made where the token is kept: the
# token itself never comes to the device and is never printed. Without it a
# reinstall keeps the server's token.
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
FILE_ARG=""
UNINSTALL=0
GITHUB=${CANWORKS_REPO:-https://github.com/tonihoohoo/canworks}
# Overridable for the tests.
UNIT_DIR=${CANWORKS_UNIT_DIR:-/etc/systemd/system}
AVAHI_DIR=${CANWORKS_AVAHI_DIR:-/etc/avahi/services}
SYSTEMCTL=${CANWORKS_SYSTEMCTL:-systemctl}
USERMOD=${CANWORKS_USERMOD:-usermod}
PYTHON=${CANWORKS_PYTHON:-python3}
OPENSSL=${CANWORKS_OPENSSL:-openssl}
DOWNLOAD=${CANWORKS_ADAPTER_DOWNLOAD:-}  # the tests' stub: DOWNLOAD URL FILE

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
        --file) [ $# -ge 2 ] || die "--file needs the adapter server file"; FILE_ARG="$2"; shift ;;
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
[ -z "$FILE_ARG" ] || [ -f "$FILE_ARG" ] || die "no such adapter server file: $FILE_ARG"
[ "$(id -u)" = 0 ] || [ -n "$DOWNLOAD" ] || die "run it as root (sudo)"

# What the file needs on the device, before anything is changed.
command -v "$PYTHON" >/dev/null 2>&1 || die "the adapter server needs python3 (3.11 or newer) on this device"
"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' ||
    die "the adapter server needs Python 3.11 or newer; this device has $("$PYTHON" -V 2>&1)"
command -v "$OPENSSL" >/dev/null 2>&1 ||
    die "the adapter server needs the openssl command (its TLS certificate): install the openssl package"

latest_version() {
    local url tag
    command -v curl >/dev/null 2>&1 || die "curl is needed"
    url=$(curl -fsSL -o /dev/null -w '%{url_effective}' "$GITHUB/releases/latest") ||
        die "could not reach $GITHUB/releases/latest"
    tag=${url##*/}
    [[ $tag == deploy-v* ]] || die "could not find the newest release at $GITHUB/releases"
    echo "${tag#deploy-v}"
}

# --- The adapter server file -----------------------------------------------------------

FILE="$PREFIX/canworks-adapter.pyz"
file_version() { "$PYTHON" -I -S "$1" --version 2>/dev/null | awk '{ print $NF }'; }
if [ -z "$VERSION" ] && [ -n "$FILE_ARG" ]; then
    VERSION=$(file_version "$FILE_ARG")
    [ -n "$VERSION" ] || die "$FILE_ARG is not an adapter server file"
fi
[ -n "$VERSION" ] || VERSION=$(latest_version)
have=""
[ -f "$FILE" ] && have=$(file_version "$FILE")
if [ "$have" = "$VERSION" ]; then
    echo "::canworks-step 1/2 The adapter server $VERSION is installed"
else
    echo "::canworks-step 1/2 Installing the adapter server $VERSION"
    mkdir -p "$PREFIX"
    tmp="$PREFIX/.canworks-adapter.pyz.new"
    if [ -n "$FILE_ARG" ]; then
        cp "$FILE_ARG" "$tmp"
    else
        url="$GITHUB/releases/download/deploy-v$VERSION/canworks-adapter-$VERSION.pyz"
        if [ -n "$DOWNLOAD" ]; then
            "$DOWNLOAD" "$url" "$tmp" || die "could not download $url"
        else
            command -v curl >/dev/null 2>&1 || die "curl is needed to download the adapter server (or give --file)"
            curl -fsSL -o "$tmp" "$url" || die "could not download $url"
        fi
    fi
    got=$(file_version "$tmp")
    if [ "$got" != "$VERSION" ]; then
        rm -f "$tmp"
        die "the adapter server file is version ${got:-unknown}, not $VERSION"
    fi
    chmod 0644 "$tmp"
    mv -f "$tmp" "$FILE"
fi
if [ -d "$PREFIX/venv" ]; then
    rm -rf "${PREFIX:?}/venv"
    say "Removed the old venv in $PREFIX (the server now runs from one file)"
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
"$PYTHON" -I -S "$FILE" adapter-serve "${opts[@]}"
say "Adapter server on $ADAPTER at $BITRATE kbit/s, port $PORT, $( [ "$ALLOW_CHANGES" -eq 1 ] && echo "changes allowed" || echo "read-only")"
