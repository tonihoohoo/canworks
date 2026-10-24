"""What a device has against what the project needs: the rows of the device
page, the one main action and why an action cannot run. Pure functions of the
probe (device-probe.sh's JSON), the project's target (None with no config
open) and the newest release, so every case is tested without a device."""

import re

MIN_FREE_MB = 2048


def version_tuple(text):
    """(0, 98, 0) for "0.98.0" or "deploy-v0.98.0"; None for anything else
    (a git describe of a development build, "unknown")."""
    m = re.match(r"^(?:deploy-)?v?(\d+)\.(\d+)\.(\d+)$", (text or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


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


def _main(action, label, version, confirm=(), **extra):
    out = {"action": action, "label": label, "version": version, "confirm": [c for c in confirm if c]}
    out.update(extra)
    return out


LINK_OFF = "Paired PCs stay paired: turning the link on again keeps them."
BRIDGE_CONFIGS = "/etc/canworks-bridge/"


def link_serves(probe, instance=None):
    """The config the remote link serves, or would serve when turned on:
    {"config", "runtime_port", "text"}; {"choose": [names]} when several
    bridge instances could and nothing says which; None with no config at
    all. An installed link keeps its config; else the bridge instance
    `instance` (the open project's, or the one picked), or the only one."""
    probe = probe or {}
    lc = probe.get("link_config") or ""
    if probe.get("link") is not None and lc:
        if lc.startswith(BRIDGE_CONFIGS):
            name = lc[len(BRIDGE_CONFIGS):].split("/")[0]
            return {"config": lc, "runtime_port": "none", "text": "the bridge %s" % name, "instance": name}
        return {"config": lc, "runtime_port": "none", "text": "another config"}
    names = [i.get("name") for i in ((probe.get("bridge") or {}).get("instances") or []) if i.get("name")]
    pick = instance if instance in names else (names[0] if len(names) == 1 else None)
    if pick:
        return {"config": "%s%s/canworks.json" % (BRIDGE_CONFIGS, pick), "runtime_port": "none",
                "text": "the bridge %s" % pick, "instance": pick}
    return {"choose": names} if names else None


NO_CONFIG_HINT = "The bridge starts with a config when that config's Devices page installs it here."


ADAPTER_PORT = 7536
NEW_TOKEN = "Every other PC must enter the new token."


def _ifname(adapter):
    return (adapter or "").split(":", 1)[1] if ":" in (adapter or "") else (adapter or "")


def adapter_row(probe, target, latest, networks=None, tokens=None, instance=None):
    """The Remote CAN adapter row (add-devices-adapter-server): the adapter
    servers on the device and their switches. `networks` are the open
    config's ({"interface", "bitrate_kbit", "device"}), `tokens` the ports
    of the servers this PC has a token for."""
    servers = [a for a in probe.get("adapters") or [] if isinstance(a, dict) and a.get("adapter")]
    tokens = set(tokens or ())
    # A simulated network keeps its adapter for switching back; the bridge never opens it.
    networks = [n for n in networks or [] if isinstance(n, dict) and not n.get("simulate")]
    instances = ((probe.get("bridge") or {}).get("instances") or [])
    mine_runs = any(i.get("name") == instance and i.get("state") == "active" for i in instances) if instance else False
    running = [i["name"] for i in instances if i.get("state") == "active" and i.get("name")]
    served = {a["adapter"] for a in servers}
    choices = []
    for item in (probe.get("can") or []) + (probe.get("vcan") or []):
        if not isinstance(item, dict) or not item.get("ifname"):
            continue
        name = item["ifname"]
        info = item.get("linkinfo") or {}
        data = info.get("info_data") or {}
        rate = (data.get("bittiming") or {}).get("bitrate") or data.get("bittiming_bitrate")
        up = "UP" in (item.get("flags") or [])
        choice = {"adapter": "socketcan:" + name, "label": name, "bitrate_kbit": None, "locked": False,
                  "note": None, "refused": None}
        net = next((n for n in networks if n.get("interface") == name), None)
        if net and mine_runs and net.get("bitrate_kbit"):
            choice.update(bitrate_kbit=net["bitrate_kbit"], locked=True,
                          note="The bridge %s is the master on %s: PCs with this project's config connect through "
                               "the bridge; a PC's changes on this adapter need force while the bridge runs."
                               % (instance, name))
        elif up and rate:
            choice["bitrate_kbit"] = rate // 1000
        elif net and net.get("bitrate_kbit"):
            choice["bitrate_kbit"] = net["bitrate_kbit"]
        if not choice["note"] and running and info.get("info_kind") != "vcan":
            choice["note"] = ("A bridge runs on this device (%s): when it uses %s, it is the master there and a PC's "
                              "changes on this adapter need force." % (", ".join(running), name))
        choices.append(choice)
    for s in probe.get("serial") or []:
        path = "/dev/serial/by-id/" + s
        choice = {"adapter": "slcan:" + path, "label": "serial " + s, "bitrate_kbit": None, "locked": False,
                  "note": None, "refused": None}
        net = next((n for n in networks if n.get("device") == path), None)
        if net and mine_runs:
            choice["refused"] = "The bridge %s uses this serial adapter: a serial port has one user at a time." % instance
        elif net and net.get("bitrate_kbit"):
            choice["bitrate_kbit"] = net["bitrate_kbit"]
        choices.append(choice)
    free = [c for c in choices if c["adapter"] not in served]
    ports = {a.get("port") for a in servers}
    port = next(p for p in range(ADAPTER_PORT, ADAPTER_PORT + 100) if p not in ports)

    texts = []
    for a in servers:
        t = [_ifname(a["adapter"])]
        if a.get("bitrate_kbit"):
            t.append("%d kbit/s" % a["bitrate_kbit"])
        if a.get("port") and a["port"] != ADAPTER_PORT:
            t.append("port %d" % a["port"])
        t.append("running" if a.get("state") == "active" else (a.get("state") or "stopped"))
        t.append("changes allowed" if a.get("allow_changes") else "read-only")
        if a.get("state") == "active" and isinstance(a.get("pcs"), int):
            t.append("%d PC%s connected" % (a["pcs"], "" if a["pcs"] == 1 else "s"))
        texts.append(" · ".join(t))
    bad = any(a.get("state") != "active" for a in servers)
    out = {"part": "adapter", "label": "Remote CAN adapter", "have": "; ".join(texts) or "off",
           "state": "warn" if bad else "ok" if servers else "off", "needs": "", "used": target != "codesys"}
    if target == "codesys":
        return out
    acts = []
    many = len(servers) > 1
    for a in servers:
        name = _ifname(a["adapter"])
        on = (" " + name) if many else ""
        same = {"adapter": a["adapter"], "port": a.get("port") or ADAPTER_PORT}
        current = dict(same, bitrate_kbit=a.get("bitrate_kbit"), allow_changes=bool(a.get("allow_changes")),
                       discovery=bool(a.get("discovery")))
        if a.get("state") == "active":
            acts.append(_main("adapter_connect", "Connect from this PC", latest, [], button="Connect from this PC%s" % on,
                              local=True, **same))
        if same["port"] in tokens:
            acts.append(_main("adapter_copy_token", "Copy token", latest, [], button="Copy token%s" % on, local=True,
                              **same))
        else:
            acts.append(_main("adapter_token", "New token for the remote CAN adapter%s" % on, latest, [NEW_TOKEN],
                              button="New token%s…" % on, **same))
        acts.append(_main("adapter_change", "Change the remote CAN adapter%s" % on, latest, [], button="Change%s…" % on,
                          dialog=True, current=current,
                          choices=[c for c in choices if c["adapter"] == a["adapter"]], **same))
        acts.append(_main("adapter_off", "Turn off the remote CAN adapter%s" % on, latest,
                          ["PCs connected to it lose the connection; %s is free on the device again." % name],
                          button="Turn off%s…" % on, **same))
    if free:
        acts.append(_main("adapter_on", "Turn on the remote CAN adapter", latest, [],
                          button="Add…" if servers else "Turn on…", dialog=True, choices=free, port=port))
    if acts:
        out["actions"] = acts
    return out


def _port(listen):
    try:
        return int(str(listen).rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


def clashes(mine, other, name):
    """The warnings for starting a bridge that uses `mine` next to the running
    instance `name` that uses `other` (device-probe.sh's bridge_uses, or
    networks_uses of the open config): the same Modbus port, diagnostics
    port or CAN interface."""
    if not isinstance(mine, dict) or not isinstance(other, dict):
        return []
    out = []
    port = _port(mine.get("listen"))
    if port and port == _port(other.get("listen")):
        out.append("%s listens on port %d too: the second bridge cannot open it." % (name, port))
    if mine.get("diag_port") and mine.get("diag_port") == other.get("diag_port"):
        out.append("%s uses the diagnostics port %d too." % (name, mine["diag_port"]))
    both = [i for i in mine.get("interfaces") or [] if i in (other.get("interfaces") or [])]
    if both:
        out.append("%s drives %s too: two masters on one bus." % (name, ", ".join(both)))
    return out


def plan(probe, target, latest, pc_version=None, instance=None, config_sha256=None, networks=None, tokens=None,
         uses=None):
    """The page's view of one device. `target` is the project's
    ("openplc_modbus", "bridge", "codesys"), or None with no config open:
    then the bridge on the device picks the main action, and a device without
    it gets **Install the bridge X**. Only canworks parts are rows: the
    OpenPLC runtime and other programs are not the configurator's.
    `latest` is the newest release ("0.98.0") or None, `instance` the bridge
    instance name of this project, `config_sha256` its saved
    canworks.json's and `uses` what its saved config listens on and drives
    (clashes())."""
    probe = probe or {}
    bridge = probe.get("bridge")
    new = version_tuple(latest)
    rows, notes, main = [], [], None
    free = target is None
    unused = "" if free else "not used by this project"
    with_latest = (lambda text: "%s %s" % (text, latest) if latest else text)

    if target == "codesys":
        notes.append("CODESYS installs its runtime itself; there is nothing for canworks to install here.")

    # Modbus bridge
    need_bridge = target in ("bridge", "openplc_modbus")
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
    older = bool(new and (bcur is None or bcur < new))
    bstate = "off"
    if need_bridge:
        bstate = "ok" if bridge and bridge.get("unit") is not False and not older and current_cfg \
            and mine.get("state") == "active" else "warn"
    elif bridge:
        bstate = "warn" if free and (bridge.get("unit") is False or older) else "ok"
    rows.append({"part": "bridge", "label": "Modbus bridge", "have": " · ".join(have), "state": bstate,
                 "needs": ("this project's config as %s" % instance) if need_bridge else unused,
                 "used": need_bridge or free, "uninstall": bool(bridge)})
    restart = "Running bridges restart." if running else ""
    if need_bridge:
        # A link that serves another config (or one whose place is unknown) stays as it is.
        lc = probe.get("link_config") or ""
        kept = {"link_kept": True} if probe.get("link") is not None and not lc.startswith(BRIDGE_CONFIGS) else {}
        if not bridge or bridge.get("unit") is False:
            main = _main("install_bridge", "Install and start this project's bridge", latest, **kept)
        elif older:
            main = _main("install_bridge", "Update %s → %s" % (bridge.get("version"), latest), latest, [restart], **kept)
        elif not current_cfg or not mine or mine.get("state") != "active":
            main = _main("bridge_config", "Start this project's bridge", latest,
                         ["The bridge %s restarts with this project's saved config." % instance
                          if mine and mine.get("state") == "active" else ""])
        others = [n for n in running if n != instance]
        if main and others:
            # Another project's bridge runs here: named, with Stop A and start B as the main choice.
            names = ", ".join(others)
            main["confirm"].append("The bridge %s runs on this device and keeps running unless it is stopped." % names)
            all_uses = probe.get("bridge_uses") if isinstance(probe.get("bridge_uses"), dict) else {}
            main["warnings"] = [w for n in others for w in clashes(uses, all_uses.get(n), n)]
            main["stop_others"] = others
            main["stop_label"] = "Stop %s and start %s" % (names, instance)
            main["next_label"] = "Start next to %s" % names
    elif free and bridge:
        # No config: the bridge alone is updated (its configs stay as they run).
        if bridge.get("unit") is False:
            main = _main("install_bridge", with_latest("Install the bridge"), latest)
        elif older:
            main = _main("install_bridge", "Update %s → %s" % (bridge.get("version"), latest), latest, [restart])

    # Remote link and discovery (device-link-switches): their own switches
    # once the bridge is there to give them a config.
    link = probe.get("link")
    serves = link_serves(probe, instance) if target != "codesys" and bridge else None
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
    elif target != "codesys":
        # No switch yet: why, instead of an empty cell.
        link_row["hint"] = "Turns on once a bridge config runs here."
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
    rows.append(adapter_row(probe, target, latest, networks, tokens, instance))

    if free and not bridge:
        # No bridge here yet and no config: the bridge alone, started later by a config.
        main = _main("install_bridge", with_latest("Install the bridge"), latest, hint=NO_CONFIG_HINT)
    reason = blocked(probe, latest) if main or any(a for r in rows for a in r.get("actions") or []
                                                   if not a.get("local")) else None
    pc = version_tuple(pc_version)
    here = version_tuple((bridge or {}).get("version"))
    # Only a newer major or minor on the device is worth a word: patch
    # releases of the PC tools and the device do not depend on each other.
    pc_older = None
    if pc and here and pc[:2] < here[:2]:
        pc_older = {"pc": pc_version, "device": ".".join(map(str, here))}
    job = probe.get("install_job")
    return {"rows": rows, "main": main, "blocked": reason, "notes": notes, "pc_older": pc_older, "job": job,
            "up_to_date": main is None and target != "codesys",
            "sudo": probe.get("sudo"), "header": header(probe)}


def networks_uses(cfg):
    """What a bridge config listens on and drives, as device-probe.sh gives it
    for the running instances: {"listen", "diag_port", "interfaces"}."""
    cfg = cfg if isinstance(cfg, dict) else {}
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
    return {"listen": b.get("listen") if isinstance(b.get("listen"), str) else None,
            "diag_port": port if isinstance(port, int) else None, "interfaces": ifs}


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
