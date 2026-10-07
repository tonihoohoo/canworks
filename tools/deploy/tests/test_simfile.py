"""The simulation file checks (simfile.py) and the shared expression corpus
test/fixtures/sim/expressions.json (canopen-device-simulator)."""

import copy
import json
import math
import os
import shutil
import unittest

from openplc_canopen_deploy import simfile

from .helpers import REPO, tmpdir

CORPUS = os.path.join(REPO, "test", "fixtures", "sim", "expressions.json")
RTD = os.path.join(REPO, "config", "rtd-sensor", "rtd8.eds")
EDS = os.path.join(REPO, "test", "fixtures", "eds")


def corpus():
    with open(CORPUS, encoding="utf-8") as f:
        return json.load(f)


class Corpus(unittest.TestCase):
    """Every case of the corpus: ok or the error's position and word, and
    the value of the first tick."""

    def test_corpus(self):
        c = corpus()
        ctx = c["context"]
        objects = {}
        for key, v in ctx["objects"].items():
            dev, _, obj = key.rpartition("/")
            dev = None if not dev else int(dev) if dev.isdigit() else dev
            objects[(dev,) + simfile.parse_object(obj)] = v

        def resolve(dev, index, sub):
            if dev not in (None, 7, "spare"):
                return "unknown device %s" % dev
            if index == 0x6999:
                return "object %s is not in the EDS" % simfile.object_key(index, sub)
            return None

        def read(dev, index, sub):
            return objects.get((dev, index, sub), 0)

        self.assertGreaterEqual(len(c["cases"]), 50)
        for case in c["cases"]:
            with self.subTest(expr=case["expr"]):
                if case["ok"]:
                    tree = simfile.parse(case["expr"], resolve)
                    value = simfile.Evaluator(tree).eval(dict(t=ctx["t"], dt=ctx["dt"], prev=ctx["prev"], read=read))
                    self.assertTrue(math.isfinite(value))
                    if "value" in case:
                        self.assertAlmostEqual(value, case["value"], places=9)
                else:
                    with self.assertRaises(simfile.ExprError) as cm:
                        simfile.parse(case["expr"], resolve)
                    self.assertEqual(cm.exception.position, case["position"], cm.exception.message)
                    self.assertIn(case["message"], cm.exception.message)


class Expressions(unittest.TestCase):
    def test_evaluation(self):
        ev = simfile.evaluate
        self.assertEqual(ev("round(-2.5)"), -3)
        self.assertEqual(ev("round(2.4999)"), 2)
        self.assertEqual(ev("7.9 & 3"), 3)
        self.assertEqual(ev("2 < 1"), 0)
        self.assertEqual(ev("-7 % 3"), -1)
        self.assertEqual(ev("2 ** -1"), 0.5)
        self.assertEqual(ev("!!3"), 1)
        for bad in ("1 / 0", "log(0)", "sqrt(-1)", "1 % 0"):
            with self.assertRaises(simfile.EvalError, msg=bad):
                ev(bad)

    def test_stateful_functions_over_ticks(self):
        ev = simfile.Evaluator(simfile.parse("integrate(10)"))
        total = 0
        for i in range(10):
            total = ev.eval({"t": i * 0.1, "dt": 0.1})
        self.assertAlmostEqual(total, 10.0)
        lag = simfile.Evaluator(simfile.parse("lag(x0, 1)".replace("x0", "100 * (t > 0)")))
        self.assertEqual(lag.eval({"t": 0, "dt": 0.1}), 0)
        self.assertAlmostEqual(lag.eval({"t": 0.1, "dt": 0.1}), 10.0)
        delay = simfile.Evaluator(simfile.parse("delay(t, 0.5)"))
        seen = [delay.eval({"t": i * 0.1, "dt": 0.1}) for i in range(11)]
        self.assertAlmostEqual(seen[-1], 0.5)
        edge = simfile.Evaluator(simfile.parse("edge(t >= 0.2)"))
        self.assertEqual([edge.eval({"t": i * 0.1}) for i in range(5)], [0, 0, 1, 0, 0])

    def test_delay_limit_only_for_constants(self):
        simfile.parse("delay(1, 600)")
        simfile.parse("delay(1, t * 1000)")
        with self.assertRaises(simfile.ExprError):
            simfile.parse("delay(1, 60 * 11)")

    def test_references(self):
        tree = simfile.parse("[0x6200:1] + lag([7/0x6000:1], 2) + integrate([spare/0x2000])")
        refs = [(n.device, n.index, n.subindex, broken) for n, broken in simfile.references(tree)]
        self.assertEqual(refs, [(None, 0x6200, 1, False), (7, 0x6000, 1, True), ("spare", 0x2000, 0, True)])


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


class Fixture:
    """A config with node 5 (the RTD sensor: startup SDOs on 0x6110:1-4, an
    SDO variable writing 0x6110:5) and node 7 (fixed-mapping I/O: RPDO 1
    with the device mapping 0x6200:1 and :2, configured with 0x6200:1
    only), and a simulation file next to it with two extra devices."""

    def __init__(self, test):
        self.dir = tmpdir(test)
        os.makedirs(os.path.join(self.dir, "eds"))
        os.makedirs(os.path.join(self.dir, "data"))
        shutil.copy(RTD, self.dir)
        shutil.copy(os.path.join(EDS, "fixed-io.eds"), self.dir)
        shutil.copy(os.path.join(EDS, "cpp-slave.eds"), os.path.join(self.dir, "eds", "pingpong.eds"))
        shutil.copy(os.path.join(EDS, "lss-slave.eds"), os.path.join(self.dir, "eds", "lss-slave.eds"))
        with open(os.path.join(self.dir, "data", "temp.csv"), "w") as f:
            f.write("time,value\n0,200\n10,260\n")
        self.cfg = {
            "schema_version": 1,
            "adapter": {"type": "socketcan", "interface": "can0", "bitrate": 125000},
            "master": {"node_id": 1, "sync_period_us": 100000},
            "nodes": [
                {"node_id": 5, "name": "rtd", "eds": "rtd8.eds",
                 "tx_pdos": [{"number": 1, "transmission": 1, "entries": [
                     {"index": "0x7130", "subindex": 1, "type": "INTEGER16", "iec_location": "%IW100"}]}],
                 "sdo": [{"index": "0x6110", "subindex": k, "type": "UNSIGNED16", "value": 30} for k in (1, 2, 3, 4)],
                 "sdo_variables": [{"name": "filter5", "index": "0x6110", "subindex": 5, "type": "UNSIGNED16",
                                    "direction": "write", "iec_location": "%QW200"}]},
                {"node_id": 7, "name": "io", "eds": "fixed-io.eds",
                 "rx_pdos": [{"number": 1, "entries": [
                     {"index": "0x6200", "subindex": 1, "type": "UNSIGNED8", "iec_location": "%QB100"}]}]},
            ],
        }
        self.config = write_json(os.path.join(self.dir, "canopen.json"), self.cfg)
        self.sim = {
            "schema_version": 1,
            "tick_ms": 10,
            "nodes": {
                "5": {"sources": {
                    "0x7130:1": {"sine": {"min": 200, "max": 260, "period_s": 10}},
                    "0x7130:2": {"expr": "20 + lag(if(bit([7/0x6200:1], 0), 80, 0), 30)"},
                    "0x7130:3": {"csv": {"file": "data/temp.csv", "interpolate": "linear", "loop": True}},
                    "0x1008": {"constant": "RTD-SIM"}},
                    "faults": [{"sdo_abort": {"object": "0x6110:1", "on": "write", "code": "0x08000020",
                                              "count": 1}}]},
                "7": {"sources": {"0x6000:1": {"expr": "[0x6200:1] + [spare/0x4001]"}}},
                "40": {"default_behaviour": False},
            },
            "extra_devices": [
                {"node": 40, "name": "pp", "eds": "eds/pingpong.eds"},
                {"node": 0, "name": "spare", "eds": "eds/lss-slave.eds", "identity": {"serial_number": 1234}},
            ],
            "scenarios": {
                "sensor-break": {"test": True, "steps": [
                    {"node": 5, "set": {"0x7130:1": 900}},
                    {"expect": {"node": 7, "object": "0x6200:1", "bit": 2, "eq": 1}, "within_ms": 500},
                    {"after_ms": 2000, "node": 5, "fault": {"emcy": {"code": "0x5000", "register": 1}}},
                    {"wait": {"expr": "[7/0x6200:1] > 5 && [5/0x7130:1] < 300"}, "timeout_ms": 1000},
                    {"repeat": {"count": 2, "steps": [{"node": "spare", "release": "all"}]}},
                    {"node": 5, "clear": "emcy"}]}},
        }
        self.sim_path = os.path.join(self.dir, "simulation.json")

    def check(self, sim=None, cfg="default"):
        data = copy.deepcopy(sim if sim is not None else self.sim)
        cfg = self.cfg if cfg == "default" else cfg
        write_json(self.sim_path, data)
        return simfile.check(data, self.sim_path, cfg, self.config if cfg else None)


class Checks(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    def errors(self, sim=None, **kw):
        r = self.f.check(sim, **kw)
        return r.errors

    def changed(self, fn):
        sim = copy.deepcopy(self.f.sim)
        fn(sim)
        return sim

    def assertError(self, sim, *words):
        errors = self.errors(sim)
        self.assertTrue(any(all(w in e for w in words) for e in errors), "%s not in %s" % (words, errors))

    def test_valid_file(self):
        r = self.f.check()
        self.assertEqual(r.errors, [])
        self.assertEqual(r.warnings, [])

    def test_several_networks(self):
        # One network in a version 2 file: checked as version 1.
        v2 = {"schema_version": 2, "networks": [dict(self.f.cfg, name="io")]}
        r = self.f.check(cfg=v2)
        self.assertEqual((r.errors, r.warnings), ([], []))
        self.assertTrue(any("node 5" in e for e in self.f.check(self.changed(
            lambda s: s["nodes"]["5"]["sources"].update({"0x6999:1": {"constant": 1}})), cfg=v2).errors))
        # Two networks: the file is not used, and not checked against nodes.
        two = {"schema_version": 2, "networks": [dict(self.f.cfg, name="io"),
                                                  dict(copy.deepcopy(self.f.cfg), name="drives")]}
        r = self.f.check(cfg=two)
        self.assertEqual(r.errors, [])
        self.assertEqual(len(r.warnings), 1)
        self.assertIn("not used: a version 1 simulation file serves a configuration with one network only", r.warnings[0])
        self.assertIn("version 2 has a section per network", r.warnings[0])

    def test_version_2_sections(self):
        # Version 2: each section checked against its own network's nodes.
        two = {"schema_version": 2, "networks": [dict(self.f.cfg, name="io"),
                                                  dict(copy.deepcopy(self.f.cfg), name="drives")]}
        body = {k: v for k, v in self.f.sim.items() if k in ("nodes", "extra_devices", "scenarios")}
        v2 = {"schema_version": 2, "networks": {"io": copy.deepcopy(body), "drives": {}}}
        r = self.f.check(v2, cfg=two)
        self.assertEqual((r.errors, r.warnings), ([], []))
        # A problem names the section.
        bad = copy.deepcopy(v2)
        bad["networks"]["io"]["nodes"]["5"]["sources"]["0x6999:1"] = {"constant": 1}
        errors = self.f.check(bad, cfg=two).errors
        self.assertTrue(any("networks.io.nodes.5.sources.0x6999:1" in e and "node 5" in e for e in errors), errors)
        # A node of another network is not a node of this section's network.
        other = {"schema_version": 2, "networks": {"drives": {"nodes": {"9": {}}}}}
        errors = self.f.check(other, cfg=two).errors
        self.assertTrue(any("networks.drives.nodes.9" in e and "neither a node of the configuration" in e
                            for e in errors), errors)
        # A section for a network that is not in the config.
        errors = self.f.check({"schema_version": 2, "networks": {"drivez": {}}}, cfg=two).errors
        self.assertTrue(any("networks.drivez" in e and "no network 'drivez'" in e and "io, drives" in e
                            for e in errors), errors)
        # Version 1 keys at the top of a version 2 file.
        errors = self.f.check(dict(body, schema_version=2, networks={}), cfg=two).errors
        self.assertTrue(any("unknown field" in e for e in errors), errors)
        # A version 1 config: the section is named after its interface.
        iface = self.f.cfg["adapter"]["interface"]
        r = self.f.check({"schema_version": 2, "networks": {iface: copy.deepcopy(body)}})
        self.assertEqual(r.errors, [])

    def test_version_2_files(self):
        # Extra devices' EDS files and CSV files of every section.
        data = {"schema_version": 2, "networks": {
            "io": {"extra_devices": [{"node": 40, "eds": "a.eds"}]},
            "drives": {"nodes": {"4": {"sources": {"0x6064:0": {"csv": {"file": "d.csv", "column": 1}}}}}}}}
        files = simfile.referenced_files(data, "/p/canopen/simulation.json")
        self.assertEqual(files["eds"], {"a.eds": "/p/canopen/a.eds"})
        self.assertEqual(files["csv"], {"d.csv": "/p/canopen/d.csv"})
        out = simfile.rewrite(data, "/p/canopen/simulation.json", lambda p: "eds/x.eds", lambda p: "csv/y.csv")
        self.assertEqual(out["networks"]["io"]["extra_devices"][0]["eds"], "eds/x.eds")
        self.assertEqual(out["networks"]["drives"]["nodes"]["4"]["sources"]["0x6064:0"]["csv"]["file"], "csv/y.csv")

    def test_check_file_and_load(self):
        write_json(self.f.sim_path, self.f.sim)
        data, r = simfile.check_file(self.f.sim_path, self.f.cfg, self.f.config)
        self.assertTrue(r.ok, r.errors)
        with open(self.f.sim_path, "w") as f:
            f.write("{ not json")
        data, r = simfile.check_file(self.f.sim_path, self.f.cfg, self.f.config)
        self.assertIsNone(data)
        self.assertIn("not valid JSON", r.errors[0])

    def test_schema(self):
        self.assertError(self.changed(lambda s: s.update(colour="red")), "unknown field", "colour")
        self.assertError(self.changed(lambda s: s["nodes"]["5"]["sources"]["0x7130:1"].update(sine={"min": 1})),
                         "nodes.5.sources.0x7130:1")
        errors = self.errors(self.changed(lambda s: s.update(schema_version=3)))
        self.assertEqual(len(errors), 1)
        self.assertIn("schema_version 3 is not supported; the highest supported version is 2", errors[0])

    def test_unknown_node(self):
        self.assertError(self.changed(lambda s: s["nodes"].update({"9": {}})),
                         "nodes.9", "node 9 is neither a node of the configuration nor an extra device")

    def test_objects_not_in_the_eds(self):
        self.assertError(self.changed(lambda s: s["nodes"]["5"]["sources"].update({"0x6999:1": {"constant": 1}})),
                         "node 5 (rtd): object 0x6999:1 is not in rtd8.eds")
        self.assertError(self.changed(lambda s: s["nodes"]["5"]["faults"].append(
            {"sdo_delay": {"ms": 100, "object": "0x6999"}})), "faults[1].sdo_delay.object", "0x6999:0")
        self.assertError(self.changed(lambda s: s["scenarios"]["sensor-break"]["steps"][1]["expect"].update(
            object="0x6201:1")), "steps[1].expect.object", "node 7 (io): object 0x6201:1 is not in fixed-io.eds")
        self.assertError(self.changed(lambda s: s["scenarios"]["sensor-break"]["steps"][0].update(
            set={"0x7130:9": 1})), "steps[0].set", "0x7130:9")
        self.assertError(self.changed(lambda s: s["nodes"]["5"]["faults"].append({"tpdo_stop": 9})),
                         "TPDO 9 does not exist in rtd8.eds")
        # No EMCY producer without 0x1014: the device could not send it.
        self.assertError(self.changed(lambda s: s["nodes"]["40"].update(faults=[{"emcy": {"code": "0x5000"}}])),
                         "nodes.40.faults[0].emcy", "cannot send EMCY", "no object 0x1014")
        self.assertError(self.changed(lambda s: s["scenarios"]["sensor-break"]["steps"].append(
            {"node": 9, "log": "x"})), "steps[6].node", "unknown device 9")

    def test_sources_on_master_written_objects(self):
        def source(node, obj):
            return self.changed(lambda s: s["nodes"].setdefault(node, {}).setdefault("sources", {}).update(
                {obj: {"constant": 1}}))
        self.assertError(source("7", "0x6200:1"), "node 7 (io): object 0x6200:1 is written by the master (RPDO 1)")
        # In the device's default mapping, which the config keeps.
        self.assertError(source("7", "0x6200:2"), "0x6200:2 is written by the master (RPDO 1)")
        self.assertError(source("5", "0x6110:2"), "0x6110:2 is written by the master (startup SDO)")
        self.assertError(source("5", "0x6110:5"), "written by the master (SDO variable 0x6110:5 (filter5))")
        # In a scenario too.
        self.assertError(self.changed(lambda s: s["scenarios"]["sensor-break"]["steps"].append(
            {"node": 7, "source": {"0x6200:1": {"constant": 1}}})), "steps[6].source.0x6200:1", "RPDO 1")
        # An override is allowed, with a warning.
        r = self.f.check(self.changed(lambda s: s["scenarios"]["sensor-break"]["steps"].append(
            {"node": 7, "override": {"0x6200:1": 1}})))
        self.assertEqual(r.errors, [])
        self.assertIn("the override makes the device ignore it", r.warnings[0])

    def test_expressions(self):
        self.assertError(self.changed(lambda s: s["nodes"]["5"]["sources"].update(
            {"0x7130:4": {"expr": "[9/0x6200:1] + 1"}})), "nodes.5.sources.0x7130:4.expr", "position 0",
            "unknown device 9")
        self.assertError(self.changed(lambda s: s["nodes"]["5"]["sources"].update(
            {"0x7130:4": {"expr": "1 + [7/0x6999:1]"}})), "position 4", "node 7 (io): object 0x6999:1")
        self.assertError(self.changed(lambda s: s["nodes"]["5"]["sources"].update(
            {"0x7130:4": {"expr": "[nobody/0x6200:1]"}})), "unknown device 'nobody'")
        self.assertError(self.changed(lambda s: s["scenarios"]["sensor-break"]["steps"][3]["wait"].update(
            expr="[0x6200:1] > 1")), "steps[3].wait.expr", "names no device")
        self.assertError(self.changed(lambda s: s["nodes"]["5"]["sources"].update(
            {"0x7130:4": {"expr": "delay(1, 601)"}})), "600")

    def test_cycles(self):
        def exprs(**by_obj):
            return self.changed(lambda s: s["nodes"]["5"]["sources"].update(
                {k.replace("_", ":").replace("x", "0x", 1): {"expr": v} for k, v in by_obj.items()}))
        self.assertError(exprs(x7130_4="[0x7130:5] + 1", x7130_5="[5/0x7130:4] * 2"),
                         "reference cycle node 5 (rtd) 0x7130:4 -> node 5 (rtd) 0x7130:5 -> node 5 (rtd) 0x7130:4")
        self.assertError(exprs(x7130_4="[0x7130:4] + 1"), "position 0: reference cycle")
        # Through another device.
        sim = exprs(x7130_4="[7/0x6000:1]")
        sim["nodes"]["7"]["sources"]["0x6000:1"] = {"expr": "[5/0x7130:4]"}
        self.assertError(sim, "reference cycle")
        for ok in (dict(x7130_4="lag([0x7130:5], 1)", x7130_5="[0x7130:4]"),
                   dict(x7130_4="[0x7130:5]", x7130_5="integrate([0x7130:4] - 1)"),
                   dict(x7130_4="prev + 1"), dict(x7130_4="delay([0x7130:4], 1)")):
            self.assertEqual(self.errors(exprs(**ok)), [], ok)

    def test_value_types(self):
        self.assertError(self.changed(lambda s: s["nodes"]["5"]["sources"].update(
            {"0x1008": {"sine": {"min": 1, "max": 2, "period_s": 1}}})), "VISIBLE_STRING, which takes only a constant")
        self.assertError(self.changed(lambda s: s["nodes"]["5"]["sources"].update(
            {"0x7130:4": {"constant": "hot"}})), "not a VISIBLE_STRING")

    def test_files(self):
        os.remove(os.path.join(self.f.dir, "data", "temp.csv"))
        self.assertError(None, "nodes.5.sources.0x7130:3.csv.file", "CSV file", "not found")
        os.remove(os.path.join(self.f.dir, "eds", "lss-slave.eds"))
        self.assertError(None, "extra_devices[1]", "extra device spare: EDS file", "not found")

    def test_extra_devices(self):
        self.assertError(self.changed(lambda s: s["extra_devices"].append({"node": 0, "eds": "eds/pingpong.eds"})),
                         "extra_devices[2]", "name")
        self.assertError(self.changed(lambda s: s["extra_devices"].append(
            {"node": 41, "name": "spare", "eds": "eds/pingpong.eds"})), "the name 'spare' is already used")
        self.assertError(self.changed(lambda s: s["extra_devices"].append({"node": 5, "eds": "eds/pingpong.eds"})),
                         "node ID 5 is a node of the configuration")
        self.assertError(self.changed(lambda s: s["extra_devices"].append({"node": 1, "eds": "eds/pingpong.eds"})),
                         "node ID 1 is the master's node ID")
        self.assertError(self.changed(lambda s: s["extra_devices"].append({"node": 40, "eds": "eds/pingpong.eds"})),
                         "node ID 40 is already used by another extra device")

    def test_without_a_config(self):
        sim = {"extra_devices": [{"node": 4, "eds": "eds/pingpong.eds", "sources": {"0x4001": {"counter": {}}}}],
               "nodes": {"4": {"default_behaviour": False}}}
        self.assertEqual(self.errors(sim, cfg=None), [])
        sim["nodes"]["6"] = {}
        self.assertError(sim, "node 6 is neither")
        self.assertIn("node 6 is not an extra device of this file", self.errors(sim, cfg=None)[0])

    def test_referenced_files_and_rewrite(self):
        files = simfile.referenced_files(self.f.sim, self.f.sim_path)
        self.assertEqual(sorted(files["eds"]), ["eds/lss-slave.eds", "eds/pingpong.eds"])
        self.assertEqual(files["csv"], {"data/temp.csv": os.path.join(self.f.dir, "data/temp.csv")})
        out = simfile.rewrite(self.f.sim, self.f.sim_path, lambda p: "E/" + os.path.basename(p),
                              lambda p: "C/" + os.path.basename(p))
        self.assertEqual([d["eds"] for d in out["extra_devices"]], ["E/pingpong.eds", "E/lss-slave.eds"])
        self.assertEqual(out["nodes"]["5"]["sources"]["0x7130:3"]["csv"]["file"], "C/temp.csv")
        self.assertEqual(self.f.sim["extra_devices"][0]["eds"], "eds/pingpong.eds")  # the original is unchanged


class Simulated(unittest.TestCase):
    def cfg(self, network=False, nodes=((5, None), (7, None))):
        return {"adapter": {"type": "socketcan", "interface": "can0", "bitrate": 125000, "simulate": network},
                "nodes": [dict({"node_id": n}, **({"simulate": s} if s is not None else {})) for n, s in nodes]}

    def test_describe(self):
        self.assertIsNone(simfile.describe_simulated(self.cfg()))
        self.assertEqual(simfile.simulated(self.cfg(True)), (True, [5, 7]))
        self.assertEqual(simfile.describe_simulated(self.cfg(True)),
                         "the network is simulated; no CAN interface is used")
        self.assertEqual(simfile.describe_simulated(self.cfg(True, ((5, None), (7, False)))),
                         "the network is simulated; no CAN interface is used; node 5 is simulated, node 7 stays absent")
        self.assertEqual(simfile.describe_simulated(self.cfg(False, ((5, True), (7, True), (9, None)))),
                         "nodes 5, 7 are simulated devices on the real network can0")
        self.assertEqual(simfile.describe_simulated(self.cfg(False, ((5, True), (7, False)))),
                         "node 5 is a simulated device on the real network can0")

    def test_describe_shared_simulated_bus(self):
        # The plugin's own slave on the master's simulated bus serves node 10.
        master = dict(self.cfg(True, ((10, False), (5, None))), name="plc")
        master["adapter"]["interface"] = "sim0"
        slave = {"name": "line", "role": "slave",
                 "adapter": {"type": "socketcan", "interface": "sim0", "bitrate": 125000, "simulate": True},
                 "slave": {"node_id": 10, "eds": "openplc-slave.eds"}}
        cfg = {"schema_version": 2, "networks": [master, slave]}
        self.assertEqual(simfile.describe_simulated(cfg),
                         "network plc: the network is simulated; no CAN interface is used; node 10 is slave network "
                         "line on the same simulated bus; network line: the slave runs on simulated bus sim0")
        master["nodes"] = [{"node_id": 10, "simulate": False}]
        self.assertEqual(simfile.describe_simulated(cfg),
                         "network plc: the network is simulated; no CAN interface is used; node 10 is slave network "
                         "line on the same simulated bus; network line: the slave runs on simulated bus sim0")

    def test_describe_several_networks(self):
        two = {"schema_version": 2, "networks": [dict(self.cfg(), name="io"), dict(self.cfg(True), name="test")]}
        self.assertEqual(simfile.describe_simulated(two),
                         "network test: the network is simulated; no CAN interface is used")
        self.assertIsNone(simfile.describe_simulated({"schema_version": 2, "networks": [self.cfg(), self.cfg()]}))


if __name__ == "__main__":
    unittest.main()
