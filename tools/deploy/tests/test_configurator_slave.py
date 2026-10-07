"""openplc-canopen-config with slave networks and the gateway: building and
exporting the slave EDS, placing slave objects, check and save
(add-canopen-slave tasks 4.1 and 6.8)."""

import base64
import json
import os
import shutil

from openplc_canopen_deploy.configurator import server as srv

from .helpers import REPO
from .test_configurator_server import Running, read

SLAVE = os.path.join(REPO, "config", "slave")
GATEWAY = os.path.join(REPO, "config", "gateway")

OBJECTS = [{"name": "setpoint", "type": "UNSIGNED16", "direction": "from_master"},
           {"name": "start", "type": "BOOLEAN", "direction": "from_master"},
           {"name": "actual", "type": "UNSIGNED16", "direction": "to_master"},
           {"name": "level", "type": "INTEGER16", "direction": "to_master", "low": -100, "high": 100}]


def slave_config(objects=None, eds="", **slave):
    s = dict({"node_id": 10, "eds": eds, "objects": objects or []}, **slave)
    return {"schema_version": 2, "networks": [
        {"name": "line", "role": "slave", "adapter": {"type": "socketcan", "interface": "vcan1", "bitrate": 250000},
         "slave": s}]}


class Slave(Running):
    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.dir, "slave")
        self.ok("POST", "/api/open", {"path": self.folder, "mode": "standalone"})

    def build(self, cfg, desc, **extra):
        return self.request("POST", "/api/slave_eds", dict({"config": cfg, "network": 0, "description": desc}, **extra))

    def test_build_bind_and_save(self):
        cfg = slave_config()
        desc = {"device_name": "Line cell", "product_code": 7, "objects": OBJECTS}
        status, r, _ = self.build(cfg, desc)
        self.assertEqual(status, 200, r)
        self.assertEqual(r["name"], "line-cell.eds")
        self.assertEqual([(b["index"], b["subindex"], b["name"], b["iec_location"]) for b in r["bindings"]],
                         [("0x2000", 1, "setpoint", "%IW100"), ("0x2001", 1, "start", "%IX100.0"),
                          ("0x2100", 1, "actual", "%QW100"), ("0x2101", 1, "level", "%QW101")])
        self.assertEqual({o["access"] for o in r["summary"]["objects"] if o["index"] == "0x2000"}, {"ro", "rww"})
        # Not in the folder until saved; the page shows it with its description.
        self.assertFalse(os.path.exists(os.path.join(self.folder, "line-cell.eds")))
        state = self.ok("GET", "/api/state")
        self.assertIn("line-cell.eds", state["eds"])
        self.assertEqual(state["slave_descriptions"]["line-cell.eds"], desc)
        cfg["networks"][0]["slave"].update(eds=r["name"], objects=r["bindings"])
        check = self.ok("POST", "/api/check", {"config": cfg})
        self.assertEqual(check["errors"], 0, check["items"])
        self.assertRegex(check["block"], r"line_setpoint +AT %IW100 : UINT;")
        self.assertRegex(check["block"], r"line_level +AT %QW101 : INT;")
        self.ok("POST", "/api/save", {"config": cfg})
        eds = read(os.path.join(self.folder, "line-cell.eds"))
        self.assertTrue(eds.startswith(b"[FileInfo]"))
        self.assertEqual(json.loads(read(os.path.join(self.folder, "line-cell.eds.json"))), desc)
        saved = json.loads(read(os.path.join(self.folder, "canopen.json")))
        self.assertEqual(saved["schema_version"], 2)
        self.assertEqual(list(saved["networks"][0]), ["name", "role", "adapter", "slave"])
        self.assertEqual(list(saved["networks"][0]["slave"]), ["node_id", "eds", "objects"])
        self.assertEqual(list(saved["networks"][0]["slave"]["objects"][0]), ["index", "subindex", "name", "iec_location"])
        # After a reload the description comes from the folder.
        state = self.ok("POST", "/api/reload")
        self.assertEqual(state["slave_descriptions"]["line-cell.eds"], desc)
        self.assertNotIn("line-cell.eds", state["unused_eds"])

    def test_rebuild_keeps_bindings(self):
        cfg = slave_config()
        r = self.build(cfg, {"objects": OBJECTS})[1]
        bindings = r["bindings"]
        bindings[0]["iec_location"] = "%IW200"
        cfg["networks"][0]["slave"].update(eds=r["name"], objects=bindings[:1])
        r = self.build(cfg, {"objects": OBJECTS + [{"name": "extra", "type": "UNSIGNED16", "direction": "to_master"}]})[1]
        self.assertEqual(r["name"], "openplc-slave.eds")
        self.assertEqual([b["iec_location"] for b in r["bindings"]], ["%IW200", "%IX100.0", "%QW100", "%QW101", "%QW102"])

    def test_description_errors(self):
        status, r, _ = self.build(slave_config(), {"objects": [{"name": "x", "type": "UNSIGNED16"}]})
        self.assertEqual(status, 422)
        self.assertIn("object 'x' (objects[0]): 'direction' must be from_master", r["error"])
        status, r, _ = self.build(slave_config(), {"objects": OBJECTS}, name="slave.txt")
        self.assertEqual(status, 422)
        status, r, _ = self.request("POST", "/api/slave_eds", {"config": {"schema_version": 2, "networks": [
            {"name": "io", "adapter": {"interface": "can0", "bitrate": 250000}, "master": {"node_id": 1}, "nodes": []}]},
            "network": 0, "description": {"objects": OBJECTS}})
        self.assertEqual(status, 400)
        self.assertIn("not a slave network", r["error"])

    def test_vendor_eds_of_the_same_name(self):
        os.makedirs(self.folder)
        shutil.copy(os.path.join(SLAVE, "openplc-slave.eds"), os.path.join(self.folder, "openplc-slave.eds"))
        status, r, _ = self.build(slave_config(), {"objects": OBJECTS})
        self.assertEqual(status, 409, r)
        self.assertEqual(r["conflict"], "openplc-slave.eds")
        self.assertEqual(self.build(slave_config(), {"objects": OBJECTS}, replace=True)[0], 200)

    def test_place(self):
        cfg = slave_config([{"index": "0x2100", "subindex": 1, "iec_location": "%QW100"}])
        place = lambda **b: self.request("POST", "/api/place", dict({"config": cfg, "network": 0}, **b))
        self.assertEqual(place(direction="slave_object", type="UNSIGNED16", access="ro")[1]["location"], "%QW101")
        self.assertEqual(place(direction="slave_object", type="UNSIGNED16", access="rwr")[1]["location"], "%QW101")
        self.assertEqual(place(direction="slave_object", type="UNSIGNED16", access="rww")[1]["location"], "%IW100")
        self.assertEqual(place(direction="slave_object", type="BOOLEAN", access="rw")[1]["location"], "%IX100.0")
        self.assertEqual(place(direction="slave_object", type="UNSIGNED16", access="const")[0], 400)
        self.assertEqual(place(direction="slave_comm_ok")[1]["location"], "%IX100.0")
        self.assertEqual(place(direction="slave_state")[1]["location"], "%IB100")
        self.assertEqual(place(direction="slave_sync_count")[1]["location"], "%IW100")
        self.assertEqual(place(direction="slave_emcy")[1]["location"], "%QW101")
        self.assertEqual(place(direction="slave_errreg")[1]["location"], "%QB100")

    def test_check_refuses_wrong_area(self):
        os.makedirs(self.folder)
        shutil.copy(os.path.join(SLAVE, "openplc-slave.eds"), self.folder)
        cfg = slave_config([{"index": "0x2100", "subindex": 1, "iec_location": "%IW100"}], eds="openplc-slave.eds")
        check = self.ok("POST", "/api/check", {"config": cfg})
        self.assertEqual(check["errors"], 1)
        item, = check["items"]
        self.assertIn("needs a %Q location", item["message"])
        self.assertEqual(item["paths"], ["networks[0].slave.objects[0].iec_location"])

    def test_export_eds(self):
        os.makedirs(self.folder)
        shutil.copy(os.path.join(SLAVE, "openplc-slave.eds"), self.folder)
        r = self.ok("POST", "/api/export_eds", {"config": slave_config(eds="openplc-slave.eds"), "network": 0})
        self.assertEqual(r["name"], "openplc-slave-example.eds")
        self.assertEqual(base64.b64decode(r["data"]), read(os.path.join(SLAVE, "openplc-slave.eds")))
        # An unsaved build exports as built.
        b = self.build(slave_config(), {"device_name": "Cell", "objects": OBJECTS})[1]
        r = self.ok("POST", "/api/export_eds", {"config": slave_config(eds=b["name"]), "network": 0})
        self.assertEqual(r["name"], "cell.eds")
        self.assertTrue(base64.b64decode(r["data"]).startswith(b"[FileInfo]"))
        self.assertEqual(self.request("POST", "/api/export_eds", {"config": slave_config(), "network": 0})[0], 422)

    def test_example_round_trip(self):
        shutil.copytree(SLAVE, self.folder)
        os.rename(os.path.join(self.folder, "canopen_config.json"), os.path.join(self.folder, "canopen.json"))
        state = self.ok("POST", "/api/reload")
        self.assertEqual(state["config"]["networks"][0]["role"], "slave")
        self.assertEqual(self.ok("POST", "/api/check", {"config": state["config"]})["errors"], 0)
        self.ok("POST", "/api/save", {"config": state["config"]})
        self.assertEqual(json.loads(read(os.path.join(self.folder, "canopen.json"))),
                         json.loads(read(os.path.join(SLAVE, "canopen_config.json"))))


class Gateway(Running):
    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.dir, "gateway")
        shutil.copytree(GATEWAY, self.folder)
        os.rename(os.path.join(self.folder, "canopen_config.json"), os.path.join(self.folder, "canopen.json"))
        self.state = self.ok("POST", "/api/open", {"path": self.folder, "mode": "standalone"})
        self.cfg = self.state["config"]

    def test_check_and_save(self):
        check = self.ok("POST", "/api/check", {"config": self.cfg})
        self.assertEqual(check["errors"], 0, check["items"])
        self.assertNotIn("openplc-gateway.eds", self.state["unused_eds"])
        self.ok("POST", "/api/save", {"config": self.cfg})
        saved = json.loads(read(os.path.join(self.folder, "canopen.json")))
        self.assertEqual(saved, json.loads(read(os.path.join(GATEWAY, "canopen_config.json"))))
        self.assertEqual(list(saved)[:3], ["schema_version", "networks", "gateway"])
        self.assertEqual(list(saved["gateway"]["routes"][0]), ["name", "slave", "field"])

    def test_check_names_the_route(self):
        self.cfg["gateway"]["routes"][0]["field"]["node"] = 9
        check = self.ok("POST", "/api/check", {"config": self.cfg})
        self.assertTrue(check["errors"])
        self.assertTrue(any(p.startswith("gateway.routes[0]") for i in check["items"] for p in i["paths"]),
                        check["items"])

    def test_build_with_routes(self):
        desc = json.loads(read(os.path.join(GATEWAY, "gateway_eds.json")))
        status, r, _ = self.request("POST", "/api/slave_eds", {"config": self.cfg, "network": 1, "description": desc,
                                                               "name": "openplc-gateway.eds", "gateway": True})
        self.assertEqual(status, 200, r)
        self.assertEqual(r["routes"], [rt["slave"] for rt in self.cfg["gateway"]["routes"]])
        # Route objects are the routes' to bind, not the program's.
        self.assertEqual([b["name"] for b in r["bindings"]], ["field_ok"])
        self.assertEqual(r["bindings"][0]["iec_location"], "%QX300.0")
        self.assertEqual(read(os.path.join(self.server.session.pending_dir, r["name"])),
                         read(os.path.join(GATEWAY, "openplc-gateway.eds")))
