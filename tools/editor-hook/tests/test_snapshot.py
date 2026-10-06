"""snapshot.materialize(): the project's canopen/ folder from an editor
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

from openplc_canopen_deploy import contract
from openplc_canopen_hook import snapshot

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
    """The RTD sensor config as a project's canopen/ folder: {name: bytes}."""
    with open(os.path.join(RTD, "canopen_config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    eds = cfg["nodes"][0]["eds"]
    cfg["nodes"][0]["eds"] = "eds/" + os.path.basename(eds)
    return {
        "canopen/canopen.json": json.dumps(cfg, indent=2).encode(),
        "canopen/eds/" + os.path.basename(eds): read(os.path.join(RTD, eds)),
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
        self.assertEqual(self.conf_files(), ["canopen.json", "canopen/eds/rtd8.eds", "ethercat.json"])
        with open(os.path.join(self.conf, "canopen.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["nodes"][0]["eds"], "canopen/eds/rtd8.eds")
        self.assertEqual(read(os.path.join(self.conf, "canopen", "eds", "rtd8.eds")),
                         project["canopen/eds/rtd8.eds"])
        self.assertEqual(messages[-1], ("INFO", "CANopen: config taken from the project snapshot "
                                                "(canopen/canopen.json, 1 EDS file)"))
        # The written config passes the deploy tool's checks where it now lives.
        r = contract.check_config(cfg, os.path.join(self.conf, "canopen.json"))
        self.assertTrue(r.ok, r.errors)

    def test_project_at_zip_root(self):
        self.check_applied("")

    def test_project_in_one_folder(self):
        self.check_applied("rtd-monitor/")

    def test_stale_files_replaced(self):
        os.makedirs(os.path.join(self.conf, "canopen", "eds"))
        with open(os.path.join(self.conf, "canopen", "eds", "old.eds"), "w") as f:
            f.write("old")
        self.check_applied("")

    def test_program_file(self):
        project = rtd_project()
        cfg = json.loads(project["canopen/canopen.json"])
        cfg["nodes"][0].update(software_file="fw/rtd.hex", software_version=2)
        project["canopen/canopen.json"] = json.dumps(cfg).encode()
        project["canopen/fw/rtd.hex"] = b":10010000214601360121470136007EFE09D2190140\n"
        applied, messages = snapshot.materialize(self.snapshot(project), self.conf)
        self.assertTrue(applied, messages)
        self.assertIn("canopen/fw/rtd.hex", self.conf_files())
        with open(os.path.join(self.conf, "canopen.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["nodes"][0]["software_file"], "canopen/fw/rtd.hex")
        self.assertEqual(read(os.path.join(self.conf, "canopen", "fw", "rtd.hex")), project["canopen/fw/rtd.hex"])

    def test_program_file_corrupted_by_the_editor(self):
        project = rtd_project()
        cfg = json.loads(project["canopen/canopen.json"])
        cfg["nodes"][0].update(software_file="fw/rtd.bin", software_version=2)
        project["canopen/canopen.json"] = json.dumps(cfg).encode()
        project["canopen/fw/rtd.bin"] = b"\x02\x00" + "\ufffd".encode() + b"\x00"
        self.assertIgnored(project, "canopen/fw/rtd.bin was corrupted")

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
        del project["canopen/eds/rtd8.eds"]
        self.assertIgnored(project, "canopen/eds/rtd8.eds is missing from the project")

    def test_invalid_json(self):
        project = rtd_project()
        project["canopen/canopen.json"] = b'{"nodes": [}'
        self.assertIgnored(project, "canopen/canopen.json is not valid JSON")

    def test_schema_failure(self):
        project = rtd_project()
        cfg = json.loads(project["canopen/canopen.json"])
        cfg["nodes"][0]["node_id"] = 200
        project["canopen/canopen.json"] = json.dumps(cfg).encode()
        self.assertIgnored(project, "canopen/canopen.json: nodes[0]")

    def test_paths_outside_canopen(self):
        for bad in ("../rtd8.eds", "/etc/rtd8.eds", "eds/../../x.eds", "C:/x.eds",
                    "eds\\rtd8.eds", "./eds/rtd8.eds"):
            with self.subTest(bad):
                project = rtd_project()
                cfg = json.loads(project["canopen/canopen.json"])
                cfg["nodes"][0]["eds"] = bad
                project["canopen/canopen.json"] = json.dumps(cfg).encode()
                self.assertIgnored(project, "invalid EDS path")

    def test_symlink_entries(self):
        project = rtd_project()
        eds = project.pop("canopen/eds/rtd8.eds")
        self.assertIgnored(project, "canopen/eds/rtd8.eds is missing",
                           symlinks=[("canopen/eds/rtd8.eds", b"/etc/passwd")])
        project["canopen/eds/rtd8.eds"] = eds
        cfg = project.pop("canopen/canopen.json")
        self.assertIgnored(project, "canopen/canopen.json is not a regular file",
                           symlinks=[("canopen/canopen.json", b"/etc/passwd")])
        del cfg

    def test_size_cap(self):
        project = rtd_project()
        with mock.patch.object(snapshot, "MAX_TOTAL_BYTES", 4096):
            self.assertIgnored(project, "larger than")

    def test_same_name_different_eds(self):
        project = rtd_project()
        cfg = json.loads(project["canopen/canopen.json"])
        node = dict(cfg["nodes"][0], node_id=6, name="rtd2", eds="other/rtd8.eds")
        for pdo in node.get("tx_pdos", []) + node.get("rx_pdos", []):
            for e in pdo["entries"]:
                e["iec_location"] = e["iec_location"].replace("%IW10", "%IW20").replace("%IB10", "%IB20")
        node.pop("status_location", None)
        cfg["nodes"].append(node)
        project["canopen/canopen.json"] = json.dumps(cfg).encode()
        project["canopen/other/rtd8.eds"] = project["canopen/eds/rtd8.eds"] + b"; changed\n"
        self.assertIgnored(project, "two different EDS files are both named rtd8.eds")


class IntoProject(Base):
    def test_into_project_output_is_applied(self):
        # What openplc-canopen-deploy --into-project writes, as the editor zips it.
        from openplc_canopen_deploy import project
        proj = os.path.join(self.tmp, "proj")
        os.makedirs(proj)
        with open(os.path.join(proj, "project.json"), "w") as f:
            f.write("{}")
        config = os.path.join(RTD, "canopen_config.json")
        with open(config, encoding="utf-8") as f:
            project.write(json.load(f), config, proj)
        files = {}
        for name in os.listdir(os.path.join(proj, "canopen")):
            files["canopen/" + name] = read(os.path.join(proj, "canopen", name))
        applied, messages = snapshot.materialize(self.snapshot(files), self.conf)
        self.assertTrue(applied, messages)


class Encoding(Base):
    def test_replacement_char_rejected(self):
        # A Latin-1 EDS as editor 4.3.2 puts it into the snapshot: read as
        # UTF-8 with replacement (fs.readFile(path, 'utf-8')), then encoded.
        project = rtd_project()
        latin1 = project["canopen/eds/rtd8.eds"].replace(
            b"[DeviceInfo]", "; Temperatur in \u00b0C\n[DeviceInfo]".encode("latin-1"), 1)
        self.assertIn(b"\xb0", latin1)
        project["canopen/eds/rtd8.eds"] = latin1.decode("utf-8", "replace").encode("utf-8")
        text = self.assertIgnored(project, "canopen/eds/rtd8.eds is not UTF-8")
        self.assertIn("--into-project", text)

    def test_utf8_eds_accepted(self):
        project = rtd_project()
        project["canopen/eds/rtd8.eds"] = project["canopen/eds/rtd8.eds"].replace(
            b"[DeviceInfo]", "; Temperatur in \u00b0C\n[DeviceInfo]".encode("utf-8"), 1)
        applied, messages = snapshot.materialize(self.snapshot(project), self.conf)
        self.assertTrue(applied, messages)


class Precedence(Base):
    def test_uploaded_config_wins(self):
        os.makedirs(os.path.join(self.conf, "canopen", "eds"))
        files = {"canopen.json": b'{"deployed": true}\n', "canopen/eds/a.eds": b"deployed eds"}
        for name, data in files.items():
            with open(os.path.join(self.conf, name), "wb") as f:
                f.write(data)
        applied, messages = snapshot.materialize(self.snapshot(rtd_project()), self.conf)
        self.assertFalse(applied)
        self.assertEqual(messages, [("INFO", "CANopen: the upload carries conf/canopen.json; "
                                             "the project snapshot is not used")])
        self.assertEqual(self.conf_files(), ["canopen.json", "canopen/eds/a.eds", "ethercat.json"])
        for name, data in files.items():
            self.assertEqual(read(os.path.join(self.conf, name)), data)


class SharedFixtures(Base):
    """The snapshot path reaches the deploy tool's verdict on every shared case."""

    def test_cases(self):
        doc = load_cases()
        eds_dir = os.path.join(FIXTURES, "eds")
        eds = {"canopen/" + n: read(os.path.join(eds_dir, n)) for n in os.listdir(eds_dir) if n.endswith(".eds")}
        eds.update({"canopen/fw/" + n: read(os.path.join(eds_dir, "fw", n)) for n in os.listdir(os.path.join(eds_dir, "fw"))})
        eds.update({"canopen/lint/" + n: read(os.path.join(eds_dir, "lint", n))
                    for n in os.listdir(os.path.join(eds_dir, "lint")) if n.endswith(".eds")})
        rejected = 0
        for case in doc["cases"]:
            with self.subTest(case["name"]):
                shutil.rmtree(self.conf)
                os.makedirs(self.conf)
                cfg = patched(doc["base"], case["patch"])
                files = dict(eds, **{"canopen/canopen.json": json.dumps(cfg).encode()})
                applied, messages = snapshot.materialize(self.snapshot(files), self.conf)
                tool = contract.check_config(cfg, "canopen/canopen.json", eds_dir=eds_dir)
                text = "\n".join(t for _, t in messages)
                self.assertEqual(applied, tool.ok, text)
                self.assertEqual(applied, case["verdict"] == "accept", text)
                reason = text.split("CANopen: project config ignored: ", 1)[-1]
                # Every rejection carries the deploy tool's own message:
                # all of its errors, or the EDS check that stopped it.
                if not applied:
                    rejected += 1
                    if reason.endswith("is missing from the project (named by canopen/canopen.json)"):
                        self.assertIn("not found", "; ".join(tool.errors))  # a file the config names
                    elif reason.startswith("canopen/canopen.json: "):
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
        env = {"OPENPLC_CANOPEN_PYTHON": sys.executable,
               "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_applied(self):
        import openplc_canopen_hook as hook
        messages = hook.run_materialize(self.snapshot(rtd_project()), self.conf)
        self.assertEqual(messages[-1][0], "INFO")
        self.assertIn("config taken from the project snapshot", messages[-1][1])
        self.assertIn("canopen.json", self.conf_files())

    def test_no_snapshot_no_process(self):
        import openplc_canopen_hook as hook
        with mock.patch.object(subprocess, "run") as run:
            self.assertEqual(hook.run_materialize(os.path.join(self.tmp, "none.zip"), self.conf), [])
        run.assert_not_called()

    def test_helper_failure(self):
        import openplc_canopen_hook as hook
        with mock.patch.dict(os.environ, {"OPENPLC_CANOPEN_PYTHON": "/bin/false"}):
            with self.assertRaises(RuntimeError) as cm:
                hook.run_materialize(self.snapshot(rtd_project()), self.conf)
        self.assertIn("exited with 1", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
