"""The tools start without importing the libraries only some of their work
needs (canopen-pc-install "Fast start")."""

import os
import subprocess
import sys
import unittest

HEAVY = ("jsonschema", "can", "cantools", "j1939", "zeroconf", "iroh")
ENTRY = ("canworks.configurator.server", "canworks.cli", "canworks.diag")


class FastStart(unittest.TestCase):
    def test_entry_modules_import_no_heavy_library(self):
        code = ("import sys\nimport %s\n"
                "print(' '.join(m for m in %r if m in sys.modules))" % (", ".join(ENTRY), HEAVY))
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        r = subprocess.run([sys.executable, "-c", code], cwd=root, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, universal_newlines=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(r.stdout.strip(), "", "imported at start: " + r.stdout.strip())

    def test_light_starter(self):
        # skip-reinstall-faster-start: canworks-config's entry starts or hands
        # over without loading the configurator itself.
        code = ("import sys\nimport canworks.configurator.start\n"
                "print(' '.join(m for m in ('canworks.configurator.server', 'canworks.diag', 'canworks.contract') "
                "if m in sys.modules))")
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        r = subprocess.run([sys.executable, "-c", code], cwd=root, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, universal_newlines=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(r.stdout.strip(), "", "imported by the starter: " + r.stdout.strip())


if __name__ == "__main__":
    unittest.main()
