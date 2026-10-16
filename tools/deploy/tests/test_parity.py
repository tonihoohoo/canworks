"""The configurator and the plugin refuse the same configs (canopen-ci:
"Configurator and plugin agree on bad configs"): every entry of
test/fixtures/config/bad/ goes through the deploy tool's checks
(contract.check_config, and simfile.check for its simulation file) and
through build/canopen_check --no-dcfgen, the plugin's config loader. Both
must refuse it.

Each entry is {"description", "config", "simulation" (optional), "message"
(optional)}; the config is written as canworks.json, with simulation.json
next to it, into a folder that holds test/fixtures/eds. An entry with
"config_text" in place of "config" is written as that text, for what a
parsed config cannot hold (a repeated key). With "message", both refusals
must contain that text. A new plugin refusal adds an entry
(docs/development.md)."""

import glob
import json
import os
import shutil
import subprocess
import unittest

from canworks import contract, simfile

from .helpers import tmpdir
from .test_contract import FIXTURES, load_cases
from .test_dcfexport import _canopen_check

CORPUS = os.path.join(FIXTURES, "config", "bad")
EDS_DIR = os.path.join(FIXTURES, "eds")


def entries():
    return sorted(glob.glob(os.path.join(CORPUS, "*.json")))


def tool_errors(doc, folder):
    """The deploy tool's errors for an entry written to `folder`."""
    path = os.path.join(folder, "canworks.json")
    if "config_text" in doc:
        try:
            doc = dict(doc, config=contract.loads(doc["config_text"]))
        except ValueError as e:
            return [str(e)]
    r = contract.check_config(doc["config"], path)
    if r.errors or "simulation" not in doc:
        return r.errors
    return simfile.check(doc["simulation"], os.path.join(folder, "simulation.json"), doc["config"], path).errors


class Corpus(unittest.TestCase):
    def test_entries(self):
        self.assertGreater(len(entries()), 20)
        for path in entries():
            with self.subTest(os.path.basename(path)):
                with open(path, encoding="utf-8") as f:
                    doc = json.load(f)
                self.assertEqual(sorted(set(doc) - {"simulation", "message", "config_text", "config"}), ["description"])
                self.assertEqual(len({"config", "config_text"} & set(doc)), 1)


class Parity(unittest.TestCase):
    def setUp(self):
        self.check = _canopen_check()
        if not self.check:
            if os.environ.get("CANWORKS_REQUIRE_PARITY") == "1":
                self.fail("canopen_check not found (build it, or set CANWORKS_CHECK)")
            self.skipTest("canopen_check not built")

    def write(self, doc):
        folder = os.path.join(tmpdir(self), "cfg")
        shutil.copytree(EDS_DIR, folder)
        with open(os.path.join(folder, "canworks.json"), "w", encoding="utf-8") as f:
            if "config_text" in doc:
                f.write(doc["config_text"])
            else:
                json.dump(doc["config"], f)
        if "simulation" in doc:
            with open(os.path.join(folder, "simulation.json"), "w", encoding="utf-8") as f:
                json.dump(doc["simulation"], f)
        return folder

    def test_both_accept_the_base(self):
        # The entries' starting point (cases.json's base, simulated, with a
        # value source the plugin takes), so the refusals are the entries' own.
        cfg = load_cases()["base"]
        cfg["adapter"]["simulate"] = True
        doc = {"description": "base", "config": cfg,
               "simulation": {"schema_version": 1, "nodes": {"2": {"sources": {"0x4001:0": {"constant": 1}}}}}}
        folder = self.write(doc)
        self.assertEqual(tool_errors(doc, folder), [])
        out = subprocess.run([self.check, "--no-dcfgen", os.path.join(folder, "canworks.json")],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_both_refuse_every_entry(self):
        for path in entries():
            name = os.path.relpath(path, FIXTURES)
            with self.subTest(name):
                with open(path, encoding="utf-8") as f:
                    doc = json.load(f)
                folder = self.write(doc)
                errors = tool_errors(doc, folder)
                out = subprocess.run([self.check, "--no-dcfgen", os.path.join(folder, "canworks.json")],
                                     capture_output=True, text=True)
                plugin = out.returncode != 0
                self.assertEqual(
                    (bool(errors), plugin), (True, True),
                    "%s (%s): configurator %s, plugin %s\n%s\n%s" % (
                        name, doc["description"], "refuses" if errors else "accepts",
                        "refuses" if plugin else "accepts", "\n".join(errors), out.stdout + out.stderr))
                if "message" in doc:
                    self.assertIn(doc["message"], "\n".join(errors), "%s: configurator" % name)
                    self.assertIn(doc["message"], out.stdout + out.stderr, "%s: plugin" % name)


if __name__ == "__main__":
    unittest.main()
