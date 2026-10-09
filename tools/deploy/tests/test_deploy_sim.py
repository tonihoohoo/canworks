"""The deploy tool and simulated devices: the simulation file in the bundle
and in editor projects, and the question before uploading a config with
simulated parts (canopen-deploy: simulation file, simulated config warning)."""

import json
import os
import shutil
import unittest
from unittest import mock

from canworks import cli, contract

from .helpers import (REPO, StubRuntime, editor_bundle, fake_editor_cli, make_cert, pingpong_config, tmpdir,
                      zip_contents)
from .test_deploy import deploy

EDS = os.path.join(REPO, "test", "fixtures", "eds")


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def sim_setup(dir_, **cfg_changes):
    """The ping-pong config with a simulation file next to it: node 2's
    0x4001 plays data/count.csv, and an extra device from extra/lss-slave.eds."""
    config = pingpong_config(dir_)
    if cfg_changes:
        with open(config, encoding="utf-8") as f:
            cfg = json.load(f)
        for key, value in cfg_changes.items():
            if key == "simulate_network":
                cfg["adapter"]["simulate"] = value
            elif key == "node_simulate":
                cfg["nodes"][0]["simulate"] = value
        write_json(config, cfg)
    os.makedirs(os.path.join(dir_, "data"))
    os.makedirs(os.path.join(dir_, "extra"))
    with open(os.path.join(dir_, "data", "count.csv"), "w", newline="") as f:  # LF on Windows too
        f.write("t,v\n0,1\n1,2\n")
    shutil.copy(os.path.join(EDS, "lss-slave.eds"), os.path.join(dir_, "extra"))
    sim = {"schema_version": 1,
           "nodes": {"2": {"sources": {"0x4001": {"csv": {"file": "data/count.csv", "loop": True}}}}},
           "extra_devices": [{"node": 40, "name": "spare", "eds": "extra/lss-slave.eds",
                              "sources": {"0x4001": {"expr": "[2/0x4001] * 2"}}}],
           "scenarios": {"count": {"steps": [{"node": "spare", "set": {"0x4001": 5}}]}}}
    return config, write_json(os.path.join(dir_, "simulation.json"), sim)


class Bundle(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.src = editor_bundle(os.path.join(self.dir, "src"))
        self.config, self.sim = sim_setup(self.dir)
        self.zip = os.path.join(self.dir, "program.zip")

    def test_simulation_file_in_the_bundle(self):
        code, out, err = deploy("--bundle", self.src, "--config", self.config, "--check-only", "--output", self.zip)
        self.assertEqual(code, 0, err)
        self.assertIn("ok: %s passes the simulation file checks" % self.sim, out)
        self.assertIn("conf/canworks/simulation.json and 1 CSV file", out)
        files = zip_contents(self.zip)
        deployed = json.loads(files["conf/canworks/simulation.json"])
        self.assertEqual(deployed["extra_devices"][0]["eds"], "eds/lss-slave.eds")
        self.assertEqual(deployed["nodes"]["2"]["sources"]["0x4001"]["csv"]["file"], "sim/count.csv")
        with open(self.sim, encoding="utf-8") as f:
            self.assertEqual(deployed["scenarios"], json.load(f)["scenarios"])
        self.assertEqual(files["conf/canworks/sim/count.csv"], b"t,v\n0,1\n1,2\n")
        with open(os.path.join(EDS, "lss-slave.eds"), "rb") as f:
            self.assertEqual(files["conf/canworks/eds/lss-slave.eds"], f.read())
        self.assertIn("conf/canworks/eds/cpp-slave.eds", files)
        self.assertEqual(json.loads(files["conf/canworks.json"])["nodes"][0]["eds"], "canworks/eds/cpp-slave.eds")
        self.assertNotIn("simulates devices", err)

    def test_sim_option_names_another_file(self):
        other = os.path.join(self.dir, "bench.json")
        os.rename(self.sim, other)
        code, out, err = deploy("--bundle", self.src, "--config", self.config, "--check-only", "--output", self.zip)
        self.assertEqual(code, 0, err)
        self.assertNotIn("conf/canworks/simulation.json", zip_contents(self.zip))
        code, out, err = deploy("--bundle", self.src, "--config", self.config, "--check-only", "--output", self.zip,
                                "--sim", other)
        self.assertEqual(code, 0, err)
        self.assertIn("conf/canworks/simulation.json", zip_contents(self.zip))
        code, out, err = deploy("--bundle", self.src, "--config", self.config, "--check-only",
                                "--sim", os.path.join(self.dir, "nope.json"))
        self.assertEqual(code, 1)
        self.assertIn("simulation file %s not found" % os.path.join(self.dir, "nope.json"), err)

    def test_checked_before_anything_is_built(self):
        with open(self.sim, encoding="utf-8") as f:
            sim = json.load(f)
        sim["nodes"]["2"]["sources"]["0x4000"] = {"constant": 1}
        sim["nodes"]["2"]["sources"]["0x4001"] = {"expr": "[0x4001] + 1"}
        write_json(self.sim, sim)
        code, out, err = deploy("--bundle", self.src, "--config", self.config, "--check-only")
        self.assertEqual(code, 1)
        self.assertIn("node 2 (pingpong): object 0x4000:0 is written by the master (RPDO 1)", err)
        self.assertIn("reference cycle", err)
        self.assertIn("nothing was uploaded", err)

    def test_extra_device_eds_with_the_name_of_another(self):
        with open(self.sim, encoding="utf-8") as f:
            sim = json.load(f)
        shutil.copy(os.path.join(EDS, "lss-slave.eds"), os.path.join(self.dir, "extra", "cpp-slave.eds"))
        sim["extra_devices"][0]["eds"] = "extra/cpp-slave.eds"
        write_json(self.sim, sim)
        code, out, err = deploy("--bundle", self.src, "--config", self.config, "--check-only")
        self.assertEqual(code, 1)
        self.assertIn("two different EDS files are both named cpp-slave.eds", err)

    def test_simulated_config_is_a_warning_in_check_only(self):
        config, _ = sim_setup(tmpdir(self), simulate_network=True)
        code, out, err = deploy("--bundle", self.src, "--config", config, "--check-only")
        self.assertEqual(code, 0, err)
        self.assertIn("warning: this config simulates devices: the network is simulated; no CAN interface is used",
                      err)

    def test_config_contract_accepts_the_switches(self):
        with open(self.config, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["adapter"]["simulate"] = True
        cfg["nodes"][0]["simulate"] = False
        r = contract.check_config(cfg, self.config)
        self.assertEqual((r.errors, r.warnings), ([], []))
        cfg["adapter"] = {"type": "slcan", "interface": "slcan0", "bitrate": 125000, "device": "/dev/ttyACM0",
                          "simulate": True}
        r = contract.check_config(cfg, self.config)
        self.assertEqual((r.errors, r.warnings), ([], []))
        cfg["adapter"]["simulate"] = "yes"
        self.assertFalse(contract.check_config(cfg, self.config).ok)


class Confirmation(unittest.TestCase):
    """The question before uploading a config with simulated parts; no
    upload is attempted when it is refused (the runtime address is closed)."""

    def setUp(self):
        self.dir = tmpdir(self)
        self.src = editor_bundle(os.path.join(self.dir, "src"))

    def upload(self, *extra, **cfg_changes):
        config, _ = sim_setup(self.dir, **cfg_changes)
        return deploy("--bundle", self.src, "--config", config, "--runtime", "127.0.0.1:1", "--insecure", *extra)

    def test_non_interactive_stops_before_uploading(self):
        code, out, err = self.upload(simulate_network=True)
        self.assertEqual(code, 1)
        self.assertIn("not uploaded: the network is simulated; no CAN interface is used. Pass --simulated (or "
                      "--yes) to upload it anyway", err)
        self.assertNotIn("uploading", out)
        self.assertIn("nothing was uploaded", err)

    def test_interactive_question_names_the_node(self):
        with mock.patch.object(cli, "_ask", return_value=False) as ask:
            code, out, err = self.upload(node_simulate=True)
        self.assertEqual(code, 1)
        self.assertIn("node 2 is a simulated device on the real network vcan0", err)
        self.assertIn("not confirmed", err)
        self.assertIn("simulated devices", ask.call_args[0][0])

    def test_confirmed_or_simulated_goes_on_to_the_upload(self):
        for extra, answer in (((), True), (("--simulated",), None), (("--yes",), None)):
            with mock.patch.object(cli, "_ask", return_value=answer) as ask:
                code, out, err = self.upload(*extra, simulate_network=True)
            self.assertEqual(ask.called, not extra)
            # It goes on to connect, which fails on the closed port.
            self.assertEqual(code, 1)
            self.assertNotIn("not confirmed", err)
            self.assertNotIn("not uploaded", err)
            self.assertIn("ok: bundle of", out)
            shutil.rmtree(self.dir)
            os.makedirs(self.dir)
            self.src = editor_bundle(os.path.join(self.dir, "src"))

    def test_nothing_simulated_asks_nothing(self):
        with mock.patch.object(cli, "_ask") as ask:
            self.upload()
        self.assertFalse(ask.called)


class Upload(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        pair = make_cert(self.dir)
        if pair is None:
            self.skipTest("openssl is not available")
        self.cert, self.key = pair
        self.src = editor_bundle(os.path.join(self.dir, "src"))
        self.config, _ = sim_setup(self.dir, simulate_network=True)

    def test_simulated_upload(self):
        stub = StubRuntime(self.cert, self.key)
        with stub:
            code, out, err = deploy("--bundle", self.src, "--config", self.config, "--runtime",
                                    "127.0.0.1:%d" % stub.port, "--ca", self.cert, "--simulated")
        self.assertEqual(code, 0, err)
        self.assertIn("the network is simulated", err)
        self.assertIn(("POST", "/api/upload-file"), stub.requests)


class Projects(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.config, self.sim = sim_setup(self.dir, node_simulate=True)

    def test_into_project(self):
        target = os.path.join(self.dir, "project")
        os.makedirs(target)
        write_json(os.path.join(target, "project.json"), {})
        code, out, err = deploy("--config", self.config, "--into-project", target)
        self.assertEqual(code, 0, err)
        self.assertIn("warning: this config simulates devices: node 2 is a simulated device", err)
        canopen = os.path.join(target, "canworks")
        self.assertEqual(sorted(os.listdir(canopen)), ["canworks.json", "count.csv", "cpp-slave.eds", "lss-slave.eds",
                                                       "simulation.json"])
        with open(os.path.join(canopen, "simulation.json"), encoding="utf-8") as f:
            sim = json.load(f)
        self.assertEqual(sim["extra_devices"][0]["eds"], "lss-slave.eds")
        self.assertEqual(sim["nodes"]["2"]["sources"]["0x4001"]["csv"]["file"], "count.csv")
        self.assertIn(os.path.join(canopen, "simulation.json"), out)

    def test_into_project_name_clash(self):
        shutil.copy(os.path.join(self.dir, "data", "count.csv"), os.path.join(self.dir, "data", "cpp-slave.eds"))
        with open(self.sim, encoding="utf-8") as f:
            sim = json.load(f)
        sim["nodes"]["2"]["sources"]["0x4001"]["csv"]["file"] = "data/cpp-slave.eds"
        write_json(self.sim, sim)
        target = os.path.join(self.dir, "project")
        os.makedirs(target)
        write_json(os.path.join(target, "project.json"), {})
        code, out, err = deploy("--config", self.config, "--into-project", target)
        self.assertEqual(code, 1)
        self.assertIn("are both named cpp-slave.eds", err)
        self.assertFalse(os.path.exists(os.path.join(target, "canworks")))

    def test_new_project(self):
        target = os.path.join(self.dir, "pp-project")
        code, out, err = deploy("--config", self.config, "--new-project", target,
                                env={"OPENPLC_CLI": fake_editor_cli(self.dir)})
        self.assertEqual(code, 0, err)
        for name in ("simulation.json", "lss-slave.eds", "count.csv"):
            self.assertTrue(os.path.isfile(os.path.join(target, "canworks", name)), name)


if __name__ == "__main__":
    unittest.main()
