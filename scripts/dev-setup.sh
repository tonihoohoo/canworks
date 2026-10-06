#!/usr/bin/env bash
# Development setup: builds Lely CANopen (C/C++ libraries + dcfgen) into
# /opt/openplc-canopen, installs the deploy tool from this checkout into its
# venv in editable mode (the plugin runs its EDS lint) and brings up a
# virtual CAN interface vcan0.
#
#   sudo scripts/dev-setup.sh [--lely-ref <git ref>] [--no-vcan]
#
# Debian/Ubuntu/Raspberry Pi OS. Idempotent: an existing Lely build with the
# same ref is kept.

set -euo pipefail

PREFIX=/opt/openplc-canopen
LELY_REF=${LELY_REF:-88848aa28599ea5d6d7e766a9ffa2054446821b5}
SETUP_VCAN=1

while [ $# -gt 0 ]; do
    case "$1" in
        --lely-ref) LELY_REF="$2"; shift ;;
        --no-vcan) SETUP_VCAN=0 ;;
        -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root (sudo $0)" >&2
    exit 1
fi

echo "==> Installing build dependencies"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    build-essential cmake pkg-config autoconf automake libtool git curl \
    python3 python3-venv iproute2 can-utils >/dev/null

"$(dirname "$0")/build-lely.sh" --prefix "$PREFIX" --ref "$LELY_REF"

echo "==> Checking dcfgen"
"$PREFIX/venv/bin/dcfgen" --help >/dev/null
echo "    dcfgen --help: ok ($PREFIX/venv/bin/dcfgen)"

echo "==> Installing the deploy tool (EDS lint) into $PREFIX/venv"
"$PREFIX/venv/bin/python" -m pip install -q -e "$(cd "$(dirname "$0")/.." && pwd)/tools/deploy"

if [ "$SETUP_VCAN" -eq 1 ]; then
    echo "==> Bringing up vcan0"
    modprobe vcan 2>/dev/null || true
    if ! ip link show vcan0 >/dev/null 2>&1; then
        if ! ip link add dev vcan0 type vcan; then
            echo "    cannot create vcan0: this kernel has no vcan support" >&2
            echo "    (on Ubuntu install linux-modules-extra-\$(uname -r); containers need the host's module)" >&2
            exit 1
        fi
    fi
    ip link set up vcan0
    ip link show vcan0
fi
echo "==> Done"
