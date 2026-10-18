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
import runpy

_guids = itertools.count(1)


class DeviceId:
    def __init__(self, type, id, version):
        self.type, self.id, self.version = type, id, version

    def __repr__(self):
        return "DeviceID(%s, %r, %r)" % (self.type, self.id, self.version)


class Element:
    def __init__(self, identifier, value):
        self.identifier, self.value = identifier, value


class IoMapping:
    def __init__(self):
        self.variable = None


class Param:
    def __init__(self, id, name, value=None, elements=None, channel=False):
        self.id, self.name = id, name
        self.elements = [Element(k, v) for k, v in elements] if elements else []
        self._value = value
        self.io_mapping = IoMapping() if channel else None

    def __iter__(self):
        return iter(self.elements)

    @property
    def value(self):
        if self.elements:
            return "{%s}" % ", ".join(e.value for e in self.elements)
        return self._value

    @value.setter
    def value(self, v):
        if self.elements:
            raise Exception("Operation not allowed on struct types")
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
        # Device types CODESYS takes under this object (None: any).
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
        if self.accepts is not None and type not in self.accepts:
            raise Exception("Exception was raised: The device cannot be added or inserted here.")
        child = self.world.make(name, DeviceId(type, id, version))
        if any(c.get_name() == child.get_name() for c in self.children):
            child._name += "_1"
        child.parent = self
        self.children.append(child)
        self.world.log.append(("add", self.get_name(), child.get_name(), type, id, version))

    def rename(self, name):
        if name in self.world.names_taken:
            raise Exception("the name %s is used already" % name)
        self._name = name

    def remove(self):
        self.parent.children.remove(self)
        self.world.log.append(("remove", self.get_name()))


class App:
    def __init__(self, project, parent=None):
        self.project, self.parent = project, parent
        self.guid = next(_guids)

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


class Repository:
    def __init__(self, world):
        self.world = world
        self.sources = ["local"]
        self.devices = []

    def get_all_devices(self):
        class Desc:
            def __init__(self, i):
                self.device_id = i
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
            return Obj(self, name, ident, [Connector([Param(i, n, v) for i, n, v in ids
                                                      if i not in self.missing_manager_ids])])
        if ident.type == 17:
            return Obj(self, name, ident, [Connector([Param(1, "Node-ID", "1")])])
        if ident.type == 18:
            return self._remote(name, ident)
        return Obj(self, name, ident)

    def _remote(self, name, ident):
        dcf = self.descriptions[(ident.type, ident.id, ident.version)]
        params = [Param(1, "Node-ID", str(_value(dcf, "DeviceComissioning", "NodeID"))),
                  Param(2, "General Options", elements=[("FLAG_DCF_Write", "FALSE"), ("FLAG_CreateAllSDOs", "FALSE"),
                                                        ("FLAG_Optional", "FALSE"), ("FLAG_NotInitialize", "FALSE"),
                                                        ("FLAG_ResetNode", "FALSE")]),
                  Param(17, "SDO Timeout", "1000000")]
        for base in list(range(0x1600, 0x1800)) + list(range(0x1A00, 0x1C00)):
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
        return Obj(self, name, ident, [Connector(params)])

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

    def run(self, folder, primary=None):
        """Runs the folder's import_canworks.py as CODESYS would."""
        self.projects.primary = primary
        script = os.path.join(folder, "import_canworks.py")
        runpy.run_path(script, init_globals={"projects": self.projects, "device_repository": self.repo,
                                             "system": self.system})
        with open(os.path.join(folder, "import_report.txt"), encoding="utf-8") as f:
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
