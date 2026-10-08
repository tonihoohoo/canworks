"""Writing a node's configuration to a live device, restoring its defaults
and verifying it (canopen-device-commissioning spec).

Like parameters.py, everything runs on the PC over the diagnostics
operations sdo_read, sdo_write and nmt, one SDO at a time, so it works on a
runtime and on a USB adapter (localbus). The source is a node of a
canopen.json (the writes the plugin makes at boot) or a CiA 306 DCF.

0x1010 (store) and 0x1011 (restore defaults) are never written as part of
a configuration: store() and restore_defaults() are separate, explicit
actions the caller asks for.
"""

import collections
import time

from . import eds as eds_mod
from . import parameters as P
from .diag import DiagError, abort_text, type_name

LEFT_OUT = ((0x1010, 0x1010, "store command: use Store on device (--store)"),
            (0x1011, 0x1011, "restore defaults command: use Restore defaults (--restore-defaults)"),
            (0x1F50, 0x1F57, "program download object"))
LOAD = b"load"  # 0x64616F6C, "load" in CiA 301
PDO_FIRST, PDO_LAST = 0x1400, 0x1BFF
INVALID = 0x80000000
CONFIG_DATE = 0x1020
OPERATIONAL = 5
HEARD_S = 30.0  # a heartbeat this recent tells the node's state
READY_S = 5.0  # how long to wait for a node after a reset


class CommissioningError(Exception):
    pass


def left_out_reason(index):
    for lo, hi, why in LEFT_OUT:
        if lo <= index <= hi:
            return why
    return None


def _num(v):
    return int(str(v), 0)


def _u(data):
    return int.from_bytes(data, "little") if data is not None else None


# -- sources ---------------------------------------------------------------------------

class Source:
    """What to write: `values` {(index, sub): bytes} in source order, the
    source's object dictionary (`eds`) for names, types and access, its node
    ID (None when it names none) and identity, and the entries left out."""

    def __init__(self, kind, name, eds, node_id=None):
        self.kind, self.name, self.eds, self.node_id = kind, name, eds, node_id
        self.values = collections.OrderedDict()
        self.skipped = []  # dicts: index, subindex, name, reason
        self.identity = {}  # vendor_id, product_code, revision_number when known
        self.warnings = []

    def entry(self, key):
        o = self.eds.find(*key)
        return P.Entry(key[0], key[1], o, self.eds.names.get(key[0], "")) if o is not None else None

    def name_of(self, key):
        e = self.entry(key)
        return e.name if e else ""

    def type_of(self, key):
        e = self.entry(key)
        return e.data_type if e else None

    def skip(self, key, reason):
        self.skipped.append({"index": key[0], "subindex": key[1], "name": self.name_of(key), "reason": reason})

    def to_json(self):
        return {"kind": self.kind, "name": self.name, "node_id": self.node_id, "identity": self.identity,
                "entries": len(self.values), "skipped": self.skipped, "warnings": self.warnings}


def _heartbeat_warnings(src):
    for (index, sub), data in src.values.items():
        if index == 0x1016 and sub >= 1 and data is not None and len(data) == 4:
            v = _u(data)
            node, ms = (v >> 16) & 0x7F, v & 0xFFFF
            if node and ms:
                src.warnings.append("0x1016 sub %d makes the device expect node %d's heartbeat every %d ms; "
                                    "without it (on a bench, no master) the device may report a heartbeat error"
                                    % (sub, node, ms))


def config_source(ctx, from_node):
    """The writes the plugin makes to `from_node` at boot, from a
    parameters.NodeContext of that node (ctx.cfg is the node's network's
    config)."""
    from . import dcfexport
    if not ctx.configured:
        raise CommissioningError("node %d is not in a configuration" % from_node)
    try:
        downloads = dcfexport.plugin_downloads(ctx.cfg, ctx.config_path, ctx.eds_paths)
    except Exception as e:  # dcfexport.ExportFailed and the config's own problems
        raise CommissioningError("the configuration's writes for node %d are not known: %s" % (from_node, e))
    d = downloads.get(from_node)
    if d is None:
        raise CommissioningError("node %d is not in the configuration" % from_node)
    src = Source("config", "node %d of %s" % (from_node, ctx.config_path or "the configuration"), ctx.eds, from_node)
    src.eds_text, src.eds_name = ctx.eds_text, ctx.eds_name
    for index, sub, data in d.writes:
        why = left_out_reason(index)
        if why:
            if index == 0x1010:
                why = "store command (the node's store_configuration): use Store on device (--store)"
            src.skip((index, sub), why)
            continue
        src.values.pop((index, sub), None)  # a later write of the same entry wins, in its own place
        src.values[(index, sub)] = data
    if d.restore is not None:
        src.skip((0x1011, d.restore), "restore defaults before the configuration (restore_configuration): use "
                                      "Restore defaults (--restore-defaults)")
    if d.firmware:
        src.skip((0x1F51, 1), "program download (software_file %s) is not written from the PC" % d.firmware)
    info = eds_mod.device_info_text(ctx.eds_text, ctx.eds_name) or {}
    for key in ("vendor_id", "product_code", "revision_number"):
        if info.get(key) is not None:
            src.identity[key] = info[key]
    node = next((n for n in ctx.cfg.get("nodes") or [] if _num(n.get("node_id")) == from_node), {})
    if node.get("revision_number") not in (None, 0, "0"):
        src.identity["revision_number"] = _num(node["revision_number"])
    _heartbeat_warnings(src)
    return src


def dcf_source(raw, name, target):
    """The writable ParameterValue entries of a DCF (bytes or text).
    `$NODEID` is resolved with the DCF's own NodeID, or `target` when it
    names none."""
    try:
        backup = P.read_backup(raw, name)
        if backup.node_id is None:
            backup = P.read_backup(raw, name, target)
            own = None
        else:
            own = backup.node_id
    except P.ParameterError as e:
        raise CommissioningError(str(e))
    src = Source("dcf", name, backup.eds, own)
    src.eds_text, src.eds_name = backup.text, name
    keys = sorted(backup.values, key=lambda k: (k[0], k[1] == 0, k[1]))
    for key in keys:
        o = backup.eds.find(*key)
        if o is None:
            continue
        if o.access in ("ro", "const"):
            continue  # values for compare (a backup's identity and measurements), never written
        why = left_out_reason(key[0])
        if why:
            src.skip(key, why)
        elif o.data_type == P.DOMAIN:
            src.skip(key, "DOMAIN entry")
        elif o.access not in P.WRITABLE:
            src.skip(key, "access %s: cannot be written and read back" % (o.access or "not given"))
        else:
            src.values[key] = backup.values[key]
    ident = backup.identity()
    info = eds_mod.device_info_text(backup.text, name) or {}
    for key in ("vendor_id", "product_code", "revision_number"):
        if key in ident:
            src.identity[key] = ident[key]
        elif info.get(key) is not None:
            src.identity[key] = info[key]
    _heartbeat_warnings(src)
    return src


# -- the plan -----------------------------------------------------------------------------

def _pdo(index):
    """(group name, comm index, map index) of a PDO object, or None."""
    if not PDO_FIRST <= index <= PDO_LAST:
        return None
    if index < 0x1800:  # 0x1400 + n communication, 0x1600 + n mapping
        n = (index - 0x1400) % 0x200
        return "RPDO%d" % (n + 1), 0x1400 + n, 0x1600 + n
    n = (index - 0x1800) % 0x200
    return "TPDO%d" % (n + 1), 0x1800 + n, 0x1A00 + n


def plan_keys(src):
    """The keys to read before planning: the identity, every source entry,
    and each PDO's COB-ID (to switch it off as it is)."""
    keys = [(0x1018, s) for s in range(1, 5)]
    for key in src.values:
        if key not in keys:
            keys.append(key)
        p = _pdo(key[0])
        if p and (p[1], 1) not in keys:
            keys.append((p[1], 1))
    return keys


class Plan:
    def __init__(self, node_id, src):
        self.node_id, self.source = node_id, src
        self.steps = []  # dicts: index, subindex, name, type, data, value, device, differs, group, role, comm, send
        self.skipped = list(src.skipped)
        self.identity = []
        self.refused = None
        self.warnings = list(src.warnings)
        self.desired = collections.OrderedDict()  # what the device should hold afterwards

    @property
    def writes(self):
        return [s for s in self.steps if s["send"]]

    @property
    def same(self):
        return [s for s in self.steps if not s["send"] and s["role"] == "set"]

    def to_json(self):
        return {"node_id": self.node_id, "source": self.source.to_json(),
                "steps": [{k: v for k, v in s.items() if k != "data"} for s in self.steps],
                "writes": len(self.writes), "same": len(self.same), "skipped": self.skipped,
                "identity": self.identity, "refused": self.refused, "warnings": self.warnings}


def _check_identity(plan, live, ignore_identity):
    want = plan.source.identity
    for sub, key, label in ((1, "vendor_id", "vendor ID"), (2, "product_code", "product code"),
                            (3, "revision_number", "revision number")):
        data = live.values.get((0x1018, sub))
        have = _u(data) if data is not None and len(data) == 4 else None
        if key not in want:
            if key != "revision_number":
                plan.identity.append({"field": label, "source": None, "device": have, "level": "warning",
                                      "text": "the source has no %s, so the device's is not checked" % label})
            continue
        if have is None:
            if key != "revision_number":
                plan.identity.append({"field": label, "source": want[key], "device": None, "level": "refuse",
                                      "text": "the device's %s could not be read" % label})
            continue
        if have != want[key]:
            level = "warning" if key == "revision_number" else "refuse"
            plan.identity.append({"field": label, "source": want[key], "device": have, "level": level,
                                  "text": "%s differs: source 0x%08X, device 0x%08X" % (label, want[key], have)})
    refusals = [i["text"] for i in plan.identity if i["level"] == "refuse"]
    if refusals and not ignore_identity:
        plan.refused = "; ".join(refusals) + " (ignore the identity check to write anyway)"


def _step(plan, key, data, live, role="set", group=None):
    src = plan.source
    t = src.type_of(key)
    dev = live.values.get(key)
    differs = not (dev is not None and P.same(data, dev, t)) if t is not None else dev != data
    plan.steps.append({"index": key[0], "subindex": key[1], "name": src.name_of(key),
                       "type": type_name(t) if t is not None else None, "data": data,
                       "value": P.shown(data, t) if t is not None else data.hex(" ").upper(),
                       "device": (P.shown(dev, t) if t is not None else dev.hex(" ").upper()) if dev is not None
                       else None,
                       "differs": differs, "group": group, "role": role, "comm": key[0] < 0x2000, "send": False})
    return plan.steps[-1]


def _ro(src, key):
    o = src.eds.find(*key)
    return o is not None and not o.writable


def _pdo_steps(plan, group, comm, mapping, live):
    """The steps of one PDO in CiA 301 order: off, mapping count 0, entries,
    count, the other communication entries, on."""
    src, want = plan.source, plan.source.values
    keys = [k for k in want if k[0] in (comm, mapping)]
    for k in keys:
        if _ro(src, k):
            plan.skipped.append({"index": k[0], "subindex": k[1], "name": src.name_of(k),
                                 "reason": "read-only in the EDS"})
    keys = [k for k in keys if not _ro(src, k)]
    if not keys:
        return
    map_keys = sorted(k for k in keys if k[0] == mapping)
    if map_keys:
        info = eds_mod.mapping_info(src.eds, mapping)
        count = want.get((mapping, 0))
        n = _u(count) if count is not None else None
        missing = [k for k in range(1, (n or 0) + 1) if (mapping, k) not in want]
        why = None
        if not info["writable"]:
            why = "the device's mapping is fixed (read-only in the EDS)"
        elif count is None or missing:
            why = "the source's mapping is incomplete (no count, or entries missing)"
        if why:
            for k in map_keys:
                plan.skipped.append({"index": k[0], "subindex": k[1], "name": src.name_of(k), "reason": why})
            map_keys = []
    comm_keys = sorted(k for k in keys if k[0] == comm and k[1] not in (0, 1))
    cob_key = (comm, 1)
    cob_final = want.get(cob_key) if cob_key in keys else None
    cob_now = live.values.get(cob_key)
    for k in map_keys + comm_keys + ([cob_key] if cob_final is not None else []):
        plan.desired[k] = want[k]
    entries = [(k, want[k]) for k in map_keys if k[1] != 0]
    count = want.get((mapping, 0)) if map_keys else None
    group_steps = []
    off_known = cob_now if cob_now is not None and len(cob_now) == 4 else cob_final
    can_switch = not _ro(src, cob_key) and src.eds.find(*cob_key) is not None and off_known is not None
    if can_switch and (map_keys or comm_keys or cob_final is not None):
        off = (_u(off_known) | INVALID).to_bytes(4, "little")
        group_steps.append(_step(plan, cob_key, off, live, "off", group))
    if map_keys:
        group_steps.append(_step(plan, (mapping, 0), bytes(len(count)), live, "clear", group))
        for k, data in entries:
            group_steps.append(_step(plan, k, data, live, "set", group))
        group_steps.append(_step(plan, (mapping, 0), count, live, "set", group))
    for k in comm_keys:
        group_steps.append(_step(plan, k, want[k], live, "set", group))
    if cob_final is not None:
        group_steps.append(_step(plan, cob_key, cob_final, live, "set", group))
    elif can_switch and (map_keys or comm_keys):
        group_steps.append(_step(plan, cob_key, off_known, live, "on", group))
    # The whole sequence goes when any value the device should end with differs.
    differs = any(s["differs"] for s in group_steps if s["role"] == "set")
    for s in group_steps:
        s["send"] = differs
        if s["role"] != "set":
            s["differs"] = differs


def build_plan(src, node_id, live, ignore_identity=False):
    """A Plan from a Source and a Reading of plan_keys(src) (live)."""
    plan = Plan(node_id, src)
    _check_identity(plan, live, ignore_identity)
    if src.node_id is not None and src.node_id != node_id:
        plan.refused = ("the source is for node %d and the device is node %d: its COB-IDs would point at the "
                        "wrong node" % (src.node_id, node_id))
    pre, post, last, groups = [], [], [], collections.OrderedDict()
    for key in src.values:
        p = _pdo(key[0])
        if p:
            groups.setdefault((p[0][0], int(p[0][4:])), p)
        elif key[0] == CONFIG_DATE:
            last.append(key)
        elif key[0] < PDO_FIRST:
            pre.append(key)
        else:
            post.append(key)
    for key in pre:
        plan.desired[key] = src.values[key]
        _step(plan, key, src.values[key], live)["send"] = None
    for _, (group, comm, mapping) in sorted(groups.items()):
        _pdo_steps(plan, group, comm, mapping, live)
    for key in post + last:
        plan.desired[key] = src.values[key]
        _step(plan, key, src.values[key], live)["send"] = None
    for s in plan.steps:
        if s["send"] is None:
            s["send"] = s["differs"]
    return plan


# -- writing ---------------------------------------------------------------------------------

def node_state(client, node_id):
    """(was OPERATIONAL, configured by the runtime) from status: on an
    adapter from the node's recent heartbeat, on a runtime from its node
    list (a node there is one the runtime configures)."""
    st = client.status()
    for nd in st.get("nodes") or []:
        if nd.get("node_id") != node_id:
            continue
        if st.get("local"):
            heard = nd.get("last_heard_s")
            return nd.get("state") == OPERATIONAL and heard is not None and heard <= HEARD_S, False
        return nd.get("state") == OPERATIONAL, True
    return False, False


def check_target(client, node_id):
    """Refuses a node the runtime configures itself; returns was OPERATIONAL."""
    operational, configured = node_state(client, node_id)
    if configured:
        raise CommissioningError("the master writes node %d's configuration at every boot; change the runtime's "
                                 "configuration and reset the node (NMT reset) instead" % node_id)
    return operational


def _failure(res):
    code = res.get("abort_code")
    return code, abort_text(code) if code is not None else res.get("error") or "failed"


def wait_ready(client, node_id, timeout_s=READY_S):
    """Until the node answers SDO again (after a reset), or timeout."""
    end = time.monotonic() + timeout_s
    time.sleep(0.2)
    while time.monotonic() < end:
        try:
            if client.sdo_read(node_id, 0x1000, 0, 300).get("success"):
                return True
        except DiagError:
            pass
        time.sleep(0.2)
    return False


def configure(client, node_id, plan, hold=True, was_operational=False, progress=None, cancel=None,
              timeout_ms=1000):
    """Writes a plan, then reads every planned entry back. Returns {written,
    failed, skipped, same, held, started, cancelled, readback, verified,
    notes}. Never writes 0x1010 or 0x1011."""
    if plan.refused:
        raise CommissioningError("configuration refused: %s" % plan.refused)
    local = bool(client.info.get("local"))
    result = {"written": [], "failed": [], "skipped": list(plan.skipped), "same": len(plan.same), "held": False,
              "started": False, "cancelled": False, "readback": [], "verified": False, "notes": []}
    writes = plan.writes
    if hold and writes:
        if local:
            client.nmt(node_id, "preop")
            result["held"] = True
        else:
            result["notes"].append("the runtime sends NMT only to the nodes it configures, so node %d was not put "
                                   "in PRE-OPERATIONAL" % node_id)
    failed_groups = set()
    try:
        for n, w in enumerate(writes):
            if cancel and cancel():
                result["cancelled"] = True
                break
            assert w["index"] not in (0x1010, 0x1011)
            base = {"index": w["index"], "subindex": w["subindex"], "name": w["name"], "value": w["value"],
                    "group": w["group"], "role": w["role"]}
            if w["group"] and w["group"] in failed_groups:
                result["skipped"].append(dict(base, reason="not written: an earlier write of %s failed, so it "
                                                           "stays switched off" % w["group"]))
                continue
            res = client.sdo_write(node_id, w["index"], w["subindex"], w["data"], timeout_ms)
            if res.get("success"):
                result["written"].append(base)
            else:
                code, text = _failure(res)
                result["failed"].append(dict(base, abort_code=code, error=text))
                if w["group"]:
                    failed_groups.add(w["group"])
            if progress:
                progress(n + 1, len(writes))
    finally:
        if result["held"] and was_operational:
            try:
                client.nmt(node_id, "start")
                result["started"] = True
            except DiagError as e:
                result["notes"].append("node %d could not be started again: %s" % (node_id, e))
        elif result["held"]:
            result["notes"].append("node %d stays PRE-OPERATIONAL (it was not seen OPERATIONAL before)" % node_id)
    if not result["cancelled"]:
        result["readback"] = verify(client, node_id, plan, timeout_ms=timeout_ms)["differences"]
        result["verified"] = not result["readback"] and not result["failed"]
    return result


def verify(client, node_id, plan, progress=None, cancel=None, timeout_ms=P.READ_TIMEOUT_MS):
    """Reads every entry the plan wants the device to hold and compares it.
    {differences: [...], checked, stopped}."""
    keys = list(plan.desired)
    reading = P.read_entries(client, node_id, keys, progress, cancel, timeout_ms)
    out = []
    for key in keys:
        want = plan.desired[key]
        t = plan.source.type_of(key)
        base = {"index": key[0], "subindex": key[1], "name": plan.source.name_of(key),
                "value": P.shown(want, t) if t is not None else want.hex(" ").upper()}
        if key in reading.failed:
            code, text = reading.failed[key]
            out.append(dict(base, device=None, error=text, abort_code=code))
            continue
        if key not in reading.values:
            continue  # the read stopped before it
        dev = reading.values[key]
        if not (P.same(want, dev, t) if t is not None else want == dev):
            out.append(dict(base, device=P.shown(dev, t) if t is not None else dev.hex(" ").upper()))
    return {"differences": out, "checked": len(reading.values) + len(reading.failed), "stopped": reading.stopped}


# -- store and restore defaults --------------------------------------------------------------

def restore_defaults(client, node_id, eds, subindex=1, reset=False):
    """Writes "load" to 0x1011 `subindex`, then (with `reset`) NMT reset node."""
    if not eds.has(0x1011):
        raise CommissioningError("node %d's EDS has no object 0x1011: the device cannot restore its defaults"
                                 % node_id)
    if eds.find(0x1011, subindex) is None:
        raise CommissioningError("node %d's EDS has no 0x1011 sub %d" % (node_id, subindex))
    res = client.sdo_write(node_id, 0x1011, subindex, LOAD, P.STORE_TIMEOUT_MS)
    if not res.get("success"):
        code, text = _failure(res)
        return {"restored": False, "subindex": subindex, "abort_code": code, "error": text, "reset": False}
    out = {"restored": True, "subindex": subindex, "reset": False}
    if reset:
        client.nmt(node_id, "reset")
        out["reset"] = True
        out["note"] = "node %d was reset and starts with its default values" % node_id
    else:
        out["note"] = "the defaults take effect at node %d's next reset or power cycle" % node_id
    return out
