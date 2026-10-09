#!/usr/bin/env bash
# Builds Lely CANopen from source: C/C++ libraries into <prefix>/lely and the
# dcf-tools (dcfgen) into a Python venv at <prefix>/venv.
#
#   scripts/build-lely.sh [--prefix /opt/canworks] [--ref <lely-core commit>]
#
# The default ref is pinned: the deploy tool vendors Lely's dcf package from the
# same commit (tools/deploy/canworks/_lely_dcf/VERSION).
#
# Needs: a C/C++ toolchain, autoconf, automake, libtool, pkg-config, git or
# curl, python3 with venv. Skips the build if <prefix>/lely/.ref matches.

set -euo pipefail

PREFIX=/opt/canworks
REF=88848aa28599ea5d6d7e766a9ffa2054446821b5
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift ;;
        --ref) REF="$2"; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

LELY_DIR="$PREFIX/lely"
VENV_DIR="$PREFIX/venv"
SRC_DIR="$PREFIX/src/lely-core"

if [ -f "$LELY_DIR/.ref" ] && [ "$(cat "$LELY_DIR/.ref")" = "$REF" ] && [ -x "$VENV_DIR/bin/dcfgen" ]; then
    echo "==> Lely CANopen ($REF) already built in $LELY_DIR"
    exit 0
fi

echo "==> Fetching Lely CANopen ($REF)"
rm -rf "$SRC_DIR"
mkdir -p "$SRC_DIR"
curl -fsSL "https://gitlab.com/lely_industries/lely-core/-/archive/$REF/lely-core-$REF.tar.gz" |
    tar xz -C "$SRC_DIR" --strip-components=1

echo "==> Building Lely CANopen into $LELY_DIR (a few minutes)"
(
    cd "$SRC_DIR"
    autoreconf -i >/dev/null 2>&1
    mkdir -p build && cd build
    # NDEBUG keeps Lely's debug trace out of the runtime log.
    ../configure --prefix="$LELY_DIR" --disable-python --disable-tests --disable-unit-tests \
        CPPFLAGS=-DNDEBUG CFLAGS=-O2 CXXFLAGS=-O2 >/dev/null
    make -j"$(nproc)" >/dev/null
    make install >/dev/null
)

echo "==> Installing dcf-tools (dcfgen) into $VENV_DIR"
python3 -m venv "$VENV_DIR"
# dcfgen imports pkg_resources, which newer setuptools releases drop.
"$VENV_DIR/bin/pip" install -q "setuptools<81" "$SRC_DIR/python/dcf-tools"

echo "$REF" > "$LELY_DIR/.ref"
echo "==> Lely CANopen ready: $LELY_DIR, $VENV_DIR/bin/dcfgen"
