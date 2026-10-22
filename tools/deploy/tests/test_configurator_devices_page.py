"""The Devices workspace in a real browser (device-install task 4.3): a
device over SSH (fake_ssh.py) with a fake file system for the probe and the
release's install scripts served from a folder, so a job runs the way it
runs on a device. Needs Playwright, like test_configurator_page.py."""

import json
import os
import shutil
import sys
import unittest
import unittest.mock

from canworks import diag

from .helpers import header_action, tmpdir, tree_view
from .test_configurator_online_page import TOKEN, OnlineBase

try:
    import paramiko
except ImportError:  # the tools and page jobs install it
    paramiko = None

if paramiko is not None:
    from canworks.devices import service, ssh
    from . import fake_ssh

SSH_PW, SUDO_PW = "ssh-secret", "sudo-secret"

# The release's install-runtime.sh, as the job fetches it with curl.
RUNTIME_SCRIPT = """#!/bin/bash
echo "::canworks-step 1/3 Downloading canworks $2"
echo "args: $*"
echo "::canworks-step 2/3 Building the plugin in the runtime's image"
sleep "${FAKE_BUILD_S:-0}"
echo "::canworks-step 3/3 Restarting the runtime (the PLC stops)"
mkdir -p "$FAKE_FS/opt/canworks/lib"
: > "$FAKE_FS/opt/canworks/lib/libcanworks_plugin.so"
echo 0.98.0 > "$FAKE_FS/opt/canworks/VERSION"
"""

# The release's install-link.sh: the files the probe looks at (device-link-switches).
LINK_SCRIPT = """#!/bin/bash
echo "args: $*"
case " $* " in
    *" --remove-discovery "*) rm -f "$FAKE_FS/etc/avahi/services/canworks.service" ;;
    *" --discovery-only "*) mkdir -p "$FAKE_FS/etc/avahi/services"; : > "$FAKE_FS/etc/avahi/services/canworks.service" ;;
    *" --uninstall "*) rm -f "$FAKE_FS/etc/systemd/system/canworks-link.service" "$FAKE_UNITS/canworks-link.service" ;;
    *) mkdir -p "$FAKE_FS/etc/systemd/system" "$FAKE_FS/etc/canworks-link"
       : > "$FAKE_FS/etc/systemd/system/canworks-link.service"
       echo '{"config": "/opt/canworks/lib/canworks.json"}' > "$FAKE_FS/etc/canworks-link/link.json"
       echo active > "$FAKE_UNITS/canworks-link.service" ;;
esac
"""


@unittest.skipUnless(paramiko is not None and sys.platform != "win32" and shutil.which("flock")
                     and shutil.which("setsid"), "needs paramiko, sh, flock and setsid")
class DevicesPage(OnlineBase):
    def setUp(self):
        super().setUp()
        env = unittest.mock.patch.dict(os.environ, {"HOME": os.path.join(self.dir, "pc-home")})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("SSH_AUTH_SOCK", None)
        self.device = fake_ssh.Device(os.path.join(tmpdir(self), "device"))
        self.addCleanup(self.device.close)
        self.fs = os.path.join(self.device.root, "fs")
        os.makedirs(os.path.join(self.fs, "run", "systemd", "system"))
        self.put("var/lib/openplc-bootloader/runtime-spec.json", '{"version": "v4.2.4"}\n')
        self.put("opt/canworks/lib/libcanworks_plugin.so", "")
        self.put("opt/canworks/VERSION", "0.93.4\n")
        self.put("opt/canworks/lib/runtime-version", "v4.2.4\n")
        raw = os.path.join(self.device.root, "raw")
        self.put_file(os.path.join(raw, "deploy-v0.98.0", "scripts", "install-runtime.sh"), RUNTIME_SCRIPT)
        self.put_file(os.path.join(raw, "deploy-v0.98.0", "scripts", "install-link.sh"), LINK_SCRIPT)
        paths = self.device.paths(self.fs)
        paths.raw = "file://" + raw
        stub = os.path.join(self.device.bin, "curl-ok")
        self.put_file(stub, '#!/bin/sh\nfor a; do [ "$a" = -w ] && printf 200; done; exit 0\n', 0o755)
        self.server.devices = service.Devices(self.cfg_dir, paths=paths, latest=lambda: "0.98.0", probe_env={
            "CANWORKS_PROBE_ROOT": self.fs, "CANWORKS_PROBE_UID": "1000", "CANWORKS_PROBE_CURL": stub,
            "CANWORKS_PROBE_SYSTEMCTL": paths.systemctl})
        self.addCleanup(self.server.devices.close_all)
        # The job's shell finds the fake file system here (RUNTIME_SCRIPT).
        os.environ["FAKE_FS"] = self.fs
        self.addCleanup(os.environ.pop, "FAKE_FS", None)

    def put(self, rel, text):
        self.put_file(os.path.join(self.fs, rel), text)

    def put_file(self, path, text, mode=0o644):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)

    def answer(self, value, fill=None):
        pg = self.page
        pg.wait_for_selector("#modal[open]")
        if fill:
            for sel, text in fill.items():
                pg.fill(sel, text)
        pg.click(f'#modal button[data-value="{value}"]')

    def add_device(self, config=True):
        pg = self.page
        if config:
            self.open()
            pg.click('#ws button[data-ws="devices"]')
        pg.wait_for_selector("[data-devices=empty]")
        pg.click("[data-devices=add]")
        self.answer("add", {"[data-devices=host]": "127.0.0.1", "[data-devices=user]": "pi",
                            "[data-devices=port]": str(self.device.port)})
        pg.wait_for_selector("#modal[open] [data-devices=fingerprint]")
        self.assertEqual(pg.inner_text("[data-devices=fingerprint]"), ssh.fingerprint(self.device.host_key))
        self.assertEqual(self.device.commands, [])  # nothing sent before Trust and connect
        self.answer("trust")
        pg.wait_for_selector("#modal[open] [data-devices=password]")
        self.assertIn("give the password", pg.inner_text("#modal-text"))
        self.answer("login", {"[data-devices=password]": SSH_PW})

    def test_add_probe_update_and_job(self):
        pg = self.page
        self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
        self.add_device()
        # After a password login: the key login offer.
        pg.wait_for_selector("#modal[open] >> text=Use key login from now on")
        self.answer("key")
        pg.wait_for_selector("#banner:has-text('Key login set up')")
        with open(os.path.join(self.device.home("pi"), ".ssh", "authorized_keys")) as f:
            self.assertEqual(len(f.read().splitlines()), 1)
        rows = pg.eval_on_selector_all("[data-devices=rows] tbody tr", "rs => rs.map((r) => [r.dataset.part, "
                                       "r.cells[1].innerText, r.cells[2].innerText, r.classList.contains('muted-row')])")
        self.assertEqual(rows[1][:3], ["plugin", "0.93.4 · built for v4.2.4 · waiting for an upload", "newest 0.98.0"])
        self.assertEqual(rows[2], ["bridge", "not installed", "not used by this project", True])
        self.assertEqual(pg.inner_text("[data-devices=start]"), "Update 0.93.4 → 0.98.0")
        self.assertIn("internet ok", pg.inner_text("[data-devices=header]"))

        os.environ["FAKE_BUILD_S"] = "2"
        self.addCleanup(os.environ.pop, "FAKE_BUILD_S", None)
        pg.click("[data-devices=start]")
        pg.wait_for_selector("#modal[open] [data-devices=sudo]")
        self.assertEqual(pg.inner_text("[data-devices=effect]"),
                         "The PLC stops and comes back without a program; upload it again afterwards.")
        self.assertEqual(pg.inner_text("#modal-text"), "Update 0.93.4 → 0.98.0 on 127.0.0.1:%d?" % self.device.port)
        self.answer("go", {"[data-devices=sudo]": "wrong"})
        pg.wait_for_selector("#modal[open] [data-devices=sudo-error]:has-text('did not accept')")
        self.answer("go", {"[data-devices=sudo]": SUDO_PW})
        pg.wait_for_selector("[data-devices=steps] li[aria-current=step]")
        # The status bar lists it, with Show.
        pg.wait_for_selector("#jobs [data-job-show]")
        self.assertIn("Installing on 127.0.0.1:%d" % self.device.port, pg.inner_text("#jobs"))

        # The page is reloaded during the build: opening the device picks the job up.
        pg.reload()
        pg.wait_for_selector("[data-devices=page]")
        pg.click(".devices-list [data-device]")
        pg.wait_for_selector("[data-devices=done]", timeout=20000)
        self.assertEqual(pg.eval_on_selector_all("[data-devices=steps] li", "ls => ls.map((l) => l.dataset.step)"),
                         ["1", "2", "3"])
        self.assertIn("switches on with the next upload", pg.inner_text("[data-devices=done]"))
        self.assertIn("Until then the PLC has no program.", pg.inner_text("[data-devices=done]"))
        pg.click("[data-devices=log] summary")
        self.assertIn("args: --version 0.98.0 --with-link", pg.inner_text("[data-devices=log] pre"))
        pg.wait_for_selector("[data-devices=up-to-date]")
        self.assertIn("0.98.0", pg.inner_text('[data-devices=rows] tr[data-part="plugin"]'))
        # The status bar drops the job at its next look (a poll in flight may still list it).
        pg.wait_for_function("() => document.querySelector('#jobs').innerText.trim() === ''")
        # Online access shows the device as the runtime host at once, without a reload.
        pg.click('#ws button[data-ws="configure"]')
        tree_view(pg, "project")
        pg.wait_for_selector("[data-devices=host-state]")
        self.assertEqual(pg.input_value('[data-online="host"]'), "127.0.0.1")
        self.assertEqual(pg.inner_text("[data-devices=host-state] .muted"), "127.0.0.1: up to date.")

        # Nothing secret on this PC.
        for dirpath, _, names in os.walk(self.cfg_dir):
            for n in names:
                with open(os.path.join(dirpath, n), "rb") as f:
                    data = f.read()
                self.assertNotIn(SSH_PW.encode(), data, n)
                self.assertNotIn(SUDO_PW.encode(), data, n)
        with open(os.path.join(self.cfg_dir, "devices.json")) as f:
            stored = json.load(f)["devices"][0]
        self.assertEqual(stored["host"], "127.0.0.1")
        self.assertIn("install_plugin", stored["job_seconds"])
        # The device became the project's runtime host (it had none).
        with open(os.path.join(self.cfg_dir, "online.json")) as f:
            self.assertEqual(json.load(f)["projects"][self.project]["host"], "127.0.0.1")

    def test_field_message_and_not_reached(self):
        # ux-cleanup "Device messages": a refused field says so under itself;
        # a device that does not answer gets one sentence and a checklist.
        import socket
        pg = self.page
        self.open()
        pg.click('#ws button[data-ws="devices"]')
        pg.click("[data-devices=add]")
        self.answer("add", {"[data-devices=host]": "127.0.0.1", "[data-devices=port]": "ssh"})
        pg.wait_for_selector("[data-devices-msg=port]:has-text('The SSH port is a number')")
        self.assertEqual(pg.inner_text("[data-devices-msg=host]"), "")
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            closed = sk.getsockname()[1]
        self.answer("add", {"[data-devices=port]": str(closed)})
        pg.wait_for_selector("[data-devices=unreached]")
        text = pg.inner_text("[data-devices=device-bars]")
        self.assertIn("Can't reach 127.0.0.1 on SSH port %d." % closed, text)
        self.assertIn("same network", text)
        self.assertNotIn("Errno", text)
        self.assertIn("Not reached", pg.inner_text(".devices-list"))
        self.assertEqual(pg.inner_text("[data-devices=menu] summary"), "Actions")

    def test_blocked_and_entry_points(self):
        pg = self.page
        self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
        self.remember("line9.local:7531")
        self.put_file(os.path.join(self.device.bin, "curl-ok"), "#!/bin/sh\nexit 7\n", 0o755)
        self.add_device()
        self.answer("cancel")  # no key login
        pg.wait_for_selector("[data-devices=blocked]")
        self.assertEqual(pg.inner_text("[data-devices=blocked]"),
                         "The device cannot reach github.com, which the install downloads from.")
        self.assertTrue(pg.is_disabled("[data-devices=start]"))
        # Remove device forgets it on this PC only.
        pg.click("[data-devices=menu] summary")
        pg.click("[data-devices=remove]")
        self.answer("remove")
        pg.wait_for_selector("[data-devices=empty]")
        self.assertTrue(os.path.isdir(self.device.home("pi")))
        # Online access: the runtime host as a device, and the way to install on it.
        pg.click('#ws button[data-ws="configure"]')
        tree_view(pg, "project")
        pg.wait_for_selector("[data-devices=host-state]")
        self.assertIn("line9.local is not in Devices yet.", pg.inner_text("[data-devices=host-state]"))
        pg.click("[data-devices=open-host]")
        pg.wait_for_selector("#modal[open] [data-devices=host]")
        self.assertEqual(pg.input_value("[data-devices=host]"), "line9.local")
        self.assertEqual(pg.evaluate("workspace()"), "devices")
        self.answer("cancel")

    def test_without_config(self):
        # devices-without-config: the start page's Install on a device, the
        # role question for a device with nothing of canworks, a job, and the
        # same device listed when a config is opened afterwards.
        pg = self.page
        shutil.rmtree(os.path.join(self.fs, "opt", "canworks"))
        pg.set_viewport_size({"width": 1280, "height": 860})
        pg.goto(self.server.url)
        self.assertEqual(pg.inner_text("#start-devices"), "Install on a device")
        pg.click("#start-devices")
        pg.wait_for_selector("#mode:has-text('Devices · no config')")
        self.assertTrue(pg.is_hidden("#ws"))
        self.assertTrue(pg.is_hidden("#btn-save"))
        # No config: the header has room, so Close, Settings and Quit are
        # buttons, not a ⋯ menu, even under 1500 px.
        self.assertTrue(pg.is_hidden("#menu-more"))
        for sel in ("#btn-close", "#menu-settings", "#btn-quit"):
            self.assertTrue(pg.is_visible(sel), sel)
        self.assertNotIn("Raspberry", pg.inner_text("#view"))
        self.add_device(config=False)
        self.answer("cancel")  # no key login
        pg.wait_for_selector("[data-devices=roles]")
        self.assertEqual(pg.eval_on_selector_all("[data-devices=rows] thead th", "ts => ts.length"), 3)
        self.assertEqual(pg.inner_text("[data-devices=start]"), "Install canworks 0.98.0")
        self.assertIn("Nothing installed yet", pg.inner_text(".devices-list"))
        pg.click("label:has([data-devices-role=bridge])")
        pg.wait_for_selector("[data-devices=start]:has-text('Install the bridge 0.98.0')")
        self.assertTrue(pg.is_checked("[data-devices-role=bridge]"))
        self.assertEqual(pg.locator("[data-devices=options]").count(), 0)
        pg.click("label:has([data-devices-role=openplc])")
        pg.wait_for_selector("[data-devices=start]:has-text('Install canworks 0.98.0')")
        pg.click("[data-devices=start]")
        self.answer("go", {"[data-devices=sudo]": SUDO_PW})
        pg.wait_for_selector("[data-devices=done]", timeout=20000)
        self.assertIn("switches on with the next upload", pg.inner_text("[data-devices=done]"))
        pg.wait_for_selector("[data-devices=up-to-date]")
        # The bridge can be added next to the PLC from its row.
        pg.click("[data-devices-install=bridge]")
        pg.wait_for_selector("#modal[open]")
        self.assertIn("Install the bridge 0.98.0", pg.inner_text("#modal-text"))
        self.assertIn("same CAN interface", pg.inner_text("#modal"))
        self.answer("cancel")
        # No project took the device as its runtime host.
        online_json = os.path.join(self.cfg_dir, "online.json")
        if os.path.isfile(online_json):
            with open(online_json) as f:
                self.assertFalse(any((p or {}).get("host") for p in (json.load(f).get("projects") or {}).values()))
        # Close: the start page; a config opened next lists the same device.
        header_action(pg, "#btn-close")
        pg.wait_for_selector("#start:not([hidden])")
        self.open()
        pg.click('#ws button[data-ws="devices"]')
        pg.wait_for_selector(".devices-list [data-device]")
        self.assertIn("127.0.0.1", pg.inner_text(".devices-list"))
        pg.click(".devices-list [data-device]")
        pg.wait_for_selector("[data-devices=rows]")
        self.assertEqual(pg.eval_on_selector_all("[data-devices=rows] thead th", "ts => ts.length"), 4)

    def test_link_and_discovery_switches(self):
        # device-link-switches: the remote link and the advertisement turned
        # on and off from their rows, with no config open.
        pg = self.page
        pg.goto(self.server.url)
        pg.click("#start-devices")
        self.add_device(config=False)
        self.answer("cancel")  # no key login
        link = "[data-devices=rows] tr[data-part=link]"
        disc = "[data-devices=rows] tr[data-part=discovery]"
        pg.wait_for_selector(link + " [data-devices-action=link_on]")
        self.assertIn("not installed", pg.inner_text(link))
        self.assertIn("no", pg.inner_text(disc))

        def run(sel, action, effect=None):
            pg.click(f"{sel} [data-devices-action={action}]")
            pg.wait_for_selector("#modal[open]")
            if effect:
                self.assertIn(effect, pg.inner_text("#modal"))
            self.answer("go", {"[data-devices=sudo]": SUDO_PW})
            pg.wait_for_selector("[data-devices=done]", timeout=20000)

        run(link, "link_on")
        pg.wait_for_selector(link + ":has-text('running · serves the PLC')")
        self.assertIn("The remote link is on", pg.inner_text("[data-devices=done]"))
        run(link, "link_off", "stay paired")
        pg.wait_for_selector(link + " [data-devices-action=link_on]")
        self.assertIn("not installed", pg.inner_text(link))
        run(disc, "discovery_on")
        pg.wait_for_selector(disc + " [data-devices-action=discovery_off]")
        self.assertIn("yes", pg.inner_text(disc))

    def test_pc_tools_older_than_the_device(self):
        # A newer minor on the device: a note with Update PC tools…, which
        # checks for a release and otherwise gives the command to copy. A
        # patch-only difference says nothing.
        pg = self.page
        self.put("opt/canworks/VERSION", "99.1.0\n")
        view = {"version": "0.111.0", "latest": "0.111.0", "newer": False, "kind": "other", "why": "test",
                "command": "curl -fsSL https://example.invalid/install.sh | sh", "release_url": "https://example.invalid"}
        for route in ("**/api/update", "**/api/update/check"):
            pg.route(route, lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(view)))
        pg.goto(self.server.url)
        pg.click("#start-devices")
        self.add_device(config=False)
        self.answer("cancel")  # no key login
        pg.wait_for_selector("[data-devices=pc-older]")
        self.assertIn("(99.1.0) is newer than these PC tools", pg.inner_text("[data-devices=pc-older]"))
        pg.click("[data-devices=update-pc]")
        pg.wait_for_selector("#modal[open] .update-command textarea")
        self.assertEqual(pg.input_value("#modal .update-command textarea"), view["command"])
        self.answer("cancel")


if __name__ == "__main__":
    unittest.main()
