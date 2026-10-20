"""canworks-config --create-shortcut / --remove-shortcut
(configurator-quit-and-background): the Linux .desktop entry and the macOS
app on a temporary home, the Windows .lnk files through PowerShell (for real
in the Windows CI row, else the PowerShell call checked), and remove touching
only its own files."""

import io
import os
import plistlib
import subprocess
import unittest
from unittest import mock

from canworks.configurator import server as srv, shortcut

from .helpers import tmpdir

LAUNCHER = "/opt/tools/bin/canworks-config"


class Base(unittest.TestCase):
    def setUp(self):
        self.home = tmpdir(self)
        self.env = {"HOME": self.home, "PATH": "/usr/bin:/bin"}
        self.calls = []
        p = mock.patch.object(shortcut, "launcher", return_value=LAUNCHER)
        p.start()
        self.addCleanup(p.stop)

    def run_(self, cmd, env=None):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def shortcut(self, platform, remove=False):
        out = io.StringIO()
        code = shortcut.main(remove=remove, platform=platform, env=self.env, run=self.run_, out=out)
        return code, out.getvalue()


class Linux(Base):
    def test_create_and_remove(self):
        code, out = self.shortcut("linux")
        self.assertEqual(code, 0, out)
        entry = os.path.join(self.home, ".local", "share", "applications", "canworks-configurator.desktop")
        icon = os.path.join(self.home, ".local", "share", "icons", "hicolor", "256x256", "apps",
                            "canworks-configurator.png")
        with open(entry) as f:
            text = f.read()
        for line in ("Name=canworks configurator", "Exec=%s --from-shortcut" % LAUNCHER, "Icon=%s" % icon, "Terminal=false",
                     "Categories=Development;Engineering;", "X-Canworks=1"):
            self.assertIn(line + "\n", text)
        self.assertTrue(os.path.isfile(icon))
        self.assertIn(entry, out)
        # Again: replaced, not refused.
        self.assertEqual(self.shortcut("linux")[0], 0)
        code, out = self.shortcut("linux", remove=True)
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(entry))
        self.assertFalse(os.path.exists(icon))
        self.assertIn("No canworks configurator shortcut", self.shortcut("linux", remove=True)[1])

    def test_xdg_data_home_and_quoting(self):
        self.env["XDG_DATA_HOME"] = os.path.join(self.home, "data")
        with mock.patch.object(shortcut, "launcher", return_value="/home/a b/bin/canworks-config"):
            self.assertEqual(self.shortcut("linux")[0], 0)
        with open(os.path.join(self.home, "data", "applications", "canworks-configurator.desktop")) as f:
            self.assertIn('Exec="/home/a b/bin/canworks-config" --from-shortcut\n', f.read())

    def test_only_its_own_file(self):
        entry = os.path.join(self.home, ".local", "share", "applications", "canworks-configurator.desktop")
        os.makedirs(os.path.dirname(entry))
        with open(entry, "w") as f:
            f.write("[Desktop Entry]\nName=mine\n")
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            self.assertEqual(self.shortcut("linux")[0], 2)
        self.assertIn("was not made by canworks-config", err.getvalue())
        self.assertEqual(self.shortcut("linux", remove=True)[0], 0)
        self.assertTrue(os.path.exists(entry))

    def test_without_the_tools_on_path(self):
        with mock.patch.object(shortcut, "launcher", return_value=None), mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(self.shortcut("linux")[0], 2)
        self.assertIn("canworks-config is not on PATH", err.getvalue())


class MacOS(Base):
    def test_app_in_applications(self):
        code, out = self.shortcut("darwin")
        self.assertEqual(code, 0, out)
        app = os.path.join(self.home, "Applications", "canworks configurator.app")
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
            info = plistlib.load(f)
        self.assertEqual((info["CFBundleExecutable"], info["CFBundleIconFile"], info["CanworksShortcut"]),
                         ("canworks-configurator", "logo", True))
        script = os.path.join(app, "Contents", "MacOS", "canworks-configurator")
        with open(script) as f:
            self.assertEqual(f.read(), "#!/bin/sh\n%s --from-shortcut </dev/null >/dev/null 2>&1 &\n" % LAUNCHER)
        if os.name != "nt":
            self.assertTrue(os.access(script, os.X_OK))
        self.assertTrue(os.path.isfile(os.path.join(app, "Contents", "Resources", "logo.icns")))
        self.assertEqual(self.shortcut("darwin")[0], 0)  # made again
        self.assertEqual(self.shortcut("darwin", remove=True)[0], 0)
        self.assertFalse(os.path.exists(app))

    def test_only_its_own_app(self):
        app = os.path.join(self.home, "Applications", "canworks configurator.app")
        os.makedirs(os.path.join(app, "Contents"))
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(self.shortcut("darwin")[0], 2)
        self.shortcut("darwin", remove=True)
        self.assertTrue(os.path.isdir(app))


class WindowsCall(Base):
    """The PowerShell call, on any system."""

    def test_create(self):
        self.env["APPDATA"] = r"C:\Users\u\AppData\Roaming"
        seen = {}

        def run(cmd, env=None):
            seen.update(cmd=cmd, env=env)
            return subprocess.CompletedProcess(cmd, 0, "a.lnk\r\nb.lnk\r\n", "")
        self.assertEqual(shortcut.main(platform="win32", env=self.env, run=run, out=io.StringIO()), 0)
        self.assertEqual(seen["cmd"][0], "powershell")
        self.assertNotIn("Bypass", " ".join(seen["cmd"]))  # windows-installer patterns: none here either
        self.assertIn("WScript.Shell", seen["cmd"][-1])
        self.assertIn("$l.Save()", seen["cmd"][-1])
        env = seen["env"]
        self.assertTrue(env["CANWORKS_LNK_START"].endswith(os.path.join(
            "Microsoft", "Windows", "Start Menu", "Programs", "canworks configurator.lnk")))
        self.assertEqual(env["CANWORKS_LNK_ARGS"], "-m canworks.configurator.start --from-shortcut")
        self.assertTrue(env["CANWORKS_LNK_ICON"].endswith("logo.ico"))
        self.assertEqual(env["CANWORKS_LNK_MARK"], shortcut.MARK)

    def test_failure(self):
        def run(cmd, env=None):
            return subprocess.CompletedProcess(cmd, 1, "", "x\nC:\\a.lnk is there already and was not made by canworks-config\n")
        with mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(shortcut.main(platform="win32", env=self.env, run=run, out=io.StringIO()), 2)
        self.assertIn("was not made by canworks-config", err.getvalue())


@unittest.skipUnless(os.name == "nt", "Windows .lnk files (the Windows CI row)")
class Windows(unittest.TestCase):
    def test_create_and_remove(self):
        d = tmpdir(self)
        env = dict(os.environ, APPDATA=os.path.join(d, "appdata"), CANWORKS_SHORTCUT_DESKTOP=os.path.join(d, "desk"))
        os.makedirs(env["CANWORKS_SHORTCUT_DESKTOP"])
        start = os.path.join(d, "appdata", "Microsoft", "Windows", "Start Menu", "Programs", "canworks configurator.lnk")
        desk = os.path.join(d, "desk", "canworks configurator.lnk")
        other = os.path.join(d, "desk", "other.lnk")
        with open(other, "wb") as f:
            f.write(b"not ours")
        self.assertEqual(shortcut.main(env=env, out=io.StringIO()), 0)
        self.assertTrue(os.path.isfile(start))
        self.assertTrue(os.path.isfile(desk))
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "$l = (New-Object -ComObject WScript.Shell).CreateShortcut($env:P); "
                            "$l.TargetPath; $l.Arguments"], env=dict(env, P=desk), capture_output=True, text=True)
        target, args = r.stdout.splitlines()[:2]
        self.assertTrue(target.lower().endswith(("pythonw.exe", "python.exe")), target)
        self.assertEqual(args, "-m canworks.configurator.start --from-shortcut")
        self.assertEqual(shortcut.main(remove=True, env=env, out=io.StringIO()), 0)
        self.assertFalse(os.path.exists(start))
        self.assertFalse(os.path.exists(desk))
        self.assertTrue(os.path.exists(other))


class Command(unittest.TestCase):
    def test_options(self):
        with mock.patch.object(shortcut, "main", return_value=0) as m:
            self.assertEqual(srv.main(["--create-shortcut"]), 0)
            m.assert_called_with(remove=False)
            self.assertEqual(srv.main(["--remove-shortcut"]), 0)
            m.assert_called_with(remove=True)

    def test_icons_in_the_package(self):
        for name in ("logo.ico", "logo.icns", "logo-256.png"):
            path = os.path.join(shortcut.ICONS, name)
            self.assertGreater(os.path.getsize(path), 1000, name)
        with open(os.path.join(shortcut.ICONS, "logo.ico"), "rb") as f:
            self.assertEqual(f.read(4), b"\0\0\1\0")
        with open(os.path.join(shortcut.ICONS, "logo.icns"), "rb") as f:
            self.assertEqual(f.read(4), b"icns")


if __name__ == "__main__":
    unittest.main()


class AppIcon(unittest.TestCase):
    """app-icon-from-logo: the committed icon files are the ones scripts/make_icons.py writes."""

    HERE = os.path.dirname(shortcut.__file__)

    def read(self, *parts):
        with open(os.path.join(self.HERE, *parts), "rb") as f:
            return f.read()

    def test_ico_sizes(self):
        data = self.read("icons", "logo.ico")
        count = int.from_bytes(data[4:6], "little")
        sizes = sorted((data[6 + 16 * i] or 256) for i in range(count))
        self.assertEqual(sizes, [16, 24, 32, 48, 64, 128, 256])

    def test_icns_small_form(self):
        """macOS shows the 32 px entry (16 pt @2x) in lists: the small form, as in the .ico."""
        icns = self.read("icons", "logo.icns")
        entries, i = {}, 8
        while i < len(icns):
            size = int.from_bytes(icns[i + 4:i + 8], "big")
            entries[icns[i:i + 4]] = icns[i + 8:i + size]
            i += size
        ico = self.read("icons", "logo.ico")
        for k in range(int.from_bytes(ico[4:6], "little")):
            d = ico[6 + 16 * k:22 + 16 * k]
            if d[0] == 32:
                size, offset = int.from_bytes(d[8:12], "little"), int.from_bytes(d[12:16], "little")
                self.assertEqual(entries[b"ic11"], ico[offset:offset + size])
                return
        self.fail("no 32 px frame in logo.ico")

    def test_favicon_follows_dark_mode(self):
        svg = self.read("static", "favicon.svg").decode()
        self.assertIn("prefers-color-scheme:dark", svg)
        self.assertIn("#1f5fbf", svg)  # the logo's blue, not the earlier square's
        self.assertNotIn("#2a5d9f", svg)

    def test_touch_icon(self):
        data = self.read("static", "apple-touch-icon.png")
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual((int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")), (180, 180))
