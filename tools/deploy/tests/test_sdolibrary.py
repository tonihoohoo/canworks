"""The canworks editor library in the deploy tool (add-plc-sdo-blocks
tasks 4.1, 4.2 and 4.5)."""

import contextlib
import io
import json
import os
import unittest
from unittest import mock

from canworks import __version__, cli, editorproject, sdolibrary

from .helpers import fake_editor_cli, pingpong_config, tmpdir
from .test_deploy import deploy

BLOCKS = ["CAN_BUS_INFO", "CAN_RECEIVE", "CAN_SEND", "CAN_SEND_CYCLIC", "CO402_CYCLICMOVEABSOLUTE", "CO402_CYCLICPOSITION", "CO402_CYCLICTORQUE", "CO402_CYCLICVELOCITY",
          "CO_GET_STATE", "CO_NETWORK_START", "CO_NETWORK_STOP", "CO_NMT", "CO_SDO_READ", "CO_SDO_READ_BYTES", "CO_SDO_READ_REAL", "CO_SDO_READ_STRING", "CO_SDO_WRITE",
          "CO_SDO_WRITE_BYTES", "CO_SDO_WRITE_REAL", "CO_SDO_WRITE_STRING"]


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Archive(unittest.TestCase):
    def test_packaged_library(self):
        data = sdolibrary.archive()
        self.assertEqual(data["manifest"]["name"], "canworks")
        self.assertEqual(data["manifest"]["version"], __version__)
        self.assertEqual(sorted(sdolibrary.block_names()), BLOCKS)
        # Every block's source travels in the archive (the editor shows it and
        # compiles it into the program): C++ for the SDO, NMT and frame blocks, ST
        # for the cyclic CiA 402 blocks and the CAN_ byte and bit helpers.
        helpers = ["CAN_GET_BITS.st", "CAN_GET_UINT16.st", "CAN_GET_UINT32.st", "CAN_J1939_ID.st",
                   "CAN_J1939_PGN.st", "CAN_J1939_SOURCE.st", "CAN_SET_BITS.st", "CAN_SET_UINT16.st",
                   "CAN_SET_UINT32.st"]
        self.assertEqual(sorted(s["fileName"] for s in data["sources"]),
                         sorted(["CO402_CyclicMoveAbsolute.st", "CO402_CyclicPosition.st", "CO402_CyclicTorque.st",
                                 "CO402_CyclicVelocity.st"] + helpers +
                                [b + ".cpp" for b in BLOCKS if not b.startswith("CO402")]))

    def test_write(self):
        d = tmpdir(self)
        path = sdolibrary.write(d)
        self.assertEqual(path, os.path.join(d, "canworks.stlib"))
        self.assertEqual(load(path)["manifest"]["version"], __version__)
        with self.assertRaises(sdolibrary.LibraryError):
            sdolibrary.write(os.path.join(d, "missing"))


class UserData(unittest.TestCase):
    def test_paths(self):
        # Joined with this computer's separator, whichever platform is named.
        self.assertEqual(sdolibrary.editor_user_data({}, "darwin", "/home/dev"),
                         os.path.join("/home/dev", "Library", "Application Support", "open-plc-editor"))
        self.assertEqual(sdolibrary.editor_user_data({"APPDATA": r"C:\\R"}, "win32", "/h"),
                         os.path.join(r"C:\\R", "open-plc-editor"))
        self.assertEqual(sdolibrary.editor_user_data({}, "linux", "/home/a"),
                         os.path.join("/home/a", ".config", "open-plc-editor"))
        self.assertEqual(sdolibrary.editor_user_data({"OPENPLC_EDITOR_USER_DATA": "/x"}, "linux", "/h"), "/x")


class Install(unittest.TestCase):
    def setUp(self):
        self.ud = os.path.join(tmpdir(self), "open-plc-editor")
        os.makedirs(self.ud)

    def test_new_registry(self):
        self.assertIsNone(sdolibrary.installed_version(self.ud))
        path = sdolibrary.install(self.ud)
        self.assertEqual(path, os.path.join(self.ud, "libraries", "canworks", "canworks.stlib"))
        reg = load(os.path.join(self.ud, "libraries", "registry.json"))
        self.assertEqual(reg["formatVersion"], "1.0")
        entry = reg["libraries"]["canworks"]
        self.assertEqual((entry["version"], entry["stlibPath"], entry["origin"]), (__version__, path, "stlib"))
        self.assertRegex(entry["installedAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertEqual(sdolibrary.installed_version(self.ud), __version__)

    def test_keeps_other_libraries(self):
        os.makedirs(os.path.join(self.ud, "libraries"))
        other = {"version": "1.0.0", "installedAt": "x", "stlibPath": "/y", "origin": "stlib"}
        with open(os.path.join(self.ud, "libraries", "registry.json"), "w") as f:
            json.dump({"formatVersion": "1.0", "libraries": {"other": other,
                                                             "canworks": dict(other, version="0.1.0")}}, f)
        sdolibrary.install(self.ud)
        reg = load(os.path.join(self.ud, "libraries", "registry.json"))
        self.assertEqual(reg["libraries"]["other"], other)
        self.assertEqual(reg["libraries"]["canworks"]["version"], __version__)

    def test_bad_registry_untouched(self):
        os.makedirs(os.path.join(self.ud, "libraries"))
        registry = os.path.join(self.ud, "libraries", "registry.json")
        with open(registry, "w") as f:
            f.write("[1]")
        with self.assertRaisesRegex(sdolibrary.LibraryError, "not an editor library registry"):
            sdolibrary.install(self.ud)
        with open(registry) as f:
            self.assertEqual(f.read(), "[1]")

    def test_no_editor(self):
        with self.assertRaisesRegex(sdolibrary.LibraryError, "start OpenPLC Editor once"):
            sdolibrary.install(os.path.join(self.ud, "nope"))

    def test_registered_file_missing(self):
        sdolibrary.install(self.ud)
        os.remove(os.path.join(self.ud, "libraries", "canworks", "canworks.stlib"))
        self.assertIsNone(sdolibrary.installed_version(self.ud))


def editor_project(d):
    os.makedirs(d)
    with open(os.path.join(d, "project.json"), "w") as f:
        json.dump({"meta": {"name": "p"}, "data": {"pous": [], "libraries": [
            {"name": "other", "version": "1.0.0"}, {"name": "canworks", "version": "0.1.0"}]}}, f)
    return d


class EnableInProject(unittest.TestCase):
    def test_enable(self):
        d = editor_project(os.path.join(tmpdir(self), "p"))
        sdolibrary.enable_in_project(d)
        sdolibrary.enable_in_project(d)
        proj = load(os.path.join(d, "project.json"))
        self.assertEqual(proj["meta"], {"name": "p"})
        self.assertEqual(proj["data"]["libraries"], [{"name": "other", "version": "1.0.0"},
                                                     {"name": "canworks", "version": __version__}])

    def test_not_a_project(self):
        d = tmpdir(self)
        with open(os.path.join(d, "project.json"), "w") as f:
            f.write("{}")
        with self.assertRaisesRegex(sdolibrary.LibraryError, "no project data"):
            sdolibrary.enable_in_project(d)


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
        self.assertEqual(sdolibrary.installed_version(self.ud), __version__)

    def test_library_list(self):
        code, out, _ = deploy("library", "--list", env=self.env)
        self.assertEqual((code, sorted(out.split())), (0, BLOCKS))

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
        code, _, err = deploy("--config", pingpong_config(self.dir), "--check-only", "--bundle", self.dir,
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
