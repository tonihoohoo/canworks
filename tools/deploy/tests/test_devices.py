"""The Devices workspace without a device (device-install): the plan from probe
results, devices.json, the job commands and log parsing, the release lookup
and device-probe.sh on fake device folders."""

import json
import os
import shutil
import subprocess
import sys
import unittest

from canworks.devices import jobs, plan, release, store

from .helpers import tmpdir

PROBE = os.path.join(os.path.dirname(jobs.__file__), "device-probe.sh")
HAVE_SH = sys.platform != "win32" and shutil.which("sh") is not None


def probe(**over):
    """A probe result: a Linux device with the managed Docker runtime and nothing of canworks."""
    out = {"probe": 1, "os": "Debian GNU/Linux 12 (bookworm)", "arch": "aarch64", "systemd": True,
           "disk_free_mb": 20000, "mem_mb": 8000, "internet": True, "sudo": "password",
           "runtime": {"kind": "docker-managed", "version": "v4.3.1", "commit": None, "answers": True},
           "plugin": None, "bridge": None, "link": None, "discovery": False, "can": [], "vcan": [],
           "serial": [], "j1939_module": False, "install_job": None}
    out.update(over)
    return out


def row(p, part):
    return next(r for r in p["rows"] if r["part"] == part)


class Plan(unittest.TestCase):
    def test_old_plugin_is_updated(self):
        p = plan.plan(probe(plugin={"version": "0.93.4", "built_for": "v4.3.1", "enabled": True}), "openplc", "0.98.0")
        self.assertIn("0.93.4", row(p, "plugin")["have"])
        self.assertEqual(row(p, "plugin")["needs"], "newest 0.98.0")
        self.assertEqual(p["main"]["action"], "install_plugin")
        self.assertEqual(p["main"]["label"], "Update 0.93.4 → 0.98.0")
        self.assertEqual(p["main"]["version"], "0.98.0")
        self.assertEqual(p["main"]["confirm"], [plan.DOCKER_STOP])

    def test_native_update_needs_no_confirmation(self):
        rt = {"kind": "native", "version": "v4.3.1", "commit": "abc", "answers": True}
        p = plan.plan(probe(runtime=rt, plugin={"version": "0.93.4", "built_for": "abc", "enabled": True}),
                      "openplc", "0.98.0")
        self.assertEqual(p["main"]["confirm"], [])

    def test_no_runtime(self):
        p = plan.plan(probe(runtime={"kind": "none"}), "openplc", "0.98.0")
        self.assertEqual(p["main"]["action"], "install_openplc")
        self.assertEqual(p["main"]["label"], "Install OpenPLC Runtime and canworks 0.98.0")
        self.assertIn(plan.OPENPLC_INSTALLER, p["main"]["confirm"][0])
        self.assertEqual(row(p, "runtime")["have"], "not installed")

    def test_runtime_no_plugin(self):
        p = plan.plan(probe(), "openplc", "0.98.0")
        self.assertEqual(p["main"]["label"], "Install canworks 0.98.0")

    def test_can_bit_rates(self):
        can = [{"ifname": "can0", "flags": ["UP"], "linkinfo": {"info_kind": "can",
                "info_data": {"bittiming": {"bitrate": 250000}}}},
               # slcan: fixed bit rates, the rate flat in info_data (ip -j -d).
               {"ifname": "slcan0", "flags": ["UP"], "linkinfo": {"info_kind": "can",
                "info_data": {"bittiming_bitrate": 500000, "bitrate_const": [125000, 500000]}}}]
        p = plan.plan(probe(can=can), "openplc", "0.98.0")
        self.assertEqual(row(p, "can")["have"], "can0 250 kbit/s up · slcan0 500 kbit/s up")

    def test_bridge_without_its_service_is_installed(self):
        b = {"version": "0.98.1", "prefix": "/opt/canworks-bridge", "unit": False, "instances": []}
        p = plan.plan(probe(bridge=b), "bridge", "0.98.1", instance="line3")
        self.assertEqual(p["main"]["action"], "install_bridge")
        self.assertEqual(p["main"]["label"], "Install and start this project's bridge")
        self.assertIn("no service", row(p, "bridge")["have"])

    def test_bridge_install_keeps_the_plcs_link(self):
        p = plan.plan(probe(link="active", link_config="/opt/canworks/lib/canworks.json"), "bridge", "0.98.3",
                      instance="line3")
        self.assertTrue(p["main"]["link_kept"])
        p = plan.plan(probe(link="active", link_config="/etc/canworks-bridge/line3/canworks.json"), "bridge",
                      "0.98.3", instance="line3")
        self.assertNotIn("link_kept", p["main"])
        self.assertNotIn("link_kept", plan.plan(probe(), "bridge", "0.98.3", instance="line3")["main"])

    def test_development_bridge_is_updated(self):
        b = {"version": "deploy-v0.32.0-192-g0bd645be", "prefix": "/opt/canworks-bridge", "unit": True, "instances": []}
        p = plan.plan(probe(bridge=b), "bridge", "0.98.2", instance="line3")
        self.assertEqual(p["main"]["action"], "install_bridge")
        self.assertEqual(p["main"]["label"], "Update deploy-v0.32.0-192-g0bd645be → 0.98.2")

    def test_native_runtime_moved_on(self):
        p = plan.plan(probe(runtime={"kind": "native", "version": "v4.2.5", "commit": "def"},
                            plugin={"version": "0.98.0", "built_for": "abc", "enabled": True}), "openplc", "0.98.0")
        self.assertEqual(p["main"]["label"], "Rebuild for runtime v4.2.5")
        self.assertIn("off", row(p, "plugin")["have"])
        self.assertIn("built for abc", p["notes"][0])

    # freeze-openplc-runtime: a managed Docker runtime off the pin goes back to it.
    def test_runtime_moved_on_from_the_editor(self):
        major, minor, patch = plan.version_tuple(plan.TESTED_RUNTIME)
        newer = "v%d.%d.%d" % (major, minor, patch + 1)
        p = plan.plan(probe(runtime={"kind": "docker-managed", "version": newer},
                            plugin={"version": "0.98.0", "built_for": plan.TESTED_RUNTIME, "enabled": True}),
                      "openplc", "0.98.0")
        self.assertEqual(row(p, "runtime")["hint"],
                         "canworks runs on runtime %s; this device runs %s." % (plan.TESTED_RUNTIME, newer))
        self.assertEqual(p["main"]["label"], "Switch runtime to %s" % plan.TESTED_RUNTIME)
        self.assertEqual(p["main"]["action"], "install_plugin")
        self.assertEqual(p["main"]["confirm"], [
            "The runtime goes from %s back to %s, the version canworks is tested with." % (newer, plan.TESTED_RUNTIME),
            plan.DOCKER_STOP])
        self.assertIn("Switch the runtime back", p["notes"][0])

    def test_update_also_switches_back(self):
        p = plan.plan(probe(runtime={"kind": "docker-managed", "version": "v4.2.4"},
                            plugin={"version": "0.97.0", "built_for": "v4.2.4", "enabled": True}), "openplc", "0.98.0")
        self.assertEqual(p["main"]["label"], "Update 0.97.0 → 0.98.0")
        self.assertIn("back to %s" % plan.TESTED_RUNTIME, p["main"]["confirm"][0])

    def test_other_runtime_note(self):
        major, minor, patch = plan.version_tuple(plan.TESTED_RUNTIME)
        older = "v%d.%d.0" % (major, minor - 1) if minor else "v0.0.1"
        p = plan.plan(probe(runtime={"kind": "docker-managed", "version": older}), "openplc", "0.98.0")
        self.assertEqual(row(p, "runtime")["hint"],
                         "canworks runs on runtime %s; this device runs %s." % (plan.TESTED_RUNTIME, older))
        for version in (plan.TESTED_RUNTIME, None, "development"):
            p = plan.plan(probe(runtime={"kind": "docker-managed", "version": version}), "openplc", "0.98.0")
            self.assertIsNone(row(p, "runtime")["hint"], version)

    def test_runtime_install_names_the_pin(self):
        p = plan.plan(probe(runtime={"kind": "none"}), "openplc", "0.98.0")
        self.assertEqual(p["main"]["action"], "install_openplc")
        self.assertIn("installs Docker and OpenPLC runtime %s, the version canworks is tested with" % plan.TESTED_RUNTIME,
                      p["main"]["confirm"][0])

    def test_up_to_date(self):
        p = plan.plan(probe(plugin={"version": "0.98.0", "built_for": "v4.3.1", "enabled": True}), "openplc", "0.98.0")
        self.assertIsNone(p["main"])
        self.assertTrue(p["up_to_date"])
        self.assertEqual(row(p, "plugin")["state"], "ok")

    def test_bridge_muted_in_an_openplc_project(self):
        p = plan.plan(probe(), "openplc", "0.98.0")
        self.assertEqual(row(p, "bridge")["state"], "off")
        self.assertFalse(row(p, "bridge")["used"])
        self.assertEqual(row(p, "bridge")["needs"], "not used by this project")

    def test_pc_tools_older_than_the_device(self):
        p = plan.plan(probe(plugin={"version": "0.99.0", "built_for": "v4.3.1", "enabled": True}), "openplc", "0.99.0",
                      pc_version="0.98.0")
        self.assertIsNone(p["main"])
        self.assertEqual(row(p, "plugin")["state"], "ok")
        self.assertEqual(p["pc_older"], {"pc": "0.98.0", "device": "0.99.0"})

    def test_pc_tools_older_by_a_patch_only(self):
        p = plan.plan(probe(plugin={"version": "0.99.2", "built_for": "v4.3.1", "enabled": True}), "openplc", "0.99.2",
                      pc_version="0.99.0")
        self.assertIsNone(p["pc_older"])
        p = plan.plan(probe(plugin={"version": "0.99.0", "built_for": "v4.3.1", "enabled": True}), "openplc", "0.99.0",
                      pc_version="0.99.0")
        self.assertIsNone(p["pc_older"])

    def test_no_internet(self):
        p = plan.plan(probe(internet=False), "openplc", "0.98.0")
        self.assertEqual(p["blocked"], "The device cannot reach github.com, which the install downloads from.")

    def test_blocked_reasons(self):
        for over, text in (({"systemd": False}, "no systemd"), ({"sudo": "unavailable"}, "cannot use sudo"),
                           ({"install_job": {"state": "active"}}, "An install is running"),
                           ({"disk_free_mb": 900}, "Less than 2 GB")):
            with self.subTest(over=over):
                self.assertIn(text, plan.plan(probe(**over), "openplc", "0.98.0")["blocked"])
        self.assertIn("could not be found", plan.plan(probe(), "openplc", None)["blocked"])

    def test_bridge_project(self):
        p = plan.plan(probe(runtime={"kind": "none"}), "bridge", "0.98.0", instance="line3")
        self.assertEqual(p["main"]["action"], "install_bridge")
        self.assertEqual(p["main"]["label"], "Install and start this project's bridge")
        self.assertFalse(row(p, "runtime")["used"])
        self.assertFalse(row(p, "plugin")["used"])

        running = {"version": "0.97.0", "prefix": "/opt/canworks-bridge",
                   "instances": [{"name": "line3", "state": "active", "sha256": "aa"}]}
        p = plan.plan(probe(bridge=running), "bridge", "0.98.0", instance="line3", config_sha256="aa")
        self.assertEqual(p["main"]["label"], "Update 0.97.0 → 0.98.0")
        self.assertEqual(p["main"]["confirm"], ["Running bridges restart."])

        current = dict(running, version="0.98.0")
        p = plan.plan(probe(bridge=current), "bridge", "0.98.0", instance="line3", config_sha256="bb")
        self.assertEqual((p["main"]["action"], p["main"]["label"]), ("bridge_config", "Start this project's bridge"))
        self.assertIn("restarts with this project's saved config", p["main"]["confirm"][0])

        p = plan.plan(probe(bridge=current), "bridge", "0.98.0", instance="line3", config_sha256="aa")
        self.assertIsNone(p["main"])
        self.assertEqual(row(p, "bridge")["state"], "ok")

    def test_openplc_modbus_project(self):
        # OpenPLC through Modbus: the runtime and this project's bridge, the plugin no longer used.
        p = plan.plan(probe(runtime={"kind": "none"}), "openplc_modbus", "0.98.0", instance="line3")
        self.assertEqual(p["main"]["action"], "install_openplc_bridge")
        self.assertEqual(p["main"]["label"], "Install OpenPLC Runtime and this project's bridge")
        self.assertIn(plan.OPENPLC_INSTALLER, p["main"]["confirm"][0])
        self.assertTrue(row(p, "runtime")["used"])
        self.assertEqual(row(p, "runtime")["needs"], "needed")
        self.assertTrue(row(p, "bridge")["used"])
        self.assertFalse(row(p, "plugin")["used"])

        # A runtime with the old plugin: the bridge is installed, the plugin row says to uninstall it.
        old = {"version": "0.93.4", "built_for": "v4.3.1", "enabled": True}
        p = plan.plan(probe(plugin=old), "openplc_modbus", "0.98.0", instance="line3")
        self.assertEqual(p["main"]["action"], "install_bridge")
        self.assertIn("no longer used", row(p, "plugin")["needs"])
        self.assertEqual(row(p, "plugin")["state"], "warn")
        self.assertTrue(row(p, "plugin")["uninstall"])
        self.assertIn("uninstall it", p["notes"][0])

        current = {"version": "0.98.0", "prefix": "/opt/canworks-bridge",
                   "instances": [{"name": "line3", "state": "active", "sha256": "aa"}]}
        p = plan.plan(probe(bridge=current), "openplc_modbus", "0.98.0", instance="line3", config_sha256="aa")
        self.assertIsNone(p["main"])
        self.assertTrue(p["up_to_date"])

    def test_codesys(self):
        p = plan.plan(probe(), "codesys", "0.98.0")
        self.assertIsNone(p["main"])
        self.assertFalse(p["up_to_date"])
        self.assertIn("CODESYS installs its runtime itself", p["notes"][0])

    def test_can_rows(self):
        can = [{"ifname": "can0", "flags": ["UP"], "linkinfo": {"info_kind": "can",
                                                              "info_data": {"bittiming": {"bitrate": 250000}}}}]
        vcan = [{"ifname": "vcan0", "flags": [], "linkinfo": {"info_kind": "vcan"}}]
        p = plan.plan(probe(can=can, vcan=vcan, serial=["usb-slcan"]), "openplc", "0.98.0")
        self.assertEqual(row(p, "can")["have"], "can0 250 kbit/s up · vcan0 (virtual) · serial usb-slcan")

    def test_header(self):
        self.assertEqual(plan.header(probe()), "Debian GNU/Linux 12 (bookworm) · aarch64 · 20 GB free · internet ok")

    def test_version_tuple(self):
        self.assertEqual(plan.version_tuple("deploy-v0.98.0"), (0, 98, 0))
        self.assertIsNone(plan.version_tuple("0.98.0-3-gabc"))


class PlanWithoutConfig(unittest.TestCase):
    """devices-without-config: no target; what the device has, or the role
    the page picks, gives the main action."""

    def test_fresh_device_asks_what_it_runs(self):
        p = plan.plan(probe(runtime={"kind": "none"}), None, "0.110.0")
        self.assertEqual([r["role"] for r in p["roles"]], ["openplc", "bridge"])
        self.assertEqual(p["roles"][0]["main"]["label"], "Install OpenPLC Runtime and canworks 0.110.0")
        self.assertEqual((p["roles"][1]["main"]["action"], p["roles"][1]["main"]["label"]),
                         ("install_bridge", "Install the bridge 0.110.0"))
        self.assertFalse(p["up_to_date"])
        self.assertTrue(all(r["used"] and r["needs"] == "" for r in p["rows"]))

    def test_runtime_without_plugin(self):
        p = plan.plan(probe(), None, "0.110.0")
        self.assertEqual(p["roles"][0]["main"]["label"], "Install canworks 0.110.0")

    def test_installed_plugin_picks_the_action(self):
        p = plan.plan(probe(plugin={"version": "0.105.0", "built_for": "v4.3.1", "enabled": True}), None, "0.110.0")
        self.assertIsNone(p["roles"])
        self.assertEqual(p["main"]["label"], "Update 0.105.0 → 0.110.0")
        p = plan.plan(probe(plugin={"version": "0.110.0", "built_for": "v4.3.1", "enabled": True}), None, "0.110.0")
        self.assertIsNone(p["main"])
        self.assertTrue(p["up_to_date"])

    def test_installed_bridge_picks_the_action(self):
        b = {"version": "0.105.0", "prefix": "/opt/canworks-bridge",
             "instances": [{"name": "packer", "state": "active", "sha256": "aa"}]}
        p = plan.plan(probe(runtime={"kind": "none"}, bridge=b), None, "0.110.0")
        self.assertIsNone(p["roles"])
        self.assertEqual((p["main"]["action"], p["main"]["label"]), ("install_bridge", "Update 0.105.0 → 0.110.0"))
        self.assertEqual(p["main"]["confirm"], ["Running bridges restart."])
        p = plan.plan(probe(runtime={"kind": "none"}, bridge=dict(b, version="0.110.0")), None, "0.110.0")
        self.assertIsNone(p["main"])
        self.assertTrue(p["up_to_date"])

    def test_the_other_part_installs_from_its_row(self):
        # A PLC device can get the bridge too (and a bridge device the plugin):
        # its row has Install, the main action stays the installed part's.
        p = plan.plan(probe(plugin={"version": "0.110.0", "built_for": "v4.3.1", "enabled": True}), None, "0.110.0")
        self.assertIsNone(p["main"])
        self.assertEqual((row(p, "bridge")["actions"][0]["action"], row(p, "bridge")["actions"][0]["label"]),
                         ("install_bridge", "Install the bridge 0.110.0"))
        self.assertIn("same CAN interface", row(p, "bridge")["actions"][0]["confirm"][0])
        self.assertNotIn("actions", row(p, "plugin"))
        b = {"version": "0.110.0", "prefix": "/opt/canworks-bridge", "instances": []}
        p = plan.plan(probe(runtime={"kind": "none"}, bridge=b), None, "0.110.0")
        self.assertEqual(row(p, "plugin")["actions"][0]["action"], "install_openplc")
        p = plan.plan(probe(bridge=b), None, "0.110.0")
        self.assertEqual(row(p, "plugin")["actions"][0]["label"], "Install canworks 0.110.0")
        # With a config, the project's target decides: no extra Install.
        p = plan.plan(probe(plugin={"version": "0.110.0", "built_for": "v4.3.1", "enabled": True}), "openplc", "0.110.0")
        self.assertNotIn("actions", row(p, "bridge"))
        p = plan.plan(probe(internet=False, plugin={"version": "0.110.0", "built_for": "v4.3.1", "enabled": True}),
                      None, "0.110.0")
        self.assertIn("github.com", p["blocked"])

    def test_link_and_discovery_switches(self):
        # device-link-switches: the rows' own actions and what the link serves.
        on = {"version": "0.110.0", "built_for": "v4.3.1", "enabled": True}
        p = plan.plan(probe(plugin=on), None, "0.110.0")
        self.assertEqual([a["action"] for a in row(p, "link")["actions"]], ["link_on"])
        self.assertEqual([a["action"] for a in row(p, "discovery")["actions"]], ["discovery_on"])
        p = plan.plan(probe(plugin=on, link="active", link_config="/opt/canworks/lib/canworks.json", discovery=True),
                      "openplc", "0.110.0")
        self.assertEqual(row(p, "link")["have"], "running · serves the PLC")
        self.assertEqual([a["action"] for a in row(p, "link")["actions"]], ["link_off"])
        self.assertIn("stay paired", row(p, "link")["actions"][0]["confirm"][0])
        self.assertEqual([a["action"] for a in row(p, "discovery")["actions"]], ["discovery_off"])
        p = plan.plan(probe(plugin=on, link="failed", link_config="/opt/canworks/lib/canworks.json"), None, "0.110.0")
        self.assertEqual([a["action"] for a in row(p, "link")["actions"]], ["link_start", "link_off"])
        # Nothing to serve, or a CODESYS project: no switches.
        self.assertNotIn("actions", row(plan.plan(probe(), None, "0.110.0"), "link"))
        self.assertNotIn("actions", row(plan.plan(probe(plugin=on), "codesys", "0.110.0"), "discovery"))

    def test_link_serves(self):
        two = {"version": "0.110.0", "instances": [{"name": "packer"}, {"name": "line2"}]}
        self.assertEqual(plan.link_serves(probe(bridge=two)), {"choose": ["packer", "line2"]})
        self.assertEqual(plan.link_serves(probe(bridge=two), "line2")["config"], "/etc/canworks-bridge/line2/canworks.json")
        self.assertEqual(plan.link_serves(probe(bridge=dict(two, instances=[{"name": "packer"}])))["text"], "the bridge packer")
        self.assertEqual(plan.link_serves(probe(bridge=two, plugin={"version": "0.110.0"}))["runtime_port"], "8443")
        self.assertEqual(plan.link_serves(probe(bridge=two, link="active",
                                                link_config="/etc/canworks-bridge/line2/canworks.json"))["text"],
                         "the bridge line2")
        self.assertIsNone(plan.link_serves(probe(bridge=dict(two, instances=[]))))
        p = plan.plan(probe(runtime={"kind": "none"}, bridge=two), None, "0.110.0")
        self.assertEqual(row(p, "link")["actions"][0]["choose"], ["packer", "line2"])

    def test_blocked_applies_to_the_roles(self):
        self.assertIn("github.com", plan.plan(probe(internet=False), None, "0.110.0")["blocked"])


class Store(unittest.TestCase):
    def test_no_secrets(self):
        d = tmpdir(self)
        s = store.Store(d)
        did = s.add("line3.local", "pi")
        with self.assertRaises(store.DeviceError):
            s.update(did, password="x")
        s.update(did, probe={"probe": 1}, latest="0.98.0")
        self.assertEqual(s.get(did)["latest"], "0.98.0")
        if os.name == "posix":
            self.assertEqual(os.stat(s.path).st_mode & 0o777, 0o600)
        self.assertEqual(s.add("line3.local", port=2222), "line3.local:2222")
        s.remove(did)
        self.assertEqual([x["host"] for x in s.devices()], ["line3.local"])

    def test_one_list_for_the_pc(self):
        # devices-without-config: one list, whatever project is open; the old per-project lists are not read.
        d = tmpdir(self)
        with open(os.path.join(d, store.FILE), "w") as f:
            json.dump({"projects": {"/p": [{"host": "old.local", "port": 22, "user": "u"}]}}, f)
        s = store.Store(d)
        self.assertEqual(s.devices(), [])
        s.add("line3.local", "admin")
        self.assertEqual([x["host"] for x in store.Store(d).devices()], ["line3.local"])
        self.assertNotIn("projects", s.load())

    def test_checks(self):
        s = store.Store(tmpdir(self))
        for host in ("", "-oProxyCommand=x", "a b"):
            with self.assertRaises(store.DeviceError):
                s.add(host)
        with self.assertRaises(store.DeviceError):
            s.add("h", "bad user")
        with self.assertRaises(store.DeviceError):
            s.add("h", port=70000)


class Jobs(unittest.TestCase):
    paths = jobs.Paths()

    def test_commands(self):
        self.assertEqual(jobs.commands("install_plugin", "0.98.0", self.paths), [
            "curl -LsSf https://raw.githubusercontent.com/tonihoohoo/canworks/deploy-v0.98.0/scripts/"
            "install-runtime.sh | bash -s -- --version 0.98.0 --with-link"])
        self.assertTrue(jobs.commands("install_openplc", "0.98.0", self.paths, link=False, discovery=False)[0]
                        .endswith("--version 0.98.0 --with-openplc --pinned-runtime --without-discovery"))
        self.assertTrue(jobs.commands("install_plugin", "0.98.0", self.paths, pinned_runtime=True)[0]
                        .endswith("--version 0.98.0 --pinned-runtime --with-link"))
        line = jobs.commands("install_bridge", "0.98.0", self.paths, instance="line3",
                             upload="/tmp/canworks-bridge-upload.abc")[0]
        self.assertIn("install-bridge.sh | bash -s -- --version 0.98.0 --instance line3 --config "
                      "/tmp/canworks-bridge-upload.abc --remove-config-dir --with-link line3", line)
        line = jobs.commands("install_openplc_bridge", "0.98.0", self.paths, instance="line3",
                             upload="/tmp/canworks-bridge-upload.abc")[0]
        self.assertIn("install-runtime.sh | bash -s -- --version 0.98.0 --with-openplc --pinned-runtime --bridge "
                      "--instance line3 --config /tmp/canworks-bridge-upload.abc --remove-config-dir --with-link line3",
                      line)
        self.assertTrue(jobs.commands("uninstall_bridge", "0.98.0", self.paths, purge=True)[0].endswith(
            "--uninstall --purge"))
        for bad in (dict(version="0.98.0; rm -rf /"), dict(instance="a b"), dict(upload="/etc")):
            with self.subTest(bad=bad), self.assertRaises(jobs.JobError):
                args = dict(version="0.98.0", instance=None, upload=None)
                args.update(bad)
                jobs.commands("install_bridge", args["version"], self.paths, instance=args["instance"],
                              upload=args["upload"])

    def test_link_commands(self):
        sh = "install-link.sh | bash -s -- "
        on = jobs.commands("link_on", "0.98.0", self.paths, discovery=False,
                           link_config="/opt/canworks/lib/canworks.json", runtime_port="8443")[0]
        self.assertTrue(on.endswith(sh + "--version 0.98.0 --config /opt/canworks/lib/canworks.json "
                                         "--runtime-port 8443 --without-discovery"), on)
        self.assertTrue(jobs.commands("link_off", "0.98.0", self.paths)[0].endswith(sh + "--uninstall --keep-discovery"))
        self.assertTrue(jobs.commands("link_off", "0.98.0", self.paths, discovery=False)[0].endswith(sh + "--uninstall"))
        self.assertIn("systemctl restart canworks-link.service", jobs.commands("link_start", "0.98.0", self.paths))
        self.assertTrue(jobs.commands("discovery_on", "0.98.0", self.paths,
                                      link_config="/etc/canworks-bridge/packer/canworks.json", runtime_port="none")[0]
                        .endswith(sh + "--discovery-only --config /etc/canworks-bridge/packer/canworks.json "
                                       "--runtime-port none"))
        self.assertTrue(jobs.commands("discovery_off", "0.98.0", self.paths)[0].endswith(sh + "--remove-discovery"))
        for bad in (dict(link_config="/etc/passwd"), dict(link_config=None), dict(runtime_port="22; reboot")):
            with self.subTest(bad=bad), self.assertRaises(jobs.JobError):
                args = dict(link_config="/opt/canworks/lib/canworks.json", runtime_port="8443")
                args.update(bad)
                jobs.commands("link_on", "0.98.0", self.paths, **args)

    def test_bridge_config_needs_the_service(self):
        lines = jobs.commands("bridge_config", "0.98.0", self.paths, instance="line3",
                              upload="/tmp/canworks-bridge-upload.abc", bridge_prefix="/opt/canworks-bridge")
        r = subprocess.run(["sh", "-ec", lines[0]], stdout=subprocess.PIPE, text=True)
        if not os.path.exists("/etc/systemd/system/canworks-bridge@.service"):
            self.assertEqual(r.returncode, 3)
            self.assertIn("install the bridge first", r.stdout)

    def test_parse(self):
        out = jobs.parse("::canworks-job 20261021T120000Z-abcd install_plugin @1000\n"
                         "::canworks-step 1/? Downloading @1001\nsome output\n"
                         "::canworks-step 2/5 Building in the image @1010\n::canworks-exit 0\n")
        self.assertEqual(out["started"], 1000)
        self.assertEqual(out["steps"], [{"n": 1, "of": None, "text": "Downloading", "at": 1001},
                                        {"n": 2, "of": 5, "text": "Building in the image", "at": 1010}])
        self.assertEqual(out["lines"], ["some output"])
        self.assertEqual(out["exit"], 0)

    def test_ids(self):
        job = jobs.new_id(1792584000)
        self.assertRegex(job, r"^20261021T120000Z-[0-9a-f]{4}$")
        self.assertEqual(jobs.started_at(job), 1792584000)
        with self.assertRaises(jobs.JobError):
            jobs.check_id("../x")
        self.assertEqual(jobs.instance_name("Line 3 (hall)"), "Line-3-hall")
        self.assertEqual(jobs.instance_name("..."), "canworks")

    def test_hints(self):
        self.assertIn("disk is full", jobs.hint(["cp: write error: No space left on device"]))
        self.assertIn("apt is locked", jobs.hint(["E: Could not get lock /var/lib/dpkg/lock-frontend"]))
        self.assertIn("github.com", jobs.hint(["curl: (6) Could not resolve host: github.com"]))
        self.assertIn("OpenPLC runtime image", jobs.hint(["error: the device cannot download OpenPLC runtime v4.3.1 "
                                                          "(ghcr.io/x:v4.3.1); nothing was changed"]))
        self.assertIsNone(jobs.hint(["something else"]))


class Release(unittest.TestCase):
    def test_from_url(self):
        self.assertEqual(release.from_url("https://github.com/tonihoohoo/canworks/releases/tag/deploy-v0.98.0"),
                         "0.98.0")
        self.assertIsNone(release.from_url("https://github.com/tonihoohoo/canworks/releases"))


@unittest.skipUnless(HAVE_SH, "device-probe.sh needs sh")
class Probe(unittest.TestCase):
    """device-probe.sh on fake device folders (CANWORKS_PROBE_ROOT) with
    stand-in commands."""

    def setUp(self):
        self.root = os.path.join(tmpdir(self), "dev")
        self.bin = os.path.join(os.path.dirname(self.root), "bin")
        os.makedirs(self.bin)
        os.makedirs(os.path.join(self.root, "etc"))
        self.write("etc/os-release", 'NAME="Debian"\nPRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\n')
        self.write("proc/meminfo", "MemTotal:        8123456 kB\n")
        os.makedirs(os.path.join(self.root, "run", "systemd", "system"))
        self.stub("curl", 'for a; do [ "$a" = -w ] && printf 200; done; exit 0')
        self.stub("systemctl", 'case $1 in is-active) echo active ;; is-enabled) echo enabled ;; '
                               'show) [ "$3" = Result ] && echo success || echo inactive ;; esac')
        self.stub("docker", "exit 1")
        self.stub("ip", 'case "$*" in *"type can"*) echo \'[{"ifname":"can0","flags":["UP"],"linkinfo":'
                        '{"info_kind":"can","info_data":{"bittiming":{"bitrate":250000}}}}]\' ;; '
                        '*"type vcan"*) echo "[]" ;; *) echo "[]" ;; esac')

    def write(self, rel, text, mode=0o644):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)

    def stub(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)

    def run_probe(self, **extra):
        env = dict(os.environ, CANWORKS_PROBE_ROOT=self.root,
                   **{"CANWORKS_PROBE_" + n.upper(): os.path.join(self.bin, n)
                      for n in ("systemctl", "docker", "ip", "curl")}, **extra)
        with open(PROBE, "rb") as f:
            out = subprocess.run(["sh", "-s"], input=f.read(), stdout=subprocess.PIPE, env=env, check=True).stdout
        return json.loads(out)

    def test_fresh_device(self):
        p = self.run_probe()
        self.assertEqual(p["probe"], 1)
        self.assertEqual(p["os"], "Debian GNU/Linux 12 (bookworm)")
        self.assertEqual(p["mem_mb"], 7933)
        self.assertTrue(p["systemd"])
        self.assertTrue(p["internet"])
        self.assertIn(p["sudo"], ("none", "nopasswd", "password", "unavailable"))
        self.assertEqual(p["runtime"], {"kind": "none", "version": None, "commit": None, "answers": None})
        self.assertIsNone(p["plugin"])
        self.assertIsNone(p["bridge"])
        self.assertIsNone(p["install_job"])
        self.assertEqual(p["can"][0]["ifname"], "can0")
        self.assertEqual(p["vcan"], [])

    def test_docker_layout(self):
        self.write("var/lib/openplc-bootloader/runtime-spec.json", '{\n  "image": "x",\n  "version": "v4.3.1"\n}\n')
        self.write("opt/canworks/lib/libcanworks_plugin.so", "")
        self.write("opt/canworks/VERSION", "0.98.0\n")
        self.write("opt/canworks/lib/runtime-version", "v4.3.1\n")
        self.write("opt/canworks/lib/plugins-line", "canworks,/opt/canworks/lib/libcanworks_plugin.so,0,0,,\n")
        self.write("etc/systemd/system/canworks-link.service", "")
        self.write("etc/canworks-link/link.json", '{"config": "/opt/canworks/lib/canworks.json", "peers": []}\n')
        self.write("etc/avahi/services/canworks.service", "")
        p = self.run_probe()
        self.assertEqual(p["link_config"], "/opt/canworks/lib/canworks.json")
        self.assertEqual(p["runtime"], {"kind": "docker-managed", "version": "v4.3.1", "commit": None, "answers": True})
        self.assertEqual(p["plugin"], {"version": "0.98.0", "built_for": "v4.3.1", "enabled": False})
        self.assertEqual(p["link"], "active")
        self.assertTrue(p["discovery"])

    def test_root_only_spec_and_a_stopped_native_unit(self):
        # A device moved from native to managed Docker: the old unit stays,
        # stopped; the bootloader's folder is root's and docker the docker group's.
        self.write("etc/systemd/system/openplc-runtime.service", "[Service]\nWorkingDirectory=/home/pi/rt\n")
        self.write("home/pi/rt/plugins.conf", "canworks,/opt/canworks/lib/libcanworks_plugin.so,0,0,,\n")
        os.makedirs(os.path.join(self.root, "var", "lib", "openplc-bootloader"))
        self.write("opt/canworks/lib/libcanworks_plugin.so", "")
        self.write("opt/canworks/lib/runtime-version", "v4.3.1\n")
        self.write("opt/canworks/lib/plugins-line", "canworks,/opt/canworks/lib/libcanworks_plugin.so,1,1,,\n")
        self.stub("systemctl", 'case $1 in is-active) echo inactive ;; esac')
        self.stub("sudo", '[ "$1 $2" = "-n true" ] && exit 0\n'
                          '[ "$2" = cat ] && { echo \'{"version": "v4.3.1"}\'; exit 0; }\nexit 1')
        sudo = {"CANWORKS_PROBE_SUDO": os.path.join(self.bin, "sudo"), "CANWORKS_PROBE_UID": "1000"}
        p = self.run_probe(**sudo)
        self.assertEqual(p["sudo"], "nopasswd")
        self.assertEqual(p["runtime"], {"kind": "docker-managed", "version": "v4.3.1", "commit": None, "answers": True})
        self.assertEqual(p["plugin"], {"version": "unknown", "built_for": "v4.3.1", "enabled": True})
        # sudo needs a password: still managed Docker, its version unknown.
        self.stub("sudo", "exit 1")
        p = self.run_probe(**sudo)
        self.assertEqual((p["runtime"]["kind"], p["runtime"]["version"]), ("docker-managed", None))
        self.assertTrue(p["plugin"]["enabled"])

    def test_managed_docker_before_the_first_upload(self):
        self.write("var/lib/openplc-bootloader/runtime-spec.json", '{"version": "v4.3.1"}\n')
        self.write("opt/canworks/lib/libcanworks_plugin.so", "")
        self.write("opt/canworks/VERSION", "0.98.4\n")
        self.write("opt/canworks/lib/runtime-version", "v4.3.1\n")
        p = self.run_probe()
        self.assertIs(p["plugin"]["enabled"], False)
        self.assertEqual(row(plan.plan(p, "openplc", "0.98.4"), "plugin")["have"],
                         "0.98.4 · built for v4.3.1 · waiting for an upload")
        self.write("opt/canworks/lib/plugins-line", "canworks,/opt/canworks/lib/libcanworks_plugin.so,1,1,,\n")
        self.assertIs(self.run_probe()["plugin"]["enabled"], True)
        # A recorded line that cannot be read stays unknown.
        if os.geteuid() != 0:
            os.chmod(os.path.join(self.root, "opt/canworks/lib/plugins-line"), 0)
            self.assertIsNone(self.run_probe()["plugin"]["enabled"])

    def test_native_runtime(self):
        self.write("etc/systemd/system/openplc-runtime.service", "[Service]\nWorkingDirectory=/home/pi/rt\n")
        self.write("home/pi/rt/plugins.conf", "canworks,/opt/canworks/lib/libcanworks_plugin.so,1,0,,\n")
        self.write("opt/canworks/lib/libcanworks_plugin.so", "")
        p = self.run_probe()
        self.assertEqual(p["runtime"]["kind"], "native")
        self.assertEqual(p["plugin"], {"version": "unknown", "built_for": None, "enabled": True})

    def test_bridge_beside_the_plugin_says_its_own_version(self):
        self.write("opt/canworks/VERSION", "0.98.1\n")
        self.write("opt/canworks/lib/libcanworks_plugin.so", "")
        self.write("opt/canworks/bin/canworks-bridge", "#!/bin/sh\necho canworks-bridge 0.32.0\n", 0o755)
        # Only the plugin venv's console script: no bridge installed.
        p = self.run_probe()
        self.assertEqual(p["plugin"]["version"], "0.98.1")
        self.assertIsNone(p["bridge"])
        self.write("etc/systemd/system/canworks-bridge@.service", "")
        p = self.run_probe()
        self.assertEqual((p["bridge"]["version"], p["bridge"]["prefix"], p["bridge"]["unit"]),
                         ("0.32.0", "/opt/canworks", True))

    def test_bridge_with_two_instances_and_a_job(self):
        self.write("opt/canworks-bridge/bin/canworks-bridge", "#!/bin/sh\necho canworks-bridge 0.97.0\n", 0o755)
        self.write("etc/canworks-bridge/line3/canworks.json", "{}")
        self.write("etc/canworks-bridge/line4/canworks.json", "{\"x\": 1}")
        self.write("var/log/canworks-install/20261020T100000Z-aaaa.log", "old\n")
        self.write("var/log/canworks-install/20261021T100000Z-bbbb.log",
                   "::canworks-job x @1\n::canworks-step 2/5 Building @2\n::canworks-exit 0\n")
        p = self.run_probe()
        b = p["bridge"]
        self.assertEqual((b["version"], b["prefix"]), ("0.97.0", "/opt/canworks-bridge"))
        self.assertEqual([i["name"] for i in b["instances"]], ["line3", "line4"])
        self.assertEqual(b["instances"][0]["state"], "active")
        self.assertEqual(len(b["instances"][0]["sha256"] or "x" * 64), 64)
        self.assertEqual(p["install_job"], {"id": "20261021T100000Z-bbbb", "state": "inactive", "result": "success",
                                            "exit": 0, "step": "2/5 Building @2", "log_size": 70})

    def test_shellcheck(self):
        if not shutil.which("shellcheck"):
            self.skipTest("no shellcheck")
        subprocess.run(["shellcheck", "-s", "sh", PROBE], check=True)


if __name__ == "__main__":
    unittest.main()
