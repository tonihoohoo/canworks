#!/usr/bin/env bash
# Temperature sensor end-to-end test on a SocketCAN interface (vcan0 by default).
#
#   test/sensor/run.sh [--build-dir build] [--iface vcan0] [--seconds 10] [--keep-vendor-pdos]
#
# Starts the simulated RTD-8 module (8x RTD, CiA 404) as node 5,
# driven by its EDS (config/rtd-sensor/rtd8.eds), with every PDO
# mapping blank, so the only PDO map the device ends up with is the one the
# master writes from config/rtd-sensor/canopen_config.json. Then loads the real
# libcanworks_plugin.so through canopen_host with the rtd program. Passes (exit
# 0) when the node status bit %IX10.0 is TRUE and %IW100-%IW103 follow the
# simulated temperatures, and (with candump) TPDO 1 carries the four 16-bit
# temperatures, TPDO 2 the four status bytes, and the device's TPDO 3 and 4
# stay silent. Halfway through, the device reports a sensor break (EMCY
# 0x5000) and a second later resets it; the plugin must log both.
# --keep-vendor-pdos starts the device with the EDS's own default mapping
# instead.
#
# Needs a build of this repo and an UP interface (sudo scripts/dev-setup.sh).

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build"
IFACE=vcan0
SECONDS_RUN=10
BLANK=--blank-pdos

while [ $# -gt 0 ]; do
    case "$1" in
        --build-dir) BUILD="$(cd "$2" && pwd)"; shift ;;
        --iface) IFACE="$2"; shift ;;
        --seconds) SECONDS_RUN="$2"; shift ;;
        --keep-vendor-pdos) BLANK= ;;
        -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

PLUGIN="$BUILD/plugins/libcanworks_plugin.so"
HOST="$BUILD/test/canopen_host"
SLAVE="$BUILD/test/sensor_slave"
for f in "$PLUGIN" "$HOST" "$SLAVE"; do
    [ -x "$f" ] || [ -f "$f" ] || { echo "missing $f; build the repo first" >&2; exit 2; }
done
if ! ip link show "$IFACE" 2>/dev/null | grep -q "state UP\|,UP"; then
    echo "$IFACE is missing or down; run: sudo scripts/dev-setup.sh" >&2
    exit 2
fi

WORK="$(mktemp -d)"
PIDS=()
cleanup() {
    for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
    wait 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

CONFIG="$ROOT/config/rtd-sensor"
cp "$CONFIG/rtd8.eds" "$WORK/"
sed "s/\"vcan0\"/\"$IFACE\"/" "$CONFIG/canopen_config.json" > "$WORK/canopen_config.json"

if command -v candump >/dev/null; then
    candump -L "$IFACE" > "$WORK/candump.log" 2>/dev/null &
    PIDS+=($!)
fi
# AI0..AI3 in 0.1 degC, the ranges canopen_host's rtd program checks.
"$SLAVE" "$IFACE" "$WORK/rtd8.eds" 5 $BLANK \
    --signal 0x7130:1=200..260 --signal 0x7130:2=300..360 \
    --signal 0x7130:3=400..460 --signal 0x7130:4=-100..-40 > "$WORK/slave.log" 2>&1 &
SLAVE_PID=$!
PIDS+=($SLAVE_PID)
sleep 0.5
# Sensor break halfway through the run, cleared a second later.
( sleep $(( (SECONDS_RUN + 1) / 2 )); kill -USR1 $SLAVE_PID; sleep 1; kill -USR2 $SLAVE_PID ) 2>/dev/null &
PIDS+=($!)

echo "==> Running the plugin on $IFACE for ${SECONDS_RUN}s against the RTD module (${BLANK:-vendor PDO defaults})"
"$HOST" "$PLUGIN" "$WORK/canopen_config.json" "$SECONDS_RUN" rtd 2>&1 | tee "$WORK/host.log"
RC=${PIPESTATUS[0]}
if [ $RC -eq 0 ]; then
    if grep -q "node 5 (rtd): EMCY 0x5000 (device hardware), error register 0x01, manufacturer bytes 01 00 00 00 00" "$WORK/host.log" &&
       grep -q "node 5 (rtd): EMCY error reset" "$WORK/host.log"; then
        echo "==> The sensor break EMCY and its reset were logged"
    else
        echo "FAIL: the plugin did not log the sensor break EMCY and its reset" >&2
        RC=1
    fi
fi

if [ -f "$WORK/candump.log" ]; then
    sleep 0.2
    LOG="$WORK/candump.log"
    count() { grep -c " $IFACE $1#" "$LOG" || true; }
    echo "==> Traffic on $IFACE: SYNC $(count 080), NMT $(count 000), SDO to node 5 $(count 605)," \
         "TPDO1 $(count 185), TPDO2 $(count 285), TPDO3 $(count 385), TPDO4 $(count 485), heartbeat $(count 705)"
    if [ $RC -eq 0 ]; then
        # Once the master's last SDO download to node 5 is done (the PDO map
        # and startup SDOs are written; the Lely slave starts itself, so
        # there may be no NMT start): TPDO 1 = 4 x INTEGER16 (8 bytes),
        # TPDO 2 = 4 x UNSIGNED8 (4 bytes), no TPDO 3 or 4 (not in the config).
        check=$(awk -v ifc="$IFACE" '
            function hex(h,   i, v) { v = 0; for (i = 1; i <= length(h); i++) v = v * 16 + index("0123456789ABCDEF", toupper(substr(h, i, 1))) - 1; return v }
            function s16(h,   v) { v = hex(substr(h, 3, 2) substr(h, 1, 2)); return v >= 32768 ? v - 65536 : v }
            $2 != ifc { next }
            FNR == NR { if ($3 ~ /^605#/) last_sdo = FNR; next }
            FNR <= last_sdo { next }
            $3 ~ /^185#/ { d = substr($3, 5); n1++
                           if (length(d) != 16) bad = bad " TPDO1-length:" length(d) / 2
                           a0 = s16(substr(d, 1, 4)); a3 = s16(substr(d, 13, 4))
                           if (a0 < 200 || a0 > 260 || a3 < -100 || a3 > -40) bad = bad " TPDO1-value:" d }
            $3 ~ /^285#/ { d = substr($3, 5); n2++; if (length(d) != 8) bad = bad " TPDO2-length:" length(d) / 2 }
            $3 ~ /^(385|485)#/ { bad = bad " unexpected:" $3 }
            END { if (!n1) bad = bad " no-TPDO1"; if (!n2) bad = bad " no-TPDO2"; print bad }' "$LOG" "$LOG" | tr ' ' '\n' | sort -u | head -5 | tr '\n' ' ')
        if [ -z "${check// /}" ]; then
            echo "==> TPDO 1 carries the 4 temperatures, TPDO 2 the 4 status bytes, TPDO 3/4 silent: the config's PDO map"
        else
            echo "FAIL: PDO traffic does not match the config's PDO map:$check" >&2
            RC=1
        fi
    fi
fi
[ $RC -eq 0 ] || { echo "--- slave log"; cat "$WORK/slave.log"; } >&2
exit $RC
