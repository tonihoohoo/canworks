#!/bin/sh
# Installs or updates the canworks PC tools (configurator, deploy tool,
# diagnostics) on macOS or Linux, with uv and a uv-managed Python: no Python
# and no admin rights needed. Run it again to update to the newest release.
#
#   curl -LsSf https://raw.githubusercontent.com/tonihoohoo/canworks/main/scripts/install-pc.sh | sh
#   curl -LsSf .../install-pc.sh | sh -s -- --version 0.82.0     # a given release
#   curl -LsSf .../install-pc.sh | sh -s -- --uninstall
#
# Options:
#   --version X    install release deploy-vX instead of the newest one
#   --wheel FILE   install this local wheel instead of a release (CI)
#   --python V     the Python uv uses (default 3.12; a path to an installed Python works too)
#   --uninstall    remove the tools (uv and the tools' settings stay)
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
PYTHON=3.12
UNINSTALL=0
DRY_RUN=0

die() { echo "install-pc: $*" >&2; exit 1; }
say() { echo "install-pc: $*"; }

usage() {
    if [ -f "$0" ]; then sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; else echo "see https://github.com/tonihoohoo/canworks/blob/main/scripts/install-pc.sh"; fi
}

while [ $# -gt 0 ]; do
    case "$1" in
        --version) [ $# -ge 2 ] || die "--version needs a version"; VERSION=${2#deploy-v}; VERSION=${VERSION#v}; shift 2 ;;
        --wheel) [ $# -ge 2 ] || die "--wheel needs a file"; WHEEL=$2; shift 2 ;;
        --python) [ $# -ge 2 ] || die "--python needs a version or path"; PYTHON=$2; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1 (see --help)" ;;
    esac
done

run() {
    if [ "$DRY_RUN" = 1 ]; then echo "would run: $*"; else "$@"; fi
}

command -v curl >/dev/null 2>&1 || die "curl is needed"

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
        echo "would run: curl -LsSf $UV_INSTALLER | sh"
        UV=uv
    else
        curl -LsSf "$UV_INSTALLER" | sh || die "could not install uv from $UV_INSTALLER"
        UV=$(find_uv)
        [ -n "$UV" ] || die "uv was installed but not found in ~/.local/bin; open a new terminal and run this again"
    fi
fi

if [ "$UNINSTALL" = 1 ]; then
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
    say "installing canworks $VERSION"
fi

run "$UV" tool install --force --compile-bytecode --python "$PYTHON" "$SPEC" ||
    die "uv could not install the tools (see its message above)"

BIN=$("$UV" tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")
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
if [ "$NEW_TERMINAL" = 1 ]; then
    say "open a new terminal so $BIN is on PATH, then run canworks-config"
else
    say "done; run canworks-config to open the configurator"
fi
}

main "$@"
