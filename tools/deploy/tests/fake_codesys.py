"""A stand-in for the parts of CODESYS's scripting API that
import_canworks.py uses (projects, device_repository, system), so the
script runs under CPython in CI. Device parameters follow what CODESYS
V3.5 SP22 (CANbus / CANopen_Manager 4.4.0.0) showed in the spike: settings
in connectors' host_parameters by numeric id, struct parameters writable
only through their elements, a mapped object at 0x1MMMMEE0 with its I/O
channel at the next id."""

import configparser
import itertools
import os
import re
import runpy

_guids = itertools.count(1)


class DeviceId:
    def __init__(self, type, id, version):
        self.type, self.id, self.version = type, id, version

    def __repr__(self):
        return "DeviceID(%s, %r, %r)" % (self.type, self.id, self.version)


class Element:
    """A struct element (or an array row holding elements). `on_set(element,
    value)` may refuse a write by returning False."""

    def __init__(self, identifier, value, children=None, on_set=None):
        self.identifier, self._value = identifier, value
        self.children = children or []
        self.on_set = on_set

    def __iter__(self):
        return iter(self.children)

    @property
    def value(self):
        if self.children:
            return "{%s}" % ", ".join(c.value for c in self.children)
        return self._value

    @value.setter
    def value(self, v):
        if self.on_set is not None and self.on_set(self, v) is False:
            return
        self._value = v


class IoMapping:
    def __init__(self):
        self.variable = None
        self.automatic_iec_address = True
        self.manual_iec_address = ""


class Param:
    def __init__(self, id, name, value=None, elements=None, channel=False, download=True, on_set=None):
        self.id, self.name = id, name
        self.elements = [e if isinstance(e, Element) else Element(e[0], e[1], on_set=on_set) for e in elements] \
            if elements else []
        self._value = value
        self.io_mapping = IoMapping() if channel else None
        self._download = download
        self.on_set = on_set

    def __iter__(self):
        return iter(self.elements)

    @property
    def downloaded_with_ioconfig(self):
        return self._download

    @property
    def value(self):
        if self.elements:
            return "{%s}" % ", ".join(e.value for e in self.elements)
        return self._value

    @value.setter
    def value(self, v):
        if self.elements:
            raise Exception("Operation not allowed on struct types")
        if self.on_set is not None and self.on_set(self, v) is False:
            return
        self._value = v


class Connector:
    def __init__(self, params):
        self.host_parameters = list(params)


class Message:
    def __init__(self, severity, text):
        self.severity, self.text = severity, text


class System:
    def __init__(self):
        self.messages = []

    def get_message_categories(self):
        return ["build"]

    def get_message_objects(self, category):
        return list(self.messages)


class Obj:
    def __init__(self, world, name, ident=None, connectors=()):
        self.world, self._name, self.ident = world, name, ident
        self.connectors = list(connectors)
        self.device_parameters = []
        self.children, self.parent = [], None
        self.guid = next(_guids)
        # Device types, or (type, id) pairs, CODESYS takes under this object (None: any).
        self.accepts = None

    @property
    def is_device(self):
        return self.ident is not None

    def get_name(self):
        return self._name

    def get_device_identification(self):
        return self.ident

    def get_children(self, recursive=False):
        out = []
        for c in self.children:
            out.append(c)
            if recursive:
                out.extend(c.get_children(True))
        return out

    def find(self, name, recursive=False):
        return [c for c in self.get_children(recursive) if c.get_name() == name]

    def add(self, name, type, id, version):
        if self.world.fail_add.get(type):
            raise Exception(self.world.fail_add[type])
        if self.accepts is not None and type not in self.accepts and (type, id) not in self.accepts:
            raise Exception("Exception was raised: The device cannot be added or inserted here.")
        top = self
        while top.parent is not None and top.parent.parent is not None:
            top = top.parent
        clash = [] if top.parent is None else [c for c in [top] + top.get_children(True)
                                               if c.get_name().lower() == name.lower()]
        if clash:
            # CODESYS wants names unique in the whole tree of a top-level device.
            raise Exception("The name conflicts with the existing object '%s'" % clash[0].get_name())
        child = self.world.make(name, DeviceId(type, id, version))
        child.parent = self
        self.children.append(child)
        self.world.log.append(("add", self.get_name(), child.get_name(), type, id, version))

    def rename(self, name):
        top = self
        while top.parent is not None and top.parent.parent is not None:
            top = top.parent
        used = [c for c in [top] + top.get_children(True) if c is not self and c.get_name().lower() == name.lower()]
        if name in self.world.names_taken or (top.parent is not None and used):
            raise Exception("the name %s is used already" % name)
        self.world.log.append(("rename", self._name, name))
        self._name = name

    def remove(self):
        self.parent.children.remove(self)
        self.world.log.append(("remove", self.get_name()))


class App:
    def __init__(self, project, parent=None):
        self.project, self.parent = project, parent
        self.guid = next(_guids)
        self.imported = []

    def get_name(self):
        return "Application"

    def import_xml(self, reporter, path):
        """PLCopen XML import: records the file; conflicts go to the reporter."""
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for name in self.imported:
            reporter.resolve_conflict(name)
            reporter.replaced(name)
        self.imported = [path]
        reporter.added(path)
        self.project.world.log.append(("import_xml", os.path.basename(path), len(text)))

    def build(self):
        w = self.project.world
        w.system.messages = []
        names = {}
        for c in self.project.get_children(True):
            for con in c.connectors:
                for p in con.host_parameters:
                    if p.io_mapping is not None and p.io_mapping.variable:
                        names.setdefault(p.io_mapping.variable.lower(), []).append(c.get_name())
        for v in w.globals:
            names.setdefault(v.lower(), []).append("GVL")
        for name, where in sorted(names.items()):
            if len(where) > 1:
                w.system.messages.append(Message("Error", "Duplicate definition of identifier '%s'" % name))
        w.builds += 1


class Project(Obj):
    def __init__(self, world, path):
        super().__init__(world, os.path.basename(path))
        self.path = path
        self.active_application = App(self)
        self.saved = self.closed = False

    def add(self, name, type, id, version):
        super().add(name, type, id, version)

    def save(self):
        self.saved = True

    def export_xml(self, objects, path, recursive=True):
        """PLCopenXML of the objects and their children, laid out as CODESYS
        V3.5 SP22 writes it (the parts the import reads)."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(plcopen_xml(self, objects))
        self.world.log.append(("export_xml", [o.get_name() for o in objects]))

    def close(self):
        self.closed = True


class Projects:
    def __init__(self, world):
        self.world = world
        self.primary = None

    def open(self, path):
        if path in self.world.in_use:
            raise Exception("The selected project is currently in use by 'someone' on 'another-pc'.")
        p = self.world.stored[path]
        self.primary = p
        return p

    def create(self, path, primary=True):
        p = Project(self.world, path)
        self.world.stored[path] = p
        self.primary = p
        return p


class Task(Obj):
    """A task of the task configuration: `pous` lists the program calls."""

    def __init__(self, world, name, pous=()):
        super().__init__(world, name)
        self.pous = PouList(pous)


class PouList(list):
    def add(self, name):
        self.append(name)


class Repository:
    def __init__(self, world):
        self.world = world
        self.sources = ["local"]
        self.devices = []
        self.names = {}  # (type, id): catalogue name

    def get_all_devices(self):
        names = self.names

        class Info:
            def __init__(self, name):
                self.name = name

        class Desc:
            def __init__(self, i):
                self.device_id = i
                self.device_info = Info(names.get((i.type, i.id), i.id))
        return [Desc(d) for d in self.devices]

    def import_device(self, path, source, guid, save):
        assert guid == "{1ce4a9c1-37d3-496c-9e80-cd99ad3807ee}", guid
        dcf = configparser.ConfigParser(strict=False, interpolation=None)
        dcf.optionxform = str
        with open(path, encoding="utf-8") as f:
            dcf.read_file(f)
        info = dcf["DeviceInfo"]
        did = DeviceId(18, "%X_%X_DCF" % (int(info["VendorNumber"], 0), int(info["ProductNumber"], 0)),
                       "Revision=16#%08X, FileVersion=1.1" % int(info.get("RevisionNumber", "0"), 0))
        self.world.descriptions[(did.type, did.id, did.version)] = dcf
        if not any(d.id == did.id and d.version == did.version for d in self.devices):
            self.devices.append(did)
        self.world.log.append(("import", os.path.basename(path)))
        return did


def _value(dcf, section, key="ParameterValue"):
    if not dcf.has_section(section):
        return None
    s = dcf[section]
    v = s.get(key) or s.get("DefaultValue")
    try:
        return int(v, 0)
    except (TypeError, ValueError):
        return None


def _number(text):
    t = str(text).strip().strip("'")
    return int(t[3:], 16) if t.upper().startswith("16#") else int(t, 0)


def _generic_text(default):
    """An EDS COB-ID default as CODESYS's generic COB-ID string."""
    t = default.replace(" ", "")
    if "$NODEID" in t.upper():
        rest = re.sub(r"(?i)\$NODEID", "", t).strip("+")
        return "$NODEID+16#%X" % (int(rest, 0) if rest else 0)
    return "16#%X" % int(t, 0)


def _resolve_text(text, node_id):
    t = str(text).strip().strip("'").replace(" ", "")
    total = 0
    for part in t.split("+"):
        if part.upper() == "$NODEID":
            total += node_id
        elif part.upper().startswith("16#"):
            total += int(part[3:], 16)
        else:
            total += int(part, 0)
    return total


def _resolve_cob(params, comm, generic):
    """A generic COB-ID string moves the PDO's COB-ID (with the node ID)."""
    node_id = int(next(p.value for p in params if p.id == 1))
    struct = next(p for p in params if p.id == comm << 12)
    cob = next(e for e in struct.elements if e.identifier == "COBID")
    cob._value = "16#%08X" % _resolve_text(generic, node_id)


class World:
    """One CODESYS: its repository, projects and messages."""

    def __init__(self, canbus_version="4.4.0.0", manager_versions=("4.4.0.0",), missing_manager_ids=()):
        self.log, self.stored, self.descriptions = [], {}, {}
        self.fail_add, self.globals, self.names_taken = {}, [], set()
        self.builds = 0
        self.in_use = set()  # projects another CODESYS holds open
        self.missing_manager_ids = set(missing_manager_ids)
        self.system = System()
        self.projects = Projects(self)
        self.repo = Repository(self)
        self.repo.devices.append(DeviceId(15, "181015", canbus_version))
        for v in manager_versions:
            self.repo.devices.append(DeviceId(16, "181016", v))
        self.repo.devices.append(DeviceId(4096, "0000 0004", "3.5.22.40"))
        for (t, i, name) in ((110, "0000 0002", "Ethernet"), (89, "0000 0001", "Modbus TCP Master"),
                             (89, "0000 0002", "Modbus TCP Slave")):
            self.repo.devices.append(DeviceId(t, i, "4.4.0.0"))
            self.repo.names[(t, i)] = name

    def make(self, name, ident):
        if ident.type == 15:
            return Obj(self, name, ident, [Connector([]), Connector(
                [Param(0, "Baudrate", "250"), Param(2, "NetID", "0")])])
        if ident.type == 16:
            ids = [(256, "Sync CycleTime in Microseconds", "1000"), (257, "Enable Sync generation", "FALSE"),
                   (259, "Synchronous Window Length", "1200"), (261, "Autostart", "TRUE"),
                   (262, "Start Slaves", "TRUE"), (263, "NMT Start All", "FALSE"), (266, "NMTInhibitTime", "10"),
                   (272, "Heartbeat in Milliseconds", "200"), (273, "Enable Heartbeat generation", "TRUE"),
                   (274, "Heartbeat Node ID", "127"), (277, "SDO Timeout Default (ms)", "1000"),
                   (288, "CANopen NodeID", "127"), (290, "TIME COBID", "256"),
                   (291, "TIME Producer Interval (ms)", "1000")]
            # TIME producing is off until its COB-ID and period are downloaded.
            return Obj(self, name, ident, [Connector([Param(i, n, v, download=i not in (290, 291)) for i, n, v in ids
                                                      if i not in self.missing_manager_ids])])
        if ident.type == 17:
            return Obj(self, name, ident, [Connector([Param(1, "Node-ID", "1")])])
        if ident.type == 18:
            return self._remote(name, ident)
        if (ident.type, ident.id) == (89, "0000 0002"):
            return Obj(self, name, ident, [Connector([Param(1, "IP address", "0.0.0.0"), Param(2, "Port", "502"),
                                                      Param(3, "Unit-ID", "255")])])
        return Obj(self, name, ident)

    def _remote(self, name, ident):
        """A remote device as CODESYS makes it from a DCF: node ID, options,
        heartbeat, consumers, guarding, identity, PDO communication objects
        (with the generic COB-ID string and "processed by the manager"),
        mapped objects with their channels, and the SDO list (generated rows
        first, then a row per object from 0x2000 whose DCF value is not the
        default)."""
        dcf = self.descriptions[(ident.type, ident.id, ident.version)]
        world = self
        node_id = _value(dcf, "DeviceComissioning", "NodeID")
        holder = {}

        def logged(what):
            def on_set(target, value):
                world.log.append(("set", holder["obj"].get_name() if "obj" in holder else name, what,
                                  getattr(target, "identifier", None), value))
            return on_set

        def generic_set(comm):
            def on_set(target, value):
                world.log.append(("set", holder["obj"].get_name(), "generic COB-ID", "%04X" % comm, value))
                target._value = value
                _resolve_cob(holder["params"], comm, value)
                return False
            return on_set

        def cob_set(target, value):
            # CODESYS ignores a COB-ID written to the struct of a PDO that is on.
            if not _number(target.value) & 0x80000000:
                world.log.append(("ignored", holder["obj"].get_name(), "COBID", value))
                return False
            world.log.append(("set", holder["obj"].get_name(), "COBID", None, value))

        def node_id_set(target, value):
            world.log.append(("set", holder["obj"].get_name(), "Node-ID", None, value))
            target._value = value
            for p in holder["params"]:
                if (p.id & 0xFFF) == 1 and 0x01400000 <= p.id < 0x01A00000:
                    _resolve_cob(holder["params"], (p.id - 1) >> 12, p.value)
            return False

        params = [Param(1, "Node-ID", str(node_id), on_set=node_id_set),
                  Param(2, "General Options", elements=[("FLAG_DCF_Write", "FALSE"), ("FLAG_CreateAllSDOs", "FALSE"),
                                                        ("FLAG_Optional", "FALSE"), ("FLAG_NotInitialize", "FALSE"),
                                                        ("FLAG_ResetNode", "FALSE")], on_set=logged("options")),
                  Param(17, "SDO Timeout", "1000000", on_set=logged("sdo timeout")),
                  Param(16846848, "SubIndex for reset node", "1", on_set=logged("reset sub")),
                  # CODESYS takes the producer time from a configured value
                  # (ParameterValue) only, not from the EDS default.
                  Param(0x01017000, "Heartbeat-Producer Time",
                        str(int(dcf["1017"].get("ParameterValue", "0"), 0) if dcf.has_section("1017") else 0),
                        on_set=logged("heartbeat"))]
        for sub in range(1, 128):
            if not dcf.has_section("1016sub%X" % sub):
                break
            v = _value(dcf, "1016sub%X" % sub) or 0
            params.append(Param(0x11016000 | (sub << 4), "Heartbeat-Consuming%d" % sub,
                                elements=[("HeartbeatConsumingNodeID", str((v >> 16) & 0xFF)),
                                          ("HeartbeatTime", str(v & 0xFFFF))], on_set=logged("consumer")))
        if dcf.has_section("100C") and dcf.has_section("100D"):
            params.append(Param(0x0100C000, "Nodeguarding",
                                elements=[("GuardTime", str(_value(dcf, "100C") or 0)),
                                          ("LifeTimeFactor", str(_value(dcf, "100D") or 0))],
                                on_set=logged("guarding")))
        if dcf.has_section("1012"):
            v = _value(dcf, "1012") or 0
            params.append(Param(0x01012000, "Time Stamp", elements=[
                ("TimeConsumingEnable", "TRUE" if v & 0x80000000 else "FALSE"),
                ("TimeProducingEnable", "TRUE" if v & 0x40000000 else "FALSE"),
                ("TimeProducingCOBID", "16#%X" % (v & 0x3FFFFFFF))], on_set=logged("time")))
        for pid, n, key, on in ((0x11018010, "Vendor ID", "VendorNumber", True),
                                (0x11018020, "Product Code", "ProductNumber", False),
                                (0x11018030, "Product Revision", "RevisionNumber", False)):
            params.append(Param(pid, n, str(int(dcf["DeviceInfo"].get(key, "0"), 0)), download=on))
        rows = []
        for d, comm_base, map_base in (("rx", 0x1400, 0x1600), ("tx", 0x1800, 0x1A00)):
            for n in range(512):
                comm = comm_base + n
                if not dcf.has_section("%Xsub1" % comm):
                    continue
                sec = dcf["%Xsub1" % comm]
                pv = sec.get("ParameterValue")
                default = sec.get("DefaultValue", "0")
                generic = ("16#%X" % int(pv, 0)) if pv else _generic_text(default)
                cob = _resolve_text(generic, node_id)
                el = [Element("COBID", "16#%08X" % cob, on_set=cob_set),
                      Element("TransmissionType", "16#%02X" % (_value(dcf, "%Xsub2" % comm) or 0),
                              on_set=logged("pdo")),
                      Element("PDOParameterAvailable", "", children=[
                          Element("PDOInhibitTimeAvailable", "TRUE" if dcf.has_section("%Xsub3" % comm) else "FALSE"),
                          Element("PDOEventTimerAvailable", "TRUE" if dcf.has_section("%Xsub5" % comm) else "FALSE")]),
                      Element("InhibitTime", str(_value(dcf, "%Xsub3" % comm) or 0), on_set=logged("pdo")),
                      Element("EventTimer", str(_value(dcf, "%Xsub5" % comm) or 0), on_set=logged("pdo"))]
                params.append(Param(comm << 12, "PDO 16#%X" % comm, elements=el))
                params.append(Param((comm << 12) + 1, "Generic COBID", "'%s'" % generic, on_set=generic_set(comm)))
                params.append(Param((comm << 12) + 2, "Process by CANopenManager", "TRUE", on_set=logged("by manager")))
                rows.append((comm, 1, cob, 32, "Set COB-ID"))
                base = map_base + n
                count = _value(dcf, "%Xsub0" % base)
                for sub in range(1, (count or 0) + 1):
                    v = _value(dcf, "%Xsub%X" % (base, sub))
                    if not v:
                        continue
                    pid = 0x10000000 | (base << 12) | (sub << 4)
                    params.append(Param(pid, "obj%X" % (v >> 16), elements=[
                        ("Index", "16#%04X" % (v >> 16)), ("SubIndex", "16#%02X" % ((v >> 8) & 0xFF)),
                        ("ObjectLength", str(v & 0xFF))]))
                    params.append(Param(pid + 1, "obj%X" % (v >> 16), "{}", channel=True))
        for section in dcf.sections():
            m = re.match(r"^([0-9A-F]{4})(?:sub([0-9A-F]+))?$", section, re.I)
            if not m or int(m.group(1), 16) < 0x2000:
                continue
            pv, default = dcf[section].get("ParameterValue"), dcf[section].get("DefaultValue", "0")
            if pv is None or _resolve_text(pv, node_id) == _resolve_text(default, node_id):
                continue
            size = {"0x0001": 8, "0x0005": 8, "0x0002": 8, "0x0006": 16, "0x0003": 16, "0x0007": 32, "0x0004": 32}.get(
                dcf[section].get("DataType", "0x0007").lower(), 32)
            rows.append((int(m.group(1), 16), int(m.group(2) or "0", 16), int(pv, 0), size, "user"))
        sdo = []
        for i, (index, sub, value, size, label) in enumerate(rows):
            sdo.append(Element("[%d]" % i, None, children=[
                Element("Index", "16#%04X" % index), Element("Subindex", "16#%02X" % sub),
                Element("Value", "16#%X" % value, on_set=logged("sdo")), Element("Size", str(size)),
                Element("AbortIfError", "FALSE", on_set=logged("sdo")),
                Element("JumpToLine", "FALSE", on_set=logged("sdo")),
                Element("Line", "0", on_set=logged("sdo"))]))
        params.append(Param(0x20001000, "SDO List", elements=sdo))
        obj = Obj(self, name, ident, [Connector(params)])
        holder.update(obj=obj, params=params)
        return obj

    def project_with_plc(self, path, name="PLC"):
        p = self.projects.create(path)
        p.add(name, 4096, "0000 0004", "3.5.22.40")
        return p

    def add_application(self, project, device, active=True):
        """Device > Plc Logic > Application, as CODESYS lays it out."""
        logic = Obj(self, "Plc Logic")
        logic.parent = device
        device.children.append(logic)
        app = App(project, logic)
        if active:
            project.active_application = app
        return app

    def add_object(self, parent, name, type=None, accepts=None):
        """An object a device description brings, e.g. Communication > CAN."""
        obj = Obj(self, name, DeviceId(type, "vendor_%s" % name, "1.0.0.0") if type is not None else None)
        obj.parent, obj.accepts = parent, accepts
        parent.children.append(obj)
        return obj

    def add_task(self, device, name, pous=()):
        """Device > Plc Logic > Application > Task Configuration > task."""
        tc = Obj(self, "Task Configuration")
        tc.parent = device
        device.children.append(tc)
        task = Task(self, name, pous)
        task.parent = tc
        tc.children.append(task)
        return task

    def run(self, folder, primary=None, script="import_canworks.py", report="import_report.txt"):
        """Runs the folder's import_canworks.py (or `script`) as CODESYS would."""
        self.projects.primary = primary
        script = os.path.join(folder, script)
        runpy.run_path(script, init_globals={"projects": self.projects, "device_repository": self.repo,
                                             "system": self.system})
        with open(os.path.join(folder, report), encoding="utf-8") as f:
            return f.read()


def channels_of(device):
    return {p.id - 1: p.io_mapping.variable for con in device.connectors for p in con.host_parameters
            if p.io_mapping is not None and p.io_mapping.variable}


def param(obj, pid):
    for con in obj.connectors:
        for p in con.host_parameters:
            if p.id == pid:
                return p
    return None


def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _elements_xml(elements):
    out = []
    for e in elements:
        if e.children:
            out.append('<Element name="%s">%s</Element>' % (_esc(e.identifier), _elements_xml(e.children)))
        else:
            out.append('<Element name="%s">%s</Element>' % (_esc(e.identifier), _esc(e.value)))
    return "".join(out)


def _param_xml(p):
    attrs = '<Attributes download="false" />' if not p.downloaded_with_ioconfig else "<Attributes />"
    fixed = ""
    if p.io_mapping is not None and not p.io_mapping.automatic_iec_address and p.io_mapping.manual_iec_address:
        fixed = ' FixedAddress="%s"' % _esc(p.io_mapping.manual_iec_address)
    if p.id == 0x20001000:
        rows = []
        for row in p.elements:
            el = {c.identifier: c.value for c in row.children}
            implicit = int(el["Index"][3:], 16) < 0x2000
            rows.append('<Value name="row">%s%s</Value>' % (_elements_xml(row.children),
                                                            "<Custom><ImplicitSDO /></Custom>" if implicit else ""))
        value = "".join(rows)
    elif p.elements:
        value = '<Value name="v">%s</Value>' % _elements_xml(p.elements)
    else:
        value = '<Value name="v">%s</Value>' % _esc(p.value if p.value is not None else "")
    mapping = ""
    if p.io_mapping is not None and p.io_mapping.variable:
        mapping = "<Mapping>%s</Mapping>" % _esc(p.io_mapping.variable)
    return '<Parameter ParameterId="%d" type="std:x"%s>%s%s<Name>%s</Name>%s</Parameter>' % (
        p.id, fixed, attrs, value, _esc(p.name), mapping)


def _config_xml(obj):
    params = "".join(_param_xml(p) for con in obj.connectors for p in con.host_parameters)
    ident = obj.ident
    kids = "".join(_config_xml(c) for c in obj.children if c.is_device)
    children = ('<data name="http://www.3s-software.com/plcopenxml/configurations" handleUnknown="implementation">'
                "<configurations>%s</configurations></data>" % kids) if kids else ""
    return ('<configuration name="%s"><addData><data name="Device" handleUnknown="discard"><Device xmlns="">'
            "<DeviceType><DeviceIdentification><Type>%s</Type><Id>%s</Id><Version>%s</Version>"
            "</DeviceIdentification><Connector><HostParameterSet>%s</HostParameterSet></Connector></DeviceType>"
            "</Device></data>%s</addData></configuration>"
            % (_esc(obj.get_name()), ident.type, _esc(ident.id), _esc(ident.version), params, children))


def plcopen_xml(project, objects):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<project xmlns="http://www.plcopen.org/xml/tc6_0200">'
            '<contentHeader name="%s" /><instances><configurations>%s</configurations></instances></project>\n'
            % (_esc(os.path.basename(project.path)), "".join(_config_xml(o) for o in objects)))
