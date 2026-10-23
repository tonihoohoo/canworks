#!/usr/bin/env bash
# Installs or updates canworks-bridge, the Modbus TCP bridge
# (docs/modbus-bridge.md), as a systemd service on a Linux device. The bridge
# runs the CAN networks itself and serves their values as Modbus registers to
# any PLC or program; with --with-openplc the OpenPLC runtime goes on first.
#
# One line, no git checkout (the newest release; run it again to update):
#   curl -LsSf https://github.com/tonihoohoo/canworks/releases/latest/download/install-bridge.sh | sudo bash
#   curl -LsSf .../install-bridge.sh | sudo bash -s -- --instance line1 --config ./line1
# From a macOS or Linux PC, onto a device over SSH (no root on the PC):
#   curl -LsSf .../install-bridge.sh | bash -s -- --ssh admin@plc.local [--instance NAME --config DIR] [options]
# From Windows: scripts/install-bridge.ps1 -Ssh admin@plc.local
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
#   --prefix DIR       install into DIR (default /opt/canworks)
#   --with-openplc     when the device has no OpenPLC runtime, install upstream's
#                      (managed Docker, https://runtime.getedge.me) first, at the
#                      runtime and bootloader versions this source is pinned to
#                      (docker/local-runtime/runtime-version and bootloader-version)
#   --pinned-runtime   put a managed Docker runtime on the pinned runtime version
#                      (nothing else in the runtime changes; other runtimes stay as they are)
#   --lely-ref COMMIT  --no-deps  --without-canopen | --without-j1939
#   --binary FILE      --with-link NAME  --without-discovery
#   --constraints FILE install the tools with these locked dependency versions (not with --ssh)
#   --uninstall [--purge]
#
# Install: builds Lely CANopen and dcfgen into <prefix> (scripts/build-lely.sh)
# and the deploy tool into <prefix>/venv (the bridge runs its EDS lint at every
# load), builds canworks-bridge (and canworks-canopen-sim with CANopen) and
# installs them to <prefix>/bin/, installs the
# template unit canworks-bridge@.service and creates /etc/canworks-bridge/.
# Bridge instances that were running are restarted on the new binary.
# The build needs this source, Lely CANopen and the system's libraries only.
#
# --with-openplc runs upstream's installer only when no OpenPLC runtime is
# found (no openplc-runtime service, no bootloader runtime spec and no runtime
# container), waits up to 10 minutes until the runtime answers on its local
# HTTPS port and then installs the bridge; a failed runtime install stops
# before the bridge. Nothing of canworks goes into the runtime or its
# container. CANWORKS_RUNTIME_VERSION and CANWORKS_BOOTLOADER_VERSION replace
# the pins, to try another runtime by hand; canworks is only tested with the
# pinned one. --pinned-runtime pulls the pinned runtime image and switches the
# bootloader's runtime spec to it; the runtime container is recreated, so the
# PLC stops and comes back without a program.
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
# --with-link NAME installs the remote link for the diagnostics channel of the
# bridge NAME (docs/remote-access.md, scripts/install-link.sh). The bridge
# (NAME, else the --instance) is advertised on the local network unless
# --without-discovery.
#
# Uninstall: stops and disables every canworks-bridge@ instance, removes the
# unit and the binary (and the remote link when it serves a bridge config);
# the configs in /etc/canworks-bridge stay. The OpenPLC runtime stays.
# --purge also removes them.
#
# The one-line forms only install released code, never main. The newest
# release is found from GitHub's releases/latest redirect, so no API token is
# needed.
#
# Dependency versions: a release installs the tools with the exact versions
# it was tested with (its canworks-<version>-constraints.txt). A checkout uses
# --constraints FILE, else tools/deploy/constraints.txt, else an export of
# tools/deploy/uv.lock when uv is installed; without any of them pip picks
# the newest versions the tools allow.

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
PREFIX=${CANWORKS_DEFAULT_PREFIX:-/opt/canworks}
LELY_REF=${LELY_REF:-}
WITH_OPENPLC=0
PINNED_RUNTIME=0
# The OpenPLC runtime on this device; overridable for the tests.
SERVICE_FILE=${OPENPLC_SERVICE_FILE:-/etc/systemd/system/openplc-runtime.service}
BOOTLOADER_SPEC=${OPENPLC_BOOTLOADER_SPEC:-/var/lib/openplc-bootloader/runtime-spec.json}
OPENPLC_INSTALLER=${CANWORKS_OPENPLC_INSTALLER:-https://runtime.getedge.me}
LOCAL_RUNTIME_URL=${CANWORKS_LOCAL_RUNTIME_URL:-https://127.0.0.1:8443/}
RUNTIME_WAIT=${CANWORKS_RUNTIME_WAIT:-600}
DEPS=1
UNINSTALL=0
PURGE=0
WITH_CANOPEN=1
WITH_J1939=1
BINARY=""
CONSTRAINTS=""
UNIT_DIR=${CANWORKS_UNIT_DIR:-/etc/systemd/system}
CONF_DIR=${CANWORKS_BRIDGE_CONF_DIR:-/etc/canworks-bridge}
SYSTEMCTL=${CANWORKS_SYSTEMCTL:-systemctl}
MODULES_LOAD=${CANWORKS_MODULES_LOAD_DIR:-/etc/modules-load.d}/canworks-j1939.conf
MODPROBE=${CANWORKS_MODPROBE:-modprobe}
LINK_DIR=${CANWORKS_LINK_DIR:-/etc/canworks-link}
LINK_NAME=""
DISCOVERY=1
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
        --prefix) need "$1" $#; PREFIX="$2"; PASS+=("$1" "$2"); shift ;;
        --with-openplc) WITH_OPENPLC=1; PASS+=("$1") ;;
        --pinned-runtime) PINNED_RUNTIME=1; PASS+=("$1") ;;
        --lely-ref) need "$1" $#; LELY_REF="$2"; PASS+=("$1" "$2"); shift ;;
        --binary) need "$1" $#; BINARY="$2"; PASS+=("$1" "$2"); shift ;;
        --with-link) need "$1" $#; LINK_NAME="$2"; PASS+=("$1" "$2"); shift ;;
        --without-discovery) DISCOVERY=0; PASS+=("$1") ;;
        --constraints) need "$1" $#; CONSTRAINTS="$2"; PASS+=("$1" "$2"); shift ;;
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
if [ -n "$SSH_TARGET" ] && [ -n "$CONSTRAINTS" ]; then
    die "--constraints names a file here, not on $SSH_TARGET; the release installs its own locked versions"
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

# The release's locked dependency versions into $2 (lock-dependency-versions).
# A release from before them has none (404) and installs unlocked; any other
# failure stops the install before it changes anything.
fetch_release_constraints() {
    local url="$GITHUB/releases/download/deploy-v$1/canworks-$1-constraints.txt" code
    code=$(curl -sSL -o "$2" -w '%{http_code}' "$url" 2>/dev/null) || code=000
    case "$code" in
        200) ;;
        404) rm -f "$2"; say "Release $1 does not lock its dependency versions: pip picks the newest ones the tools allow" ;;
        *) rm -f "$2"; die "could not download canworks-$1-constraints.txt from $url (HTTP $code); nothing was changed" ;;
    esac
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
    if [ "$UNINSTALL" -eq 1 ]; then say "Uninstalling canworks-bridge (scripts of $VERSION)"; else say "Installing canworks-bridge $VERSION"; fi
    local tarball="$GITHUB/archive/refs/tags/$tag.tar.gz"
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "would download: $tarball"
        [ "$UNINSTALL" -eq 1 ] || [ -n "$CONSTRAINTS" ] ||
            echo "would download: $GITHUB/releases/download/$tag/canworks-$VERSION-constraints.txt"
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
    # Where the release's install-bridge.sh looks for them.
    [ "$UNINSTALL" -eq 1 ] || [ -n "$CONSTRAINTS" ] ||
        fetch_release_constraints "$VERSION" "$SRC/tools/deploy/constraints.txt"
    # The source has no git history: the bridge reports the release's version.
    CANWORKS_STEP_BASE=1 CANWORKS_VERSION=$VERSION bash "$SRC/scripts/install-bridge.sh" "${args[@]+"${args[@]}"}"
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

# The remote link is the bridge's when it serves a config of a bridge instance.
link_is_ours() {
    local f=$LINK_DIR/link.json
    [ -f "$f" ] && grep -q "\"config\": \"$CONF_DIR/" "$f"
}

cleanup() {
    [ -z "$BUILD_DIR" ] || rm -rf "$BUILD_DIR"
    [ -z "$UPLOAD_DIR" ] || rm -rf "$UPLOAD_DIR"
}

# The locked dependency versions for pip: sets PIP_C to pip's -c option, or
# to nothing when no versions are locked.
resolve_constraints() {
    PIP_C=()
    if [ -n "$CONSTRAINTS" ]; then
        [ -f "$CONSTRAINTS" ] || die "no such constraints file: $CONSTRAINTS"
        CONSTRAINTS="$(cd "$(dirname "$CONSTRAINTS")" && pwd)/$(basename "$CONSTRAINTS")"
    elif [ -f "$REPO/tools/deploy/constraints.txt" ]; then
        CONSTRAINTS="$REPO/tools/deploy/constraints.txt"
    elif command -v uv >/dev/null 2>&1 && [ -f "$REPO/tools/deploy/uv.lock" ]; then
        CONSTRAINTS="$PREFIX/constraints.txt"
        uv export --project "$REPO/tools/deploy" --frozen --no-hashes --no-emit-project --no-dev \
            --format requirements-txt -q -o "$CONSTRAINTS" ||
            die "could not export the locked dependency versions from tools/deploy/uv.lock"
    else
        say "The dependency versions are not locked (no --constraints and no uv): pip picks the newest ones the tools allow"
        return 0
    fi
    PIP_C=(-c "$CONSTRAINTS")
}

# --- From a checkout ---------------------------------------------------------------

checkout_install() {
trap cleanup EXIT
[ -z "$CONFIG_DIR" ] || config_files >/dev/null
[ -n "$LELY_REF" ] || LELY_REF=$(cat "$REPO/tools/deploy/canworks/_lely_dcf/VERSION")

UNIT="$UNIT_DIR/canworks-bridge@.service"
BIN="$PREFIX/bin/canworks-bridge"
SIM="$PREFIX/bin/canworks-canopen-sim"

if [ "$UNINSTALL" -eq 1 ]; then
    STEPS=1
    next_step "Removing canworks-bridge"
    for u in $("$SYSTEMCTL" list-units --all --plain --no-legend 'canworks-bridge@*' 2>/dev/null | awk '{print $1}'); do
        "$SYSTEMCTL" disable --now "$u" >/dev/null 2>&1 || true
        say "Stopped $u"
    done
    rm -f "$UNIT" "$BIN" "$SIM" "$PREFIX/VERSION"
    "$SYSTEMCTL" daemon-reload || true
    rm -f "$MODULES_LOAD"
    if [ -f "$UNIT_DIR/canworks-link.service" ] && ! link_is_ours; then
        # Set up by hand for another config.
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
# A remote link set up for another config is not repointed at a bridge.
if [ -n "$LINK_NAME" ] && [ -f "$UNIT_DIR/canworks-link.service" ] && ! link_is_ours; then
    say "The remote link serves another config and stays; --with-link $LINK_NAME is skipped"
    LINK_NAME=""
fi
INSTALL_OPENPLC=0
if [ "$WITH_OPENPLC" -eq 1 ] && ! have_runtime; then INSTALL_OPENPLC=1; fi
# A runtime this run installs is on the pin already; a native one or one in
# a container of its own is left as it is.
SWITCH_RUNTIME=0
if [ "$PINNED_RUNTIME" -eq 1 ] && [ "$INSTALL_OPENPLC" -eq 0 ]; then
    if [ -f "$BOOTLOADER_SPEC" ]; then
        SWITCH_RUNTIME=1
    else
        say "No managed Docker runtime here ($BOOTLOADER_SPEC): --pinned-runtime leaves the runtime as it is"
    fi
fi
if [ "$INSTALL_OPENPLC" -eq 1 ] || [ "$SWITCH_RUNTIME" -eq 1 ]; then read_pins; fi
STEPS=$((DEPS + BUILD_LELY + 2 + INSTALL_OPENPLC + SWITCH_RUNTIME))
[ -z "$INSTANCE" ] || STEPS=$((STEPS + 1))
# The advertisement names a config: the linked instance's, else this one's.
ADVERTISE=""
[ "$DISCOVERY" -eq 0 ] || ADVERTISE=${LINK_NAME:-$INSTANCE}
{ [ -z "$LINK_NAME" ] && [ -z "$ADVERTISE" ]; } || STEPS=$((STEPS + 1))
if [ "$DEPS" -eq 1 ]; then
    [ "$(id -u)" -eq 0 ] || die "run as root to install build dependencies (or pass --no-deps if they are installed)"
    next_step "Installing build tools"
    say "Installing build dependencies"
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        build-essential cmake pkg-config autoconf automake libtool git curl python3 python3-venv libssl-dev >/dev/null
fi
[ "$INSTALL_OPENPLC" -eq 0 ] || install_openplc
[ "$SWITCH_RUNTIME" -eq 0 ] || switch_runtime
mkdir -p "$PREFIX/bin"
if [ "$WITH_CANOPEN" -eq 1 ]; then
    if [ "$BUILD_LELY" -eq 1 ]; then
        next_step "Building Lely CANopen and dcfgen"
        "$REPO/scripts/build-lely.sh" --prefix "$PREFIX" --ref "$LELY_REF"
    fi
    say "Installing the deploy tool into $PREFIX/venv (EDS lint)"
    resolve_constraints
    "$PREFIX/venv/bin/python" -m pip install -q ${PIP_C[@]+"${PIP_C[@]}"} "$REPO/tools/deploy"
fi

# --- canworks-bridge ----------------------------------------------------------

next_step "Building canworks-bridge"
if [ -n "$BINARY" ]; then
    [ -x "$BINARY" ] || die "--binary $BINARY is not an executable"
    install -m 0755 "$BINARY" "$BIN.new"
else
    pkg-config --atleast-version=3 openssl 2>/dev/null ||
        die "OpenSSL 3 development files are missing: apt-get install libssl-dev"
    BUILD_DIR=$(mktemp -d)
    on_off() { if [ "$1" -eq 1 ]; then echo ON; else echo OFF; fi; }
    say "Building canworks-bridge"
    cmake -S "$REPO" -B "$BUILD_DIR" -DCANWORKS_BUILD_TESTS=OFF \
        -DCANWORKS_WITH_CANOPEN="$(on_off "$WITH_CANOPEN")" -DCANWORKS_WITH_J1939="$(on_off "$WITH_J1939")" \
        -DLELY_PREFIX="$PREFIX/lely" -DCANWORKS_PREFIX="$PREFIX" -DCMAKE_BUILD_TYPE=Release >/dev/null
    # The CANopen simulator (docs/simulator.md) comes with a CANopen build.
    targets=(canworks-bridge)
    [ "$WITH_CANOPEN" -eq 0 ] || targets+=(canworks-canopen-sim)
    cmake --build "$BUILD_DIR" --target "${targets[@]}" -j"$(nproc)" >/dev/null
    install -m 0755 "$BUILD_DIR/bin/canworks-bridge" "$BIN.new"
    if [ "$WITH_CANOPEN" -eq 1 ]; then
        install -m 0755 "$BUILD_DIR/bin/canworks-canopen-sim" "$SIM"
        say "Installed $SIM"
    fi
fi
# Bridges running the old binary get the new one once the unit is in place.
ACTIVE=$("$SYSTEMCTL" list-units --state=active --plain --no-legend 'canworks-bridge@*' 2>/dev/null | awk '{print $1}' || true)
mv -f "$BIN.new" "$BIN"
say "Installed $BIN"
# The installed version, for the configurator's device probe: the release's,
# else git describe, else what git archive wrote into scripts/SOURCE_VERSION.
v=${CANWORKS_VERSION:-}
[ -n "$v" ] || v=$(git -C "$REPO" describe --always --tags --dirty 2>/dev/null || true)
if [ -z "$v" ] && [ -r "$REPO/scripts/SOURCE_VERSION" ]; then
    s=$(head -n 1 "$REPO/scripts/SOURCE_VERSION")
    case $s in
        \$Format*) ;;
        *'|'*) v=${s%%|*}; [ -n "$v" ] || v=${s#*|} ;;
    esac
fi
v=${v:-unknown}; echo "${v#deploy-v}" > "$PREFIX/VERSION"

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

# The runtime's port goes into the advertisement when a runtime is here.
RT_PORT=none
! have_runtime || RT_PORT=8443
if [ -n "$LINK_NAME" ]; then
    next_step "Setting up discovery and the remote link"
    if [ "$DISCOVERY" -eq 1 ]; then
        "$REPO/scripts/install-link.sh" --config "$CONF_DIR/$LINK_NAME/canworks.json" --runtime-port "$RT_PORT"
    else
        "$REPO/scripts/install-link.sh" --config "$CONF_DIR/$LINK_NAME/canworks.json" --runtime-port "$RT_PORT" \
            --without-discovery
    fi
elif [ -n "$ADVERTISE" ]; then
    next_step "Advertising the bridge on the local network"
    "$REPO/scripts/install-link.sh" --discovery-only --config "$CONF_DIR/$ADVERTISE/canworks.json" --runtime-port "$RT_PORT"
elif [ -n "$INSTANCE" ] && [ -z "$LINK_NAME" ]; then
    "$REPO/scripts/install-link.sh" --remove-discovery
fi

cat <<EOF

canworks-bridge is installed. For each bridge:
  1. Put its config in $CONF_DIR/NAME/canworks.json (EDS files next to it).
     Check it with: $BIN --config $CONF_DIR/NAME/canworks.json --check-only
  2. Start it now and at every boot:  systemctl enable --now canworks-bridge@NAME
  3. Its log:                         journalctl -u canworks-bridge@NAME
One CAN interface belongs to one bridge.
EOF
}

# --- The OpenPLC runtime ---------------------------------------------------------

# Is there an OpenPLC runtime: native service, managed Docker or a container?
have_runtime() {
    [ -f "$SERVICE_FILE" ] || [ -f "$BOOTLOADER_SPEC" ] && return 0
    command -v docker >/dev/null 2>&1 &&
        docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx 'openplc-runtime\|openplc-bootloader'
}

# The runtime and bootloader this source is pinned to (canopen-ci "One
# runtime pin") into PIN_RT and PIN_BL.
read_pins() {
    PIN_RT=${CANWORKS_RUNTIME_VERSION:-$(sed -n 1p "$REPO/docker/local-runtime/runtime-version" 2>/dev/null || true)}
    PIN_BL=${CANWORKS_BOOTLOADER_VERSION:-$(sed -n 1p "$REPO/docker/local-runtime/bootloader-version" 2>/dev/null || true)}
    [[ $PIN_RT =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "this source names no pinned OpenPLC runtime version"
    [[ $PIN_BL =~ ^[A-Za-z0-9._-]+$ ]] || die "this source names no pinned OpenPLC bootloader version"
}

# --with-openplc on a device without a runtime: upstream's installer at the pins.
install_openplc() {
    local waited=0
    next_step "Installing OpenPLC runtime $PIN_RT (upstream's installer, with Docker)"
    say "No OpenPLC runtime found: installing OpenPLC runtime $PIN_RT with $OPENPLC_INSTALLER"
    curl -fsSL "$OPENPLC_INSTALLER" | bash -s -- --runtime-version "$PIN_RT" --bootloader-version "$PIN_BL" ||
        die "the OpenPLC runtime install failed (see above); the bridge was not installed"
    say "Waiting for the runtime to answer at $LOCAL_RUNTIME_URL"
    until [ "$(curl -ks -o /dev/null -w '%{http_code}' "$LOCAL_RUNTIME_URL" 2>/dev/null || true)" != 000 ]; do
        [ "$waited" -lt "$RUNTIME_WAIT" ] ||
            die "the OpenPLC runtime did not answer at $LOCAL_RUNTIME_URL within $RUNTIME_WAIT s; the bridge was not installed"
        sleep 5
        waited=$((waited + 5))
    done
}

# --pinned-runtime: the managed Docker runtime on the pinned version. The image
# is pulled before anything changes; the bootloader recreates the runtime
# container from the spec.
switch_runtime() {
    local spec_tool=(python3 "$REPO/scripts/docker_spec.py") image
    next_step "Putting the runtime on OpenPLC runtime $PIN_RT (the PLC stops and comes back without a program)"
    command -v docker >/dev/null 2>&1 || die "docker not found, but $BOOTLOADER_SPEC exists"
    if [ "$("${spec_tool[@]}" version "$BOOTLOADER_SPEC")" = "$PIN_RT" ]; then
        say "The runtime is on $PIN_RT already"
        return 0
    fi
    image=$("${spec_tool[@]}" image "$BOOTLOADER_SPEC") || die "cannot read $BOOTLOADER_SPEC; nothing was changed"
    image="${image%:*}:$PIN_RT"
    say "Pulling $image"
    docker pull "$image" >/dev/null || die "the device cannot download OpenPLC runtime $PIN_RT ($image); nothing was changed"
    "${spec_tool[@]}" set-version "$BOOTLOADER_SPEC" "$PIN_RT" || die "could not update $BOOTLOADER_SPEC"
    docker rm -f openplc-runtime >/dev/null 2>&1 || true
    docker restart openplc-bootloader >/dev/null ||
        die "could not restart openplc-bootloader; run: docker restart openplc-bootloader"
    say "The runtime container is recreated on $PIN_RT; upload the program again"
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
