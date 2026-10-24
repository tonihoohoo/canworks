#!/usr/bin/env bash
# Fetches the truST runtime CLI (trust-platform, open source) at the pinned
# release, for the PLCopen export's import-and-build check
# (tools/deploy/tests/test_plcopen.py, class TrustImport; docs/development.md).
# Nothing is committed; the binary is cached in <dir>. Linux x64 only.
#
#   test/plcopen/fetch-trust.sh [--dir ~/.cache/canworks/trust]
#
# Prints the path of the trust-runtime command.

set -euo pipefail

VERSION=0.24.75
SHA256=6deb3c8469374ea0cd77b2b7a667676f139413e169d4f033b8ce3b88e13ececf
DIR="${XDG_CACHE_HOME:-$HOME/.cache}/canworks/trust"
while [ $# -gt 0 ]; do
    case "$1" in
        --dir) DIR="$2"; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

HOME_DIR="$DIR/$VERSION"
CLI="$HOME_DIR/trust-runtime"
if [ -x "$CLI" ] && [ "$("$CLI" --version 2>/dev/null)" = "trust-runtime $VERSION" ]; then
    echo "$CLI"
    exit 0
fi

mkdir -p "$HOME_DIR"
tgz="$HOME_DIR/trust-runtime-linux-x64.tar.gz"
curl -fsSL -o "$tgz.part" \
    "https://github.com/johannesPettersson80/trust-platform/releases/download/v$VERSION/trust-runtime-linux-x64.tar.gz"
echo "$SHA256  $tgz.part" | sha256sum -c --quiet - >&2 || { rm -f "$tgz.part"; echo "fetch-trust: checksum mismatch" >&2; exit 1; }
mv "$tgz.part" "$tgz"
tar -xzf "$tgz" -C "$HOME_DIR" ./trust-runtime
"$CLI" --version >&2
echo "$CLI"
