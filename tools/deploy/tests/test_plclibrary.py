"""The canworks function block library in the deploy tool (specs plc-library
and canopen-plc-sdo)."""

import contextlib
import io
import json
import os
import re
import unittest
from unittest import mock

from canworks import __version__, cli, editorproject, plclibrary

from .helpers import fake_editor_cli, pingpong_config, tmpdir
from .test_deploy import deploy

# The ST blocks over the Modbus bridge's PLC link (add-openplc-modbus-target);
# the C++ plugin blocks are no longer packaged.
BLOCKS = ["CO_NMT", "CO_NODE_LIVE", "CO_SDO_READ", "CO_SDO_WRITE", "J1939_DTC_SPLIT", "J1939_NAME_SPLIT"]
FUNCTIONS = ["CAN_GET_BITS", "CAN_GET_UINT16", "CAN_GET_UINT32", "CAN_J1939_ID", "CAN_J1939_PGN", "CAN_J1939_SOURCE",
             "CAN_SET_BITS", "CAN_SET_UINT16", "CAN_SET_UINT32", "CW_DWORD_TO_REAL", "CW_LREAL_TO_LWORD",
             "CW_LWORD_TO_LREAL", "CW_REAL_TO_DWORD", "J1939_DTC_MAKE", "J1939_GET_BITS", "J1939_NAME_MAKE",
             "J1939_SET_BITS"]


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Archive(unittest.TestCase):
    def test_packaged_library(self):
        data = plclibrary.archive()
        self.assertEqual(data["manifest"]["name"], "canworks")
        self.assertEqual(data["manifest"]["version"], __version__)
        self.assertEqual(sorted(plclibrary.block_names()), BLOCKS)
        self.assertEqual(sorted(plclibrary.function_names()), FUNCTIONS)
        # Every block's source travels in the archive (the editor shows it and
        # compiles it into the program), all ST: the PLC link blocks, the
        # REAL helpers, the CAN_ byte and bit
        # helpers and the J1939 value, bit and NAME helpers.
        helpers = [f + ".st" for f in FUNCTIONS if not f.startswith("CW_")] + ["CW_REAL.st", "J1939_DTC_SPLIT.st", "J1939_NAME_SPLIT.st"]
        self.assertEqual(sorted(s["fileName"] for s in data["sources"]),
                         sorted(["CO_NMT.st", "CO_NODE_LIVE.st", "CO_SDO_READ.st",
                                 "CO_SDO_WRITE.st"] + helpers))

    def test_function_parameters(self):
        # The editor asks a function call for every manifest parameter, so the
        # manifest lists exactly what the compiled signature takes, in its
        # order, and no VAR locals (library/build.sh).
        data = plclibrary.archive()
        headers = {c["name"]: c["header"] for c in data["chunks"] if c.get("kind") == "function"}
        for fn in data["manifest"]["functions"]:
            sig = re.sub(r"<[^<>]*>", "", headers[fn["name"]])
            sig = sig[sig.index("(") + 1:sig.rindex(")")]
            taken = [re.split(r"[\s&*]+", p.strip())[-1] for p in sig.split(",") if p.strip()]
            self.assertEqual([p["name"] for p in fn["parameters"]], taken, fn["name"])
        get_bits = next(f for f in data["manifest"]["functions"] if f["name"] == "J1939_GET_BITS")
        self.assertEqual([p["name"] for p in get_bits["parameters"]], ["DATA", "START_BIT", "BIT_LENGTH", "SIGNED"])

    def test_write(self):
        d = tmpdir(self)
        path = plclibrary.write(d)
        self.assertEqual(path, os.path.join(d, "canworks.stlib"))
        self.assertEqual(load(path)["manifest"]["version"], __version__)
        with self.assertRaises(plclibrary.LibraryError):
            plclibrary.write(os.path.join(d, "missing"))


class UserData(unittest.TestCase):
    def test_paths(self):
        # Joined with this computer's separator, whichever platform is named.
        self.assertEqual(plclibrary.editor_user_data({}, "darwin", "/home/dev"),
                         os.path.join("/home/dev", "Library", "Application Support", "open-plc-editor"))
        self.assertEqual(plclibrary.editor_user_data({"APPDATA": r"C:\\R"}, "win32", "/h"),
                         os.path.join(r"C:\\R", "open-plc-editor"))
        self.assertEqual(plclibrary.editor_user_data({}, "linux", "/home/a"),
                         os.path.join("/home/a", ".config", "open-plc-editor"))
        self.assertEqual(plclibrary.editor_user_data({"OPENPLC_EDITOR_USER_DATA": "/x"}, "linux", "/h"), "/x")


class Install(unittest.TestCase):
    def setUp(self):
        self.ud = os.path.join(tmpdir(self), "open-plc-editor")
        os.makedirs(self.ud)

    def test_new_registry(self):
        self.assertIsNone(plclibrary.installed_version(self.ud))
        path = plclibrary.install(self.ud)
        self.assertEqual(path, os.path.join(self.ud, "libraries", "canworks", "canworks.stlib"))
        reg = load(os.path.join(self.ud, "libraries", "registry.json"))
        self.assertEqual(reg["formatVersion"], "1.0")
        entry = reg["libraries"]["canworks"]
        self.assertEqual((entry["version"], entry["stlibPath"], entry["origin"]), (__version__, path, "stlib"))
        self.assertRegex(entry["installedAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertEqual(plclibrary.installed_version(self.ud), __version__)

    def test_keeps_other_libraries(self):
        os.makedirs(os.path.join(self.ud, "libraries"))
        other = {"version": "1.0.0", "installedAt": "x", "stlibPath": "/y", "origin": "stlib"}
        with open(os.path.join(self.ud, "libraries", "registry.json"), "w") as f:
            json.dump({"formatVersion": "1.0", "libraries": {"other": other,
                                                             "canworks": dict(other, version="0.1.0")}}, f)
        plclibrary.install(self.ud)
        reg = load(os.path.join(self.ud, "libraries", "registry.json"))
        self.assertEqual(reg["libraries"]["other"], other)
        self.assertEqual(reg["libraries"]["canworks"]["version"], __version__)

    def test_bad_registry_untouched(self):
        os.makedirs(os.path.join(self.ud, "libraries"))
        registry = os.path.join(self.ud, "libraries", "registry.json")
        with open(registry, "w") as f:
            f.write("[1]")
        with self.assertRaisesRegex(plclibrary.LibraryError, "not an editor library registry"):
            plclibrary.install(self.ud)
        with open(registry) as f:
            self.assertEqual(f.read(), "[1]")

    def test_no_editor(self):
        with self.assertRaisesRegex(plclibrary.LibraryError, "start OpenPLC Editor once"):
            plclibrary.install(os.path.join(self.ud, "nope"))

    def test_registered_file_missing(self):
        plclibrary.install(self.ud)
        os.remove(os.path.join(self.ud, "libraries", "canworks", "canworks.stlib"))
        self.assertIsNone(plclibrary.installed_version(self.ud))


def editor_project(d):
    os.makedirs(d)
    with open(os.path.join(d, "project.json"), "w") as f:
        json.dump({"meta": {"name": "p"}, "data": {"pous": [], "libraries": [
            {"name": "other", "version": "1.0.0"}, {"name": "canworks", "version": "0.1.0"}]}}, f)
    return d


class EnableInProject(unittest.TestCase):
    def test_enable(self):
        d = editor_project(os.path.join(tmpdir(self), "p"))
        plclibrary.enable_in_project(d)
        plclibrary.enable_in_project(d)
        proj = load(os.path.join(d, "project.json"))
        self.assertEqual(proj["meta"], {"name": "p"})
        self.assertEqual(proj["data"]["libraries"], [{"name": "other", "version": "1.0.0"},
                                                     {"name": "canworks", "version": __version__}])

    def test_not_a_project(self):
        d = tmpdir(self)
        with open(os.path.join(d, "project.json"), "w") as f:
            f.write("{}")
        with self.assertRaisesRegex(plclibrary.LibraryError, "no project data"):
            plclibrary.enable_in_project(d)


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.ud = os.path.join(self.dir, "open-plc-editor")
        os.makedirs(self.ud)
        self.env = {"OPENPLC_EDITOR_USER_DATA": self.ud, "OPENPLC_CLI": fake_editor_cli(self.dir)}

    def test_library_out_and_install(self):
        code, out, err = deploy("library", "--out", self.dir, "--install", env=self.env)
        self.assertEqual(code, 0, err)
        self.assertIn("wrote %s" % os.path.join(self.dir, "canworks.stlib"), out)
        self.assertIn("installed canworks %s into the editor" % __version__, out)
        self.assertEqual(plclibrary.installed_version(self.ud), __version__)

    def test_library_list(self):
        code, out, _ = deploy("library", "--list", env=self.env)
        self.assertEqual((code, sorted(out.split())), (0, sorted(BLOCKS + FUNCTIONS)))

    def test_library_help(self):
        out = cli.library_parser().format_help()
        self.assertIn("J1939 helper functions", " ".join(out.split()))
        self.assertNotIn("CiA 402", out)
        self.assertIn("docs/plc-library.md", " ".join(out.split()).replace("plc- library", "plc-library"))
        self.assertNotIn("SDO library", out)

    def test_library_project(self):
        d = editor_project(os.path.join(self.dir, "p"))
        code, out, err = deploy("library", "--project", d, env=self.env)
        self.assertEqual(code, 0, err)
        self.assertIn("enabled canworks in %s" % d, out)
        self.assertIn("library --install", err)

    def test_library_needs_an_action(self):
        code, _, err = deploy("library", env=self.env)
        self.assertEqual(code, 1)
        self.assertIn("give --out DIR", err)

    def test_new_project_blocks(self):
        config = pingpong_config(self.dir)
        target = os.path.join(self.dir, "pp")
        code, out, err = deploy("--config", config, "--new-project", target, "--blocks", env=self.env)
        self.assertEqual(code, 0, err)
        self.assertEqual(load(os.path.join(target, "project.json"))["data"]["libraries"],
                         [{"name": "canworks", "version": __version__}])
        self.assertIn("installed canworks %s into the editor" % __version__, out)
        # A second project finds the library installed.
        code, out, err = deploy("--config", config, "--new-project", target + "2", "--blocks", env=self.env)
        self.assertEqual(code, 0, err)
        self.assertIn("canworks %s is installed in the editor" % __version__, out)

    def test_new_project_without_editor(self):
        config = pingpong_config(self.dir)
        target = os.path.join(self.dir, "pp")
        env = dict(self.env, OPENPLC_EDITOR_USER_DATA=os.path.join(self.dir, "none"))
        code, _, err = deploy("--config", config, "--new-project", target, "--blocks", env=env)
        self.assertEqual(code, 0, err)
        self.assertIn("library --out DIR", err)
        self.assertEqual(load(os.path.join(target, "project.json"))["data"]["libraries"][0]["name"],
                         "canworks")

    def test_new_project_without_option(self):
        config = pingpong_config(self.dir)
        target = os.path.join(self.dir, "pp")
        code, _, err = deploy("--config", config, "--new-project", target, env=self.env)
        self.assertEqual(code, 0, err)
        self.assertEqual(load(os.path.join(target, "project.json"))["data"]["libraries"], [])
        self.assertFalse(os.path.exists(os.path.join(self.ud, "libraries")))

    def test_blocks_needs_new_project(self):
        code, _, err = deploy("--config", pingpong_config(self.dir), "--check",
                              "--blocks", env=self.env)
        self.assertEqual(code, 1)
        self.assertIn("--blocks needs --new-project", err)

    def test_old_option_is_unknown(self):
        """add-raw-can: --sdo-blocks became --blocks, a clean cut."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as e:
            cli.main(["--config", pingpong_config(self.dir), "--new-project", os.path.join(self.dir, "pp"),
                      "--sdo-blocks"])
        self.assertEqual(e.exception.code, 2)
        self.assertIn("unrecognized arguments: --sdo-blocks", err.getvalue())
        self.assertFalse(os.path.exists(os.path.join(self.dir, "pp")))


class CreateDirect(unittest.TestCase):
    def test_create_enables(self):
        d = tmpdir(self)
        with mock.patch.dict(os.environ, {"OPENPLC_CLI": fake_editor_cli(d)}):
            config = pingpong_config(d)
            path, _ = editorproject.create(load(config), config, os.path.join(d, "x"), blocks=True)
        self.assertEqual(load(os.path.join(path, "project.json"))["data"]["libraries"][0]["name"],
                         "canworks")


if __name__ == "__main__":
    unittest.main()
