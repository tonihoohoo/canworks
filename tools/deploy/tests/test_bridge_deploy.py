"""canworks-deploy and Modbus bridge configs (modbus-bridge): --bridge
takes only a bridge config, the OpenPLC targets refuse one, and the files a
bridge gets are the runtime's conf/ folder. The upload itself runs against
the real canworks-bridge in test/bridge/upload_test.py."""

import contextlib
import io
import json
import os
import tempfile
import unittest

from canworks import cli, diag

from .test_contract import REPO

EXAMPLE = os.path.join(REPO, "examples", "modbus-bridge", "canworks.json")


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class BridgeDeploy(unittest.TestCase):
    def test_check_only_lists_the_files(self):
        code, out, err = run_cli("--bridge", "127.0.0.1", "--config", EXAMPLE, "--check-only", "--simulated")
        self.assertEqual(code, 0, err)
        self.assertIn("4 files", out)
        self.assertIn("not uploaded (--check-only)", out)

    def test_files_are_the_conf_folder(self):
        with open(EXAMPLE, encoding="utf-8") as f:
            cfg = json.load(f)
        files = cli.bridge_files(cfg, EXAMPLE, os.path.join(os.path.dirname(EXAMPLE), "simulation.json"))
        self.assertIn("canworks.json", files)
        deployed = json.loads(files["canworks.json"])
        for node in deployed["networks"][0]["nodes"]:
            self.assertIn(node["eds"], files)
        self.assertIn("canworks/simulation.json", files)

    def test_runtime_refuses_a_bridge_config(self):
        code, out, err = run_cli("--bundle", "/nonexistent", "--runtime", "plc.local", "--config", EXAMPLE)
        self.assertNotEqual(code, 0)
        self.assertIn("is a Modbus bridge config (it has a 'bridge' object): canworks-bridge runs it, not the "
                      "OpenPLC plugin; upload it with --bridge HOST", err)

    def test_bridge_refuses_a_plain_config(self):
        with open(EXAMPLE, encoding="utf-8") as f:
            cfg = json.load(f)
        del cfg["bridge"]
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("rtd8.eds", "dio16.eds"):
                with open(os.path.join(os.path.dirname(EXAMPLE), name), "rb") as src, \
                        open(os.path.join(tmp, name), "wb") as dst:
                    dst.write(src.read())
            path = os.path.join(tmp, "canworks.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            code, out, err = run_cli("--bridge", "127.0.0.1", "--config", path, "--check-only")
        self.assertNotEqual(code, 0)
        self.assertIn("has no top-level \"bridge\" object, so canworks-bridge does not run it", err)

    def test_token_needs_bridge(self):
        code, out, err = run_cli("--bundle", "/nonexistent", "--check-only", "--config", EXAMPLE, "--token", "x")
        self.assertNotEqual(code, 0)
        self.assertIn("--token and --token-file go with --bridge", err)


class BridgeStatusLine(unittest.TestCase):
    def test_line(self):
        line = diag.bridge_status_line({
            "state": "outputs_off", "reason": "watchdog", "on_client_loss": "stop", "listen": "0.0.0.0:502",
            "unit_id": 1, "clients": [{"address": "10.0.0.5", "requests": 12, "writer": True}],
            "last_upload": {"number": 1, "result": "started"}})
        self.assertEqual(line, "Modbus bridge on 0.0.0.0:502, unit 1: outputs off (watchdog, on client loss stop); "
                               "1 client: 10.0.0.5 (writer) 12 requests; last config upload: started")


if __name__ == "__main__":
    unittest.main()
