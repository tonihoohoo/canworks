#!/usr/bin/env bash
# Fetches STruC++, the Structured Text compiler OpenPLC Editor uses, at the
# version the supported editor pins (OpenPLC Editor 4.3.2: binary-versions.json
# names STruC++ v0.7.0), for the CiA 402 tests (test/cia402/run.sh). Its
# bundled libraries include the PLCopen SoftMotion blocks the editor offers.
# Nothing is committed; the package is cached in <dir>.
#
#   scripts/fetch-strucpp.sh [--dir ~/.cache/canworks/strucpp]
#
# Prints the path of the strucpp command. Needs curl, Node.js 22 or later and
# npm (for the compiler's one dependency).

set -euo pipefail

VERSION=0.7.0
SHA256=8d78ae92d931b87c06145520222d1491206f424c147ec66ea84653cb8b0e1be5
DIR="${XDG_CACHE_HOME:-$HOME/.cache}/canworks/strucpp"
while [ $# -gt 0 ]; do
    case "$1" in
        --dir) DIR="$2"; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

HOME_DIR="$DIR/$VERSION"
CLI="$HOME_DIR/node_modules/.bin/strucpp"
if [ -x "$CLI" ] && [ "$("$CLI" --version 2>/dev/null)" = "STruC++ version $VERSION" ]; then
    echo "$CLI"
    exit 0
fi

command -v node >/dev/null || { echo "fetch-strucpp: Node.js 22 or later is needed" >&2; exit 1; }
major=$(node -p 'process.versions.node.split(".")[0]')
if [ "$major" -lt 22 ]; then
    echo "fetch-strucpp: STruC++ $VERSION needs Node.js 22 or later (found $(node --version))" >&2
    exit 1
fi

mkdir -p "$HOME_DIR"
tgz="$HOME_DIR/strucpp-$VERSION.tgz"
curl -fsSL -o "$tgz.part" "https://github.com/Autonomy-Logic/STruCpp/releases/download/v$VERSION/strucpp-$VERSION.tgz"
echo "$SHA256  $tgz.part" | sha256sum -c --quiet - >&2 || { rm -f "$tgz.part"; echo "fetch-strucpp: checksum mismatch" >&2; exit 1; }
mv "$tgz.part" "$tgz"
(cd "$HOME_DIR" && { [ -f package.json ] || echo '{"private": true}' > package.json; } &&
    npm install --silent --no-audit --no-fund "./strucpp-$VERSION.tgz" >&2)
"$CLI" --version >&2
echo "$CLI"
