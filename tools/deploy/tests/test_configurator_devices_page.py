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

# The release's install-bridge.sh, as the job fetches it with curl.
BRIDGE_SCRIPT = r"""#!/bin/bash
echo "::canworks-step 1/3 Downloading canworks $2"
echo "args: $*"
echo "::canworks-step 2/3 Building canworks-bridge"
sleep "${FAKE_BUILD_S:-0}"
echo "::canworks-step 3/3 Starting the bridge"
mkdir -p "$FAKE_FS/opt/canworks/bin" "$FAKE_FS/etc/systemd/system"
printf '#!/bin/sh\n' > "$FAKE_FS/opt/canworks/bin/canworks-bridge"
chmod +x "$FAKE_FS/opt/canworks/bin/canworks-bridge"
: > "$FAKE_FS/etc/systemd/system/canworks-bridge@.service"
echo 0.98.0 > "$FAKE_FS/opt/canworks/VERSION"
instance=""; config=""
while [ $# -gt 0 ]; do
    case $1 in
        --instance) instance=$2; shift ;;
        --config) config=$2; shift ;;
    esac
    shift
done
if [ -n "$instance" ]; then
    mkdir -p "$FAKE_FS/etc/canworks-bridge/$instance"
    cp "$config"/* "$FAKE_FS/etc/canworks-bridge/$instance/"
    echo active > "$FAKE_UNITS/canworks-bridge@$instance.service"
fi
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
       echo '{"config": "/etc/canworks-bridge/line1/canworks.json"}' > "$FAKE_FS/etc/canworks-link/link.json"
       echo active > "$FAKE_UNITS/canworks-link.service" ;;
esac
"""


# The release's install-adapter.sh: the unit the probe reads, and the verifier
# and adapter server file it was given (add-devices-adapter-server,
# add-adapter-server-file: both uploaded from this PC).
ADAPTER_SCRIPT = r"""#!/bin/bash
echo "args: $*"
mkdir -p "$FAKE_FS/etc/systemd/system"
unit="$FAKE_FS/etc/systemd/system/canworks-adapter-can0.service"
case " $* " in
    *" --uninstall "*) rm -f "$unit" "$FAKE_UNITS/canworks-adapter-can0.service"; exit 0 ;;
esac
echo "::canworks-step 1/2 Installing the adapter server"
echo "::canworks-step 2/2 Starting the adapter server on can0"
user=""; rate=""; port=""; changes=""; verifier=""; file=""
while [ $# -gt 0 ]; do
    case $1 in
        --user) user=$2; shift ;;
        --bitrate) rate=$2; shift ;;
        --port) port=$2; shift ;;
        --allow-changes) changes=" --allow-changes" ;;
        --verifier-file) verifier=$2; shift ;;
        --file) file=$2; shift ;;
    esac
    shift
done
[ -z "$verifier" ] || cp "$verifier" "$FAKE_FS/verifier-seen"
[ -z "$file" ] || cp "$file" "$FAKE_FS/file-seen"
printf '[Service]
User=%s
ExecStart=/usr/bin/python3 /opt/canworks-adapter/canworks-adapter.pyz adapter-serve --adapter socketcan:can0 --bitrate %s --port %s%s
'     "$user" "$rate" "$port" "$changes" > "$unit"
echo active > "$FAKE_UNITS/canworks-adapter-can0.service"
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
        self.put("var/lib/openplc-bootloader/runtime-spec.json", '{"version": "v4.3.1"}\n')
        # An older bridge, not started for this project yet.
        self.put_file(os.path.join(self.fs, "opt/canworks/bin/canworks-bridge"), "#!/bin/sh\n", 0o755)
        self.put("etc/systemd/system/canworks-bridge@.service", "")
        self.put("opt/canworks/VERSION", "0.93.4\n")
        raw = os.path.join(self.device.root, "raw")
        self.put_file(os.path.join(raw, "deploy-v0.98.0", "scripts", "install-bridge.sh"), BRIDGE_SCRIPT)
        self.put_file(os.path.join(raw, "deploy-v0.98.0", "scripts", "install-link.sh"), LINK_SCRIPT)
        self.put_file(os.path.join(raw, "deploy-v0.98.0", "scripts", "install-adapter.sh"), ADAPTER_SCRIPT)
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
        # canworks parts only: no OpenPLC runtime row, though the device has one.
        self.assertEqual([r[0] for r in rows], ["bridge", "link", "discovery", "can", "adapter"])
        self.assertEqual(rows[0][:3], ["bridge", "0.93.4", "this project's config as rtd-monitor"])
        self.assertEqual(pg.inner_text("[data-devices=start]"), "Update 0.93.4 → 0.98.0")
        self.assertIn("internet ok", pg.inner_text("[data-devices=header]"))
        # The device has neither the remote link nor the advertisement: the update keeps them off, unfolded.
        self.assertTrue(pg.eval_on_selector("[data-devices=options]", "d => d.open"))
        self.assertFalse(pg.is_checked("[data-devices-option=link]"))
        self.assertFalse(pg.is_checked("[data-devices-option=discovery]"))

        os.environ["FAKE_BUILD_S"] = "2"
        self.addCleanup(os.environ.pop, "FAKE_BUILD_S", None)
        pg.click("[data-devices=start]")
        pg.wait_for_selector("#modal[open] [data-devices=sudo]")
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
        self.assertIn("The bridge runs this project's saved config as rtd-monitor.", pg.inner_text("[data-devices=done]"))
        pg.click("[data-devices=log] summary")
        # the log text arrives after the click (a busy machine shows that)
        pg.wait_for_selector("[data-devices=log] pre:has-text('args: --version 0.98.0 --instance rtd-monitor --config')")
        self.assertRegex(pg.inner_text("[data-devices=log] pre"), r"(?m)--remove-config-dir --without-discovery$")
        pg.wait_for_selector("[data-devices=up-to-date]")
        self.assertIn("0.98.0", pg.inner_text('[data-devices=rows] tr[data-part="bridge"]'))
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
        self.assertIn("install_bridge", stored["job_seconds"])
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
        # bridge for a device with nothing of canworks, a job, and the
        # same device listed when a config is opened afterwards.
        pg = self.page
        # A device with nothing on it: no runtime, no bridge.
        shutil.rmtree(os.path.join(self.fs, "opt", "canworks"))
        shutil.rmtree(os.path.join(self.fs, "var/lib/openplc-bootloader"))
        os.remove(os.path.join(self.fs, "etc/systemd/system/canworks-bridge@.service"))
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
        pg.wait_for_selector("[data-devices=start]:has-text('Install the bridge 0.98.0')")
        self.assertEqual(pg.locator("[data-devices=roles]").count(), 0)
        self.assertNotIn("OpenPLC", pg.inner_text("#view"))
        self.assertEqual(pg.eval_on_selector_all("[data-devices=rows] thead th", "ts => ts.length"), 3)
        self.assertIn("Nothing installed yet", pg.inner_text(".devices-list"))
        self.assertIn("starts with a config", pg.inner_text("[data-devices=main-hint]"))
        self.assertEqual(pg.locator("[data-devices=options]").count(), 0)
        pg.click("[data-devices=start]")
        self.answer("go", {"[data-devices=sudo]": SUDO_PW})
        pg.wait_for_selector("[data-devices=done]", timeout=20000)
        self.assertIn("The bridge is installed", pg.inner_text("[data-devices=done]"))
        pg.wait_for_selector("[data-devices=up-to-date]")
        self.assertEqual(pg.locator("#modal[open]").count(), 0)
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

    def test_remote_can_adapter(self):
        # add-devices-adapter-server: turned on with no config, the token made on
        # this PC and only its verifier on the device, Change… keeping it, and
        # Connect from this PC opening the connect panel on the device.
        pg = self.page
        ip = os.path.join(self.device.bin, "ip-can0")
        self.put_file(ip, '#!/bin/sh\ncase "$*" in *"type can"*) echo \'[{"ifname":"can0","flags":["UP"],"linkinfo":'
                          '{"info_kind":"can","info_data":{"bittiming":{"bitrate":500000}}}}]\' ;; *) echo "[]" ;; esac\n', 0o755)
        self.server.devices.probe_env["CANWORKS_PROBE_IP"] = ip
        # The release's script and adapter server file, as this PC downloads them.
        release = os.path.join(self.dir, "release-0.98.0")
        self.put_file(os.path.join(release, "install-adapter.sh"), ADAPTER_SCRIPT, 0o755)
        self.put_file(os.path.join(release, "canworks-adapter-0.98.0.pyz"), "canworks-diag 0.98.0\n")
        self.server.devices.adapter_files = lambda v: [os.path.join(release, "install-adapter.sh"),
                                                       os.path.join(release, "canworks-adapter-%s.pyz" % v)]
        pg.set_viewport_size({"width": 1280, "height": 900})
        pg.goto(self.server.url)
        pg.click("#start-devices")
        self.add_device(config=False)
        self.answer("cancel")  # no key login
        row = "[data-devices=rows] tr[data-part=adapter]"
        pg.wait_for_selector(row + " [data-devices-action=adapter_on]")
        self.assertIn("Remote CAN adapter", pg.inner_text(row))
        self.assertIn("off", pg.inner_text(row))
        pg.click(row + " [data-devices-action=adapter_on]")
        pg.wait_for_selector("#modal[open] [data-devices=adapter-form]")
        self.assertEqual(pg.input_value("[data-devices=adapter-bitrate]"), "500")  # can0 is up at it
        self.assertTrue(pg.is_checked("[data-devices=adapter-allow]"))
        self.answer("go", {"[data-devices=sudo]": SUDO_PW})
        pg.wait_for_selector("[data-devices=done]", timeout=20000)
        self.assertIn("The remote CAN adapter is on", pg.inner_text("[data-devices=done]"))
        pg.wait_for_selector(row + ":has-text('can0 · 500 kbit/s · running · changes allowed')")
        # The token is this PC's; the device got its verifier only, and no log has it.
        with open(os.path.join(self.cfg_dir, "online.json")) as f:
            token = json.load(f)["adapter_tokens"]["127.0.0.1"]
        with open(os.path.join(self.fs, "verifier-seen")) as f:
            self.assertTrue(diag.token_matches(token, f.read().strip()))
        with open(os.path.join(self.fs, "file-seen")) as f:
            self.assertEqual(f.read(), "canworks-diag 0.98.0\n")  # uploaded: nothing downloaded on the device
        for folder, _, files in os.walk(self.device.root):
            for name in files:
                with open(os.path.join(folder, name), "rb") as f:
                    self.assertNotIn(token.encode(), f.read(), os.path.join(folder, name))
        self.assertEqual(pg.locator(row + " [data-devices-action=adapter_copy_token]").count(), 1)
        self.assertEqual(pg.locator(row + " [data-devices-action=adapter_token]").count(), 0)
        # Change…: read-only for every PC, same token.
        pg.click(row + " [data-devices-action=adapter_change]")
        pg.wait_for_selector("#modal[open] [data-devices=adapter-form]")
        self.assertEqual(pg.input_value("[data-devices=adapter-bitrate]"), "500")
        pg.uncheck("[data-devices=adapter-allow]")
        self.answer("go", {"[data-devices=sudo]": SUDO_PW})
        pg.wait_for_selector(row + ":has-text('read-only')", timeout=20000)
        with open(os.path.join(self.cfg_dir, "online.json")) as f:
            self.assertEqual(json.load(f)["adapter_tokens"]["127.0.0.1"], token)
        # Connect from this PC: Commission a CANopen device, the panel on this adapter.
        pg.click(row + " [data-devices-action=adapter_connect]")
        pg.wait_for_selector("#conn-dialog[open] [data-online=remote-box]")
        self.assertEqual(pg.input_value("[data-online=remote-host]"), "127.0.0.1")
        self.assertEqual(pg.get_attribute("[data-online=remote-token]", "placeholder"), "kept on this PC")
        self.assertFalse(pg.is_checked("[data-online=adapter-allow]"))  # each connection starts read-only

    def test_link_and_discovery_switches(self):
        # device-link-switches: the remote link and the advertisement turned
        # on and off from their rows, with no config open.
        pg = self.page
        self.put("etc/canworks-bridge/line1/canworks.json", "{}\n")  # the bridge the link serves
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
        pg.wait_for_selector(link + ":has-text('running · serves the bridge line1')")
        self.assertIn("The remote link is on", pg.inner_text("[data-devices=done]"))
        run(link, "link_off", "stay paired")
        pg.wait_for_selector(link + " [data-devices-action=link_on]")
        self.assertIn("not installed", pg.inner_text(link))
        run(disc, "discovery_on")
        pg.wait_for_selector(disc + " [data-devices-action=discovery_off]")
        self.assertIn("yes", pg.inner_text(disc))
        self.assertNotIn("Step ", pg.inner_text("[data-devices=job]") if pg.locator("[data-devices=job]").count() else "")
        # A narrow window: the rows' buttons stay inside the page, not behind a scroller.
        pg.set_viewport_size({"width": 800, "height": 860})
        # Long values (a commit hash, several interfaces) wrap instead of widening the table.
        pg.evaluate("""() => document.querySelector('tr[data-part=can] td:nth-child(2)').textContent =
            'slcan0 500 kbit/s up · can1 250 kbit/s up · vcan0 (virtual) · serial /dev/serial/by-id/usbCANable0123456789abcdef0123456789abcdef0123456789'""")
        pg.wait_for_timeout(100)
        cut = pg.evaluate("""() => [...document.querySelectorAll('table.devices-rows button')].filter((b) => {
            const r = b.getBoundingClientRect();
            let p = b.parentElement;
            for (; p; p = p.parentElement) {
                const c = p.getBoundingClientRect();
                if (getComputedStyle(p).overflowX !== 'visible' && (r.right > c.right + 1 || r.left < c.left - 1)) return true;
            }
            return r.right > window.innerWidth;
        }).map((b) => b.textContent)""")
        self.assertEqual(cut, [])

    def test_another_projects_bridge_runs(self):
        # UI-4, UI-5, UI-8, UI-12, UI-15: vp2 runs on the same port and
        # interface; Update names it and stops it first; the finished job keeps
        # naming its own instance in another project; the page at 800 px.
        pg = self.page
        self.put("etc/canworks-bridge/vp2/canworks.json", json.dumps({
            "schema_version": 2, "bridge": {"listen": "127.0.0.1:1502"},
            "networks": [{"name": "io", "adapter": {"interface": "vcan0"}, "nodes": []}]}))
        with open(os.path.join(self.device.units, "canworks-bridge@vp2.service"), "w") as f:
            f.write("active\n")
        self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
        self.add_device()
        self.answer("cancel")  # no key login
        pg.wait_for_selector("[data-devices=start]:has-text('Update 0.93.4 → 0.98.0')")
        pg.click("[data-devices=start]")
        pg.wait_for_selector("#modal[open] [data-devices=sudo]")
        self.assertIn("The bridge vp2 runs on this device", pg.inner_text("#modal-extra"))
        clash = pg.eval_on_selector_all("#modal [data-devices=clash]", "ns => ns.map((n) => n.innerText)")
        self.assertEqual(len(clash), 2, clash)
        self.assertIn("vp2 listens on port 1502 too", clash[0])
        self.assertIn("vp2 drives vcan0 too", clash[1])
        self.assertEqual(pg.inner_text('#modal button[data-value="stop"]'), "Stop vp2 and start rtd-monitor")
        self.assertIn("primary", pg.get_attribute('#modal button[data-value="stop"]', "class"))
        self.assertEqual(pg.inner_text('#modal button[data-value="next"]'), "Start next to vp2")
        # The sudo field: its label above the input, the hint below.
        box = pg.evaluate("""() => { const f = document.querySelector('#modal .devices-sudo');
            const r = (n) => n.getBoundingClientRect();
            return [r(f.querySelector('label')).top, r(f.querySelector('input')).top, r(f.querySelector('input')).bottom,
                    r(f.querySelector('.hint')).top]; }""")
        self.assertLess(box[0] + 4, box[1])
        self.assertLessEqual(box[2], box[3])
        self.answer("stop", {"[data-devices=sudo]": SUDO_PW})
        pg.wait_for_selector("[data-devices=done]", timeout=20000)
        self.assertIn("The bridge runs this project's saved config as rtd-monitor.", pg.inner_text("[data-devices=done]"))
        with open(os.path.join(self.device.units, "canworks-bridge@vp2.service")) as f:
            self.assertEqual(f.read().strip(), "inactive")
        pg.wait_for_selector("[data-devices=up-to-date]")
        self.assertRegex(pg.inner_text("[data-devices=log] summary"), r"^Log \(\d+ lines?\)$")

        # The page at 800 px: the list above the details, the user name in its case.
        pg.set_viewport_size({"width": 800, "height": 860})
        pg.wait_for_timeout(100)
        tops = pg.evaluate("""() => [document.querySelector('.devices-pane').getBoundingClientRect().bottom,
            document.querySelector('.devices-page').getBoundingClientRect().top]""")
        self.assertLessEqual(tops[0], tops[1])
        self.assertTrue(pg.inner_text(".devices-page > .devices-head h3").startswith("pi@"))
        split = pg.evaluate("""() => [...document.querySelectorAll('table.devices-rows td')].filter((td) => {
            const words = td.innerText.split(/\\s+/).filter(Boolean);
            return words.some((w) => { const s = document.createElement('span'); s.textContent = w;
                s.style.whiteSpace = 'nowrap'; td.append(s); const wide = s.offsetWidth > td.clientWidth; s.remove(); return wide; });
        }).map((td) => td.innerText)""")
        self.assertEqual(split, [])
        self.assertEqual(pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), True)
        pg.click("[data-devices=menu] summary")
        self.assertEqual(pg.inner_text("[data-devices=remove-all]"), "Uninstall canworks from the device…")
        self.assertEqual(pg.inner_text("[data-devices=remove]"), "Forget this device")
        pg.click("[data-devices=menu] summary")

        # Another project opened: the finished job still names rtd-monitor.
        other = os.path.join(self.dir, "om2")
        shutil.copytree(self.project, other)
        header_action(pg, "#btn-close")
        pg.wait_for_selector("#start:not([hidden])")
        # In the same tab, as Close and Open do (no reload: the page keeps its jobs).
        pg.click("#start-open")
        pg.fill("[data-folder=path]", other)
        pg.click("[data-folder=dialog] [data-value=use]")
        pg.wait_for_selector("#editor:not([hidden])")
        pg.click('#ws button[data-ws="devices"]')
        pg.wait_for_selector(".devices-list [data-device]")
        pg.click(".devices-list [data-device]")
        pg.wait_for_selector("[data-devices=done]")
        self.assertIn("The bridge runs the saved config of rtd-monitor.", pg.inner_text("[data-devices=done]"))
        self.assertEqual(pg.locator("[data-devices=open-commission]").count(), 0)

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
