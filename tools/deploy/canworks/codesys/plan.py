"""The CODESYS export: the plan file and the export folder (codesys-export
spec).

The plan holds every setting the CODESYS script applies, already worked out
here, so the script (script/import_canworks.py) knows nothing about the
config: CODESYS parameters by their numeric id (and English name, for the
report), node DCFs by path, I/O channels by PDO mapping object, index and
sub-index. Settings CODESYS has no counterpart for go into `notes`, from
the same table the check warns with (targets.py)."""

import json
import os
import re

from .. import __version__, bundle, contract, dcfexport, targets
from ..configurator import declare
from ..eds import Eds, EdsError

FORMAT = 1
PLAN_NAME = "canworks-codesys.json"
SCRIPT_NAME = "import_canworks.py"
README_NAME = "README.txt"
REPORT_NAME = "import_report.txt"
SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "script", SCRIPT_NAME)

# CODESYS CANbus (connector with the bus settings).
CANBUS_BAUDRATE = (0, "Baudrate")
# CODESYS CANopen_Manager.
MGR_SYNC_PERIOD = (256, "Sync CycleTime in Microseconds")
MGR_SYNC_ENABLE = (257, "Enable Sync generation")
MGR_SYNC_WINDOW = (259, "Synchronous Window Length")
MGR_AUTOSTART = (261, "Autostart")
MGR_START_SLAVES = (262, "Start Slaves")
MGR_START_ALL = (263, "NMT Start All")
MGR_NMT_INHIBIT = (266, "NMTInhibitTime")
MGR_HEARTBEAT_MS = (272, "Heartbeat in Milliseconds")
MGR_HEARTBEAT_ON = (273, "Enable Heartbeat generation")
MGR_HEARTBEAT_NODE = (274, "Heartbeat Node ID")
MGR_SDO_TIMEOUT = (277, "SDO Timeout Default (ms)")
MGR_NODE_ID = (288, "CANopen NodeID")
MGR_TIME_COB_ID = (290, "TIME COBID")
MGR_TIME_PERIOD = (291, "TIME Producer Interval (ms)")
# CODESYS CANopen remote device.
DEV_NODE_ID = (1, "Node-ID")
DEV_OPTIONS = (2, "General Options")
DEV_SDO_TIMEOUT = (17, "SDO Timeout")
DEV_RESET_SUB = (16846848, "SubIndex for reset node")
# 0x1017 as a CODESYS communication-object parameter (index << 12).
DEV_HEARTBEAT = (0x01017000, "Heartbeat-Producer Time")



class ExportFailed(Exception):
    """The export stopped: `problems` is a list of (message, [JSON path])."""

    def __init__(self, problems):
        super().__init__("\n".join(m for m, _ in problems))
        self.problems = problems


def _param(spec, value, what, element=None):
    pid, name = spec
    p = {"id": pid, "name": name, "value": value, "what": what}
    if element:
        p["element"] = element
    return p


def _bool(v):
    return "TRUE" if v else "FALSE"


def _int(v, default=None):
    if v is None:
        return default
    n = contract._uint(v)
    return default if n is None else n


def folder_name(net):
    """The export folder of a network: its name, else its interface, else net<index>."""
    if net["name"]:
        return net["name"]
    iface = (net.get("adapter") or {}).get("interface")
    if isinstance(iface, str) and re.match(r"^[A-Za-z0-9_.-]+$", iface):
        return iface
    return "net%d" % net["index"]


def network_number(net, overrides):
    """(CODESYS network number, note or None): the override, else the
    network's codesys.net_id, else the interface's trailing number, else 0."""
    if net["name"] in overrides:
        return overrides[net["name"]], None
    own = net["json"].get("codesys") if isinstance(net["json"].get("codesys"), dict) else {}
    if _int(own.get("net_id")) is not None:
        return _int(own.get("net_id")), None
    iface = (net.get("adapter") or {}).get("interface")
    m = re.search(r"(\d+)$", iface) if isinstance(iface, str) else None
    if m:
        return int(m.group(1)), None
    return 0, "the interface %r ends in no number, so the CODESYS network number is 0; set the network's CODESYS " \
              "network number (codesys.net_id, or --codesys-net %s=N) if the device's CAN interface has another " \
              "number" % (iface, net["name"] or "NAME")


def manager_params(master):
    out = [_param(MGR_NODE_ID, str(_int(master.get("node_id"), 127)), "master node ID")]
    hb = _int(master.get("heartbeat_ms"), 0)
    out.append(_param(MGR_HEARTBEAT_ON, _bool(hb > 0), "master heartbeat on or off"))
    if hb > 0:
        out.append(_param(MGR_HEARTBEAT_MS, str(hb), "master heartbeat period"))
        out.append(_param(MGR_HEARTBEAT_NODE, str(_int(master.get("node_id"), 127)), "master heartbeat node ID"))
    period = _int(master.get("sync_period_us"), 0)
    timer = master.get("sync_source", "timer") != "plc_cycle"
    out.append(_param(MGR_SYNC_ENABLE, _bool(timer and period > 0), "SYNC on or off"))
    if timer and period > 0:
        out.append(_param(MGR_SYNC_PERIOD, str(period), "SYNC period"))
    window = _int(master.get("sync_window_us"))
    if window:
        out.append(_param(MGR_SYNC_WINDOW, str(window), "SYNC window"))
    out.append(_param(MGR_AUTOSTART, _bool(master.get("start", True) is not False), "start the network by itself"))
    out.append(_param(MGR_START_SLAVES, _bool(master.get("start_nodes", True) is not False), "start the nodes"))
    out.append(_param(MGR_START_ALL, _bool(master.get("start_all_nodes") is True), "one NMT start for all nodes"))
    inhibit = _int(master.get("nmt_inhibit_time_us"))
    if inhibit:
        out.append(_param(MGR_NMT_INHIBIT, str(inhibit // 100), "NMT inhibit time (100 us)"))
    sdo = _int(master.get("sdo_timeout_ms"))
    if sdo:
        out.append(_param(MGR_SDO_TIMEOUT, str(sdo), "default SDO timeout"))
    if master.get("time_period_ms") is not None:
        out.append(_param(MGR_TIME_COB_ID, str(_int(master.get("time_cob_id"), 0x100) & 0x1FFFFFFF), "TIME COB-ID"))
        out.append(_param(MGR_TIME_PERIOD, str(_int(master.get("time_period_ms"))), "TIME period"))
    return out


def node_params(node, master):
    out = [_param(DEV_NODE_ID, str(_int(node["node_id"])), "node ID"),
           _param(DEV_OPTIONS, _bool(node.get("mandatory") is not True), "optional device", "FLAG_Optional")]
    if node.get("boot") is False:
        out.append(_param(DEV_OPTIONS, "TRUE", "do not initialize", "FLAG_NotInitialize"))
    restore = _int(node.get("restore_configuration"))
    if restore:
        out.append(_param(DEV_OPTIONS, "TRUE", "restore before configuring (0x1011)", "FLAG_ResetNode"))
        out.append(_param(DEV_RESET_SUB, str(restore), "0x1011 sub-index"))
    hb = _int(node.get("heartbeat_ms"), 0)
    if hb:
        # Also when it equals the EDS default: CODESYS takes the producer
        # time from configured values only, and the DCF writes none then.
        out.append(_param(DEV_HEARTBEAT, str(hb), "heartbeat producer time (ms)"))
    sdo = _int(master.get("sdo_timeout_ms"))
    if sdo:
        out.append(_param(DEV_SDO_TIMEOUT, str(sdo * 1000), "SDO timeout (us)"))
    return out


def _eds_object_names(cfg, eds_paths):
    cache = {}

    def find(value, index, sub):
        if value not in cache:
            try:
                cache[value] = Eds.read(eds_paths[value])
            except (KeyError, OSError, EdsError):
                cache[value] = None
        return cache[value].find(index, sub) if cache[value] else None
    return find


_ENTRY_PATH = re.compile(r"^(?:networks\[(\d+)\]\.)?nodes\[(\d+)\]\.(tx_pdos|rx_pdos)\[(\d+)\]\.entries\[(\d+)\]"
                         r"\.iec_location$")
_BIT_PATH = re.compile(r"^(.*\.entries\[\d+\])\.bits\[\d+\]\.iec_location$")
_UNUSED_PATH = re.compile(r"^(?:networks\[(\d+)\])?\.?(?:nodes\[(\d+)\]\.)?(.*)$")


def channels(cfg, eds_paths):
    """{(network index, node index in the network): [channel]} for every mapped
    PDO entry, named as the editor declarations name it."""
    nodes = contract.all_nodes(cfg)
    find = _eds_object_names(cfg, eds_paths)

    def object_name(i, index, sub):
        o = find(nodes[i].get("eds"), index, sub)
        return o.name if o else None

    def slave_object(value, index, sub):
        o = find(value, index, sub)
        return (o.name, o.type_name) if o else None

    out = {}
    by_entry = {}  # entry path -> its channel, for its bit channels
    for d in declare.declarations(cfg, object_name, {}, slave_object, unlocated=True):
        if d.get("kind") != "pdo":
            continue
        bit = _BIT_PATH.match(d["path"])
        if bit:
            channel = by_entry.get(bit.group(1))
            if channel is not None:
                channel.setdefault("bits", []).append({"bit": d["bit"], "variable": d["name"]})
            continue
        m = _ENTRY_PATH.match(d["path"])
        if not m:
            continue
        net_i = int(m.group(1)) if m.group(1) is not None else 0
        node_i, key, pdo_i, entry_i = int(m.group(2)), m.group(3), int(m.group(4)), int(m.group(5))
        net_json = cfg["networks"][net_i] if m.group(1) is not None else cfg
        node = net_json["nodes"][node_i]
        pdo = node[key][pdo_i]
        number = _int(pdo.get("number")) or pdo_i + 1
        try:
            entry = pdo["entries"][entry_i]
            index = _int(entry["index"])
            if index is None:
                raise ValueError("no valid index")
            channel = {
                "dir": "in" if key == "tx_pdos" else "out",
                "mapping": (0x1A00 if key == "tx_pdos" else 0x1600) + number - 1,
                "index": index, "sub": _int(entry.get("subindex", 0), 0),
                "variable": d["name"]}
            out.setdefault((net_i, node_i), []).append(channel)
            by_entry[d["path"][: -len(".iec_location")]] = channel
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ExportFailed([("cannot name the I/O channel of node %s %s%d entry %d: %s"
                                 % (node.get("name") or _int(node.get("node_id")), key[:2].upper() + "PDO",
                                    number, entry_i + 1, e), [d["path"]])])
    return out


def _unused_notes(cfg):
    """The table's CODESYS notes (targets.unused) as {where, setting, note}:
    where "field/rtd", "field/master", "field" or "config"."""
    nets = {n["index"]: n for n in contract.networks(cfg)} if isinstance(cfg.get("networks"), list) else \
        {0: contract.networks(cfg)[0]}
    out = []
    for path, key, why in targets.unused(cfg, targets.CODESYS):
        m = _UNUSED_PATH.match(path)
        if not (m.group(1) is not None or not isinstance(cfg.get("networks"), list)) or path in (
                "gateway", "cia309", "diagnostics"):
            out.append({"where": "config", "setting": path, "note": why})
            continue
        net = nets.get(int(m.group(1) or 0))
        label = (net["name"] if net else "") or "the network"
        rest = m.group(3)
        if m.group(2) is not None and net:
            node = net["nodes"][int(m.group(2))]
            where = "%s/%s" % (label, node.get("name") or "node %s" % _int(node.get("node_id")))
        elif rest.startswith("master."):
            where, rest = label + "/master", rest[len("master."):]
        else:
            where = label
        if key in targets.NETWORK_KINDS:
            rest, why = "network", "not exported: " + why
        if rest.endswith("].iec_location") and ".entries[" in rest:
            # One note per node for its PDO entry locations.
            rest = "PDO entry locations"
            if out and out[-1]["where"] == where and out[-1]["setting"] == rest:
                continue
        out.append({"where": where, "setting": rest, "note": why})
    return out


def build(cfg, config_path, eds_paths=None, overrides=None, plc=None, variables=None, project=None, create=None,
          network=None, interfaces=None):
    """(plan dict, {file name: DCF text}). Raises ExportFailed with every
    problem when the config or a DCF fails, or an override names no master
    network. `network` exports only that network."""
    overrides = dict(overrides or {})
    interfaces = dict(interfaces or {})
    eds_paths = eds_paths if eds_paths is not None else bundle.eds_files(cfg, config_path)
    flag_interfaces = set(interfaces)
    # The config's own CODESYS settings; the arguments override them.
    own = cfg.get("codesys") if isinstance(cfg.get("codesys"), dict) else {}
    if plc is None:
        plc = own.get("device") or None
    if variables is None:
        variables = own.get("variables") is not False
    for n in contract.networks(cfg):
        nc = n["json"].get("codesys") if isinstance(n["json"].get("codesys"), dict) else {}
        if n["name"] not in interfaces and isinstance(nc.get("interface"), str) and nc["interface"]:
            interfaces[n["name"]] = nc["interface"]
    nets = contract.networks(cfg)
    if network is not None:
        nets = [n for n in nets if n["name"] == network]
        if not nets:
            raise ExportFailed([("no network '%s' in the config (%s)" % (
                network, ", ".join(n["name"] for n in contract.networks(cfg))), ["networks"])])
    masters = [n for n in nets if n["role"] == "master" and n["nodes"]]
    unknown = sorted(set(overrides) - {n["name"] for n in masters})
    if unknown:
        raise ExportFailed([("--codesys-net names %s, which %s no CANopen master network in the config (%s)"
                             % (", ".join(unknown), "is" if len(unknown) == 1 else "are",
                                ", ".join(n["name"] for n in masters) or "none"), ["networks"])])
    unknown = sorted(flag_interfaces - {n["name"] for n in masters})
    if unknown:
        raise ExportFailed([("--codesys-can names %s, which %s no CANopen master network in the config (%s)"
                             % (", ".join(unknown), "is" if len(unknown) == 1 else "are",
                                ", ".join(n["name"] for n in masters) or "none"), ["networks"])])
    if not masters:
        raise ExportFailed([("the config has no CANopen master network with nodes, so nothing to export for "
                             "CODESYS", ["networks"])])
    # A config the checks refuse can fail here before the DCF export below
    # names the field, so a failure is reported after that, never swallowed.
    channels_failed = None
    try:
        chans = channels(cfg, eds_paths) if variables else {}
    except (KeyError, IndexError, TypeError, ValueError) as e:
        chans, channels_failed = {}, e
    files, problems = {}, []
    labels = {n["name"] or "the network" for n in nets}
    notes = [x for x in _unused_notes(cfg) if x["where"] == "config" or x["where"].split("/")[0] in labels]
    plan_nets, device_names = [], set()
    for net in nets:
        label = net["name"] or "the network"
        if net["role"] != "master":
            continue  # the table's note says why
        if not net["nodes"]:
            notes.append({"where": label, "setting": "network", "note": "not exported: no nodes"})
            continue
        if net["json"].get("links"):
            notes.append({"where": label, "setting": "links",
                          "note": "PDO links come through the consumers' DCFs; CODESYS shows them as the consumers' "
                                  "RPDOs"})
        folder = folder_name(net)
        try:
            got, _ = dcfexport.export(cfg, config_path, eds_paths=eds_paths, network=net["name"] or None)
        except dcfexport.ExportFailed as e:
            problems += e.problems
            continue
        for name, text in got.items():
            files[folder + "/" + name.split("/")[-1]] = text
        number, note = network_number(net, overrides)
        if note:
            notes.append({"where": label, "setting": "adapter.interface", "note": note})
        master = net["master"]
        bitrate = _int((net.get("adapter") or {}).get("bitrate"), 0) // 1000
        if master.get("time_period_ms") is not None:
            notes.append({"where": label + "/master", "setting": "time_period_ms",
                          "note": "TIME producer: the COB-ID and period are set; switch TIME producing on in the "
                                  "manager in CODESYS"})
        plan_nodes = []
        for k, node in enumerate(net["nodes"]):
            node_id = _int(node["node_id"])
            base = declare.identifier(node.get("name") or "node%s" % node_id)
            name, n = base, 2
            while name.lower() in device_names:
                name = "%s_%d" % (base, n)
                n += 1
            device_names.add(name.lower())
            plan_nodes.append({"node_id": node_id, "name": name,
                               "dcf": folder + "/" + dcfexport.dcf_name(node_id),
                               "params": node_params(node, master),
                               "channels": chans.get((net["index"] if net["path"] else 0, k), [])})
        plan_net = {"name": net["name"], "folder": folder, "net_id": number, "bitrate_kbit": bitrate,
                    "canbus": [_param(CANBUS_BAUDRATE, str(bitrate), "bit rate (kbit/s)")],
                    "manager": manager_params(master), "nodes": plan_nodes}
        if interfaces.get(net["name"]):
            plan_net["interface"] = interfaces[net["name"]]
        plan_nets.append(plan_net)
    if problems:
        raise ExportFailed(problems)
    if channels_failed is not None:
        raise ExportFailed([("cannot name the I/O channels (%s); export with variables off to leave them out"
                             % channels_failed, ["networks"])])
    if isinstance(cfg.get("bridge"), dict):
        notes.append({"where": "config", "setting": "bridge", "note": "stays with canworks"})
    notes.append({"where": "every node", "setting": "identity check",
                  "note": "the script cannot tick a device's startup checks (vendor ID, product code, revision); "
                          "set them on each device in CODESYS if wanted"})
    plan = {"format": FORMAT, "tool": "canworks-deploy %s" % __version__,
            "config": os.path.basename(config_path), "project": project, "create": create, "plc": plc,
            "variables": bool(variables), "networks": plan_nets, "notes": notes}
    return plan, files


def readme():
    return """CODESYS import of a canworks CANopen bus (canworks-deploy %s)

In CODESYS
  1. Open your project and make the device that gets the bus the active one
     (its application set with Set Active Application). The script uses the
     active application's device, or the only device in the project.
  2. Tools > Scripting > Execute Script File..., pick import_canworks.py in this folder.
  3. Read the report in the message view (also import_report.txt here), build, and save the project.

From the command line
  canworks-deploy --config canworks.json --codesys-import C:\\path\\to\\project.project
  or, with this folder's canworks-codesys.json naming the project ("project": "C:\\\\path\\\\to\\\\project.project"):
  CODESYS.exe --profile="<profile name>" --noUI --runscript="<this folder>\\import_canworks.py"

The script adds a CANbus and a CANopen Manager when the device has none with
the network number from canworks-codesys.json (under the device's own CAN
interface, for example Communication > CAN, when it has one), installs every node's DCF and adds
the node, names each mapped I/O channel, and builds. Running it again
replaces the nodes it manages. See docs/codesys.md in the canworks repository.
""" % __version__


def export_files(cfg, config_path, eds_paths=None, **kw):
    """({file name: text}, plan) of the export folder."""
    plan, files = build(cfg, config_path, eds_paths=eds_paths, **kw)
    with open(SCRIPT_PATH, encoding="utf-8") as f:
        files[SCRIPT_NAME] = f.read()
    files[PLAN_NAME] = json.dumps(plan, indent=2) + "\n"
    files[README_NAME] = readme()
    return files, plan
