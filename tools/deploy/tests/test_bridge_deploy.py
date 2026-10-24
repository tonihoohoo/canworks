"""canworks-deploy and Modbus bridge configs (modbus-bridge): --bridge
takes only a bridge config, the OpenPLC targets refuse one, and the files a
bridge gets are the runtime's conf/ folder. The upload itself runs against
the real canworks-bridge in test/bridge/upload_test.py."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

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


class UploadReadback(unittest.TestCase):
    """After the upload canworks-deploy reads back whether the bridge started
    on it: a bridge with several networks answers status for one network."""

    def run_upload(self, networks):
        asked = []

        class FakeClient:
            def __init__(self, *a, **kw):
                self.where = "127.0.0.1"

            def connect(self):
                self.info = {"host": "bridge", "allow_config_upload": True, "networks": networks}
                return self.info

            @property
            def networks(self):
                return networks

            def several(self):
                return len(networks) > 1

            def put_config(self, files):
                return {"restarting": True, "upload": 4}

            def status(self):
                return self.request("status")

            def request(self, op, **fields):
                asked.append(fields)
                if self.several() and "network" not in fields:
                    raise diag.DiagError("refused", "network required (can0, sim)")
                return {"bridge": {"last_upload": {"number": 4, "result": "started"}}}

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "cfg")
            shutil.copytree(os.path.dirname(EXAMPLE), folder)
            path = os.path.join(folder, "canworks.json")
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            cfg["diagnostics"] = {"token_verifier": "SCRAM-SHA-256$4096:b3BlbnBsYy1jYW5vcGVuLQ==$SCwajLpaZodu1wAN8vyPszAhAZJB4cXO6Rk+MpacSlQ=:7p7OTxtK+R6omxv8Fdz+xdCpEf4bc82kbkxCL8w33kg="}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            with mock.patch.object(cli.diag, "Client", FakeClient), \
                    mock.patch.object(cli.time, "sleep", lambda s: None):
                result = run_cli("--bridge", "127.0.0.1", "--config", path, "--token", "x", "--yes")
        return result, asked

    def test_one_network(self):
        (code, out, err), asked = self.run_upload([])
        self.assertEqual(code, 0, err)
        self.assertIn("ok: canworks-bridge runs the new config", out)
        self.assertEqual(asked, [{}])

    def test_several_networks(self):
        (code, out, err), asked = self.run_upload([{"name": "can0"}, {"name": "sim"}])
        self.assertEqual(code, 0, err)
        self.assertIn("ok: canworks-bridge runs the new config", out)
        self.assertEqual(asked, [{"network": "can0"}])


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
        # A program that only reads the network info (CAN_BUS_INFO) uses them.
        line = diag.mailbox_status_line({"mailboxes": {"operations": 0, "receivers_opened": 0, "info_reads": 42}})
        self.assertEqual(line, "mailboxes: 0 operations, 0 receivers opened, 42 network info or job table reads "
                               "since start")


if __name__ == "__main__":
    unittest.main()
