#!/usr/bin/env bash
# Installs the canworks plugin on an unmodified OpenPLC Runtime v4: a native
# install (install.sh --native) or upstream's managed Docker install.
#
#   sudo scripts/install-stock.sh [--runtime-dir DIR] [--prefix /opt/canworks]
#                                 [--lely-ref <commit>] [--no-deps] [--no-editor-hook]
#                                 [--without-canopen | --without-j1939]
#   sudo scripts/install-stock.sh --uninstall [--purge] [--runtime-dir DIR]
#   sudo scripts/install-stock.sh --docker-image <image>   (hand-run container)
#
# Install: builds Lely CANopen and dcfgen into <prefix> (scripts/build-lely.sh),
# installs the deploy tool into <prefix>/venv (the plugin runs its EDS lint,
# canworks.edslint, at every load), builds libcanworks_plugin.so against the runtime's headers, installs it to
# <prefix>/lib/ (outside the runtime's build tree, so a runtime rebuild keeps
# it), and puts exactly one disabled `canworks` line into the runtime's
# plugins.conf. No runtime source file changes. From then on an upload that
# carries conf/canworks.json (canworks-deploy) switches the plugin on, and
# one without it switches it off. Restart the runtime once so it loads the
# plugin.
#
# Protocols: CANopen and J1939 are both built in by default. --without-canopen
# builds J1939 only (no Lely, dcfgen or device simulator); --without-j1939
# builds CANopen only. With J1939 the script loads the kernel module
# can-j1939 and lists it in /etc/modules-load.d/canworks-j1939.conf so it
# loads at every boot (on the host also for Docker installs).
#
# Editor hook (unless --no-editor-hook): lets the editor's own "Build and
# upload" keep canworks on for a project that carries canworks/canworks.json
# (docs/install-stock.md). Installs tools/editor-hook into <prefix>/venv, the hook package to <prefix>/lib/python/ and one file,
# canworks_hook.pth, into the runtime's venv (venvs/runtime).
#
# Uninstall: removes the `canworks` line, the hook's .pth, <prefix>/lib/ and the
# modules-load.d entry.
# --purge also removes Lely and dcfgen (all of <prefix>).
#
# The runtime directory defaults to the WorkingDirectory of the
# openplc-runtime systemd service that `install.sh --native` creates.
#
# Docker: on upstream's managed install (the bootloader's runtime spec,
# /var/lib/openplc-bootloader/runtime-spec.json) the script builds everything
# inside the runtime image the bootloader runs, into <prefix> on the host, adds
# a bind of <prefix> and a PYTHONPATH entry (which loads the editor hook) to the
# spec, and recreates the runtime container: the PLC stops and restarts. The
# editor hook keeps the canworks line in plugins.conf across new containers.
# After a runtime version change canworks stays off until this script is run
# again. --uninstall removes the spec entries again. --docker-image builds for a
# runtime container you start yourself and prints the docker run flags.
# See docs/install-stock.md.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX=/opt/canworks
# The Lely commit the deploy tool's vendored dcf package comes from
# (tools/deploy/canworks/_lely_dcf/VERSION).
LELY_REF=${LELY_REF:-$(cat "$REPO/tools/deploy/canworks/_lely_dcf/VERSION")}
RUNTIME_DIR=""
UNINSTALL=0
PURGE=0
DEPS=1
SERVICE_FILE=${OPENPLC_SERVICE_FILE:-/etc/systemd/system/openplc-runtime.service}
BOOTLOADER_SPEC=${OPENPLC_BOOTLOADER_SPEC:-/var/lib/openplc-bootloader/runtime-spec.json}
RUNTIME_CONTAINER=openplc-runtime
BOOTLOADER_CONTAINER=openplc-bootloader
# Inside the runtime container the install is always here (compiled into the
# plugin); on the host it is <prefix>.
CONTAINER_PREFIX=/opt/canworks
DOCKER_IMAGE=""
IN_IMAGE=0

EDITOR_HOOK=1
WITH_CANOPEN=1
WITH_J1939=1
# J1939 needs the kernel's can-j1939 module (overridable for the tests).
MODULES_LOAD=${CANWORKS_MODULES_LOAD_DIR:-/etc/modules-load.d}/canworks-j1939.conf
MODPROBE=${CANWORKS_MODPROBE:-modprobe}

usage() { sed -n '2,48p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --runtime-dir) RUNTIME_DIR="$2"; shift ;;
        --prefix) PREFIX="$2"; shift ;;
        --lely-ref) LELY_REF="$2"; shift ;;
        --no-deps) DEPS=0 ;;
        --no-editor-hook) EDITOR_HOOK=0 ;;
        --uninstall) UNINSTALL=1 ;;
        --purge) PURGE=1 ;;
        --docker-image) DOCKER_IMAGE="$2"; shift ;;
        --in-image) IN_IMAGE=1 ;;
        --without-canopen) WITH_CANOPEN=0 ;;
        --without-j1939) WITH_J1939=0 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }

[ "$WITH_CANOPEN" -eq 1 ] || [ "$WITH_J1939" -eq 1 ] ||
    die "--without-canopen and --without-j1939 together leave no protocol to build"
if [ "$WITH_CANOPEN" -eq 1 ] && [ "$WITH_J1939" -eq 1 ]; then
    PROTOCOLS="CANopen and J1939"
elif [ "$WITH_CANOPEN" -eq 1 ]; then
    PROTOCOLS="CANopen"
else
    PROTOCOLS="J1939"
fi

# Loads can-j1939 now and at every boot; without J1939, removes the entry.
setup_j1939_module() {
    if [ "$WITH_J1939" -eq 0 ]; then
        rm -f "$MODULES_LOAD"
        return 0
    fi
    mkdir -p "$(dirname "$MODULES_LOAD")"
    echo can-j1939 > "$MODULES_LOAD"
    if "$MODPROBE" can-j1939 2>/dev/null; then
        say "Kernel module can-j1939 loaded (and at every boot: $MODULES_LOAD)"
    else
        echo "warning: the kernel module can-j1939 could not be loaded; J1939 networks stay down until it is" \
             "(modprobe can-j1939; on Ubuntu it is in linux-modules-extra-\$(uname -r))" >&2
    fi
}

# --- Docker ------------------------------------------------------------------

DOCKER_BIND="" DOCKER_ENV=""
docker_entries() {
    DOCKER_BIND="$PREFIX:$CONTAINER_PREFIX"
    DOCKER_ENV="PYTHONPATH=$CONTAINER_PREFIX/lib/sitecustomize"
}

# An install from before the rename to canworks (tools 0.41 and earlier).
# Removed once, when found; the lines naming it are kept by the rename check.
# CANWORKS_OLD_PREFIX is for the tests.
OLD_CONTAINER_PREFIX=/opt/openplc-canopen  # rename-keep
OLD_PREFIX=${CANWORKS_OLD_PREFIX:-$OLD_CONTAINER_PREFIX}
OLD_DOCKER_BIND="$OLD_PREFIX:$OLD_CONTAINER_PREFIX"
OLD_DOCKER_ENV="PYTHONPATH=$OLD_CONTAINER_PREFIX/lib/sitecustomize"

remove_old_prefix() {
    if [ -d "$OLD_PREFIX" ] && [ "$OLD_PREFIX" != "$PREFIX" ]; then
        say "Removing $OLD_PREFIX (the install from before the rename to canworks)"
        rm -rf "${OLD_PREFIX:?}"
    fi
}

# Builds Lely, dcfgen, the plugin and the editor hook in a one-shot container
# of the runtime image $1, into <prefix> on the host (--in-image below).
build_in_image() {
    local image="$1" image_id
    command -v docker >/dev/null 2>&1 || die "docker not found"
    if ! docker image inspect "$image" >/dev/null 2>&1; then
        say "Pulling $image"
        docker pull "$image" >/dev/null || die "cannot pull $image"
    fi
    image_id=$(docker image inspect --format '{{.Id}}' "$image" 2>/dev/null || echo unknown)
    mkdir -p "$PREFIX"
    # Slave networks keep what their master saves (0x1010, LSS) here, outside
    # the uploaded project; an uninstall without --purge keeps it.
    mkdir -p "$PREFIX/state"
    # A writable copy of this checkout: pip builds the tools in their source tree.
    SRC_COPY=$(mktemp -d)
    trap 'rm -rf "${SRC_COPY:?}"' EXIT
    cp -a "$REPO/." "$SRC_COPY/"
    local args=(--in-image --lely-ref "$LELY_REF")
    [ "$WITH_CANOPEN" -eq 1 ] || args+=(--without-canopen)
    [ "$WITH_J1939" -eq 1 ] || args+=(--without-j1939)
    say "Building in $image (this takes a while on a Raspberry Pi)"
    docker run --rm --network host \
        -v "$PREFIX:$CONTAINER_PREFIX" -v "$SRC_COPY:/src" \
        -e CANOPEN_IMAGE="$image" -e CANOPEN_IMAGE_ID="$image_id" \
        --entrypoint bash "$image" /src/scripts/install-stock.sh "${args[@]}" ||
        die "the build in $image failed; the runtime container was not changed"
    rm -rf "${SRC_COPY:?}"
    trap - EXIT
}

# Recreates the runtime container so the bootloader applies the spec (it reads
# the spec when it starts and creates a missing runtime container).
recreate_runtime() {
    say "Recreating the runtime container: the PLC stops now, and the new container has no program;" \
        "upload the program again afterwards"
    docker rm -f "$RUNTIME_CONTAINER" >/dev/null 2>&1 || true
    docker restart "$BOOTLOADER_CONTAINER" >/dev/null ||
        die "could not restart $BOOTLOADER_CONTAINER; run: docker restart $BOOTLOADER_CONTAINER"
}

spec_tool() { python3 "$REPO/scripts/docker_spec.py" "$@"; }

if [ "$EDITOR_HOOK" -eq 0 ] && { [ "$IN_IMAGE" -eq 1 ] || [ -n "$DOCKER_IMAGE" ] ||
        { [ -f "$BOOTLOADER_SPEC" ] && [ "$UNINSTALL" -eq 0 ]; }; }; then
    die "--no-editor-hook is not available for Docker installs: the hook is what keeps the" \
        "canworks line in plugins.conf when the runtime container is recreated"
fi

if [ "$IN_IMAGE" -eq 1 ]; then
    # Inside a one-shot container of the runtime image (see build_in_image).
    [ -n "${RUNTIME_VERSION:-}" ] || die "RUNTIME_VERSION is not set in this image; cannot stamp the build"
    PREFIX=$CONTAINER_PREFIX
    RUNTIME_DIR=${RUNTIME_DIR:-/workdir}
    # The checkout copy belongs to the host user.
    git config --global --add safe.directory '*' 2>/dev/null || true
elif [ -n "$DOCKER_IMAGE" ]; then
    [ "$(id -u)" -eq 0 ] || die "run as root (sudo)"
    [ "$UNINSTALL" -eq 0 ] || die "--uninstall with --docker-image: remove the flags from your container and delete $PREFIX"
    docker_entries
    build_in_image "$DOCKER_IMAGE"
    setup_j1939_module
    cat <<EOF
==> Done. Built for $DOCKER_IMAGE into $PREFIX.
    Start the runtime container with these extra flags (next to upstream's
    --privileged --network host -v /dev:/dev):
        -v $DOCKER_BIND -e $DOCKER_ENV
    Then deploy a program with its canworks config (docs/deploy.md). Run this
    script again whenever you change the runtime image.
EOF
    exit 0
elif [ -f "$BOOTLOADER_SPEC" ]; then
    [ "$(id -u)" -eq 0 ] || die "run as root (sudo): the runtime spec belongs to root"
    command -v docker >/dev/null 2>&1 || die "docker not found, but $BOOTLOADER_SPEC exists"
    command -v python3 >/dev/null 2>&1 || die "python3 is needed to edit $BOOTLOADER_SPEC"
    docker_entries
    IMAGE=$(spec_tool image "$BOOTLOADER_SPEC") || die "cannot read $BOOTLOADER_SPEC; nothing was changed"
    say "Managed Docker install found: runtime image $IMAGE"
    if [ "$UNINSTALL" -eq 1 ]; then
        say "Removing the canworks entries from $BOOTLOADER_SPEC"
        spec_tool remove "$BOOTLOADER_SPEC" "$DOCKER_BIND" "$DOCKER_ENV" || die "could not update $BOOTLOADER_SPEC"
        recreate_runtime
        if [ "$PURGE" -eq 1 ]; then
            say "Removing $PREFIX"
            rm -rf "${PREFIX:?}"
        else
            say "Removing $PREFIX/lib (Lely and dcfgen stay in $PREFIX; --purge removes them)"
            rm -rf "${PREFIX:?}/lib"
        fi
        rm -f "$MODULES_LOAD"
        say "Done. The runtime runs without canworks."
        exit 0
    fi
    build_in_image "$IMAGE"
    if grep -qF "$OLD_CONTAINER_PREFIX" "$BOOTLOADER_SPEC"; then
        say "Removing the entries from before the rename to canworks from $BOOTLOADER_SPEC"
        spec_tool remove "$BOOTLOADER_SPEC" "$OLD_DOCKER_BIND" "$OLD_DOCKER_ENV" || die "could not update $BOOTLOADER_SPEC"
    fi
    remove_old_prefix
    say "Adding $DOCKER_BIND and $DOCKER_ENV to $BOOTLOADER_SPEC"
    spec_tool add "$BOOTLOADER_SPEC" "$DOCKER_BIND" "$DOCKER_ENV" || die "could not update $BOOTLOADER_SPEC"
    setup_j1939_module
    recreate_runtime
    cat <<EOF
==> Done. canworks ($PROTOCOLS) is installed for $IMAGE and disabled until an upload enables it.
    Deploy a program with its canworks config (canworks-deploy, docs/deploy.md),
    or use the editor's "Build and upload" with a project that has a canworks/ folder.
    After a runtime version change canworks stays off until you run this script again.
EOF
    exit 0
elif command -v docker >/dev/null 2>&1 &&
    docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$RUNTIME_CONTAINER\|$BOOTLOADER_CONTAINER"; then
    image=$(docker inspect --format '{{.Config.Image}}' "$RUNTIME_CONTAINER" 2>/dev/null || echo "<the runtime image>")
    die "the OpenPLC runtime runs in a Docker container that no bootloader manages (no $BOOTLOADER_SPEC)." \
        "Nothing was changed. Run: sudo $0 --docker-image $image  and add the printed flags to the container."
fi

# --- The runtime -------------------------------------------------------------

if [ -z "$RUNTIME_DIR" ] && [ -f "$SERVICE_FILE" ]; then
    RUNTIME_DIR=$(sed -n 's/^WorkingDirectory=//p' "$SERVICE_FILE" | head -1)
fi
[ -n "$RUNTIME_DIR" ] || die "no OpenPLC runtime found (no $SERVICE_FILE); pass --runtime-dir <runtime checkout>"
RUNTIME_DIR="$(cd "$RUNTIME_DIR" 2>/dev/null && pwd)" || die "runtime directory $RUNTIME_DIR does not exist"

[ -f "$RUNTIME_DIR/core/src/drivers/plugin_types.h" ] && [ -f "$RUNTIME_DIR/plugins_default.conf" ] ||
    die "$RUNTIME_DIR is not an OpenPLC Runtime v4 checkout (no core/src/drivers/plugin_types.h)"

PLUGINS_CONF="$RUNTIME_DIR/plugins.conf"
LIB_DIR="$PREFIX/lib"
LIB="$LIB_DIR/libcanworks_plugin.so"
LINE="canworks,$LIB,0,1,$LIB_DIR/canworks.json,"
SIM_BIN="$LIB_DIR/canworks-sim"
SIM_LINK=/usr/local/bin/canworks-sim

# Removes the simulator link when it points into this install.
remove_sim_link() {
    if [ -L "$SIM_LINK" ] && [ "$(readlink "$SIM_LINK")" = "$SIM_BIN" ]; then
        rm -f "$SIM_LINK"
    fi
}

RUNTIME_VENV="$RUNTIME_DIR/venvs/runtime"
PTH_NAME=canworks_hook.pth
HOOK_DIR="$LIB_DIR/python"

# The runtime venv's site-packages, or nothing when there is no venv.
runtime_site() {
    [ -x "$RUNTIME_VENV/bin/python3" ] || return 0
    "$RUNTIME_VENV/bin/python3" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])'
}

remove_editor_hook() {
    local site
    site=$(runtime_site)
    if [ -n "$site" ] && [ -e "$site/$PTH_NAME" ]; then
        say "Removing the editor hook from $site"
        rm -f "$site/$PTH_NAME"
    fi
    rm -rf "$HOOK_DIR"
    if [ -x "$PREFIX/venv/bin/python" ]; then
        "$PREFIX/venv/bin/python" -m pip uninstall -q -y canworks-editor-hook >/dev/null 2>&1 || true
    fi
}

# Removes every canworks line from plugins.conf, in place (keeps owner/mode).
strip_plugin_lines() {
    [ -f "$PLUGINS_CONF" ] || return 0
    local tmp
    tmp=$(mktemp)
    grep -v '^canworks,' "$PLUGINS_CONF" > "$tmp" || true
    cat "$tmp" > "$PLUGINS_CONF"
    rm -f "$tmp"
}

# Removes the plugin line, editor hook and simulator link of an install from
# before the rename to canworks, then its folder.
remove_old_install() {
    local site tmp old_sim=/usr/local/bin/openplc-canopen-sim  # rename-keep
    if [ -f "$PLUGINS_CONF" ] && grep -q '^canopen,' "$PLUGINS_CONF"; then  # rename-keep
        say "Removing the canopen line from before the rename to canworks from $PLUGINS_CONF"  # rename-keep
        tmp=$(mktemp)
        grep -v '^canopen,' "$PLUGINS_CONF" > "$tmp" || true  # rename-keep
        cat "$tmp" > "$PLUGINS_CONF"
        rm -f "$tmp"
    fi
    site=$(runtime_site)
    if [ -n "$site" ] && [ -e "$site/openplc_canopen_hook.pth" ]; then  # rename-keep
        say "Removing the editor hook from before the rename to canworks from $site"
        rm -f "$site/openplc_canopen_hook.pth"  # rename-keep
    fi
    if [ -L "$old_sim" ]; then
        rm -f "$old_sim"
    fi
    remove_old_prefix
}

if [ "$UNINSTALL" -eq 1 ]; then
    say "Removing the canworks plugin from $PLUGINS_CONF"
    strip_plugin_lines
    remove_old_install
    remove_editor_hook
    remove_sim_link
    rm -f "$MODULES_LOAD"
    if [ -x "$PREFIX/venv/bin/python" ]; then
        "$PREFIX/venv/bin/python" -m pip uninstall -q -y canworks >/dev/null 2>&1 || true
    fi
    if [ "$PURGE" -eq 1 ]; then
        say "Removing $PREFIX"
        rm -rf "$PREFIX"
    else
        say "Removing $LIB_DIR (Lely and dcfgen stay in $PREFIX; --purge removes them)"
        rm -rf "$LIB_DIR"
    fi
    say "Done. Restart the runtime (systemctl restart openplc-runtime) to unload the plugin."
    exit 0
fi

# --- Lely CANopen and dcfgen ------------------------------------------------

if [ "$DEPS" -eq 1 ]; then
    if [ "$(id -u)" -ne 0 ]; then
        die "run as root to install build dependencies (or pass --no-deps if they are installed)"
    fi
    say "Installing build dependencies"
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        build-essential cmake pkg-config autoconf automake libtool git curl python3 python3-venv libssl-dev >/dev/null
fi
# The diagnostics channel's TLS (plugin/src/can/secure_channel.cpp) needs OpenSSL 3.
pkg-config --atleast-version=3 openssl 2>/dev/null ||
    die "OpenSSL 3 development files are missing: apt-get install libssl-dev (Debian 12 or newer, Raspberry Pi OS bookworm or newer, Ubuntu 22.04 or newer)"
mkdir -p "$PREFIX" "$PREFIX/state"  # state: slave networks' saved parameters
if [ "$WITH_CANOPEN" -eq 1 ]; then
    "$REPO/scripts/build-lely.sh" --prefix "$PREFIX" --ref "$LELY_REF"
    say "Installing the deploy tool into $PREFIX/venv (EDS lint)"
    "$PREFIX/venv/bin/python" -m pip install -q "$REPO/tools/deploy"
elif [ ! -x "$PREFIX/venv/bin/python" ]; then
    # J1939 only: no Lely or dcfgen; the venv holds the editor hook.
    python3 -m venv "$PREFIX/venv"
fi

# --- The plugin ---------------------------------------------------------------

COMMIT_FILE="$LIB_DIR/runtime-commit"
COMMIT=$(git -C "$RUNTIME_DIR" rev-parse HEAD 2>/dev/null || echo unknown)
if [ -f "$COMMIT_FILE" ] && [ "$(cat "$COMMIT_FILE")" != "$COMMIT" ]; then
    echo "warning: the runtime changed since the last install ($(cat "$COMMIT_FILE") -> $COMMIT);" \
         "rebuilding the plugin against it" >&2
fi

BUILD_DIR=$(mktemp -d)
trap 'rm -rf "$BUILD_DIR"' EXIT
say "Building the plugin ($PROTOCOLS) against $RUNTIME_DIR ($COMMIT)"
on_off() { [ "$1" -eq 1 ] && echo ON || echo OFF; }
cmake -S "$REPO" -B "$BUILD_DIR" -DOPENPLC_ROOT="$RUNTIME_DIR" -DCANOPEN_BUILD_TESTS=OFF \
    -DCANWORKS_WITH_CANOPEN="$(on_off "$WITH_CANOPEN")" -DCANWORKS_WITH_J1939="$(on_off "$WITH_J1939")" \
    -DLELY_PREFIX="$PREFIX/lely" -DCANOPEN_PREFIX="$PREFIX" -DCMAKE_BUILD_TYPE=Release >/dev/null
TARGETS=(canworks_plugin)
[ "$WITH_CANOPEN" -eq 0 ] || TARGETS+=(canworks-sim)
cmake --build "$BUILD_DIR" --target "${TARGETS[@]}" -j"$(nproc)" >/dev/null

say "Installing $LIB"
mkdir -p "$LIB_DIR"
install -m 0755 "$BUILD_DIR/plugins/libcanworks_plugin.so" "$LIB.new"
mv -f "$LIB.new" "$LIB"
# The standalone CANopen device simulator (docs/simulator.md), same version as the plugin.
if [ "$WITH_CANOPEN" -eq 1 ]; then
    install -m 0755 "$BUILD_DIR/bin/canworks-sim" "$SIM_BIN.new"
    mv -f "$SIM_BIN.new" "$SIM_BIN"
    if [ "$IN_IMAGE" -eq 0 ]; then
        ln -sfn "$SIM_BIN" "$SIM_LINK"
        say "Installed $SIM_LINK"
    fi
else
    [ "$IN_IMAGE" -eq 1 ] || remove_sim_link
    rm -f "$SIM_BIN"
fi
echo "$COMMIT" > "$COMMIT_FILE"

if [ "$IN_IMAGE" -eq 1 ]; then
    # Checked by the editor hook at webserver start and by the plugin.
    printf '%s\n%s\n%s\n' "$RUNTIME_VERSION" "${CANOPEN_IMAGE:-unknown}" "${CANOPEN_IMAGE_ID:-unknown}" \
        > "$LIB_DIR/runtime-version"
    say "Built for runtime $RUNTIME_VERSION (${CANOPEN_IMAGE:-unknown})"
fi

# --- plugins.conf -------------------------------------------------------------

# In Docker mode the editor hook adds the line in each new runtime container.
if [ "$IN_IMAGE" -eq 0 ]; then

# The runtime creates plugins.conf from plugins_default.conf when it is
# missing; do the same so the line is not lost on its first start.
if [ ! -f "$PLUGINS_CONF" ]; then
    cp "$RUNTIME_DIR/plugins_default.conf" "$PLUGINS_CONF"
fi
strip_plugin_lines
remove_old_install
# The file may end without a newline.
if [ -s "$PLUGINS_CONF" ] && [ "$(tail -c1 "$PLUGINS_CONF" | od -An -c | tr -d ' ')" != '\n' ]; then
    echo >> "$PLUGINS_CONF"
fi
echo "$LINE" >> "$PLUGINS_CONF"
say "plugins.conf: $LINE"
setup_j1939_module
fi

# --- Editor hook --------------------------------------------------------------

install_hook_package() {
    say "Installing the editor hook into $PREFIX/venv"
    "$PREFIX/venv/bin/python" -m pip install -q "$REPO/tools/editor-hook"
    rm -rf "${HOOK_DIR:?}.new"
    mkdir -p "$HOOK_DIR.new"
    cp -R "$REPO/tools/editor-hook/canworks_hook" "$HOOK_DIR.new/"
    find "$HOOK_DIR.new" -name __pycache__ -prune -exec rm -rf {} +
    rm -rf "${HOOK_DIR:?}"
    mv "$HOOK_DIR.new" "$HOOK_DIR"
}

if [ "$IN_IMAGE" -eq 1 ]; then
    install_hook_package
    # The runtime container's PYTHONPATH points here (bootloader extraEnv).
    mkdir -p "$LIB_DIR/sitecustomize"
    install -m 0644 "$REPO/tools/editor-hook/docker/sitecustomize.py" "$LIB_DIR/sitecustomize/sitecustomize.py"
    say "Editor hook: $LIB_DIR/sitecustomize/sitecustomize.py"
    say "Done in the image."
    exit 0
elif [ "$EDITOR_HOOK" -eq 1 ]; then
    SITE=$(runtime_site)
    [ -n "$SITE" ] || die "no runtime venv at $RUNTIME_VENV (run the runtime's install.sh first," \
        "or pass --no-editor-hook)"
    install_hook_package
    # Python reads it at startup in the runtime venv: the first line adds the
    # hook's directory to sys.path (only if it exists), the second registers
    # the hook. If the package is gone, the webserver runs as without it.
    {
        printf '%s\n' "$HOOK_DIR"
        printf '%s\n' 'import sys; exec("try:\n import canworks_hook\nexcept ImportError:\n pass\nelse:\n canworks_hook.install()")'
    } > "$SITE/$PTH_NAME"
    say "Editor hook: $SITE/$PTH_NAME"
    AFTER_UPLOAD="The editor's own \"Build and upload\" keeps canworks on for a project with a canworks/ folder
    (canworks-deploy --into-project) and switches it off for a project without one."
else
    remove_editor_hook
    AFTER_UPLOAD="The editor's own \"Build and upload\" switches canworks off until the next deploy
    (installed with --no-editor-hook)."
fi

cat <<EOF
==> Done. The plugin ($PROTOCOLS) is installed but disabled.
    1. Restart the runtime once so it loads the plugin:  systemctl restart openplc-runtime
    2. Deploy a program with its canworks config:        canworks-deploy --help (docs/deploy.md)
    The runtime enables canworks when an upload carries conf/canworks.json and disables it when one does not.
    $AFTER_UPLOAD
EOF
