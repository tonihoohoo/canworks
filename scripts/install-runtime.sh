#!/usr/bin/env bash
# Installs or updates the canworks runtime plugin from the newest release,
# without a git checkout: on the device itself, or from a macOS or Linux PC
# onto a remote Linux device over SSH. Run it again to update.
#
# On the device (as root):
#   curl -LsSf https://github.com/tonihoohoo/canworks/releases/latest/download/install-runtime.sh | sudo bash
#   curl -LsSf .../install-runtime.sh | sudo bash -s -- --with-link       # install-stock.sh options pass through
# From a PC, onto a device over SSH (no root on the PC):
#   curl -LsSf .../install-runtime.sh | bash -s -- --ssh pi@rpi.local [--with-link ...]
# From Windows: install-runtime.ps1 -Ssh pi@rpi.local (from the same release)
#
# Own options (every other option goes to the release's scripts/install-stock.sh):
#   --version X        install release deploy-vX instead of the newest one
#   --ssh USER@HOST    run the install on that device over ssh -t (sudo may ask for its password)
#   --port N           SSH port (with --ssh)
#   --identity FILE    SSH key (with --ssh)
#   --dry-run          print what would run, change nothing
#   --with-openplc     when the device has no OpenPLC runtime, install upstream's
#                      (managed Docker, https://runtime.getedge.me) first
#
# It only installs released code, never main. The newest release is found
# from GitHub's releases/latest redirect, so no API token is needed. The tools
# go in with the exact dependency versions the release was tested with (its
# canworks-<version>-constraints.txt asset). Running the release that is
# already installed again builds nothing and leaves the PLC and its program
# alone; --force (an install-stock.sh option) installs it again.

set -euo pipefail

# Everything runs from main, called on the last line: piped into bash, the
# whole script is read before anything runs, so no command can read the rest
# of the script from stdin.
main() {
REPO=${CANWORKS_REPO:-https://github.com/tonihoohoo/canworks}
RAW=${CANWORKS_RAW:-https://raw.githubusercontent.com/tonihoohoo/canworks}
API=${CANWORKS_API:-https://api.github.com/repos/tonihoohoo/canworks}
VERSION=""
SSH_TARGET=""
SSH_PORT=""
SSH_IDENTITY=""
DRY_RUN=0
WITH_OPENPLC=0
PASS=()

die() { echo "install-runtime: $*" >&2; exit 1; }
say() { echo "install-runtime: $*"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --version) [ $# -ge 2 ] || die "--version needs a version"; VERSION=${2#deploy-v}; VERSION=${VERSION#v}; shift ;;
        --ssh) [ $# -ge 2 ] || die "--ssh needs USER@HOST"; SSH_TARGET=$2; shift ;;
        --port) [ $# -ge 2 ] || die "--port needs a number"; SSH_PORT=$2; shift ;;
        --identity) [ $# -ge 2 ] || die "--identity needs a file"; SSH_IDENTITY=$2; shift ;;
        --dry-run) DRY_RUN=1 ;;
        --with-openplc) WITH_OPENPLC=1 ;;
        -h|--help)
            if [ -f "$0" ]; then sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; else echo "see $RAW/main/scripts/install-runtime.sh"; fi
            exit 0 ;;
        --) ;;
        *) PASS+=("$1") ;;
    esac
    shift
done

if [ -z "$SSH_TARGET" ] && [ -n "$SSH_PORT$SSH_IDENTITY" ]; then
    die "--port and --identity need --ssh USER@HOST"
fi

# Installing on this machine needs root; check before downloading anything.
if [ -z "$SSH_TARGET" ] && [ "$DRY_RUN" = 0 ] && [ "$(id -u)" != 0 ]; then
    die "run it as root: curl -LsSf $RAW/main/scripts/install-runtime.sh | sudo bash (or --ssh USER@HOST to install on another device)"
fi

command -v curl >/dev/null 2>&1 || die "curl is needed"

# The newest release: GitHub redirects releases/latest to releases/tag/<tag>.
latest_version() {
    local url tag
    url=$(curl -fsSL -o /dev/null -w '%{url_effective}' "$REPO/releases/latest") ||
        die "could not reach $REPO/releases/latest"
    tag=${url##*/}
    if [[ $tag != deploy-v* ]]; then
        # Fallback: the API, once.
        tag=$(curl -fsSL "$API/releases/latest" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1) || tag=""
    fi
    [[ $tag == deploy-v* ]] || die "could not find the newest release at $REPO/releases"
    echo "${tag#deploy-v}"
}

[ -n "$VERSION" ] || VERSION=$(latest_version)
TAG=deploy-v$VERSION

if [ -n "$SSH_TARGET" ]; then
    # The device runs this script as of the release it installs, with the
    # release pinned, so both sides agree on the version.
    remote="curl -LsSf $(printf '%q' "$RAW/$TAG/scripts/install-runtime.sh") | sudo bash -s -- --version $(printf '%q' "$VERSION")"
    [ "$WITH_OPENPLC" = 0 ] || remote+=" --with-openplc"
    for a in "${PASS[@]+"${PASS[@]}"}"; do remote+=" $(printf '%q' "$a")"; done
    cmd=(ssh -t)
    [ -z "$SSH_PORT" ] || cmd+=(-p "$SSH_PORT")
    [ -z "$SSH_IDENTITY" ] || cmd+=(-i "$SSH_IDENTITY")
    cmd+=("$SSH_TARGET" "$remote")
    say "installing canworks $VERSION on $SSH_TARGET"
    if [ "$DRY_RUN" = 1 ]; then
        echo "would run: ${cmd[*]:0:${#cmd[@]}-1} \"$remote\""
        exit 0
    fi
    command -v ssh >/dev/null 2>&1 || die "ssh is needed to install on $SSH_TARGET"
    exec "${cmd[@]}"
fi

# Is there an OpenPLC runtime: native service, managed Docker or a container?
SERVICE_FILE=${OPENPLC_SERVICE_FILE:-/etc/systemd/system/openplc-runtime.service}
BOOTLOADER_SPEC=${OPENPLC_BOOTLOADER_SPEC:-/var/lib/openplc-bootloader/runtime-spec.json}
OPENPLC_INSTALLER=${CANWORKS_OPENPLC_INSTALLER:-https://runtime.getedge.me}
RUNTIME_URL=${CANWORKS_RUNTIME_URL:-https://127.0.0.1:8443/}
RUNTIME_WAIT=${CANWORKS_RUNTIME_WAIT:-600}
have_runtime() {
    [ -f "$SERVICE_FILE" ] || [ -f "$BOOTLOADER_SPEC" ] && return 0
    command -v docker >/dev/null 2>&1 &&
        docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx 'openplc-runtime\|openplc-bootloader'
}

# Progress lines for the configurator's install job; install-stock.sh numbers
# its own steps after these (CANWORKS_STEP_BASE).
INSTALL_OPENPLC=0
if [ "$WITH_OPENPLC" = 1 ] && ! have_runtime; then INSTALL_OPENPLC=1; fi
BASE=$((1 + INSTALL_OPENPLC))
# The total is not known here yet: "?" until install-stock.sh prints N/M.
step() { echo "::canworks-step $1/? $2"; }

say "installing canworks $VERSION"
TARBALL="$REPO/archive/refs/tags/$TAG.tar.gz"
CONSTRAINTS_URL="$REPO/releases/download/$TAG/canworks-$VERSION-constraints.txt"
UNINSTALLING=0
for a in "${PASS[@]+"${PASS[@]}"}"; do [ "$a" != --uninstall ] || UNINSTALLING=1; done
if [ "$DRY_RUN" = 1 ]; then
    [ "$INSTALL_OPENPLC" = 0 ] || echo "would install the OpenPLC runtime: curl -fsSL $OPENPLC_INSTALLER | bash"
    [ "$UNINSTALLING" = 1 ] || echo "would download: $CONSTRAINTS_URL"
    echo "would download: $TARBALL"
    printf 'would run: CANWORKS_PLUGIN_VERSION=%s bash <source>/scripts/install-stock.sh' "$VERSION"; printf ' %q' "${PASS[@]+"${PASS[@]}"}"; echo
    exit 0
fi

SRC=$(mktemp -d /tmp/canworks-install.XXXXXX)
trap 'rm -rf "$SRC"' EXIT
# The release's locked dependency versions, where its install-stock.sh looks
# for them; first, so a failed download changes nothing. A release from
# before them has none (404) and installs unlocked.
if [ "$UNINSTALLING" = 0 ]; then
    mkdir -p "$SRC/tools/deploy"
    code=$(curl -sSL -o "$SRC/tools/deploy/constraints.txt" -w '%{http_code}' "$CONSTRAINTS_URL" 2>/dev/null) || code=000
    case "$code" in
        200) ;;
        404) rm -f "$SRC/tools/deploy/constraints.txt"
             say "release $VERSION does not lock its dependency versions: pip picks the newest ones the tools allow" ;;
        *) die "could not download canworks-$VERSION-constraints.txt from $CONSTRAINTS_URL (HTTP $code); nothing was changed" ;;
    esac
fi

if [ "$INSTALL_OPENPLC" = 1 ]; then
    step 1 "Installing the OpenPLC runtime (upstream's installer, with Docker)"
    say "no OpenPLC runtime found: installing it with $OPENPLC_INSTALLER"
    curl -fsSL "$OPENPLC_INSTALLER" | bash || die "the OpenPLC runtime install failed (see above); canworks was not installed"
    say "waiting for the runtime to answer at $RUNTIME_URL"
    waited=0
    until [ "$(curl -ks -o /dev/null -w '%{http_code}' "$RUNTIME_URL" 2>/dev/null || true)" != 000 ]; do
        [ "$waited" -lt "$RUNTIME_WAIT" ] || die "the OpenPLC runtime did not answer at $RUNTIME_URL within $RUNTIME_WAIT s"
        sleep 5
        waited=$((waited + 5))
    done
fi

step "$BASE" "Downloading canworks $VERSION"
curl -fsSL "$TARBALL" | tar -xz -C "$SRC" --strip-components=1 ||
    die "could not download $TARBALL"
[ -f "$SRC/scripts/install-stock.sh" ] || die "$TARBALL has no scripts/install-stock.sh"
# The source has no git history: the plugin reports the release's version.
CANWORKS_STEP_BASE=$BASE CANWORKS_PLUGIN_VERSION=$VERSION bash "$SRC/scripts/install-stock.sh" "${PASS[@]+"${PASS[@]}"}"
}

main "$@"
