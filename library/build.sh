#!/bin/sh
# Builds the canworks editor library (specs plc-library and
# canopen-cia402-axis) into the deploy tool's package, from the sources in
# library/canworks, with strucpp (the compiler OpenPLC Editor uses).
#
#   library/build.sh           write tools/deploy/canworks/library/canworks.stlib
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
out="$here/../tools/deploy/canworks/library/canworks.stlib"
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
node "$work/strucpp/node_modules/strucpp/dist/node/cli.js" --compile-lib "$here/canworks" \
  -o "$work/out" --lib-name canworks --lib-version 0.0.0 -L "$work/strucpp/node_modules/strucpp/libs" >/dev/null
# strucpp 0.7.0 lists an ST function's VAR locals among its manifest
# parameters, and the editor then asks every call for them as inputs
# ("missing required inputs: I, POS, ..."). Keep only the parameters the
# function's compiled signature (its chunk header) takes.
python3 - "$work/out/canworks.stlib" <<'PY'
import json, re, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    lib = json.load(f)
headers = {c["name"]: c["header"] for c in lib["chunks"] if c.get("kind") == "function"}
for fn in lib["manifest"]["functions"]:
    sig = headers[fn["name"]]
    sig = sig[sig.index("(") + 1:sig.rindex(")")]
    taken = {re.split(r"[\s&*]+", p.strip())[-1] for p in sig.split(",") if p.strip()}
    fn["parameters"] = [p for p in fn["parameters"] if p["name"] in taken]
with open(path, "w", encoding="utf-8") as f:
    f.write(json.dumps(lib, indent=2, ensure_ascii=False))
PY

if [ "$check" = 1 ]; then
  if ! cmp -s "$work/out/canworks.stlib" "$out"; then
    echo "canworks.stlib is out of date (run library/build.sh)" >&2
    exit 1
  fi
  exit 0
fi
mkdir -p "$(dirname "$out")"
cp "$work/out/canworks.stlib" "$out"
echo "wrote $out"
