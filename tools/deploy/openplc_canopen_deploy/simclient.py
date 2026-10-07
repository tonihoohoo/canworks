"""Client for simulated CANopen devices (docs/simulator.md, "Control protocol").

The same requests reach the plugin's simulated devices over its diagnostics
channel (port 7531, token, allow_changes for changes) and a standalone
`openplc-canopen-sim` over its control channel (port 7532, token only when
it has one). Both answer the diagnostics hello, so one diag.Client serves
both."""

from . import diag

SIM_PORT = 7532

# Requests that only read; the rest need allow_changes on the plugin.
READ_OPS = ("sim_status", "sim_get", "sim_scenario_list", "sim_check_expr")


def parse_sim(text):
    """HOST[:PORT] of a standalone simulator (default port 7532)."""
    host, port = diag.parse_runtime(text)
    if ":" not in text.rsplit("]", 1)[-1]:
        port = SIM_PORT
    return host, port


def object_key(index, subindex=0):
    """The protocol's object name, "0xIIII:S"."""
    return "0x%04X:%d" % (index, subindex)


def parse_object(text):
    """(index, subindex) from "0x6200:1", "0x6200" or "6200:1"."""
    t = text.strip()
    idx, _, sub = t.partition(":")
    try:
        index = int(idx, 16) if not idx.lower().startswith("0x") else int(idx, 0)
        subindex = int(sub, 0) if sub else 0
    except ValueError:
        raise ValueError("object %r: want 0xIIII:S" % text)
    if not 0 <= index <= 0xFFFF or not 0 <= subindex <= 0xFF:
        raise ValueError("object %r is out of range" % text)
    return index, subindex


class SimClient:
    """Simulator requests over a connected diag.Client."""

    def __init__(self, client):
        self.client = client

    @classmethod
    def for_runtime(cls, host, port=diag.DEFAULT_PORT, token="", timeout=5.0, network=None):
        c = diag.Client(host, port, token, timeout, network=network)
        c.connect()
        try:
            diag.check_network(c, network)
        except diag.DiagError:
            c.close()
            raise
        return cls(c)

    @classmethod
    def for_simulator(cls, host="127.0.0.1", port=SIM_PORT, token="", timeout=5.0):
        c = diag.Client(host, port, token or "", timeout)
        c.connect()
        return cls(c)

    @property
    def info(self):
        return self.client.info or {}

    @property
    def standalone(self):
        """True when connected to openplc-canopen-sim, not to a runtime."""
        return bool(self.info.get("simulator"))

    def close(self):
        self.client.close()

    def request(self, op, **fields):
        return self.client.request(op, **fields)

    def status(self):
        return self.request("sim_status")

    def get(self, items):
        """items: [(node, "0xIIII:S")]; the result's "values"."""
        return self.request("sim_get", items=[{"node": n, "object": o} for n, o in items]).get("values", [])

    def get_pdo(self, node):
        """Every object in the device's active PDOs."""
        return self.request("sim_get", node=node, pdo=True).get("values", [])

    def set(self, node, values):
        return self.request("sim_set", node=node, values=values)

    def override(self, node, values):
        return self.request("sim_override", node=node, values=values)

    def release(self, node, objects="all"):
        return self.request("sim_release", node=node, objects=objects)

    def source(self, node, obj, source):
        """source None removes the object's value source."""
        return self.request("sim_source", node=node, object=obj, source=source)

    def fault(self, node, fault):
        return self.request("sim_fault", node=node, fault=fault)

    def clear(self, node, fault="all", obj=None, tpdo=None):
        fields = {"node": node, "fault": fault}
        if obj is not None:
            fields["object"] = obj
        if tpdo is not None:
            fields["tpdo"] = tpdo
        return self.request("sim_clear", **fields)

    def scenarios(self):
        return self.request("sim_scenario_list").get("scenarios", [])

    def start_scenario(self, name, scenario=None):
        fields = {"name": name}
        if scenario is not None:
            fields["scenario"] = scenario
        return self.request("sim_scenario_start", **fields)

    def stop_scenario(self, name):
        return self.request("sim_scenario_stop", name=name)

    def check_expr(self, node, expr):
        return self.request("sim_check_expr", node=node, expr=expr)
