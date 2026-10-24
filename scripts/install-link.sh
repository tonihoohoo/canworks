#!/usr/bin/env bash
# Installs the remote link and the device's local-network advertisement on a
# device (docs/remote-access.md). install-bridge.sh calls it
# (--with-link, and the advertisement unless --without-discovery); it also runs
# on its own, and the configurator's Devices page runs it to turn the link and
# discovery on and off.
#
#   sudo scripts/install-link.sh --config FILE [--runtime-port 8443|none]
#                                [--diag-port PORT] [--prefix /opt/canworks-link]
#                                [--without-discovery] [--version X] [--dry-run]
#   sudo scripts/install-link.sh --discovery-only --config FILE [--runtime-port ...]
#   sudo scripts/install-link.sh --remove-discovery
#   sudo scripts/install-link.sh --uninstall [--keep-discovery] [--purge] [--prefix ...]
#
# --config is the deployed canworks.json the bridge runs
# (/etc/canworks-bridge/NAME/canworks.json). The advertisement carries its
# diagnostics.port (7531 when it has none) unless --diag-port names another.
# The link service reads its token_verifier for pairing and its
# diagnostics.remote_link for internet access, and follows changes to it.
#
# Install: a Python virtual environment in <prefix>/venv with the canworks
# package (no dependencies) and the iroh package, /usr/local/bin/canworks-link,
# the unit canworks-link.service (enabled and started), /etc/canworks-link/
# with the device's key and no paired PCs, and the Avahi service file
# /etc/avahi/services/canworks.service (_canworks._tcp with the link ID;
# --without-discovery leaves it out and removes an old one). Internet access
# stays off until a config with diagnostics.remote_link.internet true is uploaded.
# Run from a downloaded copy (curl ... | sudo bash -s -- ...) or with --version X,
# the link install downloads release deploy-vX (the newest without --version)
# and runs that release's install-link.sh.
#
# --discovery-only (old name --without-link) writes only the advertisement; it
# carries the link ID when the link is installed. --remove-discovery removes it.
#
# Uninstall: stops and removes the service, the command, <prefix> and the Avahi
# file (--keep-discovery keeps the advertisement without the link ID);
# /etc/canworks-link (key and paired PCs) stays unless --purge.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
PREFIX=/opt/canworks-link
CONFIG=""
RUNTIME_PORT=8443
DIAG_PORT=""
LINK_PORT=7533
WITH_LINK=1
UNINSTALL=0
PURGE=0
WITH_DISCOVERY=1
KEEP_DISCOVERY=0
REMOVE_DISCOVERY=0
VERSION=""
DRY_RUN=0
PASS=()
IROH_SPEC="iroh>=1.1,<1.2"
GITHUB=${CANWORKS_REPO:-https://github.com/tonihoohoo/canworks}
# Overridable for the tests.
UNIT_DIR=${CANWORKS_UNIT_DIR:-/etc/systemd/system}
LINK_DIR=${CANWORKS_LINK_DIR:-/etc/canworks-link}
AVAHI_DIR=${CANWORKS_AVAHI_DIR:-/etc/avahi/services}
BIN_DIR=${CANWORKS_BIN_DIR:-/usr/local/bin}
SYSTEMCTL=${CANWORKS_SYSTEMCTL:-systemctl}
PIP=${CANWORKS_LINK_PIP:-}

usage() {
    if [ -f "${BASH_SOURCE[0]:-}" ]; then
        awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]:-}"
    else
        echo "see $GITHUB/blob/main/scripts/install-link.sh"
    fi
}

while [ $# -gt 0 ]; do
    case "$1" in
        --config) CONFIG="$2"; PASS+=("$1" "$2"); shift ;;
        --runtime-port) RUNTIME_PORT="$2"; PASS+=("$1" "$2"); shift ;;
        --diag-port) DIAG_PORT="$2"; PASS+=("$1" "$2"); shift ;;
        --prefix) PREFIX="$2"; PASS+=("$1" "$2"); shift ;;
        --without-link|--discovery-only) WITH_LINK=0; PASS+=("$1") ;;
        --without-discovery) WITH_DISCOVERY=0; PASS+=("$1") ;;
        --remove-discovery) REMOVE_DISCOVERY=1 ;;
        --keep-discovery) KEEP_DISCOVERY=1 ;;
        --version) VERSION=${2#deploy-v}; VERSION=${VERSION#v}; shift ;;
        --dry-run) DRY_RUN=1 ;;
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

if [ "$REMOVE_DISCOVERY" -eq 1 ]; then
    [ "$UNINSTALL" -eq 0 ] || die "--remove-discovery and --uninstall: use --uninstall alone"
    rm -f "$AVAHI_FILE"
    say "No longer advertised on the local network"
    exit 0
fi

if [ "$UNINSTALL" -eq 1 ]; then
    if [ -f "$UNIT" ]; then
        say "Stopping canworks-link.service"
        "$SYSTEMCTL" disable --now canworks-link.service || true
        rm -f "$UNIT"
        "$SYSTEMCTL" daemon-reload || true
    fi
    rm -f "$LINK_BIN"
    if [ "$KEEP_DISCOVERY" -eq 1 ] && [ -f "$AVAHI_FILE" ]; then
        # Still advertised, without the link.
        sed -i -e '/<txt-record>id=/d' -e '/<txt-record>link=/d' "$AVAHI_FILE"
        say "Still advertised on the local network, without the remote link"
    else
        rm -f "$AVAHI_FILE"
    fi
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

[ "$WITH_LINK" -eq 1 ] || [ "$WITH_DISCOVERY" -eq 1 ] || die "--discovery-only and --without-discovery leave nothing to do"

# The link installs the PC tools package from the source next to this script:
# a downloaded copy (or --version) fetches the release's source first.
release_install() {
    [ -n "$VERSION" ] || VERSION=$(latest_version)
    local tarball="$GITHUB/archive/refs/tags/deploy-v$VERSION.tar.gz"
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "would download: $tarball"
        printf 'would run: bash <source>/scripts/install-link.sh'; printf ' %q' "${PASS[@]+"${PASS[@]}"}"; echo
        exit 0
    fi
    [ "$(id -u)" = 0 ] || die "run it as root (sudo)"
    command -v curl >/dev/null 2>&1 || die "curl is needed"
    echo "::canworks-step 1/2 Downloading canworks $VERSION"
    SRC=$(mktemp -d /tmp/canworks-link-install.XXXXXX)
    trap 'rm -rf "${SRC:?}"' EXIT
    curl -fsSL "$tarball" | tar -xz -C "$SRC" --strip-components=1 || die "could not download $tarball"
    [ -f "$SRC/scripts/install-link.sh" ] || die "$tarball has no scripts/install-link.sh"
    echo "::canworks-step 2/2 Installing the remote link"
    bash "$SRC/scripts/install-link.sh" "${PASS[@]+"${PASS[@]}"}"
    exit $?
}

latest_version() {
    local url tag
    command -v curl >/dev/null 2>&1 || die "curl is needed"
    url=$(curl -fsSL -o /dev/null -w '%{url_effective}' "$GITHUB/releases/latest") ||
        die "could not reach $GITHUB/releases/latest"
    tag=${url##*/}
    [[ $tag == deploy-v* ]] || die "could not find the newest release at $GITHUB/releases"
    echo "${tag#deploy-v}"
}

if [ "$WITH_LINK" -eq 1 ] && [ -z "$PIP" ] && { [ -n "$VERSION" ] || [ ! -f "$REPO/tools/deploy/pyproject.toml" ]; }; then
    release_install
fi
[ "$DRY_RUN" -eq 0 ] || die "--dry-run shows the download of a release install (--version X, or a downloaded copy)"

LINK_ID=""
if [ "$WITH_LINK" -eq 0 ] && [ -f "$UNIT" ] && [ -x "$LINK_BIN" ]; then
    # The advertisement alone, next to an installed link: it keeps the link's ID.
    LINK_ID=$("$LINK_BIN" --dir "$LINK_DIR" id 2>/dev/null) || LINK_ID=""
    p=$(sed -n 's/.*"port": *\([0-9]*\).*/\1/p' "$LINK_DIR/link.json" 2>/dev/null | head -n 1)
    [ -z "$p" ] || LINK_PORT=$p
fi
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
        "$PREFIX/venv/bin/python" -m pip install -q --no-warn-conflicts "$IROH_SPEC" ||
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
# It also exits on purpose to apply new internet settings (iroh frees its port only then).
Restart=always
RestartSec=1
# A ceiling for what PCs on the network can make it hold (it runs as root next to the PLC).
MemoryMax=128M

[Install]
WantedBy=multi-user.target
EOF
    "$SYSTEMCTL" daemon-reload
    "$SYSTEMCTL" enable canworks-link.service
    "$SYSTEMCTL" restart canworks-link.service   # a reinstall runs the new code
    say "Remote link running, link ID $LINK_ID (internet access off until the config turns it on)"
fi

# The advertisement: a static Avahi service, so the device is listed even
# while the PLC is stopped. Its port is the one the bridge listens on: the
# config's diagnostics.port.
if [ -z "$DIAG_PORT" ] && command -v python3 >/dev/null 2>&1; then
    DIAG_PORT=$(python3 -c 'import json, sys
p = (json.load(open(sys.argv[1])).get("diagnostics") or {}).get("port")
print(p if type(p) is int and 0 < p < 65536 else "")' "$CONFIG" 2>/dev/null) || DIAG_PORT=""
fi
case "$DIAG_PORT" in ''|*[!0-9]*) DIAG_PORT=7531 ;; esac
if [ "$WITH_DISCOVERY" -eq 0 ]; then
    if [ -f "$AVAHI_FILE" ]; then
        rm -f "$AVAHI_FILE"
        say "No longer advertised on the local network"
    fi
elif [ -d "$AVAHI_DIR" ] || [ -d "$(dirname "$AVAHI_DIR")" ]; then
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
