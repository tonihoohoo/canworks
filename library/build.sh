#!/bin/sh
# Builds the openplc_canopen editor library (specs canopen-plc-sdo and
# canopen-cia402-axis) into the deploy tool's package, from the sources in
# library/openplc_canopen, with strucpp (the compiler OpenPLC Editor uses).
#
#   library/build.sh           write tools/deploy/openplc_canopen_deploy/library/openplc_canopen.stlib
#   library/build.sh --check   fail if that file is not what the sources build
#
# The archive is built with version 0.0.0; the deploy tool sets the package
# version when it writes or installs it, so a version bump needs no rebuild.
# STRUCPP_TGZ names an already downloaded strucpp-<version>.tgz (the test
# build has one); otherwise it is downloaded and its checksum checked. Needs
# Node.js and npm (strucpp's parser comes from npm).
set -eu

STRUCPP_VERSION=0.7.0
STRUCPP_SHA256=8d78ae92d931b87c06145520222d1491206f424c147ec66ea84653cb8b0e1be5

here=$(cd "$(dirname "$0")" && pwd)
out="$here/../tools/deploy/openplc_canopen_deploy/library/openplc_canopen.stlib"
check=0
[ "${1:-}" = "--check" ] && check=1

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

tgz=${STRUCPP_TGZ:-}
if [ -z "$tgz" ]; then
  tgz="$work/strucpp-$STRUCPP_VERSION.tgz"
  curl -fsSL -o "$tgz" "https://github.com/Autonomy-Logic/STruCpp/releases/download/v$STRUCPP_VERSION/strucpp-$STRUCPP_VERSION.tgz"
fi
tgz="$(cd "$(dirname "$tgz")" && pwd)/$(basename "$tgz")"
echo "$STRUCPP_SHA256  $tgz" | sha256sum -c --quiet -

python3 "$here/generate.py" --check
mkdir "$work/strucpp" "$work/out"
(cd "$work/strucpp" && npm install --silent --no-save --no-audit --no-fund "$tgz" >/dev/null)
# -L: the ST blocks (CO402_Cyclic*) use the bundled PLCopen SoftMotion
# library's AXIS_REF_SM3, so the archive depends on it (every editor project
# has it).
node "$work/strucpp/node_modules/strucpp/dist/node/cli.js" --compile-lib "$here/openplc_canopen" \
  -o "$work/out" --lib-name openplc_canopen --lib-version 0.0.0 -L "$work/strucpp/node_modules/strucpp/libs" >/dev/null

if [ "$check" = 1 ]; then
  if ! cmp -s "$work/out/openplc_canopen.stlib" "$out"; then
    echo "openplc_canopen.stlib is out of date (run library/build.sh)" >&2
    exit 1
  fi
  exit 0
fi
mkdir -p "$(dirname "$out")"
cp "$work/out/openplc_canopen.stlib" "$out"
echo "wrote $out"
