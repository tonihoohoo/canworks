#!/usr/bin/env bash
# Stock-runtime install test (canopen-stock-install), on a checkout of the
# upstream runtime:
#   1. scripts/install-stock.sh twice: the second run (same version) changes
#      nothing, --force installs again; one disabled canworks line, no modified
#      tracked runtime files; an install from before the rename is removed
#   2. the runtime's own upload handling on a deploy-tool bundle (enables
#      the canworks plugin, config next to the library, EDS from core/generated/conf) and
#      on an editor bundle without it (disables the canworks plugin)
#   3. the editor hook: one .pth in the runtime venv, active when the
#      webserver imports its modules, and test/stock/editor_hook.py (the hook
#      on the runtime's own modules); --no-editor-hook removes it
#   4. --uninstall: no canworks line, library, hook and simulator link gone
#
#   test/stock/run.sh <runtime checkout> [build dir with canopen_check]
#
# Needs Lely in /opt/canworks (scripts/build-lely.sh) and write access
# to /opt/canworks and the runtime checkout.

set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME="$(cd "$1" && pwd)"
BUILD="$(cd "${2:-$REPO/build}" && pwd)"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }
# can-j1939 boot entry and modprobe: a folder of the test's own and a stub.
export CANWORKS_MODULES_LOAD_DIR="$WORK/modules-load.d" CANWORKS_MODPROBE=true

# The runtime's install.sh creates venvs/runtime; a bare checkout has none.
# This one sees the packages of the Python running the test (the runtime's
# requirements are installed there in CI).
VENV="$RUNTIME/venvs/runtime"
[ -x "$VENV/bin/python3" ] || python3 -m venv --system-site-packages "$VENV"
SITE=$("$VENV/bin/python3" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
PTH="$SITE/canworks_hook.pth"

# The hook's lines when the runtime venv's Python imports the webserver module.
hook_log() {
    (cd "$RUNTIME" && OPENPLC_RUNTIME_DIR="$WORK/state/run" OPENPLC_PERSISTENT_DATA_DIR="$WORK/state/data" \
        "$VENV/bin/python3" -c 'import webserver.plcapp_management' 2>&1 >/dev/null |
        grep '^\[canworks editor hook\]' || true)
}

echo "==> install (twice), over an install from before the rename to canworks"
OLD_PREFIX="$WORK/old-prefix"
mkdir -p "$OLD_PREFIX/lib"
[ -f "$RUNTIME/plugins.conf" ] || cp "$RUNTIME/plugins_default.conf" "$RUNTIME/plugins.conf"
echo "canopen,$OLD_PREFIX/lib/libcanopen_plugin.so,0,1,$OLD_PREFIX/lib/canopen.json," >> "$RUNTIME/plugins.conf"  # rename-keep
touch "$SITE/openplc_canopen_hook.pth"  # rename-keep
# and the simulator's name from before clear-simulator-names
mkdir -p /opt/canworks/lib
touch /opt/canworks/lib/canworks-sim  # rename-keep
ln -sfn /opt/canworks/lib/canworks-sim /usr/local/bin/canworks-sim  # rename-keep
CANWORKS_OLD_PREFIX="$OLD_PREFIX" "$REPO/scripts/install-stock.sh" --no-deps --runtime-dir "$RUNTIME" >"$WORK/old-names.log"
grep -q "Removed /usr/local/bin/canworks-sim " "$WORK/old-names.log" || fail "the old simulator link removal was not named"  # rename-keep
[ ! -e /opt/canworks/lib/canworks-sim ] && [ ! -L /usr/local/bin/canworks-sim ] || fail "the old simulator name was left"  # rename-keep
! grep -q '^canopen,' "$RUNTIME/plugins.conf" || fail "the old canopen line was left"  # rename-keep
[ ! -e "$SITE/openplc_canopen_hook.pth" ] || fail "the old editor hook was left"  # rename-keep
[ ! -e "$OLD_PREFIX" ] || fail "the old install folder was left"
# The same version again changes nothing (skip-same-version-device-install):
# an upload's enabled line stays; --force installs again (disabled line).
sed -i 's|^canworks,\(.*\),0,1,|canworks,\1,1,1,|' "$RUNTIME/plugins.conf"
ENABLED=$(grep '^canworks,' "$RUNTIME/plugins.conf")
"$REPO/scripts/install-stock.sh" --no-deps --runtime-dir "$RUNTIME" >"$WORK/again.log"
grep -q "is already installed for this runtime" "$WORK/again.log" || { cat "$WORK/again.log"; fail "the same version was installed again"; }
! grep -q "Building the plugin" "$WORK/again.log" || fail "the same version rebuilt the plugin"
[ "$(grep '^canworks,' "$RUNTIME/plugins.conf")" = "$ENABLED" ] || fail "the skipped run changed plugins.conf"
"$REPO/scripts/install-stock.sh" --no-deps --force --runtime-dir "$RUNTIME" >"$WORK/force.log"
grep -q "Building the plugin" "$WORK/force.log" || fail "--force did not rebuild the plugin"
grep -q "^version=" /opt/canworks/lib/install-stamp || fail "no install stamp"
[ "$(grep -c '^canworks,' "$RUNTIME/plugins.conf")" = 1 ] || fail "expected exactly one canworks line"
grep -qx 'canworks,/opt/canworks/lib/libcanworks_plugin.so,0,1,/opt/canworks/lib/canworks.json,' \
    "$RUNTIME/plugins.conf" || fail "unexpected canworks line"
[ -f /opt/canworks/lib/libcanworks_plugin.so ] || fail "library not installed"
grep -qx can-j1939 "$CANWORKS_MODULES_LOAD_DIR/canworks-j1939.conf" || fail "can-j1939 boot entry not written"
# The simulator and the plugin take their version from the same CMake value
# (git describe of the checkout they were built from).
SIM_VERSION=$(canworks-canopen-sim --version | awk '{print $2}')
PLUGIN_VERSION=$(git -C "$REPO" describe --always --tags --dirty)
[ "$SIM_VERSION" = "$PLUGIN_VERSION" ] ||
    fail "canworks-canopen-sim --version ($SIM_VERSION) is not the plugin version ($PLUGIN_VERSION)"
[ -z "$(git -C "$RUNTIME" status --porcelain --untracked-files=no)" ] || {
    git -C "$RUNTIME" status --short; fail "tracked runtime files were modified"; }

echo "==> editor hook"
[ -f "$PTH" ] || fail "no $PTH"
[ "$(ls "$SITE" | grep -c canworks)" = 1 ] || fail "expected exactly one hook file in $SITE"
[ -f /opt/canworks/lib/python/canworks_hook/__init__.py ] || fail "hook package not installed"
LOG=$(hook_log)
echo "    $LOG"
[ "$(echo "$LOG" | grep -c .)" = 1 ] && echo "$LOG" | grep -q 'INFO: active' || fail "hook not active in the runtime venv"
/opt/canworks/venv/bin/python -c 'import canworks_hook.snapshot' || fail "hook checks not installed"
python3 "$REPO/test/stock/editor_hook.py" --runtime-dir "$RUNTIME" --canopen-check "$BUILD/canopen_check"
# docs/install-stock.md's --into-project command, with the installed tool.
mkdir -p "$WORK/rtd-monitor" && echo '{}' > "$WORK/rtd-monitor/project.json"
(cd "$REPO" && /opt/canworks/venv/bin/canworks-deploy \
    --config config/rtd-sensor/canopen_config.json --into-project "$WORK/rtd-monitor")
[ -f "$WORK/rtd-monitor/canworks/canworks.json" ] && [ -f "$WORK/rtd-monitor/canworks/rtd8.eds" ] ||
    fail "--into-project did not write the project's canworks/ folder"
"$REPO/scripts/install-stock.sh" --no-deps --no-editor-hook --runtime-dir "$RUNTIME" >/dev/null
[ ! -e "$PTH" ] || fail "--no-editor-hook left $PTH"
[ -z "$(hook_log)" ] || fail "--no-editor-hook: the hook still logs"
/opt/canworks/venv/bin/python -m canworks.edslint --json \
    "$REPO/test/fixtures/eds/cpp-slave.eds" >/dev/null || fail "--no-editor-hook: no EDS lint for the plugin"
"$REPO/scripts/install-stock.sh" --no-deps --runtime-dir "$RUNTIME" >/dev/null
[ -f "$PTH" ] || fail "re-install did not restore the hook"

echo "==> bundles"
PYTHONPATH="$REPO/tools/deploy" python3 - "$WORK" <<'PY'
import sys, os, zipfile
from tests.helpers import editor_bundle
work = sys.argv[1]
ethercat = {"slaves": [{"channels": [{"iec_location": "%IX0.0"}]}]}
editor_bundle(os.path.join(work, "src"), {"ethercat.json": ethercat})
plain = editor_bundle(os.path.join(work, "plain"), {"ethercat.json": ethercat})
with zipfile.ZipFile(os.path.join(work, "plain.zip"), "w") as z:
    for root, _, files in os.walk(plain):
        for f in files:
            z.write(os.path.join(root, f), os.path.relpath(os.path.join(root, f), plain))
PY
PYTHONPATH="$REPO/tools/deploy" python3 -m canworks --bundle "$WORK/src" \
    --config "$REPO/config/pingpong/canopen_config.json" --check-only --output "$WORK/deployed.zip"

echo "==> the runtime's upload handling"
python3 "$REPO/test/stock/upload_rules.py" --runtime-dir "$RUNTIME" --deployed "$WORK/deployed.zip" \
    --plain "$WORK/plain.zip" --canopen-check "$BUILD/canopen_check"

echo "==> uninstall"
"$REPO/scripts/install-stock.sh" --uninstall --runtime-dir "$RUNTIME"
! grep -q '^canworks,' "$RUNTIME/plugins.conf" || fail "canworks line left in plugins.conf"
[ ! -e /opt/canworks/lib ] || fail "library directory left behind"
[ ! -e "$PTH" ] || fail "uninstall left $PTH"
[ ! -e "$CANWORKS_MODULES_LOAD_DIR/canworks-j1939.conf" ] || fail "uninstall left the can-j1939 boot entry"
[ ! -e /usr/local/bin/canworks-canopen-sim ] && [ ! -L /usr/local/bin/canworks-canopen-sim ] ||
    fail "uninstall left /usr/local/bin/canworks-canopen-sim"
[ -z "$(hook_log)" ] || fail "uninstall: the hook still logs"
[ -x /opt/canworks/venv/bin/dcfgen ] || fail "uninstall without --purge removed dcfgen"
[ -z "$(git -C "$RUNTIME" status --porcelain --untracked-files=no)" ] || fail "tracked runtime files were modified"
echo "OK"
