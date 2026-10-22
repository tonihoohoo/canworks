"""What a device has against what the project needs: the rows of the device
page, the one main action and why an action cannot run. Pure functions of the
probe (device-probe.sh's JSON), the project's target (None with no config
open) and the newest release, so every case is tested without a device."""

import re

MIN_FREE_MB = 2048
DOCKER_STOP = "The PLC stops and comes back without a program; upload it again afterwards."
OPENPLC_INSTALLER = "https://runtime.getedge.me"
# The OpenPLC runtime release canworks is pinned to: CI tests it, installs and
# every Docker-mode plugin job put devices on it, and the upstream bootloader
# pinned with it (docker/local-runtime/runtime-version and bootloader-version;
# a test keeps them the same).
TESTED_RUNTIME = "v4.3.1"
PINNED_BOOTLOADER = "bootloader-v1.1.0"


def version_tuple(text):
    """(0, 98, 0) for "0.98.0" or "deploy-v0.98.0"; None for anything else
    (a git describe of a development build, "unknown")."""
    m = re.match(r"^(?:deploy-)?v?(\d+)\.(\d+)\.(\d+)$", (text or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def _plain(v):
    return (v or "").strip().lstrip("v")


def rebuild_needed(probe):
    """The runtime the plugin was built for is not the one on the device:
    the plugin is off until it is built again."""
    plugin, rt = probe.get("plugin") or {}, probe.get("runtime") or {}
    built = (plugin.get("built_for") or "").strip()
    if not plugin or not built:
        return None
    if rt.get("kind") == "docker-managed" and rt.get("version"):
        return rt["version"] if _plain(built) != _plain(rt["version"]) else None
    if rt.get("kind") == "native" and rt.get("commit"):
        return (rt.get("version") or rt["commit"][:12]) if built != rt["commit"] else None
    return None


def blocked(probe, latest):
    """Why no install action can run on this device now, or None."""
    if probe.get("systemd") is False:
        return "This device has no systemd, which the install job needs."
    if probe.get("sudo") == "unavailable":
        return "The SSH user cannot use sudo: log in as root or as a user with sudo rights."
    job = probe.get("install_job") or {}
    if job.get("state") in ("active", "activating"):
        return "An install is running on this device."
    if probe.get("internet") is False:
        return "The device cannot reach github.com, which the install downloads from."
    free = probe.get("disk_free_mb")
    if isinstance(free, int) and free < MIN_FREE_MB:
        return "Less than 2 GB is free on the device (%d MB); the build needs about 2 GB." % free
    if not latest:
        return "The newest canworks release could not be found from this PC. Check its internet access."
    return None


def _runtime_text(rt):
    kind = rt.get("kind")
    if kind in (None, "none"):
        return "not installed"
    where = {"native": "native", "docker-managed": "Docker", "docker-other": "own Docker container"}.get(kind, kind)
    parts = [p for p in (rt.get("version"), where) if p]
    if rt.get("answers") is True:
        parts.append("answers")
    elif rt.get("answers") is False:
        parts.append("not answering")
    return " · ".join(parts)


def untested_runtime(rt):
    """A note when the device runs another runtime than the pinned one, newer
    or older; None for the pinned one or an unknown version."""
    have, tested = version_tuple(rt.get("version")), version_tuple(TESTED_RUNTIME)
    if have and tested and have != tested:
        return "canworks runs on runtime %s; this device runs %s." % (TESTED_RUNTIME, rt["version"].strip())
    return None


def runtime_off_pin(rt):
    """The managed Docker runtime's version when it is not the pinned one (the
    main action then puts it back); None otherwise."""
    have = version_tuple(rt.get("version"))
    if rt.get("kind") == "docker-managed" and have and have != version_tuple(TESTED_RUNTIME):
        return rt["version"].strip()
    return None


def switch_text(off_pin):
    """The confirmation line of a job that puts the runtime back on the pin."""
    if not off_pin:
        return ""
    return "The runtime goes from %s back to %s, the version canworks is tested with." % (off_pin, TESTED_RUNTIME)


def _main(action, label, version, confirm=(), **extra):
    out = {"action": action, "label": label, "version": version, "confirm": [c for c in confirm if c]}
    out.update(extra)
    return out


SHARE_CAN = ("The PLC and the bridge cannot use the same CAN interface: give each its own (can0, can1, …) "
             "in their configs.")

LINK_OFF = "Paired PCs stay paired: turning the link on again keeps them."
PLUGIN_CONFIG = "/opt/canworks/lib/canworks.json"
BRIDGE_CONFIGS = "/etc/canworks-bridge/"


def link_serves(probe, instance=None):
    """The config the remote link serves, or would serve when turned on:
    {"config", "runtime_port", "text"}; {"choose": [names]} when several
    bridge instances could and nothing says which; None with no config at
    all. An installed link keeps its config; else the plugin's; else the
    bridge instance `instance` (the open project's, or the one picked), or
    the only one."""
    probe = probe or {}
    lc = probe.get("link_config") or ""
    if probe.get("link") is not None and lc:
        if lc.startswith(BRIDGE_CONFIGS):
            name = lc[len(BRIDGE_CONFIGS):].split("/")[0]
            return {"config": lc, "runtime_port": "none", "text": "the bridge %s" % name, "instance": name}
        return {"config": lc, "runtime_port": "8443", "text": "the PLC"}
    if probe.get("plugin"):
        return {"config": PLUGIN_CONFIG, "runtime_port": "8443", "text": "the PLC"}
    names = [i.get("name") for i in ((probe.get("bridge") or {}).get("instances") or []) if i.get("name")]
    pick = instance if instance in names else (names[0] if len(names) == 1 else None)
    if pick:
        return {"config": "%s%s/canworks.json" % (BRIDGE_CONFIGS, pick), "runtime_port": "none",
                "text": "the bridge %s" % pick, "instance": pick}
    return {"choose": names} if names else None


ROLES = (("openplc", "OpenPLC PLC with canworks",
          "Installs the OpenPLC Runtime when there is none, and the canworks plugin. Upload a program afterwards."),
         ("bridge", "Modbus bridge",
          "For Node-RED, an HMI or SCADA. It starts with a config when that config's Devices page installs it here."))


def plan(probe, target, latest, pc_version=None, instance=None, config_sha256=None):
    """The page's view of one device. `target` is the project's ("openplc",
    "bridge", "codesys"), or None with no config open: then the parts the
    device has pick the main action, and a device with neither the plugin nor
    the bridge gets `roles`, one main action per role for the page to choose
    from. `latest` is the newest release ("0.98.0") or None, `instance` the
    bridge instance name of this project and `config_sha256` its saved
    canworks.json's."""
    probe = probe or {}
    rt = probe.get("runtime") or {}
    plugin = probe.get("plugin")
    bridge = probe.get("bridge")
    docker = rt.get("kind") == "docker-managed"
    new = version_tuple(latest)
    rows, notes, main = [], [], None
    free = target is None
    # No config: the PLC side when the plugin is there or nothing is (the
    # first role), the bridge side when only the bridge is.
    plc = target == "openplc" or (free and (bool(plugin) or not bridge))
    unused = "" if free else "not used by this project"

    if target == "codesys":
        notes.append("CODESYS installs its runtime itself; there is nothing for canworks to install here.")

    # OpenPLC runtime
    need_rt = target == "openplc"
    rows.append({"part": "runtime", "label": "OpenPLC Runtime", "have": _runtime_text(rt),
                 "state": ("ok" if rt.get("kind") not in (None, "none") else ("warn" if need_rt else "off")),
                 "needs": "needed" if need_rt else unused, "used": need_rt or free,
                 "hint": untested_runtime(rt)})

    # canworks plugin
    need_plugin = target == "openplc"
    rebuild = rebuild_needed(probe)
    off_pin = runtime_off_pin(rt)
    if plugin:
        have = [plugin.get("version") or "unknown"]
        if plugin.get("built_for"):
            have.append("built for %s" % plugin["built_for"][:12])
        if rebuild:
            have.append("off")
        elif plugin.get("enabled") is True:
            have.append("on")
        elif plugin.get("enabled") is False:
            have.append("waiting for an upload")
        cur = version_tuple(plugin.get("version"))
        state = "warn" if (rebuild or (new and (not cur or cur < new))) else "ok"
    else:
        have, state, cur = ["not installed"], ("warn" if need_plugin else "off"), None
    rows.append({"part": "plugin", "label": "canworks plugin", "have": " · ".join(have),
                 "state": state if need_plugin or plugin else "off",
                 "needs": ("newest %s" % latest if latest else "needed") if need_plugin else unused,
                 "used": need_plugin or free,
                 "uninstall": bool(plugin)})
    if plc:
        if rt.get("kind") in (None, "none"):
            main = _main("install_openplc", "Install OpenPLC Runtime and canworks %s" % latest if latest
                         else "Install OpenPLC Runtime and canworks", latest,
                         ["This runs the OpenPLC Runtime installer from %s, which installs Docker and OpenPLC "
                          "runtime %s, the version canworks is tested with." % (OPENPLC_INSTALLER, TESTED_RUNTIME)])
        elif rt.get("kind") == "docker-other":
            notes.append("The runtime runs in a Docker container that no bootloader manages: install canworks "
                         "with install-stock.sh --docker-image (docs/install-stock.md).")
        elif not plugin:
            main = _main("install_plugin", "Install canworks %s" % latest if latest else "Install canworks", latest,
                         [switch_text(off_pin), DOCKER_STOP if docker else ""])
        elif cur and new and cur < new:
            main = _main("install_plugin", "Update %s → %s" % (plugin.get("version"), latest), latest,
                         [switch_text(off_pin), DOCKER_STOP if docker else ""])
        elif off_pin:
            main = _main("install_plugin", "Switch runtime to %s" % TESTED_RUNTIME, latest,
                         [switch_text(off_pin), DOCKER_STOP])
        elif rebuild:
            main = _main("install_plugin", "Rebuild for runtime %s" % rebuild, latest,
                         [DOCKER_STOP if docker else ""])
        elif not cur and new:
            main = _main("install_plugin", "Install canworks %s" % latest, latest, [switch_text(off_pin), DOCKER_STOP if docker else ""])
        if plugin and rebuild and off_pin:
            notes.insert(0, "canworks is off on this device: the runtime is %s and canworks runs on %s. "
                            "Switch the runtime back, then upload the program." % (off_pin, TESTED_RUNTIME))
        elif plugin and rebuild:
            notes.insert(0, "canworks is off on this device: the runtime is %s and the plugin was built for %s. "
                            "Rebuild it, then upload the program." % (rebuild, plugin.get("built_for")))

    # Modbus bridge
    need_bridge = target == "bridge"
    instances = (bridge or {}).get("instances") or []
    mine = next((i for i in instances if i.get("name") == instance), None) if instance else None
    if bridge:
        have = [bridge.get("version") or "unknown"]
        running = [i["name"] for i in instances if i.get("state") == "active"]
        if running:
            have.append("running: %s" % ", ".join(running))
        if bridge.get("unit") is False:
            have.append("no service")
        bcur = version_tuple(bridge.get("version"))
    else:
        have, bcur, running = ["not installed"], None, []
    current_cfg = bool(mine and config_sha256 and mine.get("sha256") == config_sha256)
    bstate = "off"
    if need_bridge:
        bstate = "ok" if bridge and bridge.get("unit") is not False and (not new or (bcur and bcur >= new)) and current_cfg \
            and mine.get("state") == "active" else "warn"
    elif bridge:
        bstate = "warn" if free and (bridge.get("unit") is False or (new and (bcur is None or bcur < new))) else "ok"
    rows.append({"part": "bridge", "label": "Modbus bridge", "have": " · ".join(have), "state": bstate,
                 "needs": ("this project's config as %s" % instance) if need_bridge else unused,
                 "used": need_bridge or free, "uninstall": bool(bridge)})
    if need_bridge:
        restart = "Running bridges restart." if running else ""
        # A link that serves the PLC (or a config whose place is unknown) stays as it is.
        lc = probe.get("link_config") or ""
        kept = {"link_kept": True} if probe.get("link") is not None and not lc.startswith("/etc/canworks-bridge/") else {}
        if not bridge or bridge.get("unit") is False:
            main = _main("install_bridge", "Install and start this project's bridge", latest, **kept)
        elif new and (bcur is None or bcur < new):
            main = _main("install_bridge", "Update %s → %s" % (bridge.get("version"), latest), latest, [restart], **kept)
        elif not current_cfg or not mine or mine.get("state") != "active":
            main = _main("bridge_config", "Start this project's bridge", latest,
                         ["The bridge %s restarts with this project's saved config." % instance
                          if mine and mine.get("state") == "active" else ""])
    elif free and bridge and main is None:
        # No config: the bridge alone is updated (its configs stay as they run).
        restart = "Running bridges restart." if running else ""
        if bridge.get("unit") is False:
            main = _main("install_bridge", "Install the bridge %s" % latest if latest else "Install the bridge", latest)
        elif new and (bcur is None or bcur < new):
            main = _main("install_bridge", "Update %s → %s" % (bridge.get("version"), latest), latest, [restart])

    # No config: next to the plugin, the bridge installs from its own row
    # (and the plugin next to the bridge), as the role question is gone.
    if free and bool(plugin) != bool(bridge):
        row = next(r for r in rows if r["part"] == ("plugin" if bridge else "bridge"))
        if not bridge:
            row["actions"] = [_main("install_bridge", "Install the bridge %s" % latest if latest else "Install the bridge",
                                    latest, [SHARE_CAN], button="Install…")]
        elif rt.get("kind") in (None, "none"):
            row["actions"] = [_main("install_openplc", "Install OpenPLC Runtime and canworks %s" % latest if latest
                                    else "Install OpenPLC Runtime and canworks", latest, [SHARE_CAN], button="Install…")]
        elif rt.get("kind") != "docker-other":
            row["actions"] = [_main("install_plugin", "Install canworks %s" % latest if latest else "Install canworks",
                                    latest, [DOCKER_STOP if docker else "", SHARE_CAN], button="Install…")]

    # Remote link and discovery (device-link-switches): their own switches
    # once the plugin or the bridge is there to give them a config.
    link = probe.get("link")
    serves = link_serves(probe, instance) if target != "codesys" and (plugin or bridge) else None
    have = "not installed" if link is None else ("running" if link == "active" else link or "stopped")
    if link is not None and serves and serves.get("text"):
        have += " · serves %s" % serves["text"]
    link_row = {"part": "link", "label": "Remote link", "have": have,
                "state": "ok" if link == "active" else "off", "needs": "", "used": target != "codesys"}
    found = probe.get("discovery") is True
    disc_row = {"part": "discovery", "label": "Found on the local network", "have": "yes" if found else "no",
                "state": "ok" if found else "off", "needs": "", "used": target != "codesys"}
    if serves:
        if link is None:
            link_row["actions"] = [_main("link_on", "Turn on the remote link", latest, [], button="Turn on…",
                                         choose=serves.get("choose"))]
        else:
            off = _main("link_off", "Turn off the remote link", latest, [LINK_OFF], button="Turn off…")
            link_row["actions"] = [off] if link == "active" else [_main("link_start", "Start the remote link", latest,
                                                                        [], button="Start"), off]
        disc_row["actions"] = [_main("discovery_off", "Stop advertising on the local network", latest, [],
                                     button="Turn off…") if found else
                               _main("discovery_on", "Advertise on the local network", latest, [], button="Turn on…")]
    rows += [link_row, disc_row]
    can = []
    for item in (probe.get("can") or []) + (probe.get("vcan") or []):
        if not isinstance(item, dict) or not item.get("ifname"):
            continue
        info = item.get("linkinfo") or {}
        data = info.get("info_data") or {}
        # Controllers with fixed bit rates (slcan) give it flat, without bittiming.
        rate = (data.get("bittiming") or {}).get("bitrate") or data.get("bittiming_bitrate")
        text = item["ifname"]
        if rate:
            text += " %d kbit/s" % (rate // 1000)
        if "UP" in (item.get("flags") or []):
            text += " up"
        if info.get("info_kind") == "vcan":
            text += " (virtual)"
        can.append(text)
    serial = probe.get("serial") or []
    rows.append({"part": "can", "label": "CAN interfaces",
                 "have": " · ".join(can + ["serial %s" % s for s in serial]) or "none found",
                 "state": "ok" if can or serial else "off", "needs": "", "used": target != "codesys"})

    roles = None
    if free and not plugin and not bridge:
        # Nothing of canworks here yet: the page asks what the device should run.
        bridge_main = _main("install_bridge", "Install the bridge %s" % latest if latest else "Install the bridge", latest)
        roles = [{"role": r, "label": label, "text": text, "main": main if r == "openplc" else bridge_main}
                 for r, label, text in ROLES]
    reason = blocked(probe, latest) if main or roles or any(r.get("actions") for r in rows) else None
    pc = version_tuple(pc_version)
    seen = [v for v in (version_tuple((plugin or {}).get("version")), version_tuple((bridge or {}).get("version"))) if v]
    newest_here = max(seen) if seen else None
    # Only a newer major or minor on the device is worth a word: patch
    # releases of the PC tools and the device do not depend on each other.
    pc_older = None
    if pc and newest_here and pc[:2] < newest_here[:2]:
        pc_older = {"pc": pc_version, "device": ".".join(map(str, newest_here))}
    job = probe.get("install_job")
    return {"rows": rows, "main": main, "roles": roles, "blocked": reason, "notes": notes, "pc_older": pc_older, "job": job,
            "up_to_date": main is None and not roles and target != "codesys",
            "sudo": probe.get("sudo"), "header": header(probe)}


def header(probe):
    parts = []
    if probe.get("os"):
        parts.append(probe["os"])
    if probe.get("arch"):
        parts.append(probe["arch"])
    if isinstance(probe.get("disk_free_mb"), int):
        parts.append("%.0f GB free" % (probe["disk_free_mb"] / 1024))
    if probe.get("internet") is True:
        parts.append("internet ok")
    elif probe.get("internet") is False:
        parts.append("no internet")
    return " · ".join(parts)
