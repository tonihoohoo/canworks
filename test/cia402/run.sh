#!/usr/bin/env bash
# The CiA 402 example's PLC programs, compiled with the editor's compiler
# (STruC++, fetched by scripts/fetch-strucpp.sh) and its built-in PLCopen
# SoftMotion library, run against an ST model of a CiA 402 drive
# (drive_model.st):
#
#   test_axis.st     main as the project generator writes it for
#                    config/cia402-drive, with motion blocks called on its axis
#   test_scaling.st  the same with "scale_numerator": 10
#   test_demo.st     config/cia402-drive/drive_demo.st
#   test_cyclic.st   main as generated for config/cia402-drive/
#                    canopen_config_cyclic.json, with the cyclic synchronous
#                    blocks of the packaged openplc_canopen library
#   test_cyclic_demo.st  config/cia402-drive/drive_cyclic_demo.st
#
#   test/cia402/run.sh [--strucpp PATH]
#
# Needs python3 with jsonschema (the deploy tool's modules), g++, and for the
# fetch Node.js 22 or later.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
STRUCPP=""
while [ $# -gt 0 ]; do
    case "$1" in
        --strucpp) STRUCPP="$2"; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done
[ -n "$STRUCPP" ] || STRUCPP="$("$REPO/scripts/fetch-strucpp.sh")"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The program the generator writes, from the example config and a scaled copy.
PYTHONPATH="$REPO/tools/deploy" python3 - "$REPO/config/cia402-drive/canopen_config.json" "$WORK" <<'PY'
import json, sys
from openplc_canopen_deploy import editorproject
path, out = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    cfg = json.load(f)
with open(out + "/main.st", "w", encoding="utf-8") as f:
    f.write(editorproject.program(cfg, path))
cfg["nodes"][0]["axis"]["scale_numerator"] = 10
with open(out + "/main_scaled.st", "w", encoding="utf-8") as f:
    f.write(editorproject.program(cfg, path))
path = path.replace("canopen_config.json", "canopen_config_cyclic.json")
with open(path, encoding="utf-8") as f:
    cfg = json.load(f)
with open(out + "/main_cyclic.st", "w", encoding="utf-8") as f:
    f.write(editorproject.program(cfg, path, "T#10ms"))
PY

status=0
# The cyclic blocks come from the packaged openplc_canopen library (built
# from library/openplc_canopen by library/build.sh), as in an editor project.
LIBRARY=(-L "$REPO/tools/deploy/openplc_canopen_deploy/library")
run() {
    local program="$1" tests="$2" log="$WORK/$(basename "$2" .st).log"
    shift 2
    echo "== $(basename "$program") + $(basename "$tests")"
    # The test runner names its own scratch directory; keep only its verdicts.
    if "$STRUCPP" "$program" "$HERE/drive_model.st" "$@" -o "$WORK/out.cpp" --test "$tests" >"$log" 2>&1; then
        grep -E '\[(PASS|FAIL)\]|tests?, ' "$log"
    else
        grep -vE 'c\+\+17|inline CONSTANTS|^\s*\||\^~|In file included' "$log" | tail -40
        status=1
    fi
}
run "$WORK/main.st" "$HERE/test_axis.st"
run "$WORK/main_scaled.st" "$HERE/test_scaling.st"
run "$REPO/config/cia402-drive/drive_demo.st" "$HERE/test_demo.st"
run "$WORK/main_cyclic.st" "$HERE/test_cyclic.st" "${LIBRARY[@]}"
run "$REPO/config/cia402-drive/drive_cyclic_demo.st" "$HERE/test_cyclic_demo.st" "${LIBRARY[@]}"
exit $status
