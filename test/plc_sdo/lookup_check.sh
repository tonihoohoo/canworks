#!/bin/sh
# Runs lookup_check with the ping-pong config moved to a CAN interface that
# does not exist, so the plugin starts but no device ever answers.
#   lookup_check.sh <lookup_check> <libcanopen_plugin.so> <program.so> <config dir> <scratch dir>
set -eu
check=$1 plugin=$2 program=$3 config=$4 dir=$5
rm -rf "$dir"
mkdir -p "$dir"
cp "$config"/* "$dir"/
sed -i 's/"vcan0"/"plcsdo0"/' "$dir/canopen_config.json"
grep -q '"plcsdo0"' "$dir/canopen_config.json"
exec "$check" "$plugin" "$program" "$dir/canopen_config.json"
