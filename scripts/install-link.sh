#!/usr/bin/env bash
# Installs the remote link and the runtime's local-network advertisement on a
# device (docs/remote-access.md). install-stock.sh and install-bridge.sh call it
# (--with-link, and the advertisement unless --without-discovery); it can also
# run on its own.
#
#   sudo scripts/install-link.sh --config FILE [--runtime-port 8443|none]
#                                [--diag-port 7531] [--prefix /opt/canworks-link]
#                                [--without-link]
#   sudo scripts/install-link.sh --uninstall [--purge] [--prefix /opt/canworks-link]
#
# --config is the deployed canworks.json the device runs (a stock runtime:
# /opt/canworks/lib/canworks.json; a bridge: /etc/canworks-bridge/NAME/canworks.json).
# The link service reads its token_verifier for pairing and its
# diagnostics.remote_link for internet access, and follows changes to it.
#
# Install: a Python virtual environment in <prefix>/venv with the canworks
# package (no dependencies) and the iroh package, /usr/local/bin/canworks-link,
# the unit canworks-link.service (enabled and started), /etc/canworks-link/
# with the device's key and no paired PCs, and the Avahi service file
# /etc/avahi/services/canworks.service (_canworks._tcp with the link ID).
# --without-link installs only the advertisement. Internet access stays off
# until a config with diagnostics.remote_link.internet true is uploaded.
#
# Uninstall: stops and removes the service, the command, <prefix> and the Avahi
# file; /etc/canworks-link (key and paired PCs) stays unless --purge.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX=/opt/canworks-link
CONFIG=""
RUNTIME_PORT=8443
DIAG_PORT=7531
LINK_PORT=7533
WITH_LINK=1
UNINSTALL=0
PURGE=0
IROH_SPEC="iroh>=1.1,<1.2"
# Overridable for the tests.
UNIT_DIR=${CANWORKS_UNIT_DIR:-/etc/systemd/system}
LINK_DIR=${CANWORKS_LINK_DIR:-/etc/canworks-link}
AVAHI_DIR=${CANWORKS_AVAHI_DIR:-/etc/avahi/services}
BIN_DIR=${CANWORKS_BIN_DIR:-/usr/local/bin}
SYSTEMCTL=${CANWORKS_SYSTEMCTL:-systemctl}
PIP=${CANWORKS_LINK_PIP:-}

usage() { sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --config) CONFIG="$2"; shift ;;
        --runtime-port) RUNTIME_PORT="$2"; shift ;;
        --diag-port) DIAG_PORT="$2"; shift ;;
        --prefix) PREFIX="$2"; shift ;;
        --without-link) WITH_LINK=0 ;;
        --uninstall) UNINSTALL=1 ;;
        --purge) PURGE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }

UNIT="$UNIT_DIR/canworks-link.service"
AVAHI_FILE="$AVAHI_DIR/canworks.service"
LINK_BIN="$BIN_DIR/canworks-link"

if [ "$UNINSTALL" -eq 1 ]; then
    if [ -f "$UNIT" ]; then
        say "Stopping canworks-link.service"
        "$SYSTEMCTL" disable --now canworks-link.service || true
        rm -f "$UNIT"
        "$SYSTEMCTL" daemon-reload || true
    fi
    rm -f "$LINK_BIN" "$AVAHI_FILE"
    rm -rf "${PREFIX:?}"
    if [ "$PURGE" -eq 1 ]; then
        rm -rf "${LINK_DIR:?}"
        say "Removed the remote link, its key and its paired PCs"
    else
        say "Removed the remote link; the key and paired PCs stay in $LINK_DIR (--purge removes them)"
    fi
    exit 0
fi

[ -n "$CONFIG" ] || die "give --config <the deployed canworks.json> (see --help)"
case "$RUNTIME_PORT" in none|[0-9]*) ;; *) die "--runtime-port is a port number or none" ;; esac

LINK_ID=""
if [ "$WITH_LINK" -eq 1 ]; then
    command -v python3 >/dev/null 2>&1 || die "python3 is needed for the remote link"
    if [ -n "$PIP" ]; then
        mkdir -p "$PREFIX/venv"   # the tests' stub pip fills it
    elif [ ! -x "$PREFIX/venv/bin/python" ]; then
        say "Creating $PREFIX/venv"
        python3 -m venv "$PREFIX/venv" || die "python3 -m venv failed (apt-get install python3-venv)"
    fi
    say "Installing the link service and the iroh package into $PREFIX/venv"
    if [ -n "$PIP" ]; then
        "$PIP" "$PREFIX/venv" "$REPO/tools/deploy" "$IROH_SPEC"
    else
        "$PREFIX/venv/bin/python" -m pip install -q --no-deps "$REPO/tools/deploy"
        "$PREFIX/venv/bin/python" -m pip install -q "$IROH_SPEC" ||
            die "the iroh package does not install here (it has wheels for Linux aarch64 and x86_64 only)"
    fi
    mkdir -p "$BIN_DIR"
    ln -sfn "$PREFIX/venv/bin/canworks-link" "$LINK_BIN"

    mkdir -p "$LINK_DIR"
    chmod 0700 "$LINK_DIR"
    rt="$RUNTIME_PORT"
    [ "$rt" = none ] && rt=null
    printf '{\n  "config": "%s",\n  "port": %d,\n  "runtime_port": %s\n}\n' "$CONFIG" "$LINK_PORT" "$rt" \
        > "$LINK_DIR/link.json"
    LINK_ID=$("$PREFIX/venv/bin/canworks-link" --dir "$LINK_DIR" id) || die "canworks-link could not make its key"

    mkdir -p "$UNIT_DIR"
    cat > "$UNIT" <<EOF
[Unit]
Description=canworks remote link (docs/remote-access.md)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$PREFIX/venv/bin/canworks-link --dir $LINK_DIR run
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
    "$SYSTEMCTL" daemon-reload
    "$SYSTEMCTL" enable --now canworks-link.service
    say "Remote link running, link ID $LINK_ID (internet access off until the config turns it on)"
fi

# The advertisement: a static Avahi service, so the device is listed even
# while the PLC is stopped.
if [ -d "$AVAHI_DIR" ] || [ -d "$(dirname "$AVAHI_DIR")" ]; then
    mkdir -p "$AVAHI_DIR"
    {
        echo '<?xml version="1.0" standalone="no"?>'
        echo '<!DOCTYPE service-group SYSTEM "avahi-service.dtd">'
        echo '<service-group>'
        echo '  <name replace-wildcards="yes">%h</name>'
        echo '  <service>'
        echo '    <type>_canworks._tcp</type>'
        echo "    <port>$DIAG_PORT</port>"
        echo '    <txt-record>v=1</txt-record>'
        echo "    <txt-record>diag=$DIAG_PORT</txt-record>"
        [ "$RUNTIME_PORT" = none ] || echo "    <txt-record>runtime=$RUNTIME_PORT</txt-record>"
        if [ -n "$LINK_ID" ]; then
            echo "    <txt-record>id=$LINK_ID</txt-record>"
            echo "    <txt-record>link=$LINK_PORT</txt-record>"
        fi
        echo '  </service>'
        echo '</service-group>'
    } > "$AVAHI_FILE"
    say "Advertised on the local network: $AVAHI_FILE"
else
    echo "warning: Avahi is not installed, so the configurator will not find this device by itself" \
         "(apt-get install avahi-daemon, then run this again); typing its address works" >&2
fi
