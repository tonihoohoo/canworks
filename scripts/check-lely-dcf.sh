#!/usr/bin/env bash
# Checks that the deploy tool's vendored Lely dcf package matches the lely-core
# source scripts/build-lely.sh built: same commit, same files (the dcf package
# and dcfgen's cli.py, vendored as dcfgen_cli.py).
#
#   scripts/check-lely-dcf.sh [--prefix /opt/canworks]

set -euo pipefail

PREFIX=/opt/canworks
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

REPO=$(cd "$(dirname "$0")/.." && pwd)
VENDORED="$REPO/tools/deploy/canworks/_lely_dcf"
SRC="$PREFIX/src/lely-core/python/dcf-tools/dcf"

want=$(cat "$VENDORED/VERSION")
built=$(cat "$PREFIX/lely/.ref")
if [ "$want" != "$built" ]; then
    echo "vendored dcf is from lely-core $want, but $PREFIX was built from $built" >&2
    exit 1
fi
status=0
for f in __init__.py device.py lint.py parse.py print.py; do
    if ! cmp -s "$SRC/$f" "$VENDORED/$f"; then
        echo "$f differs from lely-core $want ($SRC/$f)" >&2
        status=1
    fi
done
if ! cmp -s "$SRC/../dcfgen/cli.py" "$VENDORED/dcfgen_cli.py"; then
    echo "dcfgen_cli.py differs from lely-core $want ($SRC/../dcfgen/cli.py)" >&2
    status=1
fi
[ $status -eq 0 ] && echo "vendored dcf matches lely-core $want"
exit $status
