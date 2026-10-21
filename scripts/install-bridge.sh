#!/usr/bin/env bash
# Installs or updates canworks-bridge, the Modbus TCP bridge
# (docs/modbus-bridge.md), as a systemd service on a Linux device. No OpenPLC
# runtime is needed: the bridge runs the CAN networks itself and serves their
# values as Modbus registers to any PLC or program.
#
# One line, no git checkout (the newest release; run it again to update):
#   curl -LsSf https://github.com/tonihoohoo/canworks/releases/latest/download/install-bridge.sh | sudo bash
#   curl -LsSf .../install-bridge.sh | sudo bash -s -- --instance line1 --config ./line1
# From a macOS or Linux PC, onto a device over SSH (no root on the PC):
#   curl -LsSf .../install-bridge.sh | bash -s -- --ssh pi@rpi.local [--instance NAME --config DIR] [options]
# From Windows: scripts/install-bridge.ps1 -Ssh pi@rpi.local
# From a checkout (installs the checkout):
#   sudo scripts/install-bridge.sh [options]
#
# Release and SSH options:
#   --version X        install release deploy-vX instead of the newest one (from 0.84.0 on)
#   --ssh USER@HOST    run the install on that device over ssh -t (sudo may ask for its password)
#   --port N           SSH port (with --ssh)
#   --identity FILE    SSH key (with --ssh)
#   --dry-run          print what would run, change nothing (with --ssh, or outside a checkout)
#
# Install options:
#   --instance NAME --config DIR
#                      after installing, check the config DIR/canworks.json, copy the
#                      files of DIR to /etc/canworks-bridge/NAME/ and start
#                      canworks-bridge@NAME (with --ssh, DIR is on the PC)
#   --prefix DIR       install into DIR (default /opt/canworks, or /opt/canworks-bridge
#                      when /opt/canworks belongs to an OpenPLC runtime in Docker)
#   --runtime-dir DIR | --runtime-ref REF [--runtime-sha256 HASH]
#   --lely-ref COMMIT  --no-deps  --without-canopen | --without-j1939
#   --binary FILE      --with-link NAME
#   --uninstall [--purge]
#
# Install: builds Lely CANopen and dcfgen into <prefix> (scripts/build-lely.sh)
# and the deploy tool into <prefix>/venv (the bridge runs its EDS lint at every
# load), builds canworks-bridge and installs it to <prefix>/bin/, installs the
# template unit canworks-bridge@.service and creates /etc/canworks-bridge/.
# Bridge instances that were running are restarted on the new binary.
# The build needs the plugin interface headers of the OpenPLC runtime source:
# --runtime-dir uses a checkout, otherwise the script downloads
# Autonomy-Logic/openplc-runtime into <prefix>/src: by default the release the
# project pins (docker/local-runtime/runtime-version), whose archive must match
# the sha256 in docker/local-runtime/runtime-sha256. Another --runtime-ref
# (a tag, branch or commit) needs the sha256 of its archive in
# --runtime-sha256.
#
# One service instance runs one config: --instance/--config, or put it in
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
# --with-link NAME advertises the bridge NAME on the local network and installs
# the remote link for its diagnostics channel (docs/remote-access.md,
# scripts/install-link.sh).
#
# Uninstall: stops and disables every canworks-bridge@ instance, removes the
# unit and the binary (and the remote link when it serves a bridge config, not
# one the runtime installed); the configs in /etc/canworks-bridge stay.
# --purge also removes them.
#
# The one-line forms only install released code, never main. The newest
# release is found from GitHub's releases/latest redirect, so no API token is
# needed.

set -euo pipefail

# Everything runs from main, called on the last line: piped into bash, the
# whole script is read before anything runs, so no command can read the rest
# of the script from stdin.
main() {
SCRIPT=${BASH_SOURCE[0]:-}
REPO=""
if [ -n "$SCRIPT" ] && [ -f "$SCRIPT" ]; then
    REPO="$(cd "$(dirname "$SCRIPT")/.." && pwd)"
fi
GITHUB=${CANWORKS_REPO:-https://github.com/tonihoohoo/canworks}
RAW=${CANWORKS_RAW:-https://raw.githubusercontent.com/tonihoohoo/canworks}
API=${CANWORKS_API:-https://api.github.com/repos/tonihoohoo/canworks}
# Overridable for the tests.
DEFAULT_PREFIX=${CANWORKS_DEFAULT_PREFIX:-/opt/canworks}
FALLBACK_PREFIX=${CANWORKS_FALLBACK_PREFIX:-/opt/canworks-bridge}
PREFIX=$DEFAULT_PREFIX
PREFIX_GIVEN=0
LELY_REF=${LELY_REF:-}
RUNTIME_DIR=""
RUNTIME_REF=""
RUNTIME_SHA256=""
RUNTIME_URL=${CANWORKS_RUNTIME_URL:-https://github.com/Autonomy-Logic/openplc-runtime/archive}  # the tests' archives
DEPS=1
UNINSTALL=0
PURGE=0
WITH_CANOPEN=1
WITH_J1939=1
BINARY=""
UNIT_DIR=${CANWORKS_UNIT_DIR:-/etc/systemd/system}
CONF_DIR=${CANWORKS_BRIDGE_CONF_DIR:-/etc/canworks-bridge}
SYSTEMCTL=${CANWORKS_SYSTEMCTL:-systemctl}
MODULES_LOAD=${CANWORKS_MODULES_LOAD_DIR:-/etc/modules-load.d}/canworks-j1939.conf
MODPROBE=${CANWORKS_MODPROBE:-modprobe}
LINK_DIR=${CANWORKS_LINK_DIR:-/etc/canworks-link}
LINK_NAME=""
INSTANCE=""
CONFIG_DIR=""
UPLOAD_DIR=""
BUILD_DIR=""
VERSION=""
SSH_TARGET=""
SSH_PORT=""
SSH_IDENTITY=""
DRY_RUN=0
# The install options as given, for the release's own install-bridge.sh.
PASS=()

die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }
# Progress for the configurator's install job (device-install): one line
# "::canworks-step N/M text" when a step starts; the release form passes the
# steps it ran before in CANWORKS_STEP_BASE ("?": the total is not known yet).
STEP_BASE=${CANWORKS_STEP_BASE:-0}
STEPS=0
N=0
next_step() { N=$((N + 1)); echo "::canworks-step $((STEP_BASE + N))/$((STEP_BASE + STEPS)) $1"; }
need() { [ "$2" -ge 2 ] || die "$1 needs a value"; }

usage() {
    if [ -f "$SCRIPT" ]; then
        awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$SCRIPT"
    else
        echo "see $GITHUB/blob/main/scripts/install-bridge.sh"
    fi
}

while [ $# -gt 0 ]; do
    case "$1" in
        --version) need "$1" $#; VERSION=${2#deploy-v}; VERSION=${VERSION#v}; shift ;;
        --ssh) need "$1" $#; SSH_TARGET=$2; shift ;;
        --port) need "$1" $#; SSH_PORT=$2; shift ;;
        --identity) need "$1" $#; SSH_IDENTITY=$2; shift ;;
        --dry-run) DRY_RUN=1 ;;
        --instance) need "$1" $#; INSTANCE=$2; shift ;;
        --config) need "$1" $#; CONFIG_DIR=$2; shift ;;
        # Internal: the device side of --ssh --config removes the uploaded folder.
        --remove-config-dir) UPLOAD_DIR=yes ;;
        --prefix) need "$1" $#; PREFIX="$2"; PREFIX_GIVEN=1; PASS+=("$1" "$2"); shift ;;
        --runtime-dir) need "$1" $#; RUNTIME_DIR="$2"; PASS+=("$1" "$2"); shift ;;
        --runtime-ref) need "$1" $#; RUNTIME_REF="$2"; PASS+=("$1" "$2"); shift ;;
        --runtime-sha256) need "$1" $#; RUNTIME_SHA256="$2"; PASS+=("$1" "$2"); shift ;;
        --lely-ref) need "$1" $#; LELY_REF="$2"; PASS+=("$1" "$2"); shift ;;
        --binary) need "$1" $#; BINARY="$2"; PASS+=("$1" "$2"); shift ;;
        --with-link) need "$1" $#; LINK_NAME="$2"; PASS+=("$1" "$2"); shift ;;
        --no-deps) DEPS=0; PASS+=("$1") ;;
        --without-canopen) WITH_CANOPEN=0; PASS+=("$1") ;;
        --without-j1939) WITH_J1939=0; PASS+=("$1") ;;
        --uninstall) UNINSTALL=1; PASS+=("$1") ;;
        --purge) PURGE=1; PASS+=("$1") ;;
        -h|--help) usage; exit 0 ;;
        --) ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

# --- Checks that need nothing installed ----------------------------------------

[ "$WITH_CANOPEN" -eq 1 ] || [ "$WITH_J1939" -eq 1 ] || die "--without-canopen and --without-j1939 leave nothing to build"
if [ -n "$INSTANCE$CONFIG_DIR" ]; then
    if [ -z "$INSTANCE" ] || [ -z "$CONFIG_DIR" ]; then
        die "--instance NAME and --config DIR go together"
    fi
    [[ $INSTANCE =~ ^[A-Za-z0-9_-]+$ ]] || die "--instance $INSTANCE: use letters, digits, - and _ only"
    [ "$UNINSTALL" -eq 0 ] || die "--instance and --config install a bridge; leave them out with --uninstall"
    [ -d "$CONFIG_DIR" ] || die "--config $CONFIG_DIR is not a folder"
    CONFIG_DIR=$(cd "$CONFIG_DIR" && pwd)
fi
if [ -z "$SSH_TARGET" ] && [ -n "$SSH_PORT$SSH_IDENTITY" ]; then
    die "--port and --identity need --ssh USER@HOST"
fi
if [ -n "$UPLOAD_DIR" ]; then
    # Only ever the folder the PC side made with mktemp.
    [[ $CONFIG_DIR == /tmp/canworks-bridge-upload.* ]] || die "--remove-config-dir is only for an uploaded config"
    UPLOAD_DIR=$CONFIG_DIR
fi

IN_CHECKOUT=0
if [ -n "$REPO" ] && [ -f "$REPO/tools/deploy/canworks/_lely_dcf/VERSION" ]; then
    IN_CHECKOUT=1
fi

if [ -n "$SSH_TARGET" ]; then
    ssh_install
elif [ -n "$VERSION" ] || [ "$IN_CHECKOUT" -eq 0 ]; then
    release_install
else
    [ "$DRY_RUN" -eq 0 ] || die "--dry-run works with --ssh or --version, or when the script runs from GitHub"
    checkout_install
fi
}

# --- One-line forms --------------------------------------------------------------

# The newest release: GitHub redirects releases/latest to releases/tag/<tag>.
latest_version() {
    local url tag
    command -v curl >/dev/null 2>&1 || die "curl is needed"
    url=$(curl -fsSL -o /dev/null -w '%{url_effective}' "$GITHUB/releases/latest") ||
        die "could not reach $GITHUB/releases/latest"
    tag=${url##*/}
    if [[ $tag != deploy-v* ]]; then
        # Fallback: the API, once.
        tag=$(curl -fsSL "$API/releases/latest" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1) || tag=""
    fi
    [[ $tag == deploy-v* ]] || die "could not find the newest release at $GITHUB/releases"
    echo "${tag#deploy-v}"
}

# The regular files of the config folder (its EDS and DBC files sit next to it).
config_files() {
    local f
    [ -f "$CONFIG_DIR/canworks.json" ] || die "--config $CONFIG_DIR has no canworks.json"
    for f in "$CONFIG_DIR"/*; do
        [ -f "$f" ] && printf '%s\n' "$f"
    done
    return 0
}

# Downloads the release's source and runs its install-bridge.sh.
release_install() {
    if [ "$DRY_RUN" -eq 0 ] && [ "$(id -u)" != 0 ]; then
        die "run it as root: curl -LsSf $RAW/main/scripts/install-bridge.sh | sudo bash (or --ssh USER@HOST to install on another device)"
    fi
    [ -z "$CONFIG_DIR" ] || config_files >/dev/null
    [ -n "$VERSION" ] || VERSION=$(latest_version)
    local tag=deploy-v$VERSION args=("${PASS[@]+"${PASS[@]}"}")
    [ -z "$INSTANCE" ] || args+=(--instance "$INSTANCE" --config "$CONFIG_DIR")
    [ -z "$UPLOAD_DIR" ] || args+=(--remove-config-dir)
    say "Installing canworks-bridge $VERSION"
    local tarball="$GITHUB/archive/refs/tags/$tag.tar.gz"
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "would download: $tarball"
        printf 'would run: bash <source>/scripts/install-bridge.sh'; printf ' %q' "${args[@]+"${args[@]}"}"; echo
        return 0
    fi
    command -v curl >/dev/null 2>&1 || die "curl is needed"
    echo "::canworks-step 1/? Downloading canworks-bridge $VERSION"
    SRC=$(mktemp -d /tmp/canworks-bridge-install.XXXXXX)
    trap 'rm -rf "${SRC:?}"; [ -z "$UPLOAD_DIR" ] || rm -rf "$UPLOAD_DIR"' EXIT
    curl -fsSL "$tarball" | tar -xz -C "$SRC" --strip-components=1 ||
        die "could not download $tarball"
    [ -f "$SRC/scripts/install-bridge.sh" ] || die "$tarball has no scripts/install-bridge.sh"
    # The source has no git history: the bridge reports the release's version.
    CANWORKS_STEP_BASE=1 CANWORKS_PLUGIN_VERSION=$VERSION bash "$SRC/scripts/install-bridge.sh" "${args[@]+"${args[@]}"}"
}

# Runs the release's install on another device over SSH.
ssh_install() {
    local ssh_opts=() scp_opts=() files=() remote_args remote a up f
    [ -z "$SSH_PORT" ] || { ssh_opts+=(-p "$SSH_PORT"); scp_opts+=(-P "$SSH_PORT"); }
    [ -z "$SSH_IDENTITY" ] || { ssh_opts+=(-i "$SSH_IDENTITY"); scp_opts+=(-i "$SSH_IDENTITY"); }
    if [ -n "$CONFIG_DIR" ]; then
        # A read loop, not mapfile: macOS has bash 3.2.
        while IFS= read -r f; do files+=("$f"); done < <(config_files)
        [ "${#files[@]}" -gt 0 ] || die "--config $CONFIG_DIR has no canworks.json"
    fi
    [ "$DRY_RUN" -eq 1 ] || command -v ssh >/dev/null 2>&1 || die "ssh is needed to install on $SSH_TARGET"
    [ -n "$VERSION" ] || VERSION=$(latest_version)
    remote_args=(--version "$VERSION" "${PASS[@]+"${PASS[@]}"}")
    say "Installing canworks-bridge $VERSION on $SSH_TARGET"
    if [ -n "$INSTANCE" ]; then
        # The config goes to a folder of its own on the device first; the
        # install over ssh -t cannot carry files (its stdin is the terminal).
        if [ "$DRY_RUN" -eq 1 ]; then
            up="<upload folder>"
            echo "would run: ssh ${ssh_opts[*]+"${ssh_opts[*]} "}$SSH_TARGET mktemp -d /tmp/canworks-bridge-upload.XXXXXX"
            echo "would run: scp ${scp_opts[*]+"${scp_opts[*]} "}${files[*]} $SSH_TARGET:$up/"
        else
            up=$(ssh "${ssh_opts[@]+"${ssh_opts[@]}"}" "$SSH_TARGET" "mktemp -d /tmp/canworks-bridge-upload.XXXXXX") ||
                die "could not make an upload folder on $SSH_TARGET"
            [[ $up == /tmp/canworks-bridge-upload.* ]] || die "unexpected upload folder from $SSH_TARGET: $up"
            say "Copying ${#files[@]} config files to $SSH_TARGET"
            scp -q "${scp_opts[@]+"${scp_opts[@]}"}" "${files[@]}" "$SSH_TARGET:$up/" ||
                die "could not copy $CONFIG_DIR to $SSH_TARGET"
        fi
        remote_args+=(--instance "$INSTANCE" --config "$up" --remove-config-dir)
    fi
    # The device runs this script as of the release it installs, pinned to it.
    remote="curl -LsSf $(printf '%q' "$RAW/deploy-v$VERSION/scripts/install-bridge.sh") | sudo bash -s --"
    for a in "${remote_args[@]}"; do remote+=" $(printf '%q' "$a")"; done
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "would run: ssh -t ${ssh_opts[*]+"${ssh_opts[*]} "}$SSH_TARGET \"$remote\""
        return 0
    fi
    exec ssh -t "${ssh_opts[@]+"${ssh_opts[@]}"}" "$SSH_TARGET" "$remote"
}

# A venv the host's Python cannot run: a prefix the OpenPLC runtime's Docker
# container set up (install-stock.sh with a managed install), whose venv was
# made by the container's Python.
foreign_venv() {
    local made runs
    if [ ! -f "$1/venv/pyvenv.cfg" ] || [ ! -x "$1/venv/bin/python" ]; then
        return 1
    fi
    made=$(sed -n 's/^version[_info]* *= *\([0-9]*\.[0-9]*\).*/\1/p' "$1/venv/pyvenv.cfg" | head -n1)
    runs=$("$1/venv/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)
    [ -n "$made" ] && [ "$made" != "$runs" ]
}

# The remote link is the bridge's when it serves a config of a bridge instance.
link_is_ours() {
    local f=$LINK_DIR/link.json
    [ -f "$f" ] && grep -q "\"config\": \"$CONF_DIR/" "$f"
}

cleanup() {
    [ -z "$BUILD_DIR" ] || rm -rf "$BUILD_DIR"
    [ -z "$UPLOAD_DIR" ] || rm -rf "$UPLOAD_DIR"
}

# --- From a checkout ---------------------------------------------------------------

checkout_install() {
trap cleanup EXIT
[ -z "$CONFIG_DIR" ] || config_files >/dev/null
[ -n "$LELY_REF" ] || LELY_REF=$(cat "$REPO/tools/deploy/canworks/_lely_dcf/VERSION")
PINNED_REF=$(cat "$REPO/docker/local-runtime/runtime-version")
PINNED_SHA256=$(cat "$REPO/docker/local-runtime/runtime-sha256")
[ -n "$RUNTIME_REF" ] || RUNTIME_REF=$PINNED_REF

if [ "$PREFIX_GIVEN" -eq 0 ]; then
    # The runtime's Docker container decides first: a bridge binary left in
    # its prefix by an older install does not make the prefix the bridge's.
    if foreign_venv "$PREFIX"; then
        if [ -e "$FALLBACK_PREFIX/bin/canworks-bridge" ]; then
            say "Using the bridge installed in $FALLBACK_PREFIX ($PREFIX belongs to the OpenPLC runtime's Docker container)"
        else
            say "$PREFIX belongs to the OpenPLC runtime's Docker container; installing the bridge into $FALLBACK_PREFIX"
        fi
        PREFIX=$FALLBACK_PREFIX
    elif [ ! -e "$PREFIX/bin/canworks-bridge" ] && [ -e "$FALLBACK_PREFIX/bin/canworks-bridge" ]; then
        PREFIX=$FALLBACK_PREFIX
        say "Using the bridge installed in $PREFIX"
    fi
fi

UNIT="$UNIT_DIR/canworks-bridge@.service"
BIN="$PREFIX/bin/canworks-bridge"

if [ "$UNINSTALL" -eq 1 ]; then
    STEPS=1
    next_step "Removing canworks-bridge"
    for u in $("$SYSTEMCTL" list-units --all --plain --no-legend 'canworks-bridge@*' 2>/dev/null | awk '{print $1}'); do
        "$SYSTEMCTL" disable --now "$u" >/dev/null 2>&1 || true
        say "Stopped $u"
    done
    rm -f "$UNIT" "$BIN" "$PREFIX/VERSION"
    "$SYSTEMCTL" daemon-reload || true
    rm -f "$MODULES_LOAD"
    if [ -f "$UNIT_DIR/canworks-link.service" ] && ! link_is_ours; then
        # Installed for the runtime (install-stock.sh --with-link) or another config.
        say "The remote link serves another config and stays"
    elif [ -f "$UNIT_DIR/canworks-link.service" ]; then
        if [ "$PURGE" -eq 1 ]; then
            "$REPO/scripts/install-link.sh" --uninstall --purge
        else
            "$REPO/scripts/install-link.sh" --uninstall
        fi
    fi
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

# Steps: build tools, Lely, the bridge, the service, the instance, the link
# (those that this run takes).
BUILD_LELY=0
if [ "$WITH_CANOPEN" -eq 1 ] && { [ -z "$BINARY" ] || [ ! -x "$PREFIX/venv/bin/dcfgen" ]; }; then BUILD_LELY=1; fi
STEPS=$((DEPS + BUILD_LELY + 2))
[ -z "$INSTANCE" ] || STEPS=$((STEPS + 1))
[ -z "$LINK_NAME" ] || STEPS=$((STEPS + 1))
if [ "$DEPS" -eq 1 ]; then
    [ "$(id -u)" -eq 0 ] || die "run as root to install build dependencies (or pass --no-deps if they are installed)"
    next_step "Installing build tools"
    say "Installing build dependencies"
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        build-essential cmake pkg-config autoconf automake libtool git curl python3 python3-venv libssl-dev >/dev/null
fi
mkdir -p "$PREFIX/bin"
# A prefix the OpenPLC runtime's Docker container set up: leave it to the
# container (without --prefix the bridge already moved to its own prefix).
if foreign_venv "$PREFIX"; then
    die "$PREFIX/venv was made by another Python (a prefix the runtime's Docker container uses?); install the bridge into its own prefix: --prefix $FALLBACK_PREFIX"
fi
if [ "$WITH_CANOPEN" -eq 1 ]; then
    if [ "$BUILD_LELY" -eq 1 ]; then
        next_step "Building Lely CANopen and dcfgen"
        "$REPO/scripts/build-lely.sh" --prefix "$PREFIX" --ref "$LELY_REF"
    fi
    say "Installing the deploy tool into $PREFIX/venv (EDS lint)"
    "$PREFIX/venv/bin/python" -m pip install -q "$REPO/tools/deploy"
fi

# --- canworks-bridge ----------------------------------------------------------

next_step "Building canworks-bridge"
if [ -n "$BINARY" ]; then
    [ -x "$BINARY" ] || die "--binary $BINARY is not an executable"
    install -m 0755 "$BINARY" "$BIN.new"
else
    pkg-config --atleast-version=3 openssl 2>/dev/null ||
        die "OpenSSL 3 development files are missing: apt-get install libssl-dev"
    if [ -z "$RUNTIME_DIR" ]; then
        RUNTIME_DIR="$PREFIX/src/openplc-runtime"
        if [ -z "$RUNTIME_SHA256" ]; then
            [ "$RUNTIME_REF" = "$PINNED_REF" ] ||
                die "--runtime-ref $RUNTIME_REF needs the sha256 of its archive (--runtime-sha256), or use --runtime-dir"
            RUNTIME_SHA256=$PINNED_SHA256
        fi
        say "Fetching the OpenPLC runtime's plugin headers ($RUNTIME_REF)"
        ARCHIVE=$(mktemp)
        curl -fsSL -o "$ARCHIVE" "$RUNTIME_URL/$RUNTIME_REF.tar.gz" ||
            { rm -f "$ARCHIVE"; die "cannot download the OpenPLC runtime $RUNTIME_REF"; }
        got=$(sha256sum "$ARCHIVE" | cut -d' ' -f1)
        if [ "$got" != "$RUNTIME_SHA256" ]; then
            rm -f "$ARCHIVE"
            die "the OpenPLC runtime archive $RUNTIME_REF has sha256 $got, expected $RUNTIME_SHA256; not building against it"
        fi
        rm -rf "$RUNTIME_DIR"
        mkdir -p "$RUNTIME_DIR"
        tar xzf "$ARCHIVE" -C "$RUNTIME_DIR" --strip-components=1
        rm -f "$ARCHIVE"
    fi
    [ -f "$RUNTIME_DIR/core/src/drivers/plugin_types.h" ] ||
        die "$RUNTIME_DIR is not an OpenPLC runtime v4 checkout (no core/src/drivers/plugin_types.h)"
    BUILD_DIR=$(mktemp -d)
    on_off() { if [ "$1" -eq 1 ]; then echo ON; else echo OFF; fi; }
    say "Building canworks-bridge"
    cmake -S "$REPO" -B "$BUILD_DIR" -DOPENPLC_ROOT="$RUNTIME_DIR" -DCANWORKS_BUILD_TESTS=OFF \
        -DCANWORKS_WITH_CANOPEN="$(on_off "$WITH_CANOPEN")" -DCANWORKS_WITH_J1939="$(on_off "$WITH_J1939")" \
        -DLELY_PREFIX="$PREFIX/lely" -DCANWORKS_PREFIX="$PREFIX" -DCMAKE_BUILD_TYPE=Release >/dev/null
    cmake --build "$BUILD_DIR" --target canworks-bridge -j"$(nproc)" >/dev/null
    install -m 0755 "$BUILD_DIR/bin/canworks-bridge" "$BIN.new"
fi
# Bridges running the old binary get the new one once the unit is in place.
ACTIVE=$("$SYSTEMCTL" list-units --state=active --plain --no-legend 'canworks-bridge@*' 2>/dev/null | awk '{print $1}' || true)
mv -f "$BIN.new" "$BIN"
say "Installed $BIN"
# The installed version, for the configurator's device probe.
v=${CANWORKS_PLUGIN_VERSION:-}
[ -n "$v" ] || v=$(git -C "$REPO" describe --always --tags --dirty 2>/dev/null || echo unknown)
echo "${v#deploy-v}" > "$PREFIX/VERSION"

# --- The service --------------------------------------------------------------

next_step "Installing the service and restarting running bridges"
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
for u in $ACTIVE; do
    [ "$u" != "canworks-bridge@$INSTANCE.service" ] || continue
    "$SYSTEMCTL" restart "$u" || echo "warning: could not restart $u" >&2
    say "Restarted $u on the new binary"
done

if [ "$WITH_J1939" -eq 1 ]; then
    if ! { mkdir -p "$(dirname "$MODULES_LOAD")" && echo can-j1939 > "$MODULES_LOAD"; } 2>/dev/null; then
        echo "warning: cannot write $MODULES_LOAD (not root?): can-j1939 is not loaded at boot" >&2
    fi
    "$MODPROBE" can-j1939 2>/dev/null || echo "warning: cannot load the kernel module can-j1939" >&2
fi

if [ -n "$INSTANCE" ]; then
    next_step "Checking and starting the bridge $INSTANCE"
    install_instance
fi

if [ -n "$LINK_NAME" ]; then
    next_step "Setting up discovery and the remote link"
    "$REPO/scripts/install-link.sh" --config "$CONF_DIR/$LINK_NAME/canworks.json" --runtime-port none
fi

cat <<EOF

canworks-bridge is installed. For each bridge:
  1. Put its config in $CONF_DIR/NAME/canworks.json (EDS files next to it).
     Check it with: $BIN --config $CONF_DIR/NAME/canworks.json --check-only
  2. Start it now and at every boot:  systemctl enable --now canworks-bridge@NAME
  3. Its log:                         journalctl -u canworks-bridge@NAME
Do not run the OpenPLC plugin and a bridge on the same CAN interface.
EOF
}

# --instance NAME --config DIR: check the config where it is, then copy it and
# (re)start the instance. A config that fails its check changes nothing.
install_instance() {
    local unit="canworks-bridge@$INSTANCE.service" dest="$CONF_DIR/$INSTANCE" out f
    say "Checking $CONFIG_DIR/canworks.json"
    if ! out=$("$BIN" --config "$CONFIG_DIR/canworks.json" --check-only 2>&1); then
        printf '%s\n' "$out" >&2
        die "the config in $CONFIG_DIR was not accepted; $dest and $unit are unchanged"
    fi
    [ -z "$out" ] || printf '%s\n' "$out"
    mkdir -p "$dest"
    while IFS= read -r f; do
        install -m 0644 "$f" "$dest/"
    done < <(config_files)
    say "Copied the config to $dest"
    "$SYSTEMCTL" enable "$unit" >/dev/null 2>&1 || die "could not enable $unit"
    "$SYSTEMCTL" restart "$unit" || die "could not start $unit; see journalctl -u $unit"
    say "Started $unit (log: journalctl -u $unit)"
}

main "$@"
