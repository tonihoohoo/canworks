#!/usr/bin/env bash
# Installs canworks-bridge, the Modbus TCP bridge (docs/modbus-bridge.md), as
# a systemd service on a Linux device. No OpenPLC runtime is needed: the
# bridge runs the CAN networks itself and serves their values as Modbus
# registers to any PLC or program.
#
#   sudo scripts/install-bridge.sh [--prefix /opt/canworks] [--runtime-dir DIR]
#                                  [--runtime-ref development] [--lely-ref <commit>]
#                                  [--no-deps] [--without-canopen | --without-j1939]
#                                  [--binary FILE]
#   sudo scripts/install-bridge.sh --uninstall [--purge] [--prefix /opt/canworks]
#
# Install: builds Lely CANopen and dcfgen into <prefix> (scripts/build-lely.sh)
# and the deploy tool into <prefix>/venv (the bridge runs its EDS lint at every
# load), builds canworks-bridge and installs it to <prefix>/bin/, installs the
# template unit canworks-bridge@.service and creates /etc/canworks-bridge/.
# The build needs the plugin interface headers of the OpenPLC runtime source:
# --runtime-dir uses a checkout, otherwise the script downloads
# Autonomy-Logic/openplc-runtime at --runtime-ref into <prefix>/src.
#
# One service instance runs one config: put it in
# /etc/canworks-bridge/NAME/canworks.json (its EDS files next to it), then
#   systemctl enable --now canworks-bridge@NAME
# canworks-deploy --bridge HOST replaces the config of a running bridge when
# the config allows it (diagnostics.allow_config_upload).
#
# Protocols: CANopen and J1939 by default; --without-canopen builds J1939 only
# (no Lely or dcfgen), --without-j1939 CANopen only. With J1939 the script
# loads the kernel module can-j1939 and lists it in
# /etc/modules-load.d/canworks-j1939.conf.
#
# --binary FILE installs a canworks-bridge built elsewhere and skips the build
# (and Lely, unless CANopen still needs dcfgen at load).
#
# Uninstall: stops and disables every canworks-bridge@ instance, removes the
# unit and the binary; the configs in /etc/canworks-bridge stay. --purge also
# removes them.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX=/opt/canworks
LELY_REF=${LELY_REF:-$(cat "$REPO/tools/deploy/canworks/_lely_dcf/VERSION")}
RUNTIME_DIR=""
RUNTIME_REF=development
DEPS=1
UNINSTALL=0
PURGE=0
WITH_CANOPEN=1
WITH_J1939=1
BINARY=""
# Overridable for the tests.
UNIT_DIR=${CANWORKS_UNIT_DIR:-/etc/systemd/system}
CONF_DIR=${CANWORKS_BRIDGE_CONF_DIR:-/etc/canworks-bridge}
SYSTEMCTL=${CANWORKS_SYSTEMCTL:-systemctl}
MODULES_LOAD=${CANWORKS_MODULES_LOAD_DIR:-/etc/modules-load.d}/canworks-j1939.conf
MODPROBE=${CANWORKS_MODPROBE:-modprobe}

usage() { sed -n '2,37p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift ;;
        --runtime-dir) RUNTIME_DIR="$2"; shift ;;
        --runtime-ref) RUNTIME_REF="$2"; shift ;;
        --lely-ref) LELY_REF="$2"; shift ;;
        --no-deps) DEPS=0 ;;
        --without-canopen) WITH_CANOPEN=0 ;;
        --without-j1939) WITH_J1939=0 ;;
        --binary) BINARY="$2"; shift ;;
        --uninstall) UNINSTALL=1 ;;
        --purge) PURGE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }

[ "$WITH_CANOPEN" -eq 1 ] || [ "$WITH_J1939" -eq 1 ] || die "--without-canopen and --without-j1939 leave nothing to build"

UNIT="$UNIT_DIR/canworks-bridge@.service"
BIN="$PREFIX/bin/canworks-bridge"

if [ "$UNINSTALL" -eq 1 ]; then
    for u in $("$SYSTEMCTL" list-units --all --plain --no-legend 'canworks-bridge@*' 2>/dev/null | awk '{print $1}'); do
        "$SYSTEMCTL" disable --now "$u" >/dev/null 2>&1 || true
        say "Stopped $u"
    done
    rm -f "$UNIT" "$BIN"
    "$SYSTEMCTL" daemon-reload || true
    rm -f "$MODULES_LOAD"
    if [ "$PURGE" -eq 1 ]; then
        rm -rf "$CONF_DIR"
        say "Removed $CONF_DIR"
    else
        say "The configs in $CONF_DIR stay (--purge removes them)"
    fi
    say "canworks-bridge removed"
    exit 0
fi

# --- Build dependencies, Lely CANopen and dcfgen ------------------------------

if [ "$DEPS" -eq 1 ]; then
    [ "$(id -u)" -eq 0 ] || die "run as root to install build dependencies (or pass --no-deps if they are installed)"
    say "Installing build dependencies"
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        build-essential cmake pkg-config autoconf automake libtool git curl python3 python3-venv libssl-dev >/dev/null
fi
mkdir -p "$PREFIX/bin"
# A prefix the OpenPLC runtime's Docker container set up (install-stock.sh
# with a managed install) has a venv made by the container's Python, which
# the host's Python cannot use. Leave it to the container.
if [ -f "$PREFIX/venv/pyvenv.cfg" ] && [ -x "$PREFIX/venv/bin/python" ]; then
    made=$(sed -n 's/^version[_info]* *= *\([0-9]*\.[0-9]*\).*/\1/p' "$PREFIX/venv/pyvenv.cfg" | head -n1)
    runs=$("$PREFIX/venv/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)
    if [ -n "$made" ] && [ "$made" != "$runs" ]; then
        die "$PREFIX/venv was made with Python $made but runs as ${runs:-nothing} here (a prefix the runtime's Docker container uses?); install the bridge into its own prefix: --prefix /opt/canworks-bridge"
    fi
fi
if [ "$WITH_CANOPEN" -eq 1 ]; then
    if [ -z "$BINARY" ] || [ ! -x "$PREFIX/venv/bin/dcfgen" ]; then
        "$REPO/scripts/build-lely.sh" --prefix "$PREFIX" --ref "$LELY_REF"
    fi
    say "Installing the deploy tool into $PREFIX/venv (EDS lint)"
    "$PREFIX/venv/bin/python" -m pip install -q "$REPO/tools/deploy"
fi

# --- canworks-bridge ----------------------------------------------------------

if [ -n "$BINARY" ]; then
    [ -x "$BINARY" ] || die "--binary $BINARY is not an executable"
    install -m 0755 "$BINARY" "$BIN.new"
else
    pkg-config --atleast-version=3 openssl 2>/dev/null ||
        die "OpenSSL 3 development files are missing: apt-get install libssl-dev"
    if [ -z "$RUNTIME_DIR" ]; then
        RUNTIME_DIR="$PREFIX/src/openplc-runtime"
        say "Fetching the OpenPLC runtime's plugin headers ($RUNTIME_REF)"
        rm -rf "$RUNTIME_DIR"
        mkdir -p "$RUNTIME_DIR"
        curl -fsSL "https://github.com/Autonomy-Logic/openplc-runtime/archive/$RUNTIME_REF.tar.gz" |
            tar xz -C "$RUNTIME_DIR" --strip-components=1
    fi
    [ -f "$RUNTIME_DIR/core/src/drivers/plugin_types.h" ] ||
        die "$RUNTIME_DIR is not an OpenPLC runtime v4 checkout (no core/src/drivers/plugin_types.h)"
    BUILD_DIR=$(mktemp -d)
    trap 'rm -rf "$BUILD_DIR"' EXIT
    on_off() { [ "$1" -eq 1 ] && echo ON || echo OFF; }
    say "Building canworks-bridge"
    cmake -S "$REPO" -B "$BUILD_DIR" -DOPENPLC_ROOT="$RUNTIME_DIR" -DCANWORKS_BUILD_TESTS=OFF \
        -DCANWORKS_WITH_CANOPEN="$(on_off "$WITH_CANOPEN")" -DCANWORKS_WITH_J1939="$(on_off "$WITH_J1939")" \
        -DLELY_PREFIX="$PREFIX/lely" -DCANWORKS_PREFIX="$PREFIX" -DCMAKE_BUILD_TYPE=Release >/dev/null
    cmake --build "$BUILD_DIR" --target canworks-bridge -j"$(nproc)" >/dev/null
    install -m 0755 "$BUILD_DIR/bin/canworks-bridge" "$BIN.new"
fi
mv -f "$BIN.new" "$BIN"
say "Installed $BIN"

# --- The service --------------------------------------------------------------

mkdir -p "$UNIT_DIR" "$CONF_DIR"
cat > "$UNIT" <<EOF
# canworks-bridge: one instance per config, /etc/canworks-bridge/NAME/canworks.json
# (docs/modbus-bridge.md). Installed by scripts/install-bridge.sh.
[Unit]
Description=canworks Modbus TCP bridge (%i)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$BIN --config $CONF_DIR/%i/canworks.json
Restart=on-failure
RestartSec=2
# Port 502 and the CAN link setup (bit rate) need these; the service runs as root.
AmbientCapabilities=CAP_NET_BIND_SERVICE CAP_NET_ADMIN
# A fault in the bridge cannot use up the device's memory or processes.
MemoryMax=256M
TasksMax=64

[Install]
WantedBy=multi-user.target
EOF
"$SYSTEMCTL" daemon-reload
say "Installed $UNIT"

if [ "$WITH_J1939" -eq 1 ]; then
    if ! { mkdir -p "$(dirname "$MODULES_LOAD")" && echo can-j1939 > "$MODULES_LOAD"; } 2>/dev/null; then
        echo "warning: cannot write $MODULES_LOAD (not root?): can-j1939 is not loaded at boot" >&2
    fi
    "$MODPROBE" can-j1939 2>/dev/null || echo "warning: cannot load the kernel module can-j1939" >&2
fi

cat <<EOF

canworks-bridge is installed. For each bridge:
  1. Put its config in $CONF_DIR/NAME/canworks.json (EDS files next to it).
     Check it with: $BIN --config $CONF_DIR/NAME/canworks.json --check-only
  2. Start it now and at every boot:  systemctl enable --now canworks-bridge@NAME
  3. Its log:                         journalctl -u canworks-bridge@NAME
Do not run the OpenPLC plugin and a bridge on the same CAN interface.
EOF
