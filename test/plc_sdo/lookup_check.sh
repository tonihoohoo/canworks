#!/bin/sh
# Runs lookup_check with the ping-pong config moved to a CAN interface that
# does not exist, so the plugin starts but no device ever answers.
# With --stop-check as a sixth argument the config stays on vcan0 (which
# must exist and be up) and a PLC stop during a transfer is checked too.
#   lookup_check.sh <lookup_check> <libcanworks_plugin.so> <program.so> <config dir> <scratch dir> [--stop-check]
set -eu
check=$1 plugin=$2 program=$3 config=$4 dir=$5 mode=${6:-}
rm -rf "$dir"
mkdir -p "$dir"
cp "$config"/* "$dir"/
if [ "$mode" = "--stop-check" ]; then
  exec "$check" "$plugin" "$program" "$dir/canopen_config.json" --stop-check
fi
sed -i 's/"vcan0"/"plcsdo0"/' "$dir/canopen_config.json"
grep -q '"plcsdo0"' "$dir/canopen_config.json"
exec "$check" "$plugin" "$program" "$dir/canopen_config.json"
