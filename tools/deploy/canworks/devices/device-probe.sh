#!/bin/sh
# Reads what a Linux device has for canworks and prints it as one JSON object
# (device-install: the configurator's Devices workspace runs it over SSH,
# from its standard input: `sh -s < device-probe.sh`). It changes nothing and
# needs neither root nor canworks on the device; what it cannot read is null.
#
# For the tests: CANWORKS_PROBE_ROOT puts every file path under another folder,
# CANWORKS_PROBE_SYSTEMCTL, _DOCKER, _IP, _SUDO and _CURL replace those
# commands, CANWORKS_PROBE_URL is the release host checked for internet access
# and CANWORKS_PROBE_UID the user id.

R=${CANWORKS_PROBE_ROOT:-}
SYSTEMCTL=${CANWORKS_PROBE_SYSTEMCTL:-systemctl}
DOCKER=${CANWORKS_PROBE_DOCKER:-docker}
IP=${CANWORKS_PROBE_IP:-ip}
SUDO=${CANWORKS_PROBE_SUDO:-sudo}
CURL=${CANWORKS_PROBE_CURL:-curl}
URL=${CANWORKS_PROBE_URL:-https://github.com}

have() { command -v "$1" >/dev/null 2>&1; }

# A JSON string, or null for an empty value.
js() {
    if [ -z "$1" ]; then
        printf null
    else
        printf '"%s"' "$(printf '%s' "$1" | tr -d '\000-\037' | sed 's/\\/\\\\/g; s/"/\\"/g')"
    fi
}
# A JSON number, or null.
jn() { case "$1" in ''|*[!0-9]*) printf null ;; *) printf '%s' "$1" ;; esac; }
jb() { if [ "$1" = 1 ]; then printf true; else printf false; fi; }
first_line() { [ -r "$1" ] && head -n 1 "$1" 2>/dev/null; }

# --- The system -------------------------------------------------------------------

os=$(sed -n 's/^PRETTY_NAME="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' "$R/etc/os-release" 2>/dev/null | head -n 1)
arch=$(uname -m 2>/dev/null)
systemd=0; [ -d "$R/run/systemd/system" ] && systemd=1
df_dir="$R/opt"; [ -d "$df_dir" ] || df_dir="$R/"
disk=$(df -Pm "$df_dir" 2>/dev/null | awk 'NR == 2 { print $4 }')
mem=$(awk '/^MemTotal:/ { print int($2 / 1024) }' "$R/proc/meminfo" 2>/dev/null)
internet=""
if have "$CURL"; then
    if "$CURL" -sSI --max-time 5 -o /dev/null "$URL" 2>/dev/null; then internet=true; else internet=false; fi
fi
if [ "${CANWORKS_PROBE_UID:-$(id -u)}" = 0 ]; then
    sudo_mode=none
elif have "$SUDO" && "$SUDO" -n true 2>/dev/null; then
    sudo_mode=nopasswd
elif have "$SUDO"; then
    sudo_mode=password
else
    sudo_mode=unavailable
fi

# --- The OpenPLC runtime ------------------------------------------------------------

SERVICE_FILE="$R/etc/systemd/system/openplc-runtime.service"
BOOT="$R/var/lib/openplc-bootloader"
SPEC="$BOOT/runtime-spec.json"
# The bootloader's folder can be root's only and Docker the docker group's:
# with password-less sudo the probe reads both through it (read-only).
spec=""
if [ -r "$SPEC" ]; then
    spec=$(cat "$SPEC" 2>/dev/null)
elif [ "$sudo_mode" = nopasswd ]; then
    spec=$("$SUDO" -n cat "$SPEC" 2>/dev/null)
fi
containers=""
if have "$DOCKER"; then
    containers=$("$DOCKER" ps -a --format '{{.Names}}' 2>/dev/null)
    if [ -z "$containers" ] && [ "$sudo_mode" = nopasswd ]; then
        containers=$("$SUDO" -n "$DOCKER" ps -a --format '{{.Names}}' 2>/dev/null)
    fi
fi
has_container() { printf '%s\n' "$containers" | grep -qx "$1"; }
native_active=0
if [ -f "$SERVICE_FILE" ] && [ "$("$SYSTEMCTL" is-active openplc-runtime.service 2>/dev/null)" = active ]; then
    native_active=1
fi
rt_kind=none rt_version="" rt_dir="" rt_commit=""
# An installed native unit that is not running is weaker evidence than the
# managed runtime's folder or containers (a device moved from native to Docker).
if [ -n "$spec" ] || { [ "$native_active" = 0 ] && { [ -d "$BOOT" ] || has_container openplc-bootloader; }; }; then
    rt_kind=docker-managed
    rt_version=$(printf '%s\n' "$spec" | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' | head -n 1)
elif [ "$native_active" = 1 ] || { [ -f "$SERVICE_FILE" ] && ! has_container openplc-runtime; }; then
    rt_kind=native
    rt_dir=$(sed -n 's/^WorkingDirectory=//p' "$SERVICE_FILE" | head -n 1)
    if [ -n "$rt_dir" ] && have git; then
        rt_version=$(git -C "$R$rt_dir" describe --tags --always 2>/dev/null)
        rt_commit=$(git -C "$R$rt_dir" rev-parse HEAD 2>/dev/null)
    fi
elif has_container openplc-runtime; then
    rt_kind=docker-other
fi
rt_answers=""
if [ "$rt_kind" != none ] && have "$CURL"; then
    code=$("$CURL" -ks --max-time 3 -o /dev/null -w '%{http_code}' https://127.0.0.1:8443/ 2>/dev/null)
    if [ -n "$code" ] && [ "$code" != 000 ]; then rt_answers=true; else rt_answers=false; fi
fi

# --- The bridge -------------------------------------------------------------------------

bridge=null
b="$R/opt/canworks"
if [ -x "$b/bin/canworks-bridge" ]; then
    unit=0; [ -f "$R/etc/systemd/system/canworks-bridge@.service" ] && unit=1
    b_version=$(first_line "$b/VERSION")
    if [ -z "$b_version" ]; then
        b_version=$("$b/bin/canworks-bridge" --version 2>/dev/null | awk '{ print $2; exit }')
    fi
    instances=""
    for d in "$R"/etc/canworks-bridge/*/; do
        [ -f "${d}canworks.json" ] || continue
        name=$(basename "$d")
        state=$("$SYSTEMCTL" is-active "canworks-bridge@$name.service" 2>/dev/null)
        enabled=$("$SYSTEMCTL" is-enabled "canworks-bridge@$name.service" 2>/dev/null)
        sum=""
        have sha256sum && sum=$(sha256sum "${d}canworks.json" 2>/dev/null | cut -d' ' -f1)
        instances="$instances${instances:+, }$(printf '{"name": %s, "state": %s, "enabled": %s, "sha256": %s}' \
            "$(js "$name")" "$(js "$state")" "$(js "$enabled")" "$(js "$sum")")"
    done
    # Without its template unit no instance can start (a partial install).
    bridge=$(printf '{"version": %s, "prefix": %s, "unit": %s, "instances": [%s]}' \
        "$(js "${b_version:-unknown}")" "$(js "${b#"$R"}")" "$(jb "$unit")" "$instances")
fi

# --- Remote access, CAN, the last install job ----------------------------------------------

link=null link_config=""
if [ -f "$R/etc/systemd/system/canworks-link.service" ]; then
    link=$(js "$("$SYSTEMCTL" is-active canworks-link.service 2>/dev/null)")
    # The config it serves: the PLC's, or a bridge's under /etc/canworks-bridge/.
    link_config=$(sed -n 's/.*"config": *"\([^"]*\)".*/\1/p' "$R/etc/canworks-link/link.json" 2>/dev/null | head -n 1)
fi
discovery=0; [ -f "$R/etc/avahi/services/canworks.service" ] && discovery=1

# ip's own JSON, passed through as it is (the configurator reads it).
can=null vcan=null
if have "$IP" && "$IP" -j link show >/dev/null 2>&1; then
    can=$("$IP" -j -d link show type can 2>/dev/null); [ -n "$can" ] || can="[]"
    vcan=$("$IP" -j -d link show type vcan 2>/dev/null); [ -n "$vcan" ] || vcan="[]"
fi
serial=""
for f in "$R"/dev/serial/by-id/*; do
    [ -e "$f" ] || continue
    serial="$serial${serial:+, }$(js "$(basename "$f")")"
done
j1939=0; [ -d "$R/sys/module/can_j1939" ] && j1939=1

job=null
JOBS="$R/var/log/canworks-install"
# Job ids start with their UTC start time, so the glob's order is the age.
last=""
for f in "$JOBS"/*.log; do [ -f "$f" ] && last=$f; done
if [ -n "$last" ]; then
    id=$(basename "$last" .log)
    state=$("$SYSTEMCTL" show -p ActiveState --value "canworks-install-$id.service" 2>/dev/null)
    result=$("$SYSTEMCTL" show -p Result --value "canworks-install-$id.service" 2>/dev/null)
    status=$(sed -n 's/^::canworks-exit //p' "$last" | tail -n 1)
    step=$(grep '^::canworks-step ' "$last" | tail -n 1 | sed 's/^::canworks-step //')
    size=$(wc -c < "$last" | tr -d ' ')
    job=$(printf '{"id": %s, "state": %s, "result": %s, "exit": %s, "step": %s, "log_size": %s}' \
        "$(js "$id")" "$(js "$state")" "$(js "$result")" "$(jn "$status")" "$(js "$step")" "$(jn "$size")")
fi

printf '{"probe": 1, "os": %s, "arch": %s, "systemd": %s, "disk_free_mb": %s, "mem_mb": %s, ' \
    "$(js "$os")" "$(js "$arch")" "$(jb "$systemd")" "$(jn "$disk")" "$(jn "$mem")"
printf '"internet": %s, "sudo": %s, ' "${internet:-null}" "$(js "$sudo_mode")"
printf '"runtime": {"kind": %s, "version": %s, "commit": %s, "answers": %s}, ' \
    "$(js "$rt_kind")" "$(js "$rt_version")" "$(js "$rt_commit")" "${rt_answers:-null}"
printf '"bridge": %s, "link": %s, "link_config": %s, "discovery": %s, ' \
    "$bridge" "$link" "$(js "$link_config")" "$(jb "$discovery")"
printf '"can": %s, "vcan": %s, "serial": [%s], "j1939_module": %s, "install_job": %s}\n' \
    "$can" "$vcan" "$serial" "$(jb "$j1939")" "$job"
