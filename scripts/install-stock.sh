#!/usr/bin/env bash
# Installs the CANopen plugin on an unmodified OpenPLC Runtime v4: a native
# install (install.sh --native) or upstream's managed Docker install.
#
#   sudo scripts/install-stock.sh [--runtime-dir DIR] [--prefix /opt/openplc-canopen]
#                                 [--lely-ref <commit>] [--no-deps] [--no-editor-hook]
#   sudo scripts/install-stock.sh --uninstall [--purge] [--runtime-dir DIR]
#   sudo scripts/install-stock.sh --docker-image <image>   (hand-run container)
#
# Install: builds Lely CANopen and dcfgen into <prefix> (scripts/build-lely.sh),
# installs the deploy tool into <prefix>/venv (the plugin runs its EDS lint,
# openplc_canopen_deploy.edslint, at every load), builds libcanopen_plugin.so against the runtime's headers, installs it to
# <prefix>/lib/ (outside the runtime's build tree, so a runtime rebuild keeps
# it), and puts exactly one disabled `canopen` line into the runtime's
# plugins.conf. No runtime source file changes. From then on an upload that
# carries conf/canopen.json (openplc-canopen-deploy) switches the plugin on, and
# one without it switches it off. Restart the runtime once so it loads the
# plugin.
#
# Editor hook (unless --no-editor-hook): lets the editor's own "Build and
# upload" keep CANopen on for a project that carries canopen/canopen.json
# (docs/install-stock.md). Installs tools/editor-hook into <prefix>/venv, the hook package to <prefix>/lib/python/ and one file,
# openplc_canopen_hook.pth, into the runtime's venv (venvs/runtime).
#
# Uninstall: removes the `canopen` line, the hook's .pth and <prefix>/lib/.
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
# editor hook keeps the canopen line in plugins.conf across new containers.
# After a runtime version change CANopen stays off until this script is run
# again. --uninstall removes the spec entries again. --docker-image builds for a
# runtime container you start yourself and prints the docker run flags.
# See docs/install-stock.md.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX=/opt/openplc-canopen
# The Lely commit the deploy tool's vendored dcf package comes from
# (tools/deploy/openplc_canopen_deploy/_lely_dcf/VERSION).
LELY_REF=${LELY_REF:-$(cat "$REPO/tools/deploy/openplc_canopen_deploy/_lely_dcf/VERSION")}
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
CONTAINER_PREFIX=/opt/openplc-canopen
DOCKER_IMAGE=""
IN_IMAGE=0

EDITOR_HOOK=1

usage() { sed -n '2,45p' "$0" | sed 's/^# \{0,1\}//'; }

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
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

die() { echo "error: $*" >&2; exit 1; }
say() { echo "==> $*"; }

# --- Docker ------------------------------------------------------------------

DOCKER_BIND="" DOCKER_ENV=""
docker_entries() {
    DOCKER_BIND="$PREFIX:$CONTAINER_PREFIX"
    DOCKER_ENV="PYTHONPATH=$CONTAINER_PREFIX/lib/sitecustomize"
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
        "canopen line in plugins.conf when the runtime container is recreated"
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
    cat <<EOF
==> Done. Built for $DOCKER_IMAGE into $PREFIX.
    Start the runtime container with these extra flags (next to upstream's
    --privileged --network host -v /dev:/dev):
        -v $DOCKER_BIND -e $DOCKER_ENV
    Then deploy a program with its CANopen config (docs/deploy.md). Run this
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
        say "Removing the CANopen entries from $BOOTLOADER_SPEC"
        spec_tool remove "$BOOTLOADER_SPEC" "$DOCKER_BIND" "$DOCKER_ENV" || die "could not update $BOOTLOADER_SPEC"
        recreate_runtime
        if [ "$PURGE" -eq 1 ]; then
            say "Removing $PREFIX"
            rm -rf "${PREFIX:?}"
        else
            say "Removing $PREFIX/lib (Lely and dcfgen stay in $PREFIX; --purge removes them)"
            rm -rf "${PREFIX:?}/lib"
        fi
        say "Done. The runtime runs without CANopen."
        exit 0
    fi
    build_in_image "$IMAGE"
    say "Adding $DOCKER_BIND and $DOCKER_ENV to $BOOTLOADER_SPEC"
    spec_tool add "$BOOTLOADER_SPEC" "$DOCKER_BIND" "$DOCKER_ENV" || die "could not update $BOOTLOADER_SPEC"
    recreate_runtime
    cat <<EOF
==> Done. CANopen is installed for $IMAGE and disabled until an upload enables it.
    Deploy a program with its CANopen config (openplc-canopen-deploy, docs/deploy.md),
    or use the editor's "Build and upload" with a project that has a canopen/ folder.
    After a runtime version change CANopen stays off until you run this script again.
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
LIB="$LIB_DIR/libcanopen_plugin.so"
LINE="canopen,$LIB,0,1,$LIB_DIR/canopen.json,"

RUNTIME_VENV="$RUNTIME_DIR/venvs/runtime"
PTH_NAME=openplc_canopen_hook.pth
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
        "$PREFIX/venv/bin/python" -m pip uninstall -q -y openplc-canopen-editor-hook >/dev/null 2>&1 || true
    fi
}

# Removes every canopen line from plugins.conf, in place (keeps owner/mode).
strip_canopen_lines() {
    [ -f "$PLUGINS_CONF" ] || return 0
    local tmp
    tmp=$(mktemp)
    grep -v '^canopen,' "$PLUGINS_CONF" > "$tmp" || true
    cat "$tmp" > "$PLUGINS_CONF"
    rm -f "$tmp"
}

if [ "$UNINSTALL" -eq 1 ]; then
    say "Removing the canopen plugin from $PLUGINS_CONF"
    strip_canopen_lines
    remove_editor_hook
    if [ -x "$PREFIX/venv/bin/python" ]; then
        "$PREFIX/venv/bin/python" -m pip uninstall -q -y openplc-canopen-deploy >/dev/null 2>&1 || true
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
        build-essential cmake pkg-config autoconf automake libtool git curl python3 python3-venv >/dev/null
fi
mkdir -p "$PREFIX" "$PREFIX/state"  # state: slave networks' saved parameters
"$REPO/scripts/build-lely.sh" --prefix "$PREFIX" --ref "$LELY_REF"
say "Installing the deploy tool into $PREFIX/venv (EDS lint)"
"$PREFIX/venv/bin/python" -m pip install -q "$REPO/tools/deploy"

# --- The plugin ---------------------------------------------------------------

COMMIT_FILE="$LIB_DIR/runtime-commit"
COMMIT=$(git -C "$RUNTIME_DIR" rev-parse HEAD 2>/dev/null || echo unknown)
if [ -f "$COMMIT_FILE" ] && [ "$(cat "$COMMIT_FILE")" != "$COMMIT" ]; then
    echo "warning: the runtime changed since the last install ($(cat "$COMMIT_FILE") -> $COMMIT);" \
         "rebuilding the plugin against it" >&2
fi

BUILD_DIR=$(mktemp -d)
trap 'rm -rf "$BUILD_DIR"' EXIT
say "Building the plugin against $RUNTIME_DIR ($COMMIT)"
cmake -S "$REPO" -B "$BUILD_DIR" -DOPENPLC_ROOT="$RUNTIME_DIR" -DCANOPEN_BUILD_TESTS=OFF \
    -DLELY_PREFIX="$PREFIX/lely" -DCANOPEN_PREFIX="$PREFIX" -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build "$BUILD_DIR" --target canopen_plugin -j"$(nproc)" >/dev/null

say "Installing $LIB"
mkdir -p "$LIB_DIR"
install -m 0755 "$BUILD_DIR/plugins/libcanopen_plugin.so" "$LIB.new"
mv -f "$LIB.new" "$LIB"
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
strip_canopen_lines
# The file may end without a newline.
if [ -s "$PLUGINS_CONF" ] && [ "$(tail -c1 "$PLUGINS_CONF" | od -An -c | tr -d ' ')" != '\n' ]; then
    echo >> "$PLUGINS_CONF"
fi
echo "$LINE" >> "$PLUGINS_CONF"
say "plugins.conf: $LINE"
fi

# --- Editor hook --------------------------------------------------------------

install_hook_package() {
    say "Installing the editor hook into $PREFIX/venv"
    "$PREFIX/venv/bin/python" -m pip install -q "$REPO/tools/editor-hook"
    rm -rf "${HOOK_DIR:?}.new"
    mkdir -p "$HOOK_DIR.new"
    cp -R "$REPO/tools/editor-hook/openplc_canopen_hook" "$HOOK_DIR.new/"
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
        printf '%s\n' 'import sys; exec("try:\n import openplc_canopen_hook\nexcept ImportError:\n pass\nelse:\n openplc_canopen_hook.install()")'
    } > "$SITE/$PTH_NAME"
    say "Editor hook: $SITE/$PTH_NAME"
    AFTER_UPLOAD="The editor's own \"Build and upload\" keeps CANopen on for a project with a canopen/ folder
    (openplc-canopen-deploy --into-project) and switches it off for a project without one."
else
    remove_editor_hook
    AFTER_UPLOAD="The editor's own \"Build and upload\" switches CANopen off until the next deploy
    (installed with --no-editor-hook)."
fi

cat <<EOF
==> Done. The plugin is installed but disabled.
    1. Restart the runtime once so it loads the plugin:  systemctl restart openplc-runtime
    2. Deploy a program with its CANopen config:         openplc-canopen-deploy --help (docs/deploy.md)
    The runtime enables CANopen when an upload carries conf/canopen.json and disables it when one does not.
    $AFTER_UPLOAD
EOF
