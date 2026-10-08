"""openplc-canopen-config's local server, over HTTP
(add-canopen-configurator tasks 3.1-3.3)."""

import base64
import http.client
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import unittest

from openplc_canopen_deploy.configurator import server as srv

from .helpers import PINGPONG, REPO, editor_bundle, fake_editor_cli, tmpdir

RTD = os.path.join(REPO, "config", "rtd-sensor")
LINT = os.path.join(REPO, "test", "fixtures", "eds", "lint")
DRIVES = os.path.join(REPO, "test", "fixtures", "eds", "drives")
FIXTURE = os.path.join(REPO, "test", "fixtures", "editor-project")
DEPLOY = os.path.join(REPO, "tools", "deploy")


def read(path, mode="rb"):
    with open(path, mode) as f:
        return f.read()


def rtd_node(eds="rtd8.eds"):
    return {"node_id": 5, "name": "rtd", "eds": eds, "heartbeat_ms": 100, "heartbeat_timeout_ms": 300,
            "status_location": "%IX10.0",
            "tx_pdos": [{"entries": [{"index": "0x7130", "subindex": s, "type": "INTEGER16",
                                      "iec_location": "%%IW%d" % (99 + s)} for s in range(1, 5)]}]}

# A valid token_verifier (the token "test"'s, as in test/fixtures/config).
FIXTURE_VERIFIER = "SCRAM-SHA-256$4096:b3BlbnBsYy1jYW5vcGVuLQ==$SCwajLpaZodu1wAN8vyPszAhAZJB4cXO6Rk+MpacSlQ=:7p7OTxtK+R6omxv8Fdz+xdCpEf4bc82kbkxCL8w33kg="



class Running(unittest.TestCase):
    """A server on a free port, with recent folders kept in a temp dir."""

    def setUp(self):
        self.dir = tmpdir(self)
        os.environ["OPENPLC_CANOPEN_CONFIG_DIR"] = os.path.join(self.dir, "cfg")
        self.addCleanup(os.environ.pop, "OPENPLC_CANOPEN_CONFIG_DIR", None)
        self.server = srv.Server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.project = os.path.join(self.dir, "rtd-monitor")
        shutil.copytree(FIXTURE, self.project)

    def request(self, method, path, body=None, token=True, host=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        h = {"Host": host or "127.0.0.1:%d" % self.server.server_port}
        if token:
            h[srv.TOKEN_HEADER] = self.server.token if token is True else token
        if body is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            return r.status, json.loads(data.decode()) if data else {}, r
        except ValueError:
            return r.status, data, r

    def ok(self, method, path, body=None):
        status, data, _ = self.request(method, path, body)
        self.assertEqual(status, 200, data)
        return data

    def eds(self, path, name=None, **extra):
        body = dict(name=name or os.path.basename(path), data=base64.b64encode(read(path)).decode(), **extra)
        return self.request("POST", "/api/eds", body)

    def open_project(self):
        return self.ok("POST", "/api/open", {"path": self.project, "mode": "project"})


class Access(Running):
    def test_api_needs_the_token(self):
        status, data, _ = self.request("GET", "/api/state", token=False)
        self.assertEqual(status, 403)
        status, _, _ = self.request("GET", "/api/state", token="wrong")
        self.assertEqual(status, 403)
        self.assertEqual(self.request("GET", "/api/state")[0], 200)

    def test_save_without_token_writes_nothing(self):
        self.open_project()
        status, _, _ = self.request("POST", "/api/save", {"config": srv.empty_config()}, token=False)
        self.assertEqual(status, 403)
        self.assertFalse(os.path.exists(os.path.join(self.project, "canopen")))

    def test_unexpected_error_is_one_sentence(self):
        """A bug in a handler answers 500 with one plain sentence; the
        traceback goes to the terminal, not to the page."""
        from unittest import mock
        with mock.patch.object(srv, "list_folders", side_effect=RuntimeError("boom")), \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            status, data, _ = self.request("GET", "/api/folders")
        self.assertEqual(status, 500)
        self.assertEqual(data, {"error": srv.UNEXPECTED_ERROR})
        self.assertIn("RuntimeError: boom", err.getvalue())

    def test_host_must_be_loopback(self):
        status, data, _ = self.request("GET", "/api/state", host="evil.example:%d" % self.server.server_port)
        self.assertEqual(status, 403)
        self.assertIn("127.0.0.1", data["error"])

    def test_listens_on_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_page_needs_the_cookie(self):
        status, _, _ = self.request("GET", "/", token=False)
        self.assertEqual(status, 403)
        status, _, r = self.request("GET", "/?token=" + self.server.token, token=False)
        self.assertEqual(status, 303)
        cookie = r.getheader("Set-Cookie").split(";")[0]
        status, page, _ = self.request("GET", "/", token=False, headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn(self.server.token.encode(), page)
        self.assertNotIn(b"http", page.replace(b"http-equiv", b""))  # nothing loaded from the network
        status, js, _ = self.request("GET", "/app.js", token=False, headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertNotIn(b"https://", js)
        self.assertEqual(self.request("GET", "/../server.py", token=False, headers={"Cookie": cookie})[0], 404)


class Theme(Running):
    """fix-configurator-layout: the theme is kept in ui.json in the settings
    folder and put into the page."""

    def page(self):
        _, _, r = self.request("GET", "/?token=" + self.server.token, token=False)
        cookie = r.getheader("Set-Cookie").split(";")[0]
        return self.request("GET", "/", token=False, headers={"Cookie": cookie})[1]

    def test_default_auto(self):
        self.assertEqual(self.ok("GET", "/api/ui"), {"theme": "auto", "dbc_sdo": "none"})
        self.assertIn(b'data-theme="auto"', self.page())

    def test_kept_and_in_the_page(self):
        self.ok("POST", "/api/ui", {"theme": "dark"})
        with open(os.path.join(self.dir, "cfg", "ui.json")) as f:
            self.assertEqual(json.load(f), {"theme": "dark", "dbc_sdo": "none"})
        self.assertEqual(self.ok("GET", "/api/ui"), {"theme": "dark", "dbc_sdo": "none"})
        self.assertIn(b'data-theme="dark"', self.page())

    def test_bad_value_refused(self):
        status, data, _ = self.request("POST", "/api/ui", {"theme": "blue"})
        self.assertEqual(status, 400)
        self.assertIn("theme", data["error"])
        self.assertEqual(self.request("POST", "/api/ui", {"theme": "x"}, token="wrong")[0], 403)
        self.assertEqual(self.ok("GET", "/api/ui"), {"theme": "auto", "dbc_sdo": "none"})

    def test_broken_file_reads_as_auto(self):
        os.makedirs(os.path.join(self.dir, "cfg"))
        with open(os.path.join(self.dir, "cfg", "ui.json"), "w") as f:
            f.write("[1, 2")
        self.assertEqual(self.ok("GET", "/api/ui"), {"theme": "auto", "dbc_sdo": "none"})

    def test_dbc_sdo_kept_with_theme(self):
        self.ok("POST", "/api/ui", {"theme": "dark"})
        self.assertEqual(self.ok("POST", "/api/ui", {"dbc_sdo": "config"}), {"theme": "dark", "dbc_sdo": "config"})
        self.assertEqual(self.ok("GET", "/api/ui"), {"theme": "dark", "dbc_sdo": "config"})
        status, data, _ = self.request("POST", "/api/ui", {"dbc_sdo": "some"})
        self.assertEqual(status, 400)
        self.assertIn("dbc_sdo", data["error"])
        self.assertEqual(self.request("POST", "/api/ui", {"colour": "red"})[0], 400)

    def test_nothing_written_to_the_project(self):
        before = sorted(os.listdir(self.project))
        self.open_project()
        self.ok("POST", "/api/ui", {"theme": "light"})
        self.assertEqual(sorted(os.listdir(self.project)), before)


class OpenAndModes(Running):
    def test_project_without_config(self):
        state = self.open_project()
        self.assertEqual(state["mode"], "project")
        self.assertFalse(state["config_exists"])
        self.assertEqual(state["config"]["nodes"], [])
        self.assertFalse(os.path.exists(os.path.join(self.project, "canopen")))
        self.assertIn({"file": "devices/remote/ecat-bus.json", "kind": "device", "location": "%ID100",
                       "name": "drive1", "path": "ethercatConfig.devices[0].channelMappings[0].iecLocation"},
                      state["project_uses"])
        self.assertEqual(state["recent"][0], {"path": self.project, "mode": "project"})

    def test_not_a_project(self):
        status, data, _ = self.request("POST", "/api/open", {"path": self.dir, "mode": "project"})
        self.assertEqual(status, 422)
        self.assertTrue(data["not_a_project"])

    def test_auto_mode(self):
        self.assertEqual(self.ok("POST", "/api/open", {"path": self.project})["mode"], "project")
        state = self.ok("POST", "/api/open", {"path": os.path.join(self.dir, "standalone")})
        self.assertEqual(state["mode"], "standalone")
        self.assertEqual(state["project_uses"], [])

    def test_folders(self):
        data = self.ok("GET", "/api/folders?path=" + self.dir)
        entry = [e for e in data["entries"] if e["name"] == "rtd-monitor"][0]
        self.assertTrue(entry["project"])
        self.assertEqual(data["parent"], os.path.dirname(self.dir))

    def test_old_style_keys_shown_as_adapter(self):
        os.makedirs(os.path.join(self.project, "canopen"))
        cfg = {"interface": "vcan0", "bitrate": 125000, "master": {"node_id": 1, "sync_period_us": 100000},
               "nodes": []}
        with open(os.path.join(self.project, "canopen", "canopen.json"), "w") as f:
            json.dump(cfg, f)
        state = self.open_project()
        self.assertEqual(state["config"]["adapter"],
                         {"type": "socketcan", "interface": "vcan0", "bitrate": 125000, "configure_link": False})
        self.assertNotIn("interface", state["config"])
        self.assertIn("old top-level", state["notices"][0])

    def test_strict_eds_shown_as_eds_lint(self):
        os.makedirs(os.path.join(self.project, "canopen"))
        for strict, mode in ((False, "off"), (True, "all")):
            cfg = srv.empty_config()
            cfg["master"] = {"node_id": 1, "sync_period_us": 10000, "strict_eds": strict, "heartbeat_ms": 100}
            with open(os.path.join(self.project, "canopen", "canopen.json"), "w") as f:
                json.dump(cfg, f)
            state = self.open_project()
            self.assertEqual(state["config"]["master"],
                             {"node_id": 1, "sync_period_us": 10000, "eds_lint": mode, "heartbeat_ms": 100})
            self.assertIn("old 'strict_eds'", state["notices"][0])
        # The default as a field is shown as the default (no field).
        cfg["master"] = {"node_id": 1, "sync_period_us": 10000, "eds_lint": "communication"}
        with open(os.path.join(self.project, "canopen", "canopen.json"), "w") as f:
            json.dump(cfg, f)
        self.assertEqual(self.open_project()["config"]["master"], {"node_id": 1, "sync_period_us": 10000})


class EdsImport(Running):
    def setUp(self):
        super().setUp()
        self.open_project()

    def test_latin1_converted(self):
        text = read(os.path.join(PINGPONG, "cpp-slave.eds")).decode("utf-8")
        text = text.replace("ParameterName=UNSIGNED32 sent from slave", "ParameterName=Temperature °C", 1)
        path = os.path.join(self.dir, "vendor.eds")
        with open(path, "wb") as f:
            f.write(text.encode("latin-1"))
        status, data, _ = self.eds(path)
        self.assertEqual(status, 200, data)
        self.assertTrue(data["converted"])
        names = {o["name"] for o in data["summary"]["objects"]}
        self.assertIn("Temperature °C", names)
        cfg = srv.empty_config()
        cfg["nodes"] = [{"node_id": 2, "eds": "vendor.eds", "tx_pdos": [{"entries": [
            {"index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID110"}]}]}]
        self.ok("POST", "/api/save", {"config": cfg})
        saved = read(os.path.join(self.project, "canopen", "vendor.eds"))
        self.assertEqual(saved.decode("utf-8"), text)

    def test_not_an_eds(self):
        path = os.path.join(self.dir, "x.eds")
        with open(path, "w") as f:
            f.write("[DeviceInfo]\nVendorName=x\n")
        status, data, _ = self.eds(path)
        self.assertEqual(status, 422)
        self.assertIn("0x1000/0x1018", data["error"])

    def test_same_name_conflict(self):
        os.makedirs(os.path.join(self.project, "canopen"))
        shutil.copy(os.path.join(PINGPONG, "cpp-slave.eds"), os.path.join(self.project, "canopen", "rtd8.eds"))
        status, data, _ = self.eds(os.path.join(RTD, "rtd8.eds"))
        self.assertEqual(status, 409)
        self.assertEqual(data["conflict"], "rtd8.eds")
        status, data, _ = self.eds(os.path.join(RTD, "rtd8.eds"), on_conflict="keep_both")
        self.assertEqual(data["name"], "rtd8-2.eds")
        status, data, _ = self.eds(os.path.join(RTD, "rtd8.eds"), on_conflict="replace")
        self.assertEqual(data["name"], "rtd8.eds")
        # Nothing on disk changed before a save.
        self.assertEqual(read(os.path.join(self.project, "canopen", "rtd8.eds")),
                         read(os.path.join(PINGPONG, "cpp-slave.eds")))

    def test_lint_accepted_findings(self):
        # Servo drive fixture: limit-only findings in profile objects.
        status, data, _ = self.eds(os.path.join(DRIVES, "servo-drive.eds"))
        self.assertEqual(status, 200, data)
        self.assertEqual(data["lint"]["mode"], "communication")
        self.assertEqual([f["object"] for f in data["lint"]["accepted"]], ["0x60C0", "0x60C2 sub 2"])
        self.assertEqual(data["lint"]["corrections"], [])
        # The same file is refused under "all".
        status, data, _ = self.eds(os.path.join(DRIVES, "servo-drive.eds"), name="e2.eds", eds_lint="all")
        self.assertEqual(status, 422)
        self.assertIn("fails dcfgen's lint (eds_lint \"all\"): 0x60C0: LowLimit overflow", data["error"])

    def test_lint_corrections(self):
        status, data, _ = self.eds(os.path.join(LINT, "octet-string.eds"))
        self.assertEqual(status, 200, data)
        self.assertEqual([(c["kind"], c["items"][0]["old"]) for c in data["lint"]["corrections"]], [("string", "----")])
        status, data, _ = self.eds(os.path.join(LINT, "real-decimal.eds"))
        self.assertEqual(status, 200, data)
        self.assertEqual([c["kind"] for c in data["lint"]["corrections"]], ["real"])
        # The stored file is the vendor's, not the corrected copy.
        self.assertEqual(read(os.path.join(self.server.session.pending_dir, "real-decimal.eds")),
                         read(os.path.join(LINT, "real-decimal.eds")))

    def test_lint_refuses_communication_finding(self):
        status, data, _ = self.eds(os.path.join(LINT, "comm-broken.eds"))
        self.assertEqual(status, 422)
        self.assertEqual(data["error"], "EDS comm-broken.eds fails dcfgen's lint (eds_lint \"communication\"): "
                                        "0x1A00 sub 0: DataType should be UNSIGNED8 in [1A00sub0]; eds_lint: \"off\" "
                                        "would accept it")
        self.assertEqual([f["object"] for f in data["findings"]], ["0x1A00 sub 0"])
        self.assertNotIn("comm-broken.eds", self.ok("GET", "/api/state")["eds"])
        status, data, _ = self.eds(os.path.join(LINT, "comm-broken.eds"), eds_lint="off")
        self.assertEqual(status, 200, data)
        self.assertEqual([f["object"] for f in data["lint"]["accepted"]], ["0x1A00 sub 0"])

    def test_lint_mode_of_the_saved_config(self):
        os.makedirs(os.path.join(self.project, "canopen"), exist_ok=True)
        cfg = srv.empty_config()
        cfg["master"]["strict_eds"] = True
        with open(os.path.join(self.project, "canopen", "canopen.json"), "w") as f:
            json.dump(cfg, f)
        self.open_project()
        status, data, _ = self.eds(os.path.join(LINT, "signed-hex.eds"))
        self.assertEqual(status, 422)
        self.assertIn("(eds_lint \"all\")", data["error"])

    def test_same_file_again_is_fine(self):
        self.assertEqual(self.eds(os.path.join(RTD, "rtd8.eds"))[0], 200)
        self.assertEqual(self.eds(os.path.join(RTD, "rtd8.eds"))[0], 200)


class CheckAndSave(Running):
    def setUp(self):
        super().setUp()
        self.open_project()
        self.assertEqual(self.eds(os.path.join(RTD, "rtd8.eds"))[0], 200)
        self.cfg = srv.empty_config()
        self.cfg["nodes"] = [rtd_node()]
        self.canopen = os.path.join(self.project, "canopen")

    def snapshot(self):
        out = {}
        for root, _, files in os.walk(self.project):
            for f in files:
                p = os.path.join(root, f)
                out[os.path.relpath(p, self.project)] = read(p)
        return out

    def test_check_paths_and_declarations(self):
        self.cfg["nodes"][0]["tx_pdos"][0]["entries"][0]["iec_location"] = "%ID100"
        data = self.ok("POST", "/api/check", {"config": self.cfg})
        self.assertGreaterEqual(data["errors"], 1)
        paths = [p for i in data["items"] for p in i["paths"]]
        self.assertIn("nodes[0].tx_pdos[0].entries[0].iec_location", paths)
        self.cfg["nodes"][0]["tx_pdos"][0]["entries"][0]["iec_location"] = "%IW100"
        data = self.ok("POST", "/api/check", {"config": self.cfg})
        self.assertEqual(data["errors"], 0, data["items"])
        self.assertIn("rtd_AI0_Input_PV AT %IW100 : INT;", data["block"])

    def test_check_without_sync_period(self):
        # An empty SYNC period field saves no sync_period_us; Check then names
        # a PDO left at a synchronous transmission type.
        del self.cfg["master"]["sync_period_us"]
        self.cfg["nodes"][0]["tx_pdos"][0]["transmission"] = 1
        data = self.ok("POST", "/api/check", {"config": self.cfg})
        [item] = [i for i in data["items"] if "needs SYNC" in i["message"]]
        self.assertIn("TPDO 1: transmission type 1 needs SYNC, but the master produces none", item["message"])
        self.assertIn("nodes[0].tx_pdos[0].transmission", item["paths"])

    def test_check_with_plc_cycle_sync(self):
        # PLC-cycle SYNC: synchronous PDOs are fine without a SYNC period.
        del self.cfg["master"]["sync_period_us"]
        self.cfg["master"]["sync_source"] = "plc_cycle"
        self.cfg["master"]["sync_cycles"] = 2
        self.cfg["nodes"][0]["tx_pdos"][0]["transmission"] = 1
        data = self.ok("POST", "/api/check", {"config": self.cfg})
        self.assertFalse([i for i in data["items"] if "SYNC" in i["message"]], data["items"])

    def test_check_reruns_the_lint(self):
        # A node whose EDS has a finding in 0x6061: accepted with "off", the
        # plugin's error with "all".
        self.assertEqual(self.eds(os.path.join(LINT, "signed-hex.eds"))[0], 200)
        self.cfg["nodes"].append({"node_id": 2, "name": "pingpong", "eds": "signed-hex.eds", "tx_pdos": [
            {"entries": [{"index": "0x4001", "subindex": 0, "type": "UNSIGNED32", "iec_location": "%ID110"}]}]})
        self.cfg["master"]["eds_lint"] = "off"
        data = self.ok("POST", "/api/check", {"config": self.cfg})
        self.assertEqual(data["errors"], 0, data["items"])
        self.assertTrue(any("signed-hex.eds: 2 lint findings accepted (eds_lint \"off\")" in i["message"]
                            for i in data["items"]), data["items"])
        self.cfg["master"]["eds_lint"] = "all"
        data = self.ok("POST", "/api/check", {"config": self.cfg})
        self.assertEqual([i["message"] for i in data["items"] if i["level"] == "error"],
                         ["node 2 (pingpong): EDS signed-hex.eds fails dcfgen's lint (eds_lint \"all\"): 0x6061: "
                          "HighLimit overflow in [6061]; 0x60C0: LowLimit overflow in [60C0]; eds_lint: "
                          "\"communication\" would accept it"])
        self.assertEqual([i["paths"] for i in data["items"] if i["level"] == "error"], [["nodes[1].eds"]])

    def test_overlap_with_project(self):
        self.cfg["nodes"][0]["status_location"] = "%IX0.0"  # the pin mapping's input
        status, data, _ = self.request("POST", "/api/save", {"config": self.cfg})
        self.assertEqual(status, 422)
        [item] = [i for i in data["check"]["items"] if i.get("overlap")]
        self.assertIn("devices/pin-mapping.json", item["message"])
        self.assertFalse(os.path.exists(self.canopen))
        # Allowed, the overlap stays listed (as a warning) next to the override.
        allowed = self.ok("POST", "/api/check", {"config": self.cfg, "allow_overlap": True})
        [item] = [i for i in allowed["items"] if i.get("overlap_allowed")]
        self.assertEqual(item["level"], "warning")
        self.ok("POST", "/api/save", {"config": self.cfg, "allow_overlap": True})
        self.assertTrue(os.path.isfile(os.path.join(self.canopen, "canopen.json")))

    def test_save_writes_only_canopen(self):
        before = self.snapshot()
        data = self.ok("POST", "/api/save", {"config": self.cfg})
        after = self.snapshot()
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        self.assertEqual(changed, {os.path.join("canopen", "canopen.json"), os.path.join("canopen", "rtd8.eds")})
        self.assertEqual(sorted(os.path.basename(p) for p in data["written"]), ["canopen.json", "rtd8.eds"])

    def test_export_dcf_one_node_unsaved(self):
        # The draft (EDS only imported, nothing saved) exports; the project
        # is not touched.
        before = self.snapshot()
        self.cfg["nodes"][0]["heartbeat_ms"] = 200
        data = self.ok("POST", "/api/export_dcf", {"config": self.cfg, "node": 5})
        self.assertEqual((data["errors"], data["name"], data["files"]), (0, "node_5.dcf", ["node_5.dcf"]))
        text = base64.b64decode(data["data"]).decode("utf-8")
        self.assertIn("[DeviceComissioning]\nNodeID=5\n", text.replace("\r\n", "\n"))
        self.assertRegex(text, r"\[1017\][^\[]*ParameterValue=0xC8")
        self.assertEqual(self.snapshot(), before)

    def test_export_dcf_all_as_zip(self):
        import io
        import zipfile
        data = self.ok("POST", "/api/export_dcf", {"config": self.cfg})
        self.assertEqual((data["name"], data["content_type"]), ("rtd-monitor_dcf.zip", "application/zip"))
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(data["data"]))) as z:
            self.assertEqual(z.namelist(), ["node_5.dcf"])

    def test_export_dcf_problems(self):
        self.cfg["nodes"][0]["node_id"] = 1  # the master's
        data = self.ok("POST", "/api/export_dcf", {"config": self.cfg, "node": 1})
        self.assertGreaterEqual(data["errors"], 1)
        self.assertNotIn("data", data)
        self.assertIn("is the master's node ID", "\n".join(i["message"] for i in data["items"]))
        status, _, _ = self.request("POST", "/api/export_dcf", {"config": self.cfg, "node": "5"})
        self.assertEqual(status, 400)

    def test_export_dbc_unsaved(self):
        before = self.snapshot()
        data = self.ok("POST", "/api/export_dbc", {"config": self.cfg})
        self.assertEqual((data["errors"], data["name"]), (0, "rtd-monitor.dbc"))
        text = base64.b64decode(data["data"]).decode("ascii")
        self.assertIn("BO_ 389 rtd_TPDO1: 8 rtd", text)
        self.assertNotIn("SDO_Rx", text)
        self.assertEqual(self.snapshot(), before)

    def test_export_dbc_with_sdo(self):
        data = self.ok("POST", "/api/export_dbc", {"config": self.cfg, "sdo": "all"})
        self.assertIn("BO_ 1541 rtd_SDO_Rx: 8 Master", base64.b64decode(data["data"]).decode("ascii"))
        self.assertEqual(self.request("POST", "/api/export_dbc", {"config": self.cfg, "sdo": "x"})[0], 400)

    def test_export_dbc_problems(self):
        self.cfg["nodes"][0]["node_id"] = 1  # the master's
        data = self.ok("POST", "/api/export_dbc", {"config": self.cfg})
        self.assertGreaterEqual(data["errors"], 1)
        self.assertNotIn("data", data)
        self.assertIn("is the master's node ID", "\n".join(i["message"] for i in data["items"]))

    def test_export_html_unsaved(self):
        before = self.snapshot()
        data = self.ok("POST", "/api/export_html", {"config": self.cfg})
        self.assertEqual((data["errors"], data["name"], data["content_type"]), (0, "rtd-monitor.html", "text/html"))
        text = base64.b64decode(data["data"]).decode("utf-8")
        self.assertIn('id="node-5"', text)
        self.assertIn("0x185", text)
        self.assertEqual(self.snapshot(), before)

    def test_export_html_problems(self):
        self.cfg["nodes"][0]["node_id"] = 1  # the master's
        data = self.ok("POST", "/api/export_html", {"config": self.cfg})
        self.assertGreaterEqual(data["errors"], 1)
        self.assertNotIn("data", data)
        self.assertIn("is the master's node ID", "\n".join(i["message"] for i in data["items"]))
        self.assertEqual(self.request("POST", "/api/export_html", {"config": []})[0], 400)

    def test_invalid_config_not_saved(self):
        self.cfg["nodes"].append(dict(rtd_node(), status_location="%IX10.1",
                                      tx_pdos=[{"entries": [dict(e, iec_location="%%IW%d" % (110 + k)) for k, e in
                                                            enumerate(rtd_node()["tx_pdos"][0]["entries"])]}]))
        status, data, _ = self.request("POST", "/api/save", {"config": self.cfg})
        self.assertEqual(status, 422)
        dup = [i for i in data["check"]["items"] if "more than one slave" in i["message"]][0]
        self.assertEqual(dup["paths"], ["nodes[0].node_id", "nodes[1].node_id"])
        self.assertFalse(os.path.exists(self.canopen))

    def test_unknown_fields_kept(self):
        self.cfg["x_note"] = {"by": "hand"}
        self.cfg["nodes"][0]["x_comment"] = "keep me"
        self.ok("POST", "/api/save", {"config": self.cfg})
        state = self.ok("POST", "/api/reload")
        cfg = state["config"]
        cfg["nodes"][0]["heartbeat_ms"] = 200
        self.ok("POST", "/api/save", {"config": cfg})
        saved = json.loads(read(os.path.join(self.canopen, "canopen.json")))
        self.assertEqual(saved["x_note"], {"by": "hand"})
        self.assertEqual(saved["nodes"][0]["x_comment"], "keep me")
        self.assertEqual(saved["nodes"][0]["heartbeat_ms"], 200)
        self.assertEqual(list(saved)[:5], ["schema_version", "adapter", "master", "nodes", "x_note"])

    def test_changed_on_disk(self):
        self.ok("POST", "/api/save", {"config": self.cfg})
        path = os.path.join(self.canopen, "canopen.json")
        doc = json.loads(read(path))
        doc["master"]["sync_period_us"] = 20000
        time.sleep(0.01)
        with open(path, "w") as f:
            json.dump(doc, f)
        self.cfg["adapter"]["bitrate"] = 500000
        status, data, _ = self.request("POST", "/api/save", {"config": self.cfg})
        self.assertEqual(status, 409)
        self.assertTrue(data["changed_on_disk"])
        self.assertEqual(json.loads(read(path))["master"]["sync_period_us"], 20000)
        self.ok("POST", "/api/save", {"config": self.cfg, "overwrite": True})
        self.assertEqual(json.loads(read(path))["adapter"]["bitrate"], 500000)

    def test_adapter_and_sdo_round_trip(self):
        self.cfg["adapter"] = {"type": "socketcan", "interface": "can0", "bitrate": 250000, "configure_link": True,
                               "restart_ms": 100}
        self.cfg["master"]["sync_period_us"] = 10000
        self.cfg["nodes"][0]["sdo"] = [{"index": "0x6110", "subindex": 1, "type": "UNSIGNED16", "value": "0x1E"}]
        self.ok("POST", "/api/save", {"config": self.cfg})
        saved = json.loads(read(os.path.join(self.canopen, "canopen.json")))
        self.assertEqual(saved["adapter"], self.cfg["adapter"])
        self.assertEqual(saved["nodes"][0]["sdo"][0],
                         {"index": "0x6110", "subindex": 1, "type": "UNSIGNED16", "value": "0x1E"})
        # A read-only object and an out-of-range value are refused.
        self.cfg["nodes"][0]["sdo"] = [{"index": "0x1018", "subindex": 1, "type": "UNSIGNED32", "value": 1}]
        self.assertEqual(self.request("POST", "/api/save", {"config": self.cfg})[0], 422)
        self.cfg["nodes"][0]["sdo"] = [{"index": "0x6112", "subindex": 1, "type": "UNSIGNED8", "value": 300}]
        status, data, _ = self.request("POST", "/api/save", {"config": self.cfg})
        self.assertEqual(status, 422)
        self.assertEqual(data["check"]["items"][0]["paths"], ["nodes[0].sdo[0].value"])

    def test_deploy_tool_accepts_the_result(self):
        self.ok("POST", "/api/save", {"config": self.cfg})
        before = read(os.path.join(self.canopen, "canopen.json"))
        env = dict(os.environ, PYTHONPATH=DEPLOY)
        bundle = editor_bundle(os.path.join(self.dir, "bundle"))
        r = subprocess.run([sys.executable, "-m", "openplc_canopen_deploy", "--bundle", bundle, "--config",
                            os.path.join(self.canopen, "canopen.json"), "--check-only"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read(os.path.join(self.canopen, "canopen.json")), before)

    def test_place(self):
        self.cfg["nodes"][0]["tx_pdos"] = []
        data = self.ok("POST", "/api/place", {"config": self.cfg, "node": 0, "direction": "input", "type": "INTEGER16"})
        self.assertEqual(data, {"location": "%IW100", "pdo": 0, "reason": None})
        data = self.ok("POST", "/api/place", {"config": self.cfg, "node": 0, "direction": "output", "type": "UNSIGNED8"})
        self.assertIsNone(data["pdo"])
        self.assertIn("no PDO", data["reason"])
        data = self.ok("POST", "/api/place", {"config": self.cfg, "node": 0, "direction": "status"})
        self.assertEqual(data["location"], "%IX100.0")
        data = self.ok("POST", "/api/place", {"config": self.cfg, "node": 0, "direction": "state"})
        self.assertEqual(data["location"], "%IB100")
        self.cfg["nodes"][0]["state_location"] = "%IB100"
        data = self.ok("POST", "/api/place", {"config": self.cfg, "node": 0, "direction": "boot_error"})
        self.assertEqual(data["location"], "%IB101")
        data = self.ok("POST", "/api/place", {"config": self.cfg, "direction": "state_location"})
        self.assertEqual(data, {"location": "%IB101"})
        del self.cfg["nodes"][0]["state_location"]
        # NMT command byte and SDO variable locations.
        data = self.ok("POST", "/api/place", {"config": self.cfg, "node": 0, "direction": "nmt"})
        self.assertEqual(data, {"location": "%QB100"})
        self.cfg["nodes"][0]["sdo_variables"] = [{"index": "0x2000", "type": "UNSIGNED8", "direction": "write",
                                                  "iec_location": "%QB101"}]
        data = self.ok("POST", "/api/place", {"config": self.cfg, "node": 0, "direction": "sdo_write",
                                              "type": "UNSIGNED8"})
        self.assertEqual(data, {"location": "%QB100"})
        data = self.ok("POST", "/api/place", {"config": self.cfg, "node": 0, "direction": "sdo_read",
                                              "type": "INTEGER32"})
        self.assertEqual(data, {"location": "%ID101"})  # the config already uses %ID100
        for direction, want in (("sdo_trigger", "%QX100.0"), ("sdo_status", "%IB100"), ("sdo_abort", "%ID101")):
            self.assertEqual(self.ok("POST", "/api/place", {"config": self.cfg, "node": 0, "direction": direction}),
                             {"location": want})
        del self.cfg["nodes"][0]["sdo_variables"]
        # Master bus diagnostics need no node.
        data = self.ok("POST", "/api/place", {"config": self.cfg, "direction": "bus_state_location"})
        self.assertEqual(data, {"location": "%IB100"})
        self.cfg["master"]["bus_state_location"] = "%IB100"
        data = self.ok("POST", "/api/place", {"config": self.cfg, "direction": "tx_error_count_location"})
        self.assertEqual(data, {"location": "%IB101"})
        data = self.ok("POST", "/api/place", {"config": self.cfg, "direction": "bus_off_count_location"})
        self.assertEqual(data["location"][:3], "%IW")
        # EMCY inputs: a word, and the byte after the bus state byte.
        data = self.ok("POST", "/api/place", {"config": self.cfg, "node": 0, "direction": "emcy"})
        self.assertEqual(data["location"], "%IW100")
        data = self.ok("POST", "/api/place", {"config": self.cfg, "node": 0, "direction": "errreg"})
        self.assertEqual(data["location"], "%IB101")


TWO = os.path.join(REPO, "config", "two-networks")


class Networks(Running):
    """Several networks (add-several-can-networks task 6.1): the lowest
    schema version on save, exports and suggestions per network."""

    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.dir, "plant")
        os.makedirs(self.folder)
        shutil.copy(os.path.join(TWO, "cpp-slave.eds"), self.folder)
        self.path = os.path.join(self.folder, "canopen.json")
        self.two = json.loads(read(os.path.join(TWO, "canopen_config.json")))
        self.two["diagnostics"] = {"token_verifier": FIXTURE_VERIFIER, "port": 7600}

    def open(self, cfg):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return self.ok("POST", "/api/open", {"path": self.folder, "mode": "standalone"})

    def saved(self):
        return json.loads(read(self.path))

    def one(self):
        """The two-network config's io network as a version 1 file."""
        net = self.two["networks"][0]
        master = dict(net["master"], diagnostics=self.two["diagnostics"])
        return {"schema_version": 1, "adapter": net["adapter"], "master": master, "nodes": net["nodes"]}

    def test_one_network_round_trip_is_byte_identical(self):
        state = self.open(self.one())
        self.ok("POST", "/api/save", {"config": state["config"]})
        before = read(self.path)
        # Saved again as loaded, and as the page's network list sends it
        # (version 2, one network named after its interface): the same bytes.
        state = self.ok("POST", "/api/reload")
        self.ok("POST", "/api/save", {"config": state["config"]})
        self.assertEqual(read(self.path), before)
        cfg = state["config"]
        master = {k: v for k, v in cfg["master"].items() if k != "diagnostics"}
        v2 = {"schema_version": 2, "networks": [{"name": "vcan0", "adapter": cfg["adapter"], "master": master,
                                                  "nodes": cfg["nodes"]}],
              "diagnostics": cfg["master"]["diagnostics"]}
        self.ok("POST", "/api/save", {"config": v2})
        self.assertEqual(read(self.path), before)
        self.assertEqual(list(self.saved()), ["schema_version", "adapter", "master", "nodes"])
        self.assertEqual(self.saved()["master"]["diagnostics"]["port"], 7600)

    def test_second_network_saves_version_2(self):
        self.open(self.one())
        cfg = self.two
        data = self.ok("POST", "/api/check", {"config": cfg})
        self.assertEqual(data["errors"], 0, data["items"])
        self.ok("POST", "/api/save", {"config": cfg})
        saved = self.saved()
        self.assertEqual(list(saved), ["schema_version", "networks", "diagnostics"])
        self.assertEqual(saved["schema_version"], 2)
        self.assertEqual([n["name"] for n in saved["networks"]], ["io", "drives"])
        self.assertEqual(list(saved["networks"][0]), ["name", "adapter", "master", "nodes"])
        self.assertNotIn("diagnostics", saved["networks"][0]["master"])
        self.assertEqual(saved["diagnostics"], {"token_verifier": FIXTURE_VERIFIER, "port": 7600})
        state = self.ok("POST", "/api/reload")
        self.assertEqual(state["config"]["schema_version"], 2)
        self.assertEqual(state["unused_eds"], [])

    def test_back_to_one_network_saves_version_1(self):
        self.open(self.two)
        cfg = json.loads(json.dumps(self.two))
        del cfg["networks"][1]
        del cfg["networks"][0]["name"]
        self.ok("POST", "/api/save", {"config": cfg})
        saved = self.saved()
        self.assertEqual(saved["schema_version"], 1)
        self.assertEqual(list(saved), ["schema_version", "adapter", "master", "nodes"])
        self.assertEqual(saved["master"]["diagnostics"]["port"], 7600)
        # A name of its own needs version 2.
        cfg["networks"][0]["name"] = "io"
        self.ok("POST", "/api/save", {"config": cfg})
        self.assertEqual(self.saved()["schema_version"], 2)

    def test_check_names_the_network(self):
        cfg = self.two
        cfg["networks"][1]["nodes"][0]["status_location"] = "%IX10.0"  # io's node uses it
        cfg["networks"][1]["adapter"]["interface"] = "vcan0"
        self.open(self.one())
        data = self.ok("POST", "/api/check", {"config": cfg})
        paths = [p for i in data["items"] if i["level"] == "error" for p in i["paths"]]
        self.assertIn("networks[1].nodes[0].status_location", paths)
        self.assertIn("networks[1].adapter.interface", paths)
        text = "\n".join(i["message"] for i in data["items"])
        self.assertIn("drives", text)

    def test_place_skips_every_network(self):
        self.open(self.two)
        cfg = self.two
        cfg["networks"][1]["nodes"][0]["tx_pdos"] = []
        # io uses %IW100: a 16-bit input of drives goes elsewhere.
        cfg["networks"][0]["nodes"][0]["tx_pdos"][0]["entries"][0].update(type="UNSIGNED16", iec_location="%IW100")
        got = self.ok("POST", "/api/place", {"config": cfg, "network": 1, "node": 0, "direction": "input",
                                             "type": "UNSIGNED16"})
        self.assertEqual(got["location"], "%IW101")
        got = self.ok("POST", "/api/place", {"config": cfg, "network": 1, "node": 0, "direction": "state"})
        self.assertEqual(got["location"], "%IB100")
        cfg["networks"][0]["nodes"][0]["state_location"] = "%IB100"
        got = self.ok("POST", "/api/place", {"config": cfg, "network": 1, "node": 0, "direction": "state"})
        self.assertEqual(got["location"], "%IB101")
        self.assertEqual(self.request("POST", "/api/place", {"config": cfg, "network": 2, "node": 0,
                                                             "direction": "state"})[0], 400)

    def test_exports_per_network(self):
        import io
        import zipfile
        self.open(self.two)
        cfg = self.two
        data = self.ok("POST", "/api/export_dbc", {"config": cfg, "network": "drives"})
        self.assertEqual((data["errors"], data["name"]), (0, "plant_drives.dbc"))
        self.assertIn("drives", base64.b64decode(data["data"]).decode("ascii"))
        self.assertEqual(self.request("POST", "/api/export_dbc", {"config": cfg})[0], 400)
        data = self.ok("POST", "/api/export_dcf", {"config": cfg})
        self.assertEqual(data["name"], "plant_dcf.zip")
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(data["data"]))) as z:
            self.assertEqual(sorted(z.namelist()), ["drives/node_2.dcf", "io/node_2.dcf"])
        data = self.ok("POST", "/api/export_dcf", {"config": cfg, "network": "drives"})
        self.assertEqual((data["name"], data["files"]), ("plant_drives_dcf.zip", ["node_2.dcf"]))
        data = self.ok("POST", "/api/export_dcf", {"config": cfg, "network": "io", "node": 2})
        self.assertEqual(data["name"], "node_2.dcf")
        self.assertEqual(self.request("POST", "/api/export_dcf", {"config": cfg, "node": 2})[0], 400)
        data = self.ok("POST", "/api/export_html", {"config": cfg})
        self.assertEqual(data["name"], "plant.html")
        text = base64.b64decode(data["data"]).decode("utf-8")
        self.assertIn('id="net-io"', text)
        self.assertIn('id="net-drives"', text)
        self.assertNotIn("ab" * 32, text)


class Standalone(Running):
    def test_save_then_move_into_project(self):
        folder = os.path.join(self.dir, "canopen-rtd")
        state = self.ok("POST", "/api/open", {"path": folder, "mode": "standalone"})
        self.assertFalse(os.path.exists(folder))
        self.assertEqual(state["project_uses"], [])
        self.assertEqual(self.eds(os.path.join(RTD, "rtd8.eds"))[0], 200)
        cfg = srv.empty_config()
        cfg["nodes"] = [rtd_node()]
        # Not saved yet: moving is refused.
        self.assertEqual(self.request("POST", "/api/move", {"project": self.project})[0], 409)
        self.ok("POST", "/api/save", {"config": cfg})
        self.assertTrue(os.path.isfile(os.path.join(folder, "canopen.json")))
        self.assertTrue(os.path.isfile(os.path.join(folder, "rtd8.eds")))
        data = self.ok("POST", "/api/move", {"project": self.project})
        self.assertEqual(data["state"]["mode"], "project")
        self.assertEqual(data["state"]["folder"], self.project)
        self.assertTrue(data["state"]["project_uses"])
        moved = json.loads(read(os.path.join(self.project, "canopen", "canopen.json")))
        self.assertEqual(moved["nodes"][0]["eds"], "rtd8.eds")
        # Address checks now run against the project.
        moved["nodes"][0]["tx_pdos"][0]["entries"][0]["iec_location"] = "%IW200"
        data = self.ok("POST", "/api/check", {"config": moved})
        self.assertTrue(any("io-rack.json" in i["message"] for i in data["items"]))

    def test_move_asks_before_replacing(self):
        folder = os.path.join(self.dir, "canopen-rtd")
        self.ok("POST", "/api/open", {"path": folder, "mode": "standalone"})
        self.eds(os.path.join(RTD, "rtd8.eds"))
        cfg = srv.empty_config()
        cfg["nodes"] = [rtd_node()]
        self.ok("POST", "/api/save", {"config": cfg})
        os.makedirs(os.path.join(self.project, "canopen"))
        status, data, _ = self.request("POST", "/api/move", {"project": self.project})
        self.assertEqual(status, 409)
        self.assertTrue(data["exists"])
        self.assertEqual(os.listdir(os.path.join(self.project, "canopen")), [])
        self.ok("POST", "/api/move", {"project": self.project, "replace": True})
        self.assertTrue(os.path.isfile(os.path.join(self.project, "canopen", "canopen.json")))


class NewProject(Running):
    """POST /api/new_project (add-editor-project-template task 4.1)."""

    def setUp(self):
        super().setUp()
        cli = fake_editor_cli(self.dir)
        os.environ["OPENPLC_CLI"] = cli
        self.addCleanup(os.environ.pop, "OPENPLC_CLI", None)
        self.folder = os.path.join(self.dir, "canopen-rtd")
        self.work = os.path.join(self.dir, "work")
        os.makedirs(self.work)
        self.ok("POST", "/api/open", {"path": self.folder, "mode": "standalone"})
        self.eds(os.path.join(RTD, "rtd8.eds"))
        self.cfg = srv.empty_config()
        self.cfg["nodes"] = [rtd_node()]

    def test_create_and_switch(self):
        self.assertEqual(self.request("POST", "/api/new_project", {"parent": self.work, "name": "rtd-monitor"},
                                      token="wrong")[0], 403)
        # Not saved yet: refused.
        status, data, _ = self.request("POST", "/api/new_project", {"parent": self.work, "name": "rtd-monitor"})
        self.assertEqual(status, 409)
        self.assertTrue(data["unsaved"])
        self.ok("POST", "/api/save", {"config": self.cfg})
        before = sorted(os.listdir(self.folder))
        self.ok("POST", "/api/online/settings", {"host": "plc.local:7778"})
        data = self.ok("POST", "/api/new_project", {"parent": self.work, "name": "rtd-monitor",
                                                    "interval": "T#10ms"})
        target = os.path.join(self.work, "rtd-monitor")
        self.assertEqual(data["project"], target)
        self.assertEqual(data["declared"], 5)
        self.assertEqual(data["state"]["mode"], "project")
        self.assertEqual(data["state"]["folder"], target)
        self.assertEqual(sorted(os.listdir(self.folder)), before)
        device = json.loads(read(os.path.join(target, "devices", "configuration.json")))
        self.assertEqual((device["deviceBoard"], device["runtimeIpAddress"]), ("OpenPLC Runtime v4", "plc.local"))
        args = json.loads(read(os.path.join(self.dir, "cli-args.json")))
        self.assertIn("--time=T#10ms", args)
        # Every CANopen entry now shows as declared in the project.
        cfg = json.loads(read(os.path.join(target, "canopen", "canopen.json")))
        check = self.ok("POST", "/api/check", {"config": cfg})
        self.assertEqual(check["errors"], 0, check["items"])
        self.assertEqual(len(check["declared"]), 5)
        self.assertEqual(check["block"], "")

    def test_refusals(self):
        self.ok("POST", "/api/save", {"config": self.cfg})
        os.makedirs(os.path.join(self.work, "taken"))
        status, data, _ = self.request("POST", "/api/new_project", {"parent": self.work, "name": "taken"})
        self.assertEqual(status, 409)
        self.assertTrue(data["exists"])
        self.assertEqual(os.listdir(os.path.join(self.work, "taken")), [])
        for name in ("", "a/b", ".."):
            self.assertEqual(self.request("POST", "/api/new_project", {"parent": self.work, "name": name})[0], 422)
        status, data, _ = self.request("POST", "/api/new_project",
                                       {"parent": self.work, "name": "x", "interval": "10ms"})
        self.assertEqual(status, 422)
        self.assertIn("IEC duration", data["error"])
        self.assertFalse(os.path.exists(os.path.join(self.work, "x")))
        state = self.ok("GET", "/api/state")
        self.assertEqual(state["mode"], "standalone")
        # Only from a standalone config.
        self.open_project()
        self.assertEqual(self.request("POST", "/api/new_project", {"parent": self.work, "name": "y"})[0], 400)


class Command(unittest.TestCase):
    def test_help_as_documented(self):
        env = dict(os.environ, PYTHONPATH=DEPLOY)
        r = subprocess.run([sys.executable, "-m", "openplc_canopen_deploy.configurator.server", "--help"],
                           capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertIn("--no-browser", r.stdout)

    def test_refuses_a_file_path_and_prints_url(self):
        d = tmpdir(self)
        f = os.path.join(d, "file")
        open(f, "w").close()
        env = dict(os.environ, PYTHONPATH=DEPLOY, OPENPLC_CANOPEN_CONFIG_DIR=os.path.join(d, "cfg"))
        r = subprocess.run([sys.executable, "-m", "openplc_canopen_deploy.configurator.server", f, "--no-browser"],
                           capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 2)
        self.assertIn("is not a folder", r.stderr)

    def test_starts_on_a_project(self):
        d = tmpdir(self)
        project = os.path.join(d, "p")
        shutil.copytree(FIXTURE, project)
        env = dict(os.environ, PYTHONPATH=DEPLOY, OPENPLC_CANOPEN_CONFIG_DIR=os.path.join(d, "cfg"))
        p = subprocess.Popen([sys.executable, "-m", "openplc_canopen_deploy.configurator.server", project,
                              "--no-browser"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        try:
            line = p.stdout.readline()
            self.assertIn("http://127.0.0.1:", line)
            url = line.split()[-1]
            port = int(url.split(":")[2].split("/")[0])
            token = url.split("token=")[1]
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("GET", "/api/state", headers={srv.TOKEN_HEADER: token, "Host": "127.0.0.1:%d" % port})
            state = json.loads(c.getresponse().read())
            self.assertEqual((state["mode"], state["folder"]), ("project", project))
            c.request("POST", "/api/quit", "{}", {srv.TOKEN_HEADER: token, "Host": "127.0.0.1:%d" % port,
                                                  "Content-Type": "application/json"})
            c.getresponse().read()
            self.assertEqual(p.wait(timeout=10), 0)
        finally:
            if p.poll() is None:
                p.kill()
            p.stdout.close()
            p.stderr.close()


if __name__ == "__main__":
    unittest.main()


class Cia402(Running):
    """add-cia402-drive-support: "Map CiA 402 objects" and the axis lines in
    the declarations."""

    def setUp(self):
        super().setUp()
        self.open_project()
        example = os.path.join(REPO, "config", "cia402-drive")
        self.assertEqual(self.eds(os.path.join(example, "servo402.eds"))[0], 200)
        self.cfg = srv.empty_config()
        self.cfg["nodes"] = [{"node_id": 4, "name": "drive", "eds": "servo402.eds", "axis": {}}]

    def test_map_and_declarations(self):
        data = self.ok("POST", "/api/map_cia402", {"config": self.cfg, "node": 0})
        self.assertEqual(data["missing"], [])
        self.assertEqual(data["node"]["status_location"], "%IX100.0")
        self.assertEqual(data["node"]["rx_pdos"][1]["entries"][1]["index"], "0x6081")
        self.assertNotIn("rx_pdos", self.cfg["nodes"][0])
        self.cfg["nodes"][0] = data["node"]
        self.cfg["nodes"][0]["heartbeat_ms"] = 50
        checked = self.ok("POST", "/api/check", {"config": self.cfg})
        self.assertEqual(checked["errors"], 0, checked["items"])
        self.assertIn("drive_Statusword", checked["block"])
        self.assertIn("  drive        : AXIS_REF_SM3;", checked["block"])
        self.assertIn("drive_bridge(Axis := drive,", checked["block"])

    def test_cyclic_map_and_declarations(self):
        # add-cia402-cyclic-modes: the cyclic layout with transmission type 1,
        # the SYNC check, and the cycle time line from the task interval.
        self.cfg["nodes"][0]["axis"] = {"cyclic": True}
        data = self.ok("POST", "/api/map_cia402", {"config": self.cfg, "node": 0})
        node = data["node"]
        self.assertEqual([e["index"] for e in node["rx_pdos"][0]["entries"]], ["0x6040", "0x6060", "0x607A"])
        self.assertEqual([e["index"] for e in node["tx_pdos"][0]["entries"]], ["0x6041", "0x6061", "0x6064"])
        self.assertEqual([c["pdo"] for c in data["changes"]], ["RPDO1", "RPDO2", "TPDO1", "TPDO2", "RPDO3"])
        self.assertEqual({c["was"] for c in data["changes"]}, {255})
        self.assertTrue(all(p["transmission"] == 1 for p in node["rx_pdos"] + node["tx_pdos"]))
        self.cfg["nodes"][0] = node
        self.cfg["nodes"][0]["heartbeat_ms"] = 50
        checked = self.ok("POST", "/api/check", {"config": self.cfg})
        messages = [i["message"] for i in checked["items"] if i["level"] == "error"]
        self.assertEqual(len(messages), 1, messages)
        self.assertIn("needs SYNC from the PLC cycle", messages[0])
        self.cfg["master"] = {"node_id": 1, "sync_source": "plc_cycle"}
        checked = self.ok("POST", "/api/check", {"config": self.cfg})
        self.assertEqual(checked["errors"], 0, checked["items"])
        self.assertIn("drive.fCycleTime := LREAL#0.02;", checked["block"])
        checked = self.ok("POST", "/api/check", {"config": self.cfg, "task_interval": "T#2ms"})
        self.assertIn("drive.fCycleTime := LREAL#0.002;", checked["block"])
        checked = self.ok("POST", "/api/check", {"config": self.cfg, "task_interval": "fast"})
        self.assertEqual(checked["errors"], 0)
        self.assertTrue(any(i["paths"] == ["task_interval"] for i in checked["items"]))

    def test_map_refused(self):
        status, data, _ = self.request("POST", "/api/map_cia402", {"config": self.cfg, "node": 3})
        self.assertEqual(status, 400)
        self.cfg["nodes"][0]["eds"] = "missing.eds"
        status, data, _ = self.request("POST", "/api/map_cia402", {"config": self.cfg, "node": 0})
        self.assertEqual(status, 400)
        self.assertIn("not found", data["error"])
