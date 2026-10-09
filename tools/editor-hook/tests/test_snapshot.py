"""snapshot.materialize(): the project's canworks/ folder from an editor
project snapshot into the upload's conf/ directory."""

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

from canworks import contract, simfile
from canworks_hook import snapshot

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
FIXTURES = os.path.join(REPO, "test", "fixtures")
RTD = os.path.join(REPO, "config", "rtd-sensor")

# The shared fixtures' patch format, from the deploy tool's own test.
_spec = importlib.util.spec_from_file_location(
    "deploy_test_contract", os.path.join(REPO, "tools", "deploy", "tests", "test_contract.py"))
_deploy_test = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_deploy_test)
patched, load_cases = _deploy_test.patched, _deploy_test.load_cases


def read(path):
    with open(path, "rb") as f:
        return f.read()


def rtd_project():
    """The RTD sensor config as a project's canworks/ folder: {name: bytes}."""
    with open(os.path.join(RTD, "canopen_config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    eds = cfg["nodes"][0]["eds"]
    cfg["nodes"][0]["eds"] = "eds/" + os.path.basename(eds)
    return {
        "canworks/canworks.json": json.dumps(cfg, indent=2).encode(),
        "canworks/eds/" + os.path.basename(eds): read(os.path.join(RTD, eds)),
    }


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.conf = os.path.join(self.tmp, "core", "generated", "conf")
        os.makedirs(self.conf)
        with open(os.path.join(self.conf, "ethercat.json"), "w") as f:
            f.write("{}\n")

    def snapshot(self, files, prefix="", symlinks=()):
        """A project snapshot zip; `symlinks` are (name, target) entries."""
        path = os.path.join(self.tmp, "project.zip")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(prefix + "project.json", b"{}")
            for name, data in files.items():
                z.writestr(prefix + name, data)
            for name, target in symlinks:
                info = zipfile.ZipInfo(prefix + name)
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(info, target)
        return path

    def conf_files(self):
        out = []
        for root, _, files in os.walk(self.conf):
            out += [os.path.relpath(os.path.join(root, f), self.conf) for f in files]
        return sorted(out)

    def assertIgnored(self, files, reason, **kw):
        applied, messages = snapshot.materialize(self.snapshot(files, **kw), self.conf)
        self.assertFalse(applied)
        self.assertEqual(self.conf_files(), ["ethercat.json"], "nothing may be written")
        self.assertEqual(len(messages), 1, messages)
        level, text = messages[0]
        self.assertEqual(level, "WARNING")
        self.assertTrue(text.startswith("CANopen: project config ignored: "), text)
        self.assertIn(reason, text)
        return text


class Materialize(Base):
    def check_applied(self, prefix):
        project = rtd_project()
        applied, messages = snapshot.materialize(self.snapshot(project, prefix), self.conf)
        self.assertTrue(applied, messages)
        self.assertEqual(self.conf_files(), ["canworks.json", "canworks/eds/rtd8.eds", "ethercat.json"])
        with open(os.path.join(self.conf, "canworks.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["nodes"][0]["eds"], "canworks/eds/rtd8.eds")
        self.assertEqual(read(os.path.join(self.conf, "canworks", "eds", "rtd8.eds")),
                         project["canworks/eds/rtd8.eds"])
        self.assertEqual(messages[-1], ("INFO", "CANopen: config taken from the project snapshot "
                                                "(canworks/canworks.json, 1 EDS file)"))
        # The written config passes the deploy tool's checks where it now lives.
        r = contract.check_config(cfg, os.path.join(self.conf, "canworks.json"))
        self.assertTrue(r.ok, r.errors)

    def test_project_at_zip_root(self):
        self.check_applied("")

    def test_project_in_one_folder(self):
        self.check_applied("rtd-monitor/")

    def test_stale_files_replaced(self):
        os.makedirs(os.path.join(self.conf, "canworks", "eds"))
        with open(os.path.join(self.conf, "canworks", "eds", "old.eds"), "w") as f:
            f.write("old")
        self.check_applied("")

    def test_program_file(self):
        project = rtd_project()
        cfg = json.loads(project["canworks/canworks.json"])
        cfg["nodes"][0].update(software_file="fw/rtd.hex", software_version=2)
        project["canworks/canworks.json"] = json.dumps(cfg).encode()
        project["canworks/fw/rtd.hex"] = b":10010000214601360121470136007EFE09D2190140\n"
        applied, messages = snapshot.materialize(self.snapshot(project), self.conf)
        self.assertTrue(applied, messages)
        self.assertIn("canworks/fw/rtd.hex", self.conf_files())
        with open(os.path.join(self.conf, "canworks.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["nodes"][0]["software_file"], "canworks/fw/rtd.hex")
        self.assertEqual(read(os.path.join(self.conf, "canworks", "fw", "rtd.hex")), project["canworks/fw/rtd.hex"])

    def test_program_file_corrupted_by_the_editor(self):
        project = rtd_project()
        cfg = json.loads(project["canworks/canworks.json"])
        cfg["nodes"][0].update(software_file="fw/rtd.bin", software_version=2)
        project["canworks/canworks.json"] = json.dumps(cfg).encode()
        project["canworks/fw/rtd.bin"] = b"\x02\x00" + "\ufffd".encode() + b"\x00"
        self.assertIgnored(project, "canworks/fw/rtd.bin was corrupted")

    def test_no_canopen_folder(self):
        path = self.snapshot({"src/main.st": b"PROGRAM main END_PROGRAM"})
        self.assertEqual(snapshot.materialize(path, self.conf), (False, []))
        self.assertEqual(self.conf_files(), ["ethercat.json"])

    def test_no_snapshot(self):
        self.assertEqual(snapshot.materialize(os.path.join(self.tmp, "none.zip"), self.conf), (False, []))

    def test_not_a_zip(self):
        path = os.path.join(self.tmp, "project.zip")
        with open(path, "wb") as f:
            f.write(b"not a zip")
        applied, messages = snapshot.materialize(path, self.conf)
        self.assertFalse(applied)
        self.assertIn("cannot read the project snapshot", messages[0][1])

    def test_missing_eds(self):
        project = rtd_project()
        del project["canworks/eds/rtd8.eds"]
        self.assertIgnored(project, "canworks/eds/rtd8.eds is missing from the project")

    def test_invalid_json(self):
        project = rtd_project()
        project["canworks/canworks.json"] = b'{"nodes": [}'
        self.assertIgnored(project, "canworks/canworks.json is not valid JSON")

    def test_schema_failure(self):
        project = rtd_project()
        cfg = json.loads(project["canworks/canworks.json"])
        cfg["nodes"][0]["node_id"] = 200
        project["canworks/canworks.json"] = json.dumps(cfg).encode()
        self.assertIgnored(project, "canworks/canworks.json: nodes[0]")

    def test_paths_outside_canopen(self):
        for bad in ("../rtd8.eds", "/etc/rtd8.eds", "eds/../../x.eds", "C:/x.eds",
                    "eds\\rtd8.eds", "./eds/rtd8.eds"):
            with self.subTest(bad):
                project = rtd_project()
                cfg = json.loads(project["canworks/canworks.json"])
                cfg["nodes"][0]["eds"] = bad
                project["canworks/canworks.json"] = json.dumps(cfg).encode()
                self.assertIgnored(project, "invalid EDS path")

    def test_symlink_entries(self):
        project = rtd_project()
        eds = project.pop("canworks/eds/rtd8.eds")
        self.assertIgnored(project, "canworks/eds/rtd8.eds is missing",
                           symlinks=[("canworks/eds/rtd8.eds", b"/etc/passwd")])
        project["canworks/eds/rtd8.eds"] = eds
        cfg = project.pop("canworks/canworks.json")
        self.assertIgnored(project, "canworks/canworks.json is not a regular file",
                           symlinks=[("canworks/canworks.json", b"/etc/passwd")])
        del cfg

    def test_size_cap(self):
        project = rtd_project()
        with mock.patch.object(snapshot, "MAX_TOTAL_BYTES", 4096):
            self.assertIgnored(project, "larger than")

    def test_same_name_different_eds(self):
        project = rtd_project()
        cfg = json.loads(project["canworks/canworks.json"])
        node = dict(cfg["nodes"][0], node_id=6, name="rtd2", eds="other/rtd8.eds")
        for pdo in node.get("tx_pdos", []) + node.get("rx_pdos", []):
            for e in pdo["entries"]:
                e["iec_location"] = e["iec_location"].replace("%IW10", "%IW20").replace("%IB10", "%IB20")
        node.pop("status_location", None)
        cfg["nodes"].append(node)
        project["canworks/canworks.json"] = json.dumps(cfg).encode()
        project["canworks/other/rtd8.eds"] = project["canworks/eds/rtd8.eds"] + b"; changed\n"
        self.assertIgnored(project, "two different EDS files are both named rtd8.eds")


class Simulation(Base):
    """canworks/simulation.json travels with the config, in the deploy
    tool's layout."""

    def project(self, sim=None, simulate=False):
        project = rtd_project()
        if simulate:
            cfg = json.loads(project["canworks/canworks.json"])
            cfg["adapter"]["simulate"] = True
            project["canworks/canworks.json"] = json.dumps(cfg).encode()
        project["canworks/devices/pingpong.eds"] = read(os.path.join(FIXTURES, "eds", "cpp-slave.eds"))
        project["canworks/data/temp.csv"] = b"time,value\n0,200\n10,260\n"
        if sim is None:
            sim = {
                "schema_version": 1,
                "nodes": {"5": {"sources": {
                    "0x7130:1": {"sine": {"min": 200, "max": 260, "period_s": 10}},
                    "0x7130:2": {"csv": {"file": "data/temp.csv", "interpolate": "linear", "loop": True}}}}},
                "extra_devices": [{"node": 40, "name": "pp", "eds": "devices/pingpong.eds"}],
            }
        project["canworks/simulation.json"] = json.dumps(sim).encode()
        return project

    def test_carried_and_rewritten(self):
        project = self.project(simulate=True)
        applied, messages = snapshot.materialize(self.snapshot(project), self.conf)
        self.assertTrue(applied, messages)
        self.assertEqual(self.conf_files(), ["canworks.json", "canworks/eds/pingpong.eds", "canworks/eds/rtd8.eds",
                                             "canworks/sim/temp.csv", "canworks/simulation.json", "ethercat.json"])
        with open(os.path.join(self.conf, "canworks", "simulation.json"), encoding="utf-8") as f:
            sim = json.load(f)
        self.assertEqual(sim["extra_devices"][0]["eds"], "eds/pingpong.eds")
        self.assertEqual(sim["nodes"]["5"]["sources"]["0x7130:2"]["csv"]["file"], "sim/temp.csv")
        self.assertEqual(sim["nodes"]["5"]["sources"]["0x7130:1"],
                         json.loads(project["canworks/simulation.json"])["nodes"]["5"]["sources"]["0x7130:1"])
        self.assertEqual(read(os.path.join(self.conf, "canworks", "eds", "pingpong.eds")),
                         project["canworks/devices/pingpong.eds"])
        self.assertEqual(read(os.path.join(self.conf, "canworks", "sim", "temp.csv")),
                         project["canworks/data/temp.csv"])
        self.assertIn(("INFO", "CANopen: simulation file carried (canworks/simulation.json, 1 extra device EDS "
                               "file, 1 CSV file)"), messages)
        sims = [t for level, t in messages if level == "WARNING" and "simulates devices" in t]
        self.assertEqual(len(sims), 1, messages)
        self.assertIn("the network is simulated", sims[0])
        # The written simulation file passes the deploy tool's checks where it now lives.
        with open(os.path.join(self.conf, "canworks.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        _, r = simfile.check_file(os.path.join(self.conf, "canworks", "simulation.json"), cfg,
                                  os.path.join(self.conf, "canworks.json"))
        self.assertTrue(r.ok, r.errors)

    def test_carried_when_nothing_is_simulated(self):
        applied, messages = snapshot.materialize(self.snapshot(self.project()), self.conf)
        self.assertTrue(applied, messages)
        self.assertIn("canworks/simulation.json", self.conf_files())
        self.assertFalse([t for _, t in messages if "simulates devices" in t], messages)
        self.assertIn("the config simulates nothing", messages[-1][1])

    def test_bad_simulation_file_rejects_the_config(self):
        sim = {"schema_version": 1, "nodes": {"5": {"sources": {"0x7130:1": {"constant": 1}}}}, "bogus": 1}
        self.assertIgnored(self.project(sim), "canworks/simulation.json: ")
        # Schema-valid, but the object is not in the node's EDS.
        sim = {"schema_version": 1, "nodes": {"5": {"sources": {"0x7FFF:1": {"constant": 1}}}}}
        self.assertIgnored(self.project(sim), "canworks/simulation.json: ")

    def test_invalid_json(self):
        project = self.project()
        project["canworks/simulation.json"] = b"{"
        self.assertIgnored(project, "canworks/simulation.json is not valid JSON")

    def test_missing_csv(self):
        project = self.project()
        del project["canworks/data/temp.csv"]
        self.assertIgnored(project, "canworks/data/temp.csv is missing from the project "
                                    "(named by canworks/simulation.json)")

    def test_paths_outside_canopen(self):
        for bad in ("../pingpong.eds", "/etc/pingpong.eds", "devices/../../x.eds", "./devices/pingpong.eds"):
            with self.subTest(bad):
                sim = json.loads(self.project()["canworks/simulation.json"])
                sim["extra_devices"][0]["eds"] = bad
                self.assertIgnored(self.project(sim), "canworks/simulation.json: invalid EDS path")
        sim = json.loads(self.project()["canworks/simulation.json"])
        sim["nodes"]["5"]["sources"]["0x7130:2"]["csv"]["file"] = "../temp.csv"
        self.assertIgnored(self.project(sim), "canworks/simulation.json: invalid CSV file path")

    def test_size_cap(self):
        project = self.project()
        project["canworks/data/temp.csv"] = b"time,value\n" + b"0,1\n" * 4096
        size = sum(len(v) for k, v in project.items() if k != "canworks/data/temp.csv")
        with mock.patch.object(snapshot, "MAX_TOTAL_BYTES", size + 1024):
            self.assertIgnored(project, "larger than")

    def test_extra_device_eds_name_clash(self):
        project = self.project()
        project["canworks/devices/rtd8.eds"] = project.pop("canworks/devices/pingpong.eds")
        sim = json.loads(project["canworks/simulation.json"])
        sim["extra_devices"][0]["eds"] = "devices/rtd8.eds"
        project["canworks/simulation.json"] = json.dumps(sim).encode()
        self.assertIgnored(project, "two different EDS files are both named rtd8.eds")

    def test_no_simulation_file_leaves_none_behind(self):
        os.makedirs(os.path.join(self.conf, "canworks", "sim"))
        for name in ("simulation.json", os.path.join("sim", "old.csv")):
            with open(os.path.join(self.conf, "canworks", name), "w") as f:
                f.write("{}")
        applied, messages = snapshot.materialize(self.snapshot(rtd_project()), self.conf)
        self.assertTrue(applied, messages)
        self.assertEqual(self.conf_files(), ["canworks.json", "canworks/eds/rtd8.eds", "ethercat.json"])
        self.assertFalse([t for _, t in messages if "simulat" in t], messages)


class MachineFile(Base):
    """A machine file the simulation file's section names travels next to
    it (examples/gantry-cell's network as a version 1 config, whose section
    is its interface)."""

    def project(self, sim=None, machine=None):
        gantry = os.path.join(REPO, "examples", "gantry-cell", "canworks")
        project = {"canworks/" + n: read(os.path.join(gantry, n)) for n in ("servo402.eds", "dio16.eds", "machine.json")}
        with open(os.path.join(gantry, "canworks.json"), encoding="utf-8") as f:
            net = json.load(f)["networks"][0]
        cfg = {"schema_version": 1, "adapter": net["adapter"], "master": net["master"], "nodes": net["nodes"]}
        project["canworks/canworks.json"] = json.dumps(cfg).encode()
        if machine is not None:
            project["canworks/machine.json"] = json.dumps(machine).encode()
        sim = sim or {"schema_version": 2, "networks": {"sim1": {"machine": "machine.json"}}}
        project["canworks/simulation.json"] = json.dumps(sim).encode()
        return project

    def test_carried(self):
        project = self.project()
        applied, messages = snapshot.materialize(self.snapshot(project), self.conf)
        self.assertTrue(applied, messages)
        self.assertIn("canworks/machine.json", self.conf_files())
        self.assertEqual(read(os.path.join(self.conf, "canworks", "machine.json")), project["canworks/machine.json"])
        with open(os.path.join(self.conf, "canworks", "simulation.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["networks"]["sim1"]["machine"], "machine.json")
        self.assertIn(("INFO", "CANopen: simulation file carried (canworks/simulation.json, 0 extra device EDS "
                               "files, 0 CSV files, machine file machine.json)"), messages)

    def test_in_a_subfolder(self):
        project = self.project({"schema_version": 2, "networks": {"sim1": {"machine": "cells/gantry.json"}}})
        project["canworks/cells/gantry.json"] = project.pop("canworks/machine.json")
        applied, messages = snapshot.materialize(self.snapshot(project), self.conf)
        self.assertTrue(applied, messages)
        self.assertIn("canworks/cells/gantry.json", self.conf_files())

    def test_missing_bad_or_outside(self):
        project = self.project()
        del project["canworks/machine.json"]
        self.assertIgnored(project, "canworks/machine.json is missing from the project "
                                    "(named by canworks/simulation.json)")
        self.assertIgnored(self.project({"schema_version": 2, "networks": {"sim1": {"machine": "../m.json"}}}),
                           "canworks/simulation.json: invalid machine file path")
        with open(os.path.join(REPO, "examples", "gantry-cell", "canworks", "machine.json"), encoding="utf-8") as f:
            machine = json.load(f)
        machine["joints"]["x"]["node"] = 10
        self.assertIgnored(self.project(machine=machine), "joint x: node 10 (io) has no `axis`")


class IntoProject(Base):
    def test_into_project_output_is_applied(self):
        # What canworks-deploy --into-project writes, as the editor zips it.
        from canworks import project
        proj = os.path.join(self.tmp, "proj")
        os.makedirs(proj)
        with open(os.path.join(proj, "project.json"), "w") as f:
            f.write("{}")
        config = os.path.join(RTD, "canopen_config.json")
        with open(config, encoding="utf-8") as f:
            project.write(json.load(f), config, proj)
        files = {}
        for name in os.listdir(os.path.join(proj, "canworks")):
            files["canworks/" + name] = read(os.path.join(proj, "canworks", name))
        applied, messages = snapshot.materialize(self.snapshot(files), self.conf)
        self.assertTrue(applied, messages)


class Encoding(Base):
    def test_replacement_char_rejected(self):
        # A Latin-1 EDS as editor 4.3.2 puts it into the snapshot: read as
        # UTF-8 with replacement (fs.readFile(path, 'utf-8')), then encoded.
        project = rtd_project()
        latin1 = project["canworks/eds/rtd8.eds"].replace(
            b"[DeviceInfo]", "; Temperatur in \u00b0C\n[DeviceInfo]".encode("latin-1"), 1)
        self.assertIn(b"\xb0", latin1)
        project["canworks/eds/rtd8.eds"] = latin1.decode("utf-8", "replace").encode("utf-8")
        text = self.assertIgnored(project, "canworks/eds/rtd8.eds is not UTF-8")
        self.assertIn("--into-project", text)

    def test_utf8_eds_accepted(self):
        project = rtd_project()
        project["canworks/eds/rtd8.eds"] = project["canworks/eds/rtd8.eds"].replace(
            b"[DeviceInfo]", "; Temperatur in \u00b0C\n[DeviceInfo]".encode("utf-8"), 1)
        applied, messages = snapshot.materialize(self.snapshot(project), self.conf)
        self.assertTrue(applied, messages)


class Precedence(Base):
    def test_uploaded_config_wins(self):
        os.makedirs(os.path.join(self.conf, "canworks", "eds"))
        files = {"canworks.json": b'{"deployed": true}\n', "canworks/eds/a.eds": b"deployed eds"}
        for name, data in files.items():
            with open(os.path.join(self.conf, name), "wb") as f:
                f.write(data)
        applied, messages = snapshot.materialize(self.snapshot(rtd_project()), self.conf)
        self.assertFalse(applied)
        self.assertEqual(messages, [("INFO", "CANopen: the upload carries conf/canworks.json; "
                                             "the project snapshot is not used")])
        self.assertEqual(self.conf_files(), ["canworks.json", "canworks/eds/a.eds", "ethercat.json"])
        for name, data in files.items():
            self.assertEqual(read(os.path.join(self.conf, name)), data)


class SharedFixtures(Base):
    """The snapshot path reaches the deploy tool's verdict on every shared case."""

    def test_cases(self):
        doc = load_cases()
        eds_dir = os.path.join(FIXTURES, "eds")
        eds = {"canworks/" + n: read(os.path.join(eds_dir, n)) for n in os.listdir(eds_dir) if n.endswith(".eds")}
        eds.update({"canworks/fw/" + n: read(os.path.join(eds_dir, "fw", n)) for n in os.listdir(os.path.join(eds_dir, "fw"))})
        eds.update({"canworks/lint/" + n: read(os.path.join(eds_dir, "lint", n))
                    for n in os.listdir(os.path.join(eds_dir, "lint")) if n.endswith(".eds")})
        eds.update({"canworks/drives/" + n: read(os.path.join(eds_dir, "drives", n))
                    for n in os.listdir(os.path.join(eds_dir, "drives")) if n.endswith(".eds")})
        rejected = 0
        for case in doc["cases"]:
            with self.subTest(case["name"]):
                shutil.rmtree(self.conf)
                os.makedirs(self.conf)
                cfg = patched(doc["base"], case["patch"])
                files = dict(eds, **{"canworks/canworks.json": json.dumps(cfg).encode()})
                applied, messages = snapshot.materialize(self.snapshot(files), self.conf)
                tool = contract.check_config(cfg, "canworks/canworks.json", eds_dir=eds_dir)
                text = "\n".join(t for _, t in messages)
                self.assertEqual(applied, tool.ok, text)
                self.assertEqual(applied, case["verdict"] == "accept", text)
                reason = text.split("CANopen: project config ignored: ", 1)[-1]
                # Every rejection carries the deploy tool's own message:
                # all of its errors, or the EDS check that stopped it.
                if not applied:
                    rejected += 1
                    if reason.endswith("is missing from the project (named by canworks/canworks.json)"):
                        self.assertIn("not found", "; ".join(tool.errors))  # a file the config names
                    elif reason.startswith("canworks/canworks.json: "):
                        self.assertEqual(reason, "; ".join(tool.errors))
                    else:
                        self.assertIn(reason, "; ".join(tool.errors))
                for w in tool.warnings:
                    self.assertIn(w, text)
        self.assertGreater(rejected, 15)


class ChildProcess(Base):
    """The webserver side runs materialize() in the helper Python."""

    def setUp(self):
        super().setUp()
        env = {"CANWORKS_PYTHON": sys.executable,
               "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_applied(self):
        import canworks_hook as hook
        messages = hook.run_materialize(self.snapshot(rtd_project()), self.conf)
        self.assertEqual(messages[-1][0], "INFO")
        self.assertIn("config taken from the project snapshot", messages[-1][1])
        self.assertIn("canworks.json", self.conf_files())

    def test_no_snapshot_no_process(self):
        import canworks_hook as hook
        with mock.patch.object(subprocess, "run") as run:
            self.assertEqual(hook.run_materialize(os.path.join(self.tmp, "none.zip"), self.conf), [])
        run.assert_not_called()

    def test_helper_failure(self):
        import canworks_hook as hook
        with mock.patch.dict(os.environ, {"CANWORKS_PYTHON": "/bin/false"}):
            with self.assertRaises(RuntimeError) as cm:
                hook.run_materialize(self.snapshot(rtd_project()), self.conf)
        self.assertIn("exited with 1", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
