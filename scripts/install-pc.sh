#!/bin/sh
# Installs or updates the canworks PC tools (configurator, deploy tool,
# diagnostics) on macOS or Linux, with uv and a uv-managed Python: no Python
# and no admin rights needed. Run it again to update to the newest release.
#
#   curl -LsSf https://github.com/tonihoohoo/canworks/releases/latest/download/install-pc.sh | sh
#   curl -LsSf .../install-pc.sh | sh -s -- --version 0.82.0     # a given release
#   curl -LsSf .../install-pc.sh | sh -s -- --uninstall
#
# Options:
#   --version X    install release deploy-vX instead of the newest one
#   --wheel FILE   install this local wheel instead of a release (CI)
#   --python V     the Python uv uses (default 3.14; a path to an installed Python works too)
#   --no-shortcut  do not add the "canworks configurator" app shortcut
#   --force        install even when this version is already installed
#   --uninstall    remove the tools and the shortcut (uv and the tools' settings stay)
#   --dry-run      print what would run, change nothing
#
# It only installs released wheels, never the code on main. The newest release
# is found from GitHub's releases/latest redirect, so no API token is needed.
# Behind a TLS-inspecting company proxy set UV_NATIVE_TLS=1 (docs/install-pc.md).

set -eu

# Everything runs from main, called on the last line: piped into sh, the whole
# script is read before anything runs.
main() {
REPO=${CANWORKS_REPO:-https://github.com/tonihoohoo/canworks}
API=${CANWORKS_API:-https://api.github.com/repos/tonihoohoo/canworks}
UV_INSTALLER=${CANWORKS_UV_INSTALLER:-https://astral.sh/uv/install.sh}
VERSION=""
WHEEL=""
PYTHON=3.14
# The first uv release that knows the default Python: an older uv is updated.
UV_MIN=0.9.0
UNINSTALL=0
SHORTCUT=1
FORCE=0
DRY_RUN=0

die() { echo "install-pc: $*" >&2; exit 1; }
say() { echo "install-pc: $*"; }

usage() {
    if [ -f "$0" ]; then sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; else echo "see https://github.com/tonihoohoo/canworks/blob/main/scripts/install-pc.sh"; fi
}

while [ $# -gt 0 ]; do
    case "$1" in
        --version) [ $# -ge 2 ] || die "--version needs a version"; VERSION=${2#deploy-v}; VERSION=${VERSION#v}; shift 2 ;;
        --wheel) [ $# -ge 2 ] || die "--wheel needs a file"; WHEEL=$2; shift 2 ;;
        --python) [ $# -ge 2 ] || die "--python needs a version or path"; PYTHON=$2; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        --no-shortcut) SHORTCUT=0; shift ;;
        --force) FORCE=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1 (see --help)" ;;
    esac
done

run() {
    if [ "$DRY_RUN" = 1 ]; then echo "would run: $*"; else "$@"; fi
}

command -v curl >/dev/null 2>&1 || die "curl is needed"

# A folder for the uv installer and the overrides file, removed at the end.
TMP=$(mktemp -d 2>/dev/null || mktemp -d -t canworks-install) || die "could not make a temporary folder"
trap 'rm -rf "$TMP"' EXIT

# uv on PATH, else where its installer puts it, else install it now.
find_uv() {
    if command -v uv >/dev/null 2>&1; then command -v uv; return; fi
    for d in "${XDG_BIN_HOME:-}" "$HOME/.local/bin" "$HOME/.cargo/bin"; do
        if [ -n "$d" ] && [ -x "$d/uv" ]; then echo "$d/uv"; return; fi
    done
    echo ""
}

UV=$(find_uv)
if [ -z "$UV" ]; then
    [ "$UNINSTALL" = 0 ] || die "uv is not installed, so neither are the tools"
    say "installing uv ($UV_INSTALLER)"
    if [ "$DRY_RUN" = 1 ]; then
        echo "would run: curl -LsSf $UV_INSTALLER | sh (with --quiet when it has that option)"
        UV=uv
    else
        curl -LsSf -o "$TMP/uv-install.sh" "$UV_INSTALLER" || die "could not download the uv installer from $UV_INSTALLER"
        # Quietly when it can: its PATH message would come next to this script's own hint.
        if grep -q -e "--quiet" "$TMP/uv-install.sh"; then
            sh "$TMP/uv-install.sh" --quiet || die "could not install uv from $UV_INSTALLER"
        else
            sh "$TMP/uv-install.sh" || die "could not install uv from $UV_INSTALLER"
        fi
        UV=$(find_uv)
        [ -n "$UV" ] || die "uv was installed but not found in ~/.local/bin; open a new terminal and run this again"
    fi
fi

# True when version $1 is older than $2 (both like 0.9.0).
version_lt() {
    [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -t. -k1,1n -k2,2n -k3,3n | head -n 1)" = "$1" ]
}

# A uv too old to know the default Python: update it (uv's own installer
# made it), else say how. An unreadable version is left as it is.
if [ "$UNINSTALL" = 0 ]; then
    UV_VERSION=$("$UV" --version 2>/dev/null | sed -n 's/^uv \([0-9][0-9.]*\).*/\1/p' | head -n 1)
    if [ -n "$UV_VERSION" ] && version_lt "$UV_VERSION" "$UV_MIN"; then
        say "uv $UV_VERSION is older than $UV_MIN; updating it"
        run "$UV" self update ||
            die "could not update uv $UV_VERSION; update it with the tool that installed it (for example brew upgrade uv) and run this again"
    fi
fi

BIN=$("$UV" tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")

if [ "$UNINSTALL" = 1 ]; then
    # The app shortcut first, while canworks-config is still there to remove it.
    if [ "$DRY_RUN" = 1 ] || [ -x "$BIN/canworks-config" ]; then
        run "$BIN/canworks-config" --remove-shortcut || say "could not remove the app shortcut (see above)"
    fi
    run "$UV" tool uninstall canworks
    say "removed; uv and the tools' settings folder were kept"
    exit 0
fi

# The newest release: GitHub redirects releases/latest to releases/tag/<tag>.
latest_version() {
    url=$(curl -fsSL -o /dev/null -w '%{url_effective}' "$REPO/releases/latest") ||
        die "could not reach $REPO/releases/latest (behind a company proxy? see docs/install-pc.md)"
    tag=${url##*/}
    case "$tag" in
        deploy-v*) echo "${tag#deploy-v}"; return ;;
    esac
    # Fallback: the API, once.
    tag=$(curl -fsSL "$API/releases/latest" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1) ||
        die "could not find the newest release at $REPO/releases"
    case "$tag" in
        deploy-v*) echo "${tag#deploy-v}" ;;
        *) die "could not find the newest release at $REPO/releases" ;;
    esac
}

if [ -n "$WHEEL" ]; then
    [ -f "$WHEEL" ] || die "no such wheel: $WHEEL"
    SPEC=$WHEEL
    say "installing $WHEEL"
else
    [ -n "$VERSION" ] || VERSION=$(latest_version)
    SPEC="canworks @ $REPO/releases/download/deploy-v$VERSION/canworks-$VERSION-py3-none-any.whl"
    # Already this version on this Python (uv's own record, "canworks v0.94.2
    # [CPython 3.14.8]"): nothing to do, unless --force. The Python is
    # compared only when --python is a version, not a path.
    INSTALLED_LINE=$("$UV" tool list --show-python 2>/dev/null | grep '^canworks v' | head -n 1)
    INSTALLED_VERSION=$(echo "$INSTALLED_LINE" | sed -n 's/^canworks v\([^ ]*\).*/\1/p')
    SAME_PYTHON=1
    if echo "$PYTHON" | grep -Eq '^[0-9]+\.[0-9]+(\.[0-9]+)?$'; then
        WANT_PYTHON=$(echo "$PYTHON" | sed 's/^\([0-9]*\.[0-9]*\).*/\1/')
        HAVE_PYTHON=$(echo "$INSTALLED_LINE" | sed -n 's/.*\[CPython \([0-9]*\.[0-9]*\).*/\1/p')
        [ "$HAVE_PYTHON" = "$WANT_PYTHON" ] || SAME_PYTHON=0
    fi
    if [ "$FORCE" = 0 ] && [ "$INSTALLED_VERSION" = "$VERSION" ] && [ "$SAME_PYTHON" = 1 ]; then
        say "canworks $VERSION is already installed; --force installs it again"
        case ":$PATH:" in
            *":$BIN:"*) ;;
            *) say "open a new terminal so $BIN is on PATH, then run canworks-config" ;;
        esac
        exit 0
    fi
    if [ "$INSTALLED_VERSION" = "$VERSION" ] && [ "$SAME_PYTHON" = 0 ]; then
        say "installing canworks $VERSION again on Python $WANT_PYTHON (it was on ${HAVE_PYTHON:-another Python})"
    else
        say "installing canworks $VERSION"
    fi
fi

# Only runtime dependencies: can-j1939 lists pytest as one but never imports
# it, so an override drops it (docs/install-pc.md).
OVERRIDES="$TMP/overrides.txt"
echo "pytest; sys_platform == 'never'" > "$OVERRIDES"
# uv's bin folder first on PATH for this one call: uv then prints no PATH
# warning of its own, and the hint below says what to do once.
USER_PATH=$PATH
PATH="$BIN:$PATH"
export PATH
INSTALLED=1
run "$UV" tool install --force --compile-bytecode --python "$PYTHON" --overrides "$OVERRIDES" "$SPEC" || INSTALLED=0
PATH=$USER_PATH
[ "$INSTALLED" = 1 ] || die "uv could not install the tools (see its message above)"

NEW_TERMINAL=0
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) run "$UV" tool update-shell || true; NEW_TERMINAL=1 ;;
esac

if [ "$DRY_RUN" = 1 ]; then
    echo "would run: $BIN/canworks-deploy --version"
else
    "$BIN/canworks-deploy" --version || die "the tools were installed but canworks-deploy does not start"
fi
# The app shortcut: starts the configurator without a terminal. Not fatal.
if [ "$SHORTCUT" = 1 ]; then
    run "$BIN/canworks-config" --create-shortcut || say "could not add the app shortcut; run canworks-config --create-shortcut later"
fi
if [ "$NEW_TERMINAL" = 1 ]; then
    say "open a new terminal so $BIN is on PATH, then run canworks-config"
else
    say "done; open the canworks configurator app, or run canworks-config"
fi
}

main "$@"
