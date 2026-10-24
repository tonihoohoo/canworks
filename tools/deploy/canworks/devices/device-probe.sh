#!/bin/sh
# Reads what a Linux device has for canworks and prints it as one JSON object
# (device-install: the configurator's Devices workspace runs it over SSH,
# from its standard input: `sh -s < device-probe.sh`). It changes nothing and
# needs neither root nor canworks on the device; what it cannot read is null.
# It reads canworks' own parts only, never the OpenPLC runtime or Docker.
#
# For the tests: CANWORKS_PROBE_ROOT puts every file path under another folder,
# CANWORKS_PROBE_SYSTEMCTL, _IP, _SUDO, _CURL, _PYTHON and _OPENSSL replace those
# commands, CANWORKS_PROBE_URL is the release host checked for internet access
# and CANWORKS_PROBE_UID the user id.

R=${CANWORKS_PROBE_ROOT:-}
SYSTEMCTL=${CANWORKS_PROBE_SYSTEMCTL:-systemctl}
IP=${CANWORKS_PROBE_IP:-ip}
SUDO=${CANWORKS_PROBE_SUDO:-sudo}
CURL=${CANWORKS_PROBE_CURL:-curl}
PYTHON=${CANWORKS_PROBE_PYTHON:-python3}
OPENSSL=${CANWORKS_PROBE_OPENSSL:-openssl}
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
        # Only names install-bridge.sh --instance takes: copies such as
        # line1.bak-271 are not instances.
        case $name in *[!A-Za-z0-9_-]*) continue ;; esac
        state=$("$SYSTEMCTL" is-active "canworks-bridge@$name.service" 2>/dev/null)
        enabled=$("$SYSTEMCTL" is-enabled "canworks-bridge@$name.service" 2>/dev/null)
        sum="" files=""
        have sha256sum && sum=$(sha256sum "${d}canworks.json" 2>/dev/null | cut -d' ' -f1)
        # "name sha256" of every file: the configurator compares them with the files a job uploads.
        for f in "$d"*; do
            { [ -f "$f" ] && have sha256sum; } || continue
            fsum=$(sha256sum "$f" 2>/dev/null | cut -d' ' -f1)
            [ -z "$fsum" ] || files="$files${files:+, }$(js "$(basename "$f") $fsum")"
        done
        instances="$instances${instances:+, }$(printf '{"name": %s, "state": %s, "enabled": %s, "sha256": %s, "files": [%s]}' \
            "$(js "$name")" "$(js "$state")" "$(js "$enabled")" "$(js "$sum")" "$files")"
    done
    # Without its template unit no instance can start (a partial install).
    bridge=$(printf '{"version": %s, "prefix": %s, "unit": %s, "instances": [%s]}' \
        "$(js "${b_version:-unknown}")" "$(js "${b#"$R"}")" "$(jb "$unit")" "$instances")
fi

# What each running bridge instance listens on and drives (the Devices page
# warns before a second one starts on the same port or interface): the Modbus
# listen address, the diagnostics port and the CAN interfaces of networks
# that are not simulated. Only these fields, never the config itself (it can
# hold a token verifier); null without python3.
bridge_uses=null
if [ "$bridge" != null ] && have python3; then
    active=""
    for d in "$R"/etc/canworks-bridge/*/; do
        [ -f "${d}canworks.json" ] || continue
        name=$(basename "$d")
        case $name in *[!A-Za-z0-9_-]*) continue ;; esac
        [ "$("$SYSTEMCTL" is-active "canworks-bridge@$name.service" 2>/dev/null)" = active ] && active="$active $d"
    done
    # shellcheck disable=SC2086 # one folder per word
    bridge_uses=$(python3 -c '
import json, os, sys
out = {}
for d in sys.argv[1:]:
    try:
        with open(os.path.join(d, "canworks.json")) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        continue
    if not isinstance(cfg, dict):
        continue
    b = cfg.get("bridge") if isinstance(cfg.get("bridge"), dict) else {}
    g = cfg.get("diagnostics")
    nets = cfg.get("networks") if isinstance(cfg.get("networks"), list) else [cfg]
    ifs = []
    for n in nets:
        a = n.get("adapter") if isinstance(n, dict) and isinstance(n.get("adapter"), dict) else {}
        if isinstance(n, dict) and not a and isinstance(n.get("interface"), str):
            a = {"interface": n["interface"]}
        if a.get("simulate") is True:
            continue
        for k in ("interface", "device"):
            if isinstance(a.get(k), str) and a[k] and a[k] not in ifs:
                ifs.append(a[k])
    port = g.get("port", 7531) if isinstance(g, dict) else None
    out[os.path.basename(os.path.normpath(d))] = {
        "listen": b.get("listen") if isinstance(b.get("listen"), str) else None,
        "diag_port": port if isinstance(port, int) else None, "interfaces": ifs}
print(json.dumps(out))
' $active 2>/dev/null) || bridge_uses=null
    [ -n "$bridge_uses" ] || bridge_uses=null
fi

# --- Remote access, CAN, the last install job ----------------------------------------------

link=null link_config=""
if [ -f "$R/etc/systemd/system/canworks-link.service" ]; then
    link=$(js "$("$SYSTEMCTL" is-active canworks-link.service 2>/dev/null)")
    # The config it serves: the PLC's, or a bridge's under /etc/canworks-bridge/.
    link_config=$(sed -n 's/.*"config": *"\([^"]*\)".*/\1/p' "$R/etc/canworks-link/link.json" 2>/dev/null | head -n 1)
fi
discovery=0; [ -f "$R/etc/avahi/services/canworks.service" ] && discovery=1

# Adapter servers (canworks-diag adapter-serve --install-service): one unit
# each, its options from ExecStart, its connected PCs from the status file of
# the user it runs as when this user can read it.
opt() { printf '%s\n' "$1" | sed -n "s/.* $2 \([^ ]*\).*/\1/p" | head -n 1; }
adapters=""
for f in "$R"/etc/systemd/system/canworks-adapter-*.service; do
    [ -f "$f" ] || continue
    name=$(basename "$f")
    exec_line=$(sed -n 's/^ExecStart=//p' "$f" | head -n 1)
    user=$(sed -n 's/^User=//p' "$f" | head -n 1)
    a_state=$("$SYSTEMCTL" is-active "$name" 2>/dev/null)
    a_adapter=$(opt "$exec_line" --adapter)
    a_rate=$(opt "$exec_line" --bitrate)
    a_port=$(opt "$exec_line" --port); [ -n "$a_port" ] || a_port=7536
    a_changes=0; case "$exec_line " in *" --allow-changes "*) a_changes=1 ;; esac
    a_adv=0; [ -f "$R/etc/avahi/services/$name" ] && a_adv=1
    pcs=""
    home=$(awk -F: -v u="$user" '$1 == u { print $6; exit }' "$R/etc/passwd" 2>/dev/null)
    st="$R$home/.config/canworks/adapter-serve-$a_port.status.json"
    if [ "$a_state" = active ] && [ -n "$home" ] && [ -r "$st" ]; then
        pcs=$(grep -c '"address"' "$st" 2>/dev/null)
    fi
    adapters="$adapters${adapters:+, }$(printf '{"unit": %s, "state": %s, "adapter": %s, "bitrate_kbit": %s, "port": %s, "allow_changes": %s, "discovery": %s, "user": %s, "pcs": %s}' \
        "$(js "$name")" "$(js "$a_state")" "$(js "$a_adapter")" "$(jn "$a_rate")" "$(jn "$a_port")" "$(jb "$a_changes")" \
        "$(jb "$a_adv")" "$(js "$user")" "$(jn "$pcs")")"
done

# What the adapter server file needs (python3 3.11+ and the openssl command).
python=""
have "$PYTHON" && python=$("$PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null)
openssl=0; have "$OPENSSL" && openssl=1

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
    # The job appends " @<epoch>" to these lines: the status alone, the step without it.
    status=$(sed -n 's/^::canworks-exit \([0-9]*\).*/\1/p' "$last" | tail -n 1)
    step=$(grep '^::canworks-step ' "$last" | tail -n 1 | sed 's/^::canworks-step //; s/ @[0-9]*$//')
    size=$(wc -c < "$last" | tr -d ' ')
    job=$(printf '{"id": %s, "state": %s, "result": %s, "exit": %s, "step": %s, "log_size": %s}' \
        "$(js "$id")" "$(js "$state")" "$(js "$result")" "$(jn "$status")" "$(js "$step")" "$(jn "$size")")
fi

printf '{"probe": 1, "os": %s, "arch": %s, "systemd": %s, "disk_free_mb": %s, "mem_mb": %s, ' \
    "$(js "$os")" "$(js "$arch")" "$(jb "$systemd")" "$(jn "$disk")" "$(jn "$mem")"
printf '"internet": %s, "sudo": %s, ' "${internet:-null}" "$(js "$sudo_mode")"
printf '"bridge": %s, "link": %s, "link_config": %s, "discovery": %s, "adapters": [%s], ' \
    "$bridge" "$link" "$(js "$link_config")" "$(jb "$discovery")" "$adapters"
printf '"bridge_uses": %s, ' "$bridge_uses"
printf '"python3": %s, "openssl": %s, ' "$(js "$python")" "$(jb "$openssl")"
printf '"can": %s, "vcan": %s, "serial": [%s], "j1939_module": %s, "install_job": %s}\n' \
    "$can" "$vcan" "$serial" "$(jb "$j1939")" "$job"
