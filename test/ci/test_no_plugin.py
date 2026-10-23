"""The OpenPLC plugin stays removed (remove-openplc-plugin): no engine, test
or tool source includes an OpenPLC runtime header, and no build file asks
for the runtime's sources. No spec outside the archive describes canworks as a
plugin."""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCES = ("plugin", "test", "tools")
# The runtime's plugin interface headers (core/src/drivers/ in its tree).
RUNTIME_HEADERS = ("plugin_types.h", "plugin_logger.h", "iec_types.h", "plugin_driver.h")
# "the plugin" or "the plugin's" for canworks; a line about the removed plugin
# may name it.
PLUGIN_WORDING = re.compile(r"\b(the|canworks|CANopen) plugin\b|\bplugin's\b", re.I)
INCLUDE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.M)


def files(exts):
    for top in SOURCES:
        for root, dirs, names in os.walk(os.path.join(ROOT, top)):
            dirs[:] = [d for d in dirs if d not in ("node_modules", ".venv", "__pycache__")]
            for name in names:
                if name.endswith(exts):
                    yield os.path.join(root, name)


class NoRuntimeHeaders(unittest.TestCase):
    def test_no_source_includes_a_runtime_header(self):
        found = []
        for path in files((".c", ".cpp", ".h", ".hpp")):
            with open(path, encoding="utf-8", errors="replace") as f:
                for inc in INCLUDE.findall(f.read()):
                    if os.path.basename(inc) in RUNTIME_HEADERS or "core/src/drivers" in inc:
                        found.append("%s: %s" % (os.path.relpath(path, ROOT), inc))
        self.assertEqual(found, [])

    def test_no_build_file_needs_the_runtime(self):
        builds = [os.path.join(ROOT, "CMakeLists.txt")] + list(files(("CMakeLists.txt", ".cmake")))
        found = []
        for path in builds:
            with open(path, encoding="utf-8") as f:
                if "OPENPLC_ROOT" in f.read():
                    found.append(os.path.relpath(path, ROOT))
        self.assertEqual(found, [])


class NoPluginInSpecs(unittest.TestCase):
    def test_specs_do_not_call_canworks_a_plugin(self):
        found = []
        specs = os.path.join(ROOT, "openspec", "specs")
        for name in sorted(os.listdir(specs)):
            path = os.path.join(specs, name, "spec.md")
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    if PLUGIN_WORDING.search(line) and not re.search(r"removed|no longer", line, re.I):
                        found.append("%s:%d" % (os.path.relpath(path, ROOT), n))
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
