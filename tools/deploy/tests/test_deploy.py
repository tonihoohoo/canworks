"""The deploy tool end to end: --check, the files a bridge gets, refused
configs and --new-project (canopen-deploy spec). The upload itself runs
against the real canworks-bridge in test/bridge/upload_test.py."""

import contextlib
import io
import json
import os
import unittest
from unittest import mock

from canworks import cli, contract

from .helpers import fake_editor_cli, pingpong_config, tmpdir


def deploy(*argv, env=None):
    """Runs the tool; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Check(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.config = pingpong_config(self.dir)

    def edit(self, change):
        with open(self.config, encoding="utf-8") as f:
            cfg = json.load(f)
        change(cfg)
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

    def test_help_lists_options(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(["--help"])
        for opt in ("--check", "--bridge", "--into-project", "--new-project", "--config", "--token"):
            self.assertIn(opt, out.getvalue())
        for gone in ("--bundle", "--project ", "--runtime", "--allow-clash", "--fingerprint"):
            self.assertNotIn(gone, out.getvalue())

    def test_check(self):
        code, out, err = deploy("--config", self.config, "--check")
        self.assertEqual(code, 0, err)
        self.assertIn("passes the schema and EDS checks", out)

    def test_bridge_files(self):
        with open(self.config, encoding="utf-8") as f:
            cfg = json.load(f)
        files = cli.bridge_files(cfg, self.config)
        with open(os.path.join(self.dir, "cpp-slave.eds"), "rb") as f:
            self.assertEqual(files["canworks/eds/cpp-slave.eds"], f.read())
        deployed = json.loads(files["canworks.json"])
        self.assertEqual(deployed["networks"][0]["nodes"][0]["eds"], "canworks/eds/cpp-slave.eds")
        cfg["networks"][0]["nodes"][0]["eds"] = "canworks/eds/cpp-slave.eds"
        self.assertEqual(deployed, cfg)

    def test_notes_file_not_sent(self):
        # Notes files are PC-side documentation (canopen-device-notes).
        with open(os.path.join(self.dir, "cpp-slave.eds.notes.json"), "w", encoding="utf-8") as f:
            json.dump({"format": "canworks-notes.v1", "objects": {"0x2000": {"text": "x"}}}, f)
        with open(self.config, encoding="utf-8") as f:
            files = cli.bridge_files(json.load(f), self.config)
        self.assertIn("canworks/eds/cpp-slave.eds", files)
        self.assertFalse([name for name in files if "notes" in name], sorted(files))

    def test_cp1252_eds_converted(self):
        eds = os.path.join(self.dir, "cpp-slave.eds")
        with open(eds, "rb") as f:
            data = f.read()
        with open(eds, "wb") as f:
            f.write(data.replace(b"[Comments]\nLines=0\n", b"[Comments]\nLines=1\nLine1=Range 0-100 \x94C\n"))
        with open(eds, "rb") as f:
            original = f.read()
        with open(self.config, encoding="utf-8") as f:
            shipped = cli.bridge_files(json.load(f), self.config)["canworks/eds/cpp-slave.eds"]
        self.assertEqual(shipped, original.decode("cp1252").encode("utf-8"))
        with open(eds, "rb") as f:
            self.assertEqual(f.read(), original)  # the source on the PC is unchanged

    def test_program_file_fields_rejected(self):
        self.edit(lambda cfg: cfg["networks"][0]["nodes"][0].update(software_file="fw/node2.bin"))
        code, _, err = deploy("--config", self.config, "--check")
        self.assertEqual(code, 1)
        self.assertIn("unknown field 'software_file'", err)

    def test_eds_file_missing(self):
        os.remove(os.path.join(self.dir, "cpp-slave.eds"))
        code, _, err = deploy("--config", self.config, "--check")
        self.assertEqual(code, 1)
        self.assertIn("node 2: EDS file", err)
        self.assertIn("cpp-slave.eds not found", err)

    def test_schema_violation(self):
        self.edit(lambda cfg: cfg["networks"][0]["nodes"][0].update(node_id=200))
        code, _, err = deploy("--config", self.config, "--check")
        self.assertEqual(code, 1)
        self.assertIn("networks[0]: nodes[0].node_id: node ID must be 1 to 127", err)

    def test_eds_check_fails_with_the_bridges_message(self):
        eds = os.path.join(self.dir, "cpp-slave.eds")
        with open(eds, encoding="utf-8") as f:
            text = f.read().replace("DataType=0x0007\nAccessType=rww", "DataType=0x0007\nAccessType=ro")
        with open(eds, "w", encoding="utf-8") as f:
            f.write(text)
        code, _, err = deploy("--config", self.config, "--check")
        self.assertEqual(code, 1)
        self.assertIn("node 2, index 0x4000, subindex 0: rx_pdos entry needs an object the slave can receive "
                      "(AccessType wo, rw or rww), but its AccessType is ro", err)

    def test_plugin_config_refused(self):
        # A config without "bridge" or "codesys" is the removed plugin's.
        self.edit(lambda cfg: cfg.pop("bridge"))
        code, _, err = deploy("--config", self.config, "--check")
        self.assertEqual(code, 1)
        self.assertIn(contract.NOT_BRIDGE_MESSAGE, err)

    def test_check_only_needs_bridge(self):
        code, _, err = deploy("--config", self.config, "--check", "--check-only")
        self.assertNotEqual(code, 0)
        self.assertIn("--check-only", err)


class NewProject(unittest.TestCase):
    """--new-project (add-editor-project-template task 3.1)."""

    def setUp(self):
        self.dir = tmpdir(self)
        self.config = pingpong_config(self.dir)
        self.env = {"OPENPLC_CLI": fake_editor_cli(self.dir)}
        self.target = os.path.join(self.dir, "pp-project")

    def test_create(self):
        code, out, err = deploy("--config", self.config, "--new-project", self.target, "--task-interval", "T#10ms",
                                env=self.env)
        self.assertEqual(code, 0, err)
        self.assertIn("created %s" % self.target, out)
        with open(os.path.join(self.dir, "cli-args.json")) as f:
            self.assertIn("--time=T#10ms", json.load(f))
        self.assertTrue(os.path.isfile(os.path.join(self.target, "canworks", "canworks.json")))

    def test_existing_folder(self):
        os.makedirs(self.target)
        with open(os.path.join(self.target, "x"), "w") as f:
            f.write("x")
        # windows-safe-new-config: a folder without editor or canworks files
        # becomes the project and keeps its other files; one with them is refused.
        code, _, err = deploy("--config", self.config, "--new-project", self.target, env=self.env)
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.target, "x")) as f:
            self.assertEqual(f.read(), "x")
        self.assertTrue(os.path.isfile(os.path.join(self.target, "canworks", "canworks.json")))
        code, _, err = deploy("--config", self.config, "--new-project", self.target, env=self.env)
        self.assertEqual(code, 1)
        self.assertIn("already has project.json", err)

    def test_interval_needs_new_project(self):
        code, _, err = deploy("--config", self.config, "--check", "--task-interval", "T#10ms", env=self.env)
        self.assertEqual(code, 1)
        self.assertIn("--task-interval needs --new-project", err)


if __name__ == "__main__":
    unittest.main()
