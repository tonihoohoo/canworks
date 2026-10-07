"""OpenPLC as a CANopen slave and gateway in the deploy tool (openspec change
add-canopen-slave, tasks 1.3, 3.1-3.3 and 6.7): the slave EDS generator and
its command, the contract checks of slave networks and the gateway, the
bundle and the declarations, on config/slave and config/gateway."""

import copy
import json
import os
import shutil
import unittest

import jsonschema

from openplc_canopen_deploy import bundle, cli, contract, edslint, editorproject, project, slaveeds
from openplc_canopen_deploy.configurator import declare, layout
from openplc_canopen_deploy.eds import Eds

from .helpers import REPO, editor_bundle, tmpdir, zip_contents
from .test_deploy import deploy

SLAVE = os.path.join(REPO, "config", "slave")
GATEWAY = os.path.join(REPO, "config", "gateway")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def obj(name, type_name, direction, **more):
    return dict(name=name, type=type_name, direction=direction, **more)


def generate(test, desc, gateway=None):
    """Generates, checks the lint verdict with eds_lint "all", and reads it back."""
    text, info = slaveeds.generate(desc, gateway)
    _, corrections, lint = edslint.check(text.encode("utf-8"))
    test.assertEqual(corrections, [], "the plugin would read a corrected copy, not the file itself")
    test.assertIsNone(lint.read_error)
    test.assertEqual([f.message for f in lint.failing("all")], [])
    path = os.path.join(tmpdir(test), "slave.eds")
    slaveeds.write(text, path)
    return Eds.read(path), info, text


def mapping(eds, index):
    count = eds.find(index, 0).value(0)
    return [eds.find(index, k).value(0) for k in range(1, count + 1)]


class Generator(unittest.TestCase):
    def test_manufacturer_layout(self):
        eds, info, _ = generate(self, {"objects": [
            obj("speed", "UNSIGNED16", "from_master", default=5, low=0, high=3000), obj("mode", "UNSIGNED8", "from_master"),
            obj("limit", "UNSIGNED16", "from_master"), obj("actual", "UNSIGNED16", "to_master"),
            obj("temp", "REAL32", "to_master", default=21.5)]})
        self.assertEqual([(o["name"], o["index"], o["subindex"]) for o in info["objects"]],
                         [("speed", 0x2000, 1), ("mode", 0x2001, 1), ("limit", 0x2000, 2), ("actual", 0x2100, 1),
                          ("temp", 0x2101, 1)])
        speed = eds.find(0x2000, 1)
        self.assertEqual((speed.access, speed.pdo_mapping, speed.name, speed.default, speed.low_limit,
                          speed.high_limit), ("rww", True, "speed", "5", "0", "3000"))
        self.assertEqual(eds.find(0x2000, 0).value(0), 2)
        self.assertEqual(eds.names[0x2000], "UNSIGNED16 from master")
        self.assertEqual(eds.names[0x2101], "REAL32 to master")
        self.assertEqual((eds.find(0x2100, 1).access, eds.find(0x2100, 1).pdo_mapping), ("ro", True))
        self.assertEqual(eds.find(0x2101, 1).default, "0x41AC0000")  # 21.5 as Lely's bit pattern
        self.assertEqual(eds.find(0x1000, 0).value(0), 0)
        self.assertEqual(eds.find(0x1017, 0).value(0), 1000)
        self.assertEqual(eds.find(0x1018, 1).value(0), 0)  # vendor ID defaults to 0
        # The communication objects a CiA 301 slave with store, restore, configuration check and LSS needs.
        for index in (0x1001, 0x1003, 0x1005, 0x1008, 0x1010, 0x1011, 0x1014, 0x1015, 0x1016, 0x1020, 0x1029, 0x1200):
            self.assertTrue(eds.has(index), hex(index))
        self.assertEqual(eds.find(0x1014, 0).value(10), 0x8A)
        self.assertEqual(eds.find(0x1200, 1).value(10), 0x60A)

    def test_default_pdos(self):
        # Five UNSIGNED16 to the master: TPDO 1 maps four, TPDO 2 the fifth.
        eds, info, _ = generate(self, {"objects": [obj("v%d" % k, "UNSIGNED16", "to_master") for k in range(5)]
                                       + [obj("in", "INTEGER32", "from_master")]})
        self.assertEqual(mapping(eds, 0x1A00), [0x21000110, 0x21000210, 0x21000310, 0x21000410])
        self.assertEqual(mapping(eds, 0x1A01), [0x21000510])
        self.assertEqual(mapping(eds, 0x1600), [0x20000120])
        self.assertEqual(info["pdos"], {"rx": 1, "tx": 2})
        self.assertEqual(eds.find(0x1800, 1).value(10), 0x18A)
        self.assertEqual(eds.find(0x1801, 1).value(10), 0x28A)
        self.assertEqual(eds.find(0x1400, 1).value(10), 0x20A)
        for comm in (0x1400, 0x1800, 0x1801):
            self.assertEqual(eds.find(comm, 2).value(10), 255)
        # Unused PDOs of the predefined set are there to remap, switched off.
        self.assertEqual(eds.pdo_count("input"), 4)
        self.assertTrue(eds.find(0x1802, 1).value(10) & 0x80000000)
        self.assertEqual(mapping(eds, 0x1A02), [])
        # The master may remap: mapping and communication parameters are writable.
        for index, sub in ((0x1A00, 0), (0x1A00, 1), (0x1600, 0), (0x1800, 1), (0x1800, 2), (0x1400, 1)):
            self.assertTrue(eds.find(index, sub).writable, "0x%04X:%d" % (index, sub))

    def test_more_than_four_pdos(self):
        eds, info, _ = generate(self, {"objects": [obj("v%d" % k, "UNSIGNED32", "to_master") for k in range(11)]})
        self.assertEqual(info["pdos"]["tx"], 6)
        self.assertEqual(eds.find(0x1805, 1).value(10), 0x80000000)  # no CiA 301 default above PDO 4
        self.assertEqual(mapping(eds, 0x1A05), [0x21000B20])

    def test_booleans_pack_by_bit(self):
        eds, _, text = generate(self, {"objects": [obj("b%d" % k, "BOOLEAN", "from_master") for k in range(12)]})
        self.assertEqual(len(mapping(eds, 0x1600)), 12)
        self.assertIn("Granularity=1", text)

    def test_cia401_layout(self):
        eds, info, _ = generate(self, {"layout": "cia401", "objects": [
            obj("di", "UNSIGNED8", "to_master"), obj("ai", "INTEGER16", "to_master"),
            obj("do", "UNSIGNED8", "from_master"), obj("ao", "INTEGER16", "from_master"), obj("di2", "UNSIGNED8", "to_master")]})
        self.assertEqual([(o["index"], o["subindex"]) for o in info["objects"]],
                         [(0x6000, 1), (0x6401, 1), (0x6200, 1), (0x6411, 1), (0x6000, 2)])
        self.assertEqual(eds.find(0x1000, 0).value(0), 0x000F0191)
        self.assertEqual((eds.find(0x6200, 1).access, eds.find(0x6000, 1).access), ("rww", "ro"))
        eds, _, _ = generate(self, {"layout": "cia401", "objects": [obj("di", "UNSIGNED8", "to_master")]})
        self.assertEqual(eds.find(0x1000, 0).value(0), 0x00010191)

    def test_cia401_refuses_other_types(self):
        with self.assertRaisesRegex(slaveeds.DescriptionError, "object 'flow' .*layout cia401 .*\"REAL\""):
            slaveeds.generate({"layout": "cia401", "objects": [obj("flow", "REAL", "to_master")]})

    def test_unsupported_type_names_object_and_types(self):
        with self.assertRaisesRegex(slaveeds.DescriptionError,
                                    "object 'label' .*type \"STRING\" is not supported \\(supported: BOOLEAN, .*REAL64"):
            slaveeds.generate({"objects": [obj("label", "STRING", "to_master")]})

    def test_description_errors(self):
        for objects, pattern in (
                ([{"name": "x", "direction": "to_master"}], "object 'x' \\(objects\\[0\\]\\) has no 'type'"),
                ([{"type": "UNSIGNED8", "direction": "to_master"}], "objects\\[0\\] has no 'name'"),
                ([obj("x", "UNSIGNED8", "up")], "'direction' must be from_master"),
                ([obj("x", "UNSIGNED8", "to_master"), obj("X", "UNSIGNED8", "to_master")], "also used by objects\\[0\\]"),
                ([obj("x", "UNSIGNED8", "to_master", default=300)], "'default' 300 does not fit UNSIGNED8"),
                ([obj("x", "UNSIGNED8", "to_master", low=5, high=1)], "'low' is above 'high'"),
                ([obj("x", "INTEGER8", "to_master", default=-9, low=-5)], "'default' is outside"),
                ([obj("x", "REAL32", "to_master", default="a")], "must be a number")):
            with self.subTest(pattern), self.assertRaisesRegex(slaveeds.DescriptionError, pattern):
                slaveeds.generate({"objects": objects})
        with self.assertRaisesRegex(slaveeds.DescriptionError, "layout \"x\" is not supported"):
            slaveeds.generate({"layout": "x"})
        with self.assertRaisesRegex(slaveeds.DescriptionError, "'heartbeat_ms' must be 0-65535"):
            slaveeds.generate({"heartbeat_ms": 70000})

    def test_identity_tracks_the_content(self):
        desc = {"objects": [obj("a", "UNSIGNED8", "to_master")]}
        _, first, text = generate(self, desc)
        _, again, text2 = generate(self, copy.deepcopy(desc))
        self.assertEqual((first["revision_number"], text), (again["revision_number"], text2))  # deterministic
        desc["objects"].append(obj("b", "UNSIGNED8", "to_master"))
        _, more, _ = generate(self, desc)
        self.assertNotEqual(more["revision_number"], first["revision_number"])
        eds, fixed, _ = generate(self, dict(desc, revision_number=7, vendor_id="0x1234", product_code=3))
        self.assertEqual((fixed["revision_number"], eds.find(0x1018, 3).value(0), eds.find(0x1018, 1).value(0),
                          eds.find(0x1018, 2).value(0)), (7, 7, 0x1234, 3))

    def test_every_type_lints(self):
        objects = []
        for t in ("BOOLEAN", "INTEGER8", "INTEGER16", "INTEGER32", "INTEGER64", "UNSIGNED8", "UNSIGNED16",
                  "UNSIGNED32", "UNSIGNED64", "REAL32", "REAL64"):
            hi = True if t == "BOOLEAN" else 1.5 if t.startswith("REAL") else 100
            for d in ("from_master", "to_master"):
                objects.append(obj("%s_%s" % (t, d), t, d, low=0, high=hi))
        eds, info, _ = generate(self, {"device_name": "Test slave", "heartbeat_ms": 0, "objects": objects})
        self.assertEqual(len(info["objects"]), 22)
        self.assertEqual(eds.find(0x1017, 0).value(0), 0)

    def test_example_is_the_generated_file(self):
        # config/slave/openplc-slave.eds is what the generator writes from slave_eds.json.
        text, _ = slaveeds.generate(load(os.path.join(SLAVE, "slave_eds.json")), file_name="openplc-slave.eds")
        with open(os.path.join(SLAVE, "openplc-slave.eds"), encoding="utf-8", newline="") as f:
            self.assertEqual(f.read(), text)
        text, _ = slaveeds.generate(load(os.path.join(GATEWAY, "gateway_eds.json")),
                                    load(os.path.join(GATEWAY, "canopen_config.json")), "openplc-gateway.eds")
        with open(os.path.join(GATEWAY, "openplc-gateway.eds"), encoding="utf-8", newline="") as f:
            self.assertEqual(f.read(), text)


class GatewayObjects(unittest.TestCase):
    def config(self):
        return load(os.path.join(GATEWAY, "canopen_config.json"))

    def test_routes_status_and_bridge(self):
        eds, info, _ = generate(self, {"objects": [obj("own", "UNSIGNED8", "to_master")]}, self.config())
        self.assertEqual(info["routes"], [{"index": 0x2101, "subindex": 1}, {"index": 0x2000, "subindex": 1}])
        pong, ping = eds.find(0x2101, 1), eds.find(0x2000, 1)
        self.assertEqual((pong.name, pong.access, pong.type_name), ("pong", "ro", "UNSIGNED32"))
        self.assertEqual((ping.name, ping.access, ping.type_name), ("ping", "rww", "UNSIGNED32"))
        # Node states of field network "field" and its operational bits.
        self.assertEqual(eds.find(0x5E00, 0).value(0), 127)
        self.assertEqual((eds.find(0x5E00, 5).access, eds.find(0x5E00, 5).type_name), ("ro", "UNSIGNED8"))
        self.assertEqual([eds.find(0x5E10, k).type_name for k in range(1, 5)], ["UNSIGNED32"] * 4)
        # The default PDOs carry the routed values and the status bits.
        self.assertIn(0x20000120, mapping(eds, 0x1600))
        tx = [v for n in range(eds.pdo_count("input")) for v in mapping(eds, 0x1A00 + n)]
        self.assertIn(0x21010120, tx)
        self.assertTrue(all((0x5E10 << 16) | (k << 8) | 32 in tx for k in range(1, 5)))
        # The SDO bridge record.
        self.assertEqual(eds.find(0x5F00, 0).value(0), 9)
        self.assertEqual([(eds.find(0x5F00, k).access, eds.find(0x5F00, k).pdo_mapping) for k in (1, 5, 7, 8, 9)],
                         [("rw", False), ("rw", True), ("rw", False), ("ro", True), ("ro", False)])

    def test_three_up_two_down(self):
        cfg = self.config()
        node = cfg["networks"][0]["nodes"][0]
        node["tx_pdos"][0]["entries"] = [{"index": "0x4001", "subindex": 0, "type": "UNSIGNED32"}] * 1
        cfg["gateway"]["routes"] = [{"slave": {"index": 0}, "field": {"network": "field", "node": 2, "index": "0x4001"}}
                                    for _ in range(3)] + \
            [{"slave": {"index": 0}, "field": {"network": "field", "node": 2, "index": "0x4000"}} for _ in range(2)]
        del cfg["gateway"]["status"]
        cfg["gateway"]["sdo_bridge"] = False
        eds, info, _ = generate(self, {}, cfg)
        access = [eds.find(r["index"], r["subindex"]).access for r in info["routes"]]
        self.assertEqual(sorted(access), ["ro", "ro", "ro", "rww", "rww"])
        self.assertEqual([o["name"] for o in info["objects"]], ["route1", "route2", "route3", "route4", "route5"])
        self.assertFalse(eds.has(0x5F00) or eds.has(0x5E00))

    def test_route_without_a_field_entry(self):
        cfg = self.config()
        cfg["gateway"]["routes"][0]["field"]["index"] = "0x4002"
        with self.assertRaisesRegex(slaveeds.DescriptionError, "routes\\[0\\]: network field node 2 0x4002:0 is not"):
            slaveeds.generate({}, cfg)

    def test_route_name_taken(self):
        with self.assertRaisesRegex(slaveeds.DescriptionError, "routes\\[0\\]: object 'pong' \\(route\\): the name is "
                                                               "also used by an object of the description"):
            slaveeds.generate({"objects": [obj("pong", "UNSIGNED8", "to_master")]}, self.config())

    def test_cia401_with_routes(self):
        eds, info, _ = generate(self, {"layout": "cia401", "objects": [obj("di", "UNSIGNED8", "to_master")]},
                                self.config())
        self.assertEqual(info["routes"], [{"index": 0x2100, "subindex": 1}, {"index": 0x2000, "subindex": 1}])
        self.assertEqual(eds.find(0x6000, 1).name, "di")


class Command(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)

    def write(self, name, doc):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        return path

    def test_writes_the_eds(self):
        desc = self.write("slave.json", {"objects": [obj("a", "UNSIGNED16", "from_master"),
                                                     obj("b", "UNSIGNED16", "from_master"),
                                                     obj("c", "INTEGER16", "to_master"),
                                                     obj("d", "INTEGER16", "to_master")]})
        out = os.path.join(self.dir, "slave.eds")
        code, stdout, err = deploy("slave-eds", desc, "-o", out)
        self.assertEqual(code, 0, err)
        self.assertIn("wrote %s: 2 objects from the master, 2 to the master" % out, stdout)
        self.assertIn("0x2000:2 UNSIGNED16 rww (PLC input) b", stdout)
        with open(out, "rb") as f:
            _, _, lint = edslint.check(f.read())
        self.assertEqual(lint.findings, [])

    def test_invalid_description(self):
        desc = self.write("slave.json", {"objects": [{"name": "speed", "direction": "to_master"}]})
        out = os.path.join(self.dir, "slave.eds")
        code, _, err = deploy("slave-eds", desc, "-o", out)
        self.assertEqual(code, 1)
        self.assertIn("error: %s: object 'speed' (objects[0]) has no 'type'" % desc, err)
        self.assertFalse(os.path.exists(out))
        code, _, err = deploy("slave-eds", os.path.join(self.dir, "missing.json"), "-o", out)
        self.assertEqual(code, 1)
        self.assertIn("cannot read description", err)
        code, _, err = deploy("slave-eds", desc, "-o", out, "--update-config")
        self.assertEqual((code, err.strip()), (1, "error: --update-config needs --gateway"))

    def test_gateway_update_config(self):
        cfg = load(os.path.join(GATEWAY, "canopen_config.json"))
        for rt in cfg["gateway"]["routes"]:
            rt["slave"] = {"index": "0x2FFF"}
        config = self.write("canopen.json", cfg)
        desc = self.write("gw.json", {})
        out = os.path.join(self.dir, "gw.eds")
        code, stdout, err = deploy("slave-eds", desc, "-o", out, "--gateway", config)
        self.assertEqual(code, 0, err)
        self.assertIn("note: 2 routes of %s name another slave object" % config, stdout)
        self.assertEqual(load(config)["gateway"]["routes"][0]["slave"], {"index": "0x2FFF"})
        code, stdout, err = deploy("slave-eds", desc, "-o", out, "--gateway", config, "--update-config")
        self.assertEqual(code, 0, err)
        self.assertIn("updated %s: 2 routes with a new slave object" % config, stdout)
        self.assertEqual([rt["slave"] for rt in load(config)["gateway"]["routes"]],
                         [{"index": "0x2100", "subindex": 1}, {"index": "0x2000", "subindex": 1}])


class SlaveContract(unittest.TestCase):
    """The plugin's checks of a slave network and a gateway, on the PC."""

    def setUp(self):
        self.dir = tmpdir(self)
        for name in ("openplc-slave.eds",):
            shutil.copy(os.path.join(SLAVE, name), self.dir)
        for name in ("openplc-gateway.eds", "cpp-slave.eds"):
            shutil.copy(os.path.join(GATEWAY, name), self.dir)
        self.path = os.path.join(self.dir, "canopen.json")

    def slave(self):
        return load(os.path.join(SLAVE, "canopen_config.json"))

    def gateway(self):
        return load(os.path.join(GATEWAY, "canopen_config.json"))

    def check(self, cfg):
        return contract.check_config(cfg, self.path)

    def errors(self, cfg):
        return "\n".join(self.check(cfg).errors)

    def test_examples_validate(self):
        for cfg in (self.slave(), self.gateway()):
            self.assertEqual(list(jsonschema.Draft202012Validator(contract.schema(2)).iter_errors(cfg)), [])
            r = self.check(cfg)
            self.assertEqual((r.errors, r.warnings), ([], []))

    def test_networks_reports_the_role(self):
        nets = contract.networks(self.gateway())
        self.assertEqual([(n["name"], n["role"], len(n["nodes"]), n["slave"].get("node_id")) for n in nets],
                         [("field", "master", 1, None), ("upper", "slave", 0, 20)])
        self.assertEqual([n.get("eds") for n in contract.eds_users(self.gateway())],
                         ["cpp-slave.eds", "openplc-gateway.eds"])
        one = contract.network_config(self.gateway(), "upper")
        self.assertEqual((one["master"], one["nodes"]), ({}, []))

    def test_output_bound_to_a_master_written_object(self):
        cfg = self.slave()
        cfg["networks"][0]["slave"]["objects"][0]["iec_location"] = "%QW310"
        self.assertIn("networks[0]: slave: objects[0]: the master writes 0x2000:1 (AccessType rww), so it needs an "
                      "%I location, not %QW310", self.errors(cfg))
        r = self.check(cfg)
        self.assertEqual(r.items[0]["paths"], ["networks[0].slave.objects[0].iec_location"])

    def test_input_bound_to_a_master_read_object(self):
        cfg = self.slave()
        cfg["networks"][0]["slave"]["objects"][3]["iec_location"] = "%IW310"
        self.assertIn("the master reads 0x2100:1 (AccessType ro), so it needs a %Q location, not %IW310",
                      self.errors(cfg))

    def test_binding_checks(self):
        cfg = self.slave()
        objects = cfg["networks"][0]["slave"]["objects"]
        objects[1]["iec_location"] = "%IW305"
        objects.append({"index": "0x2005", "subindex": 1, "iec_location": "%IW330"})
        objects.append({"index": "0x2001", "subindex": 1, "iec_location": "%IB331"})
        objects.append({"index": "0x1008", "subindex": 0, "iec_location": "%QD331"})
        objects.append({"index": "0x1018", "subindex": 0, "iec_location": "%QB331"})
        text = self.errors(cfg)
        self.assertIn("slave object 0x2001:1: type UNSIGNED8 (8 bit) does not fit location %IW305 (16 bit)", text)
        self.assertIn("slave object 0x2005:1 is not defined in openplc-slave.eds", text)
        self.assertIn("slave object 0x2001:1 is bound twice (objects[1] and objects[7])", text)
        self.assertIn("slave object 0x1008:0 has AccessType const in openplc-slave.eds and cannot be bound", text)
        self.assertNotIn("0x1018:0", text)  # sub-index 0 of a record is ro and an UNSIGNED8: allowed

    def test_rw_object_suggests_rwr(self):
        cfg = self.slave()
        cfg["networks"][0]["slave"]["objects"] = [{"index": "0x1017", "subindex": 0, "iec_location": "%QW310"}]
        self.assertIn("so it needs an %I location, not %QW310; an object the PLC writes needs AccessType ro or rwr",
                      self.errors(cfg))

    def test_node_id_and_eds(self):
        cfg = self.slave()
        cfg["networks"][0]["slave"]["node_id"] = None
        self.assertTrue(self.check(cfg).ok)
        cfg["networks"][0]["slave"]["node_id"] = "200"
        self.assertIn("slave: field 'node_id' must be 1-127, or null for LSS: 200", self.errors(cfg))
        cfg = self.slave()
        cfg["networks"][0]["slave"]["eds"] = "missing.eds"
        self.assertIn("networks[0]: slave: EDS file %s not found" % os.path.join(self.dir, "missing.eds"),
                      self.errors(cfg))

    def test_slave_eds_lint(self):
        with open(os.path.join(self.dir, "openplc-slave.eds"), encoding="utf-8", newline="") as f:
            text = f.read()
        with open(os.path.join(self.dir, "odd.eds"), "w", encoding="utf-8", newline="") as f:
            f.write(text.replace("[1A00sub0]\r\nParameterName=Number of mapped objects\r\nObjectType=0x7\r\n"
                                 "DataType=0x0005\r\n",
                                 "[1A00sub0]\r\nParameterName=Number of mapped objects\r\nObjectType=0x7\r\n"
                                 "DataType=0x0007\r\n"))
        cfg = self.slave()
        cfg["networks"][0]["slave"]["eds"] = "odd.eds"
        self.assertIn("slave: EDS odd.eds fails dcfgen's lint (eds_lint \"communication\"): 0x1A00 sub 0: DataType "
                      "should be UNSIGNED8", self.errors(cfg))
        cfg["networks"][0]["slave"]["eds_lint"] = "off"
        r = self.check(cfg)
        self.assertTrue(r.ok, r.errors)
        self.assertIn("slave: EDS odd.eds: 1 lint finding accepted", "\n".join(r.warnings))

    def test_misplaced_keys(self):
        cfg = self.slave()
        cfg["networks"][0]["nodes"] = []
        text = self.errors(cfg)
        self.assertIn("networks[0]: field 'nodes' belongs to a master network; a slave network (\"role\": \"slave\") "
                      "has 'slave' instead", text)
        self.assertNotIn("lists no slave nodes", text)
        cfg = self.gateway()
        cfg["networks"][0]["slave"] = {"node_id": 3, "eds": "x.eds"}
        self.assertIn("networks[0]: field 'slave' belongs to a slave network: give the network \"role\": \"slave\"",
                      self.errors(cfg))
        cfg = self.slave()
        del cfg["networks"][0]["slave"]
        self.assertIn("networks[0]: 'slave' is a required property", self.errors(cfg))

    def test_version_1_refuses_slave_and_gateway(self):
        cfg = {"adapter": {"type": "socketcan", "interface": "can0", "bitrate": 125000}, "master": {"node_id": 1},
               "nodes": [{"node_id": 2, "eds": "cpp-slave.eds"}], "slave": {"node_id": 3, "eds": "x.eds"},
               "gateway": {"upper": "x"}}
        r = self.check(cfg)
        self.assertIn("field 'slave' needs schema_version 2: slave networks are entries of 'networks' with "
                      "\"role\": \"slave\"", "\n".join(r.errors))
        self.assertIn("field 'gateway' needs schema_version 2", "\n".join(r.errors))
        self.assertFalse(any("unknown field" in w for w in r.warnings))
        self.assertFalse(jsonschema.Draft202012Validator(contract.schema(2)).is_valid(cfg))

    def test_only_a_slave(self):
        cfg = self.slave()
        self.assertEqual(contract.version_of(cfg), 2)
        self.assertEqual(len(contract.networks(cfg)), 1)

    def test_master_and_slave_on_one_interface(self):
        cfg = self.gateway()
        cfg["networks"][1]["adapter"]["interface"] = "vcan0"
        self.assertIn("networks[0] (field) and networks[1] (upper) both use interface vcan0", self.errors(cfg))

    def test_simulated_bus(self):
        cfg = self.gateway()
        for net in cfg["networks"]:
            net["adapter"]["interface"] = "bench"
            net["adapter"]["simulate"] = True
        r = self.check(cfg)
        self.assertFalse([e for e in r.errors if "bench" in e], r.errors)
        two = copy.deepcopy(cfg["networks"][0])
        two["name"] = "field2"
        cfg["networks"].append(two)
        self.assertIn("networks[0] (field) and networks[2] (field2) are both master networks on simulated bus bench",
                      self.errors(cfg))

    def test_locations_overlap_across_networks(self):
        cfg = self.gateway()
        cfg["networks"][1]["slave"]["comm_ok_location"] = "%IX10.0"
        self.assertIn("networks[0] (field) node 2 (pingpong) status_location and networks[1] (upper) slave "
                      "comm_ok_location both map to %IX10.0", self.errors(cfg))

    def test_gateway_upper_must_be_a_slave(self):
        cfg = self.gateway()
        cfg["gateway"]["upper"] = "field"
        self.assertIn("gateway: the upper network 'field' must be a slave network", self.errors(cfg))
        cfg["gateway"]["upper"] = "nowhere"
        self.assertIn("gateway: upper network 'nowhere' is not in the config (networks: field, upper)", self.errors(cfg))

    def test_gateway_needs_a_master_network(self):
        cfg = self.slave()
        cfg["gateway"] = {"upper": "line"}
        self.assertIn("gateway: a gateway needs at least one master network", self.errors(cfg))

    def test_route_wrong_direction(self):
        cfg = self.gateway()
        cfg["gateway"]["routes"][1]["slave"] = {"index": "0x2101", "subindex": 1}
        self.assertIn("gateway: routes[1]: the upper master cannot write slave object 0x2101:1 (AccessType ro), so it "
                      "cannot feed the RPDO entry network field node 2 0x4000:0", self.errors(cfg))
        cfg = self.gateway()
        cfg["gateway"]["routes"][0]["slave"] = {"index": "0x2000", "subindex": 1}
        self.assertIn("the upper master writes slave object 0x2000:1 (AccessType rww), so the TPDO entry network "
                      "field node 2 0x4001:0 cannot write it", self.errors(cfg))

    def test_route_type_mismatch(self):
        cfg = self.gateway()
        cfg["gateway"]["routes"][0]["slave"] = {"index": "0x2100", "subindex": 1}
        r = self.check(cfg)
        self.assertIn("gateway: routes[0]: network field node 2 0x4001:0 (UNSIGNED32) and slave object 0x2100:1 "
                      "(BOOLEAN) need the same data type", "\n".join(r.errors))

    def test_route_two_writers(self):
        cfg = self.gateway()
        cfg["networks"][0]["nodes"][0]["rx_pdos"][0]["entries"][0]["iec_location"] = "%QD100"
        r = self.check(cfg)
        self.assertIn("gateway: routes[1]: the RPDO entry network field node 2 0x4000:0 is written by routes[1] and "
                      "by %QD100", "\n".join(r.errors))
        item = next(i for i in r.items if "%QD100" in i["message"])
        self.assertEqual(item["paths"], ["gateway.routes[1]", "networks[0].nodes[0].rx_pdos[0].entries[0].iec_location"])
        cfg = self.gateway()
        cfg["networks"][1]["slave"]["objects"].append({"index": "0x2101", "subindex": 1, "iec_location": "%QD300"})
        self.assertIn("slave object 0x2101:1 is written by routes[0] and by %QD300", self.errors(cfg))
        cfg = self.gateway()
        cfg["gateway"]["routes"].append(copy.deepcopy(cfg["gateway"]["routes"][1]))
        self.assertIn("the RPDO entry network field node 2 0x4000:0 is written by routes[1] and routes[2]",
                      self.errors(cfg))

    def test_routed_value_also_read_by_the_plc(self):
        # 0x4001 is routed up and also bound to %ID100 in the example: allowed.
        self.assertTrue(self.check(self.gateway()).ok)

    def test_route_ends_exist(self):
        cfg = self.gateway()
        cfg["gateway"]["routes"][0]["field"]["node"] = 9
        self.assertIn("gateway: routes[0]: network field has no node 9", self.errors(cfg))
        cfg = self.gateway()
        cfg["gateway"]["routes"][0]["field"]["network"] = "upper"
        self.assertIn("field network 'upper' is a slave network", self.errors(cfg))
        cfg = self.gateway()
        cfg["gateway"]["routes"][0]["field"]["index"] = "0x1017"
        self.assertIn("network field node 2 0x1017:0 is not an entry of the node's tx_pdos or rx_pdos",
                      self.errors(cfg))
        cfg = self.gateway()
        cfg["gateway"]["routes"][0]["slave"]["index"] = "0x2222"
        self.assertIn("slave object 0x2222:1 is not defined in openplc-gateway.eds", self.errors(cfg))

    def test_entry_without_location_only_when_routed(self):
        cfg = self.gateway()
        del cfg["gateway"]["routes"][1]
        self.assertIn("networks[0]: nodes[0]: rx_pdos[0]: entries[0]: node 2 (pingpong), object 0x4000:0: missing "
                      "'iec_location' (only an entry a gateway route uses may leave it out)", self.errors(cfg))

    def test_status_and_bridge_need_their_objects(self):
        cfg = self.gateway()
        shutil.copy(os.path.join(SLAVE, "openplc-slave.eds"), os.path.join(self.dir, "openplc-gateway.eds"))
        cfg["gateway"]["routes"] = []
        cfg["networks"][1]["slave"]["objects"] = []
        text = self.errors(cfg)
        self.assertIn('gateway status of network "field" needs object 0x5E00 in the EDS', text)
        self.assertIn("gateway: 'sdo_bridge' needs the SDO bridge record 0x5F00", text)
        cfg = self.gateway()
        cfg["gateway"]["sdo_bridge_write"] = True
        del cfg["gateway"]["sdo_bridge"]
        r = self.check(cfg)
        self.assertIn("'sdo_bridge_write' has no effect without 'sdo_bridge'", "\n".join(r.warnings))

    def test_exports_skip_the_slave_network(self):
        from openplc_canopen_deploy import dbcexport, dcfexport
        cfg = self.gateway()
        files, _ = dcfexport.export(cfg, self.path)
        self.assertEqual(sorted(files), ["field/node_2.dcf"])
        with self.assertRaisesRegex(dcfexport.ExportFailed, ""):
            dcfexport.export(cfg, self.path, network="upper")
        texts, _ = dbcexport.export_networks(cfg, self.path)
        self.assertEqual([n for n, _ in texts], ["field"])
        with self.assertRaises(dbcexport.ExportFailed) as e:
            dbcexport.export_networks(self.slave(), os.path.join(self.dir, "x.json"))
        self.assertIn("no master network", str(e.exception.problems))


class Deploy(unittest.TestCase):
    def test_bundle_carries_the_slave_eds(self):
        d = tmpdir(self)
        src = editor_bundle(os.path.join(d, "src"))
        out = os.path.join(d, "program.zip")
        code, stdout, err = deploy("--bundle", src, "--config", os.path.join(GATEWAY, "canopen_config.json"),
                                   "--check-only", "--output", out)
        self.assertEqual(code, 0, err)
        files = zip_contents(out)
        with open(os.path.join(GATEWAY, "openplc-gateway.eds"), "rb") as f:
            self.assertEqual(files["conf/canopen/eds/openplc-gateway.eds"], f.read())
        deployed = json.loads(files["conf/canopen.json"])
        self.assertEqual(deployed["networks"][1]["slave"]["eds"], "canopen/eds/openplc-gateway.eds")
        self.assertEqual(deployed["networks"][0]["nodes"][0]["eds"], "canopen/eds/cpp-slave.eds")
        self.assertEqual(deployed["gateway"], load(os.path.join(GATEWAY, "canopen_config.json"))["gateway"])
        self.assertIn("2 EDS files", stdout)

    def test_check_finds_a_binding_error_before_upload(self):
        d = tmpdir(self)
        for name in os.listdir(SLAVE):
            shutil.copy(os.path.join(SLAVE, name), d)
        cfg = load(os.path.join(d, "canopen_config.json"))
        cfg["networks"][0]["slave"]["objects"][0]["iec_location"] = "%QW310"
        config = os.path.join(d, "canopen_config.json")
        with open(config, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        src = editor_bundle(os.path.join(d, "src"))
        code, _, err = deploy("--bundle", src, "--config", config, "--check-only")
        self.assertEqual(code, 1)
        self.assertIn("the master writes 0x2000:1 (AccessType rww), so it needs an %I location, not %QW310", err)
        self.assertIn("nothing was uploaded", err)
        os.remove(os.path.join(d, "openplc-slave.eds"))
        code, _, err = deploy("--bundle", src, "--config", config, "--check-only")
        self.assertIn("slave: EDS file %s not found" % os.path.join(d, "openplc-slave.eds"), err)

    def test_into_project(self):
        d = tmpdir(self)
        proj = os.path.join(d, "proj")
        os.makedirs(proj)
        with open(os.path.join(proj, "project.json"), "w") as f:
            f.write("{}")
        cfg = load(os.path.join(SLAVE, "canopen_config.json"))
        written, _ = project.write(cfg, os.path.join(SLAVE, "canopen_config.json"), proj)
        self.assertIn(os.path.join(proj, "canopen", "openplc-slave.eds"), written)
        self.assertEqual(load(os.path.join(proj, "canopen", "canopen.json"))["networks"][0]["slave"]["eds"],
                         "openplc-slave.eds")

    def test_clash_keys(self):
        from openplc_canopen_deploy import clash
        self.assertIn("comm_ok_location", clash.LOCATION_KEYS)
        self.assertIn("sync_count_location", clash.LOCATION_KEYS)


class Declarations(unittest.TestCase):
    def test_slave_declarations(self):
        path = os.path.join(SLAVE, "canopen_config.json")
        decls = editorproject.declarations(load(path), path)
        block = declare.st_block(decls)
        self.assertIn("line_speed_setpoint AT %IW300 : UINT;", block)
        self.assertIn("line_mode           AT %IB300 : USINT;", block)  # named from the EDS ParameterName
        self.assertIn("line_run            AT %IX300.0 : BOOL;", block)
        self.assertIn("line_temperature    AT %QW302 : INT;", block)
        self.assertIn("line_comm_ok        AT %IX300.1 : BOOL;", block)
        self.assertIn("line_emcy           AT %QW303 : WORD;", block)
        self.assertEqual([d["location"][:2] for d in decls], ["%I"] * 6 + ["%Q"] * 5)  # inputs first

    def test_without_eds_names(self):
        cfg = load(os.path.join(SLAVE, "canopen_config.json"))
        decls = declare.declarations(cfg, lambda i, ix, sub: None, {"networks[0].slave.objects[0].iec_location": "x"})
        by_loc = {d["location"]: d for d in decls}
        self.assertEqual((by_loc["%IB300"]["name"], by_loc["%IB300"]["type"]), ("line_x2001_1", "USINT"))
        self.assertEqual(by_loc["%IW300"]["declared_as"], "x")
        self.assertEqual(by_loc["%QW302"]["type"], "UINT")  # from the size when the type is unknown

    def test_gateway_project_program(self):
        path = os.path.join(GATEWAY, "canopen_config.json")
        text = editorproject.program(load(path), path)
        self.assertIn("field_pingpong_ok", text)
        self.assertIn("upper_field_ok", text)
        self.assertIn("upper_comm_ok", text)
        self.assertLess(text.index("field_pingpong_ok"), text.index("upper_comm_ok"))

    def test_layout_uses(self):
        cfg = load(os.path.join(SLAVE, "canopen_config.json"))
        paths = [p for p, _ in layout.canopen_uses(cfg)]
        self.assertIn("networks[0].slave.objects[5].iec_location", paths)
        self.assertIn("networks[0].slave.error_register_location", paths)
        self.assertEqual(len(paths), 11)


class Schema(unittest.TestCase):
    def test_field_node_lists_every_node_property(self):
        # schema v2's field_node copies the version 1 node's property list.
        v1 = contract.schema(1)["$defs"]["node"]["properties"]
        v2 = contract.schema(2)["$defs"]["field_node"]["properties"]
        self.assertEqual(list(v1), list(v2))
        self.assertEqual(contract.schema(1)["$defs"]["node"]["required"],
                         contract.schema(2)["$defs"]["field_node"]["required"])

    def test_schema_cases(self):
        v = jsonschema.Draft202012Validator(contract.schema(2))
        cfg = load(os.path.join(GATEWAY, "canopen_config.json"))
        self.assertTrue(v.is_valid(cfg))
        bad = copy.deepcopy(cfg)
        bad["networks"][1]["nodes"] = []
        self.assertFalse(v.is_valid(bad))
        bad = copy.deepcopy(cfg)
        bad["networks"][0]["slave"] = {"node_id": 1, "eds": "x"}
        self.assertFalse(v.is_valid(bad))
        bad = copy.deepcopy(cfg)
        bad["networks"][1]["slave"]["objects"][0]["iec_location"] = "%MW1"
        self.assertFalse(v.is_valid(bad))
        bad = copy.deepcopy(cfg)
        bad["gateway"]["on_upper_loss"] = "panic"
        self.assertFalse(v.is_valid(bad))
        ok = copy.deepcopy(cfg)
        ok["networks"][1]["slave"]["node_id"] = None
        self.assertTrue(v.is_valid(ok))
