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

    def test_config_folder_means_its_canworks_json(self):
        # Opening a folder fails differently per OS ("Permission denied" on Windows).
        code, out, err = run_cli("--bridge", "127.0.0.1", "--config", os.path.dirname(EXAMPLE), "--check-only",
                                 "--simulated")
        self.assertEqual(code, 0, err)
        self.assertIn("4 files", out)

    def test_files_are_the_conf_folder(self):
        with open(EXAMPLE, encoding="utf-8") as f:
            cfg = json.load(f)
        files = cli.bridge_files(cfg, EXAMPLE, os.path.join(os.path.dirname(EXAMPLE), "simulation.json"))
        self.assertIn("canworks.json", files)
        deployed = json.loads(files["canworks.json"])
        for node in deployed["networks"][0]["nodes"]:
            self.assertIn(node["eds"], files)
        self.assertIn("canworks/simulation.json", files)

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
        self.assertIn("this config is for the removed OpenPLC plugin", err)

    def test_token_needs_bridge(self):
        code, out, err = run_cli("--check", "--config", EXAMPLE, "--token", "x")
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

    def test_last_stop(self):
        base = {"state": "running", "listen": "0.0.0.0:502", "unit_id": 1, "clients": []}
        self.assertTrue(diag.bridge_status_line(dict(base, last_stop="unclean")).endswith(
            "; last stop unclean (crash, kill or power loss)"))
        self.assertTrue(diag.bridge_status_line(dict(base, last_stop="clean")).endswith("; last stop clean"))
        self.assertNotIn("last stop", diag.bridge_status_line(dict(base, last_stop="unknown")))

    def test_mailbox_use(self):
        self.assertEqual(diag.mailbox_status_line({}), "mailboxes: no mailboxes")
        self.assertEqual(diag.mailbox_status_line({"mailboxes": {"operations": 13, "receivers_opened": 1}}),
                         "mailboxes: 13 operations, 1 receiver opened since start")
        self.assertEqual(diag.mailbox_status_line({"mailboxes": {"operations": 0, "receivers_opened": 0}}),
                         "mailboxes: 0 operations, 0 receivers opened since start: nothing has used the mailboxes; "
                         "turning them off saves Modbus requests")


if __name__ == "__main__":
    unittest.main()
