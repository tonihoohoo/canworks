"""The Devices workspace without a device (device-install): the plan from probe
results, devices.json, the job commands and log parsing, the release lookup
and device-probe.sh on fake device folders."""

import json
import os
import shutil
import subprocess
import sys
import time
import unittest
import unittest.mock

from canworks.devices import jobs, plan, release, service, store

from .helpers import tmpdir

PROBE = os.path.join(os.path.dirname(jobs.__file__), "device-probe.sh")
HAVE_SH = sys.platform != "win32" and shutil.which("sh") is not None


def probe(**over):
    """A probe result: a Linux device with nothing of canworks."""
    out = {"probe": 1, "os": "Debian GNU/Linux 12 (bookworm)", "arch": "aarch64", "systemd": True,
           "disk_free_mb": 20000, "mem_mb": 8000, "internet": True, "sudo": "password",
           "bridge": None, "link": None, "discovery": False, "can": [], "vcan": [],
           "serial": [], "j1939_module": False, "install_job": None}
    out.update(over)
    return out


def row(p, part):
    return next(r for r in p["rows"] if r["part"] == part)


class Plan(unittest.TestCase):
    def current(self, version="0.98.0", sha="aa"):
        return {"version": version, "prefix": "/opt/canworks", "unit": True,
                "instances": [{"name": "line3", "state": "active", "sha256": sha}]}

    def test_openplc_project_on_a_fresh_device(self):
        p = plan.plan(probe(), "openplc_modbus", "0.98.0", instance="line3")
        self.assertEqual((p["main"]["action"], p["main"]["label"]),
                         ("install_bridge", "Install and start this project's bridge"))
        self.assertEqual(p["main"]["confirm"], [])
        self.assertEqual(p["notes"], [])
        self.assertTrue(row(p, "bridge")["used"])

    def test_canworks_parts_only(self):
        # device-install: no OpenPLC runtime row or action, whatever the probe says.
        old = {"kind": "docker-managed", "version": "v4.3.2", "commit": None, "answers": True}
        for target in (None, "bridge", "openplc_modbus", "codesys"):
            for over in ({}, {"runtime": old}, {"runtime": old, "bridge": self.current()}):
                with self.subTest(target=target, over=over):
                    p = plan.plan(probe(**over), target, "0.98.0", instance="line3", config_sha256="aa")
                    self.assertEqual([r["part"] for r in p["rows"]], ["bridge", "link", "discovery", "can", "adapter"])
                    self.assertNotIn("roles", p)
                    if p["main"]:
                        self.assertIn(p["main"]["action"], ("install_bridge", "bridge_config"))

    def test_can_bit_rates(self):
        can = [{"ifname": "can0", "flags": ["UP"], "linkinfo": {"info_kind": "can",
                "info_data": {"bittiming": {"bitrate": 250000}}}},
               # slcan: fixed bit rates, the rate flat in info_data (ip -j -d).
               {"ifname": "slcan0", "flags": ["UP"], "linkinfo": {"info_kind": "can",
                "info_data": {"bittiming_bitrate": 500000, "bitrate_const": [125000, 500000]}}}]
        p = plan.plan(probe(can=can), "openplc_modbus", "0.98.0")
        self.assertEqual(row(p, "can")["have"], "can0 250 kbit/s up · slcan0 500 kbit/s up")

    def test_bridge_without_its_service_is_installed(self):
        b = {"version": "0.98.1", "prefix": "/opt/canworks", "unit": False, "instances": []}
        p = plan.plan(probe(bridge=b), "bridge", "0.98.1", instance="line3")
        self.assertEqual(p["main"]["action"], "install_bridge")
        self.assertEqual(p["main"]["label"], "Install and start this project's bridge")
        self.assertIn("no service", row(p, "bridge")["have"])

    def test_bridge_install_keeps_another_configs_link(self):
        p = plan.plan(probe(link="active", link_config="/srv/other/canworks.json"), "bridge", "0.98.3",
                      instance="line3")
        self.assertTrue(p["main"]["link_kept"])
        p = plan.plan(probe(link="active", link_config="/etc/canworks-bridge/line3/canworks.json"), "bridge",
                      "0.98.3", instance="line3")
        self.assertNotIn("link_kept", p["main"])
        self.assertNotIn("link_kept", plan.plan(probe(), "bridge", "0.98.3", instance="line3")["main"])

    def test_development_bridge_is_updated(self):
        b = {"version": "deploy-v0.32.0-192-g0bd645be", "prefix": "/opt/canworks", "unit": True, "instances": []}
        p = plan.plan(probe(bridge=b), "bridge", "0.98.2", instance="line3")
        self.assertEqual(p["main"]["action"], "install_bridge")
        self.assertEqual(p["main"]["label"], "Update deploy-v0.32.0-192-g0bd645be → 0.98.2")

    def test_runtime_moved_on(self):
        # A stored probe of the old shape: its runtime is not read.
        p = plan.plan(probe(runtime={"kind": "docker-managed", "version": "v4.3.2"}, bridge=self.current()),
                      "openplc_modbus", "0.98.0", instance="line3", config_sha256="aa")
        self.assertIsNone(p["main"])
        self.assertTrue(p["up_to_date"])
        self.assertEqual(row(p, "bridge")["state"], "ok")

    def test_up_to_date(self):
        p = plan.plan(probe(bridge=self.current()), "openplc_modbus", "0.98.0", instance="line3", config_sha256="aa")
        self.assertIsNone(p["main"])
        self.assertTrue(p["up_to_date"])
        self.assertEqual(row(p, "bridge")["state"], "ok")

    def test_pc_tools_older_than_the_device(self):
        p = plan.plan(probe(bridge=self.current("0.99.0")), "openplc_modbus", "0.99.0", pc_version="0.98.0",
                      instance="line3", config_sha256="aa")
        self.assertIsNone(p["main"])
        self.assertEqual(row(p, "bridge")["state"], "ok")
        self.assertEqual(p["pc_older"], {"pc": "0.98.0", "device": "0.99.0"})

    def test_pc_tools_older_by_a_patch_only(self):
        p = plan.plan(probe(bridge=self.current("0.111.2")), "openplc_modbus", "0.111.2", pc_version="0.111.0")
        self.assertIsNone(p["pc_older"])
        p = plan.plan(probe(bridge=self.current("0.99.0")), "openplc_modbus", "0.99.0", pc_version="0.99.0")
        self.assertIsNone(p["pc_older"])

    def test_no_internet(self):
        p = plan.plan(probe(internet=False), "openplc_modbus", "0.98.0")
        self.assertEqual(p["blocked"], "The device cannot reach github.com, which the install downloads from.")

    def test_blocked_reasons(self):
        for over, text in (({"systemd": False}, "no systemd"), ({"sudo": "unavailable"}, "cannot use sudo"),
                           ({"install_job": {"state": "active"}}, "An install is running"),
                           ({"disk_free_mb": 900}, "Less than 2 GB")):
            with self.subTest(over=over):
                self.assertIn(text, plan.plan(probe(**over), "openplc_modbus", "0.98.0")["blocked"])
        self.assertIn("could not be found", plan.plan(probe(), "openplc_modbus", None)["blocked"])

    def test_bridge_project(self):
        p = plan.plan(probe(), "bridge", "0.98.0", instance="line3")
        self.assertEqual(p["main"]["action"], "install_bridge")
        self.assertEqual(p["main"]["label"], "Install and start this project's bridge")

        running = self.current("0.97.0")
        p = plan.plan(probe(bridge=running), "bridge", "0.98.0", instance="line3", config_sha256="aa")
        self.assertEqual(p["main"]["label"], "Update 0.97.0 → 0.98.0")
        self.assertEqual(p["main"]["confirm"], ["Running bridges restart."])

        current = self.current()
        p = plan.plan(probe(bridge=current), "bridge", "0.98.0", instance="line3", config_sha256="bb")
        self.assertEqual((p["main"]["action"], p["main"]["label"]), ("bridge_config", "Start this project's bridge"))
        self.assertIn("restarts with this project's saved config", p["main"]["confirm"][0])

        p = plan.plan(probe(bridge=current), "bridge", "0.98.0", instance="line3", config_sha256="aa")
        self.assertIsNone(p["main"])
        self.assertEqual(row(p, "bridge")["state"], "ok")

    def test_current_config_over_every_uploaded_file(self):
        # The config is current only when every file the job uploads matches (an edited EDS does not).
        b = self.current()
        b["instances"][0]["files"] = ["canworks.json aa", "dio16.eds e1", "old.eds 00"]
        saved = ["canworks.json aa", "dio16.eds e1"]
        p = plan.plan(probe(bridge=b), "bridge", "0.98.0", instance="line3", config_sha256=saved)
        self.assertIsNone(p["main"])  # a file left on the device from before does not matter
        p = plan.plan(probe(bridge=b), "bridge", "0.98.0", instance="line3",
                      config_sha256=["canworks.json aa", "dio16.eds e2"])
        self.assertEqual((p["main"]["action"], p["main"]["label"]), ("bridge_config", "Start this project's bridge"))
        self.assertEqual(row(p, "bridge")["state"], "warn")
        # A probe from before the file list: canworks.json's own hash.
        p = plan.plan(probe(bridge=self.current()), "bridge", "0.98.0", instance="line3", config_sha256=saved)
        self.assertIsNone(p["main"])

    def test_config_hashes(self):
        d = tmpdir(self)
        for name, text in (("canworks.json", "{}"), ("dio16.eds", "[x]"), (".hidden", "")):
            with open(os.path.join(d, name), "w") as f:
                f.write(text)
        os.makedirs(os.path.join(d, "sub"))
        self.assertEqual(service.config_hashes(os.path.join(d, "canworks.json")),
                         ["canworks.json " + service.file_sha256(os.path.join(d, "canworks.json")),
                          "dio16.eds " + service.file_sha256(os.path.join(d, "dio16.eds"))])
        self.assertIsNone(service.config_hashes(None))

    def test_remote_link_says_why_it_has_no_switch(self):
        # UI-15: no bridge config on the device yet.
        self.assertEqual(row(plan.plan(probe(), "bridge", "0.98.0", instance="line3"), "link")["hint"],
                         "Turns on once a bridge config runs here.")
        self.assertNotIn("hint", row(plan.plan(probe(bridge=self.current()), "bridge", "0.98.0", instance="line3"),
                                     "link"))

    def test_another_instance_runs(self):
        # UI-4: the confirmation names the running vp2, warns about what both use and offers to stop it.
        b = {"version": "0.98.0", "prefix": "/opt/canworks", "unit": True,
             "instances": [{"name": "vp2", "state": "active", "sha256": "aa"}]}
        mine = plan.networks_uses({"bridge": {"listen": "127.0.0.1:1502"}, "diagnostics": {},
                                   "networks": [{"adapter": {"interface": "can0"}},
                                                {"adapter": {"interface": "can1", "simulate": True}}]})
        self.assertEqual(mine, {"listen": "127.0.0.1:1502", "diag_port": 7531, "interfaces": ["can0"]})
        uses = {"vp2": {"listen": "0.0.0.0:1502", "diag_port": 7531, "interfaces": ["can0", "can1"]}}
        p = plan.plan(probe(bridge=b, bridge_uses=uses), "openplc_modbus", "0.98.0", instance="om2", uses=mine)
        m = p["main"]
        self.assertEqual((m["action"], m["stop_others"]), ("bridge_config", ["vp2"]))
        self.assertEqual((m["stop_label"], m["next_label"]), ("Stop vp2 and start om2", "Start next to vp2"))
        self.assertIn("The bridge vp2 runs on this device", " ".join(m["confirm"]))
        self.assertEqual(m["warnings"], ["vp2 listens on port 1502 too: the second bridge cannot open it.",
                                         "vp2 uses the diagnostics port 7531 too.",
                                         "vp2 drives can0 too: two masters on one bus."])
        # Nothing in common, or a probe without bridge_uses: named, no warnings.
        other = {"listen": "127.0.0.1:1503", "diag_port": None, "interfaces": ["can2"]}
        p = plan.plan(probe(bridge=b, bridge_uses={"vp2": other}), "bridge", "0.98.0", instance="om2", uses=mine)
        self.assertEqual(p["main"]["warnings"], [])
        p = plan.plan(probe(bridge=b), "bridge", "0.98.0", instance="om2", uses=mine)
        self.assertEqual((p["main"]["warnings"], p["main"]["stop_others"]), ([], ["vp2"]))
        # The project's own instance alone: nothing to name.
        p = plan.plan(probe(bridge=b), "bridge", "0.98.0", instance="vp2", config_sha256="bb", uses=mine)
        self.assertNotIn("stop_others", p["main"])

    def test_codesys(self):
        p = plan.plan(probe(), "codesys", "0.98.0")
        self.assertIsNone(p["main"])
        self.assertFalse(p["up_to_date"])
        self.assertIn("CODESYS installs its runtime itself", p["notes"][0])

    def test_can_rows(self):
        can = [{"ifname": "can0", "flags": ["UP"], "linkinfo": {"info_kind": "can",
                                                              "info_data": {"bittiming": {"bitrate": 250000}}}}]
        vcan = [{"ifname": "vcan0", "flags": [], "linkinfo": {"info_kind": "vcan"}}]
        p = plan.plan(probe(can=can, vcan=vcan, serial=["usb-slcan"]), "openplc_modbus", "0.98.0")
        self.assertEqual(row(p, "can")["have"], "can0 250 kbit/s up · vcan0 (virtual) · serial usb-slcan")

    def test_header(self):
        self.assertEqual(plan.header(probe()), "Debian GNU/Linux 12 (bookworm) · aarch64 · 20 GB free · internet ok")

    def test_version_tuple(self):
        self.assertEqual(plan.version_tuple("deploy-v0.98.0"), (0, 98, 0))
        self.assertIsNone(plan.version_tuple("0.98.0-3-gabc"))


class PlanWithoutConfig(unittest.TestCase):
    """devices-without-config: no target; the bridge on the device, or the
    role the page picks, gives the main action."""

    def test_fresh_device_installs_the_bridge(self):
        # No question about what the device runs: canworks installs the bridge only.
        for over in ({}, {"runtime": {"kind": "docker-managed", "version": "v4.3.1"}}):
            p = plan.plan(probe(**over), None, "0.120.0")
            self.assertEqual((p["main"]["action"], p["main"]["label"]), ("install_bridge", "Install the bridge 0.120.0"))
            self.assertEqual(p["main"]["hint"], plan.NO_CONFIG_HINT)
            self.assertEqual(p["main"]["confirm"], [])
            self.assertNotIn("roles", p)
            self.assertFalse(p["up_to_date"])
            self.assertTrue(all(r["used"] and r["needs"] == "" for r in p["rows"]))

    def test_installed_bridge_picks_the_action(self):
        # Spec scenario "Old plugin with no config": the bridge on the device decides.
        b = {"version": "0.115.0", "prefix": "/opt/canworks",
             "instances": [{"name": "packer", "state": "active", "sha256": "aa"}]}
        p = plan.plan(probe(bridge=b), None, "0.120.0")
        self.assertEqual((p["main"]["action"], p["main"]["label"]), ("install_bridge", "Update 0.115.0 → 0.120.0"))
        self.assertEqual(p["main"]["confirm"], ["Running bridges restart."])
        p = plan.plan(probe(bridge=dict(b, version="0.120.0")), None, "0.120.0")
        self.assertIsNone(p["main"])
        self.assertTrue(p["up_to_date"])

    def test_link_and_discovery_switches(self):
        # device-link-switches: the rows' own actions and what the link serves.
        b = {"version": "0.110.0", "prefix": "/opt/canworks", "instances": [{"name": "line3", "state": "active"}]}
        p = plan.plan(probe(bridge=b), None, "0.110.0")
        self.assertEqual([a["action"] for a in row(p, "link")["actions"]], ["link_on"])
        self.assertEqual([a["action"] for a in row(p, "discovery")["actions"]], ["discovery_on"])
        served = "/etc/canworks-bridge/line3/canworks.json"
        p = plan.plan(probe(bridge=b, link="active", link_config=served, discovery=True), "openplc_modbus", "0.110.0",
                      instance="line3")
        self.assertEqual(row(p, "link")["have"], "running · serves the bridge line3")
        self.assertEqual([a["action"] for a in row(p, "link")["actions"]], ["link_off"])
        self.assertIn("stay paired", row(p, "link")["actions"][0]["confirm"][0])
        self.assertEqual([a["action"] for a in row(p, "discovery")["actions"]], ["discovery_off"])
        p = plan.plan(probe(bridge=b, link="failed", link_config=served), None, "0.110.0")
        self.assertEqual([a["action"] for a in row(p, "link")["actions"]], ["link_start", "link_off"])
        # Nothing to serve (no bridge), or a CODESYS project: no switches.
        self.assertNotIn("actions", row(plan.plan(probe(), None, "0.110.0"), "link"))
        self.assertNotIn("actions", row(plan.plan(probe(bridge=b), "codesys", "0.110.0"), "discovery"))

    def test_link_serves(self):
        two = {"version": "0.110.0", "instances": [{"name": "packer"}, {"name": "line2"}]}
        self.assertEqual(plan.link_serves(probe(bridge=two)), {"choose": ["packer", "line2"]})
        self.assertEqual(plan.link_serves(probe(bridge=two), "line2")["config"], "/etc/canworks-bridge/line2/canworks.json")
        self.assertEqual(plan.link_serves(probe(bridge=dict(two, instances=[{"name": "packer"}])))["text"], "the bridge packer")
        self.assertEqual(plan.link_serves(probe(bridge=two, link="active",
                                                link_config="/etc/canworks-bridge/line2/canworks.json"))["text"],
                         "the bridge line2")
        self.assertEqual(plan.link_serves(probe(bridge=two, link="active", link_config="/srv/x/canworks.json"))["text"],
                         "another config")
        self.assertIsNone(plan.link_serves(probe(bridge=dict(two, instances=[]))))
        p = plan.plan(probe(bridge=two), None, "0.110.0")
        self.assertEqual(row(p, "link")["actions"][0]["choose"], ["packer", "line2"])

    def test_blocked_applies_without_a_config(self):
        self.assertIn("github.com", plan.plan(probe(internet=False), None, "0.110.0")["blocked"])


class AdapterRow(unittest.TestCase):
    """add-devices-adapter-server: the Remote CAN adapter row from the probe."""
    can0 = [{"ifname": "can0", "flags": ["UP"], "linkinfo": {"info_kind": "can",
                                                           "info_data": {"bittiming": {"bitrate": 500000}}}}]

    def server(self, **over):
        out = {"unit": "canworks-adapter-can0.service", "state": "active", "adapter": "socketcan:can0",
               "bitrate_kbit": 500, "port": 7536, "allow_changes": True, "discovery": True, "user": "pi", "pcs": 1}
        out.update(over)
        return out

    def acts(self, p):
        return [a["action"] for a in row(p, "adapter").get("actions") or []]

    def test_off_with_no_config_and_no_bridge(self):
        p = plan.plan(probe(can=self.can0), None, "0.131.0")
        r = row(p, "adapter")
        self.assertEqual((r["label"], r["have"], r["state"]), ("Remote CAN adapter", "off", "off"))
        on = r["actions"][0]
        self.assertEqual((on["action"], on["button"], on["port"]), ("adapter_on", "Turn on…", 7536))
        self.assertEqual(on["choices"][0]["adapter"], "socketcan:can0")
        self.assertEqual(on["choices"][0]["bitrate_kbit"], 500)  # the interface is up at it
        self.assertFalse(on["choices"][0]["locked"])
        self.assertEqual(p["main"]["action"], "install_bridge")  # the row's switch is not the main action
        # Nothing to serve: no switch.
        self.assertNotIn("actions", row(plan.plan(probe(), None, "0.131.0"), "adapter"))

    def test_running_server(self):
        p = plan.plan(probe(can=self.can0, adapters=[self.server()]), None, "0.131.0")
        r = row(p, "adapter")
        self.assertEqual(r["have"], "can0 · 500 kbit/s · running · changes allowed · 1 PC connected")
        self.assertEqual(r["state"], "ok")
        self.assertEqual(self.acts(p), ["adapter_connect", "adapter_token", "adapter_change", "adapter_off"])
        token = r["actions"][1]
        self.assertEqual(token["confirm"], [plan.NEW_TOKEN])
        change = r["actions"][2]
        self.assertEqual(change["current"], {"adapter": "socketcan:can0", "port": 7536, "bitrate_kbit": 500,
                                             "allow_changes": True, "discovery": True})
        # This PC has the token: Copy token instead of New token.
        p = plan.plan(probe(can=self.can0, adapters=[self.server()]), None, "0.131.0", tokens={7536})
        self.assertEqual(self.acts(p), ["adapter_connect", "adapter_copy_token", "adapter_change", "adapter_off"])
        self.assertTrue(row(p, "adapter")["actions"][1]["local"])

    def test_device_without_internet(self):
        # add-adapter-server-file: the PC uploads the file, so the adapter needs no internet on the device.
        p = plan.plan(probe(can=self.can0, internet=False), None, "0.133.0")
        self.assertIn("github.com", p["blocked"])  # the bridge install still downloads there
        on = row(p, "adapter")["actions"][0]
        self.assertEqual(on["action"], "adapter_on")
        self.assertIsNone(on["blocked"])
        self.assertIsNone(plan.blocked(probe(internet=False, disk_free_mb=100), "0.133.0", adapter=True))
        self.assertIn("2 GB", plan.blocked(probe(disk_free_mb=100), "0.133.0"))
        self.assertIn("systemd", plan.blocked(probe(systemd=False), "0.133.0", adapter=True))

    def test_python_or_openssl_missing(self):
        p = plan.plan(probe(can=self.can0, python3="3.9.2", openssl=True), None, "0.133.0")
        r = row(p, "adapter")
        self.assertEqual(r["hint"], "The remote CAN adapter needs Python 3.11 or newer on the device (it has 3.9.2).")
        self.assertNotIn("actions", r)
        p = plan.plan(probe(can=self.can0, python3=None, openssl=True), None, "0.133.0")
        self.assertEqual(row(p, "adapter")["hint"], "The remote CAN adapter needs Python 3.11 or newer on the device.")
        p = plan.plan(probe(can=self.can0, adapters=[self.server()], python3="3.13.5", openssl=False), None,
                      "0.133.0")
        r = row(p, "adapter")
        self.assertIn("openssl command", r["hint"])
        self.assertEqual(self.acts(p), ["adapter_connect", "adapter_off"])  # no Change… or New token…
        p = plan.plan(probe(can=self.can0, python3="3.11.2", openssl=True), None, "0.133.0")
        self.assertNotIn("hint", row(p, "adapter"))
        self.assertEqual(self.acts(p), ["adapter_on"])
        # A probe from before the check: nothing is assumed missing.
        self.assertEqual(self.acts(plan.plan(probe(can=self.can0), None, "0.133.0")), ["adapter_on"])

    def test_second_interface_gets_the_next_port(self):
        can = self.can0 + [{"ifname": "can1", "flags": [], "linkinfo": {"info_kind": "can"}}]
        p = plan.plan(probe(can=can, adapters=[self.server(state="failed", allow_changes=False)]), None, "0.131.0")
        r = row(p, "adapter")
        self.assertEqual(r["have"], "can0 · 500 kbit/s · failed · read-only")
        self.assertEqual(r["state"], "warn")
        add = r["actions"][-1]
        self.assertEqual((add["action"], add["button"], add["port"]), ("adapter_on", "Add…", 7537))
        self.assertEqual([c["adapter"] for c in add["choices"]], ["socketcan:can1"])
        self.assertIsNone(add["choices"][0]["bitrate_kbit"])  # down, no config: never guessed

    def test_next_to_this_projects_bridge(self):
        b = {"version": "0.131.0", "prefix": "/opt/canworks", "unit": True,
             "instances": [{"name": "line3", "state": "active", "sha256": "aa"}]}
        nets = [{"interface": "can0", "bitrate_kbit": 250, "device": None}]
        p = plan.plan(probe(can=self.can0, bridge=b), "bridge", "0.131.0", instance="line3", config_sha256="aa",
                      networks=nets)
        c = row(p, "adapter")["actions"][0]["choices"][0]
        self.assertEqual((c["bitrate_kbit"], c["locked"]), (250, True))
        self.assertIn("The bridge line3 is the master on can0", c["note"])
        # No config: the running bridges are named, the rate stays the interface's.
        c = row(plan.plan(probe(can=self.can0, bridge=b), None, "0.131.0"), "adapter")["actions"][0]["choices"][0]
        self.assertEqual((c["bitrate_kbit"], c["locked"]), (500, False))
        self.assertIn("A bridge runs on this device (line3)", c["note"])

    def test_simulated_network_is_left_out(self):
        # UI-1: a simulated network keeps its adapter can0 at 250 kbit/s; the bridge never opens it.
        from canworks.configurator.server import device_networks
        b = {"version": "0.131.0", "prefix": "/opt/canworks", "unit": True,
             "instances": [{"name": "vp", "state": "active", "sha256": "aa"}]}
        cfg = {"schema_version": 2, "networks": [
            {"name": "io", "adapter": {"interface": "can0", "bitrate": 250000, "simulate": True}, "nodes": []}]}
        p = plan.plan(probe(can=self.can0, bridge=b), "bridge", "0.131.0", instance="vp", config_sha256="aa",
                      networks=device_networks(cfg))
        c = row(p, "adapter")["actions"][0]["choices"][0]
        self.assertEqual((c["bitrate_kbit"], c["locked"]), (500, False))
        self.assertNotIn("is the master on can0", c["note"] or "")
        serial = [{"interface": "slcan0", "bitrate_kbit": 250, "device": "/dev/serial/by-id/usb-canable",
                   "simulate": True}]
        p = plan.plan(probe(serial=["usb-canable"], bridge=b), "bridge", "0.131.0", instance="vp", networks=serial)
        self.assertIsNone(row(p, "adapter")["actions"][0]["choices"][0]["refused"])

    def test_serial_used_by_the_bridge(self):
        b = {"version": "0.131.0", "prefix": "/opt/canworks", "unit": True,
             "instances": [{"name": "line3", "state": "active"}]}
        nets = [{"interface": "slcan0", "bitrate_kbit": 250, "device": "/dev/serial/by-id/usb-canable"}]
        p = plan.plan(probe(serial=["usb-canable"], bridge=b), "bridge", "0.131.0", instance="line3", networks=nets)
        c = row(p, "adapter")["actions"][0]["choices"][0]
        self.assertEqual(c["adapter"], "slcan:/dev/serial/by-id/usb-canable")
        self.assertIn("one user at a time", c["refused"])

    def test_codesys_and_blocked(self):
        r = row(plan.plan(probe(can=self.can0), "codesys", "0.131.0"), "adapter")
        self.assertFalse(r["used"])
        self.assertNotIn("actions", r)
        # Connect and Copy token are this PC's: a device that cannot run jobs does not block them.
        p = plan.plan(probe(can=self.can0, adapters=[self.server()], internet=False), None, "0.131.0", tokens={7536})
        self.assertIn("github.com", p["blocked"])
        self.assertTrue(all(a.get("local") for a in row(p, "adapter")["actions"][:2]))


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
        bridge = ("release_script https://raw.githubusercontent.com/tonihoohoo/canworks/deploy-v0.98.0/scripts/"
                  "install-bridge.sh --version 0.98.0")
        self.assertEqual(jobs.commands("install_bridge", "0.98.0", self.paths), [bridge])
        self.assertEqual(jobs.commands("install_bridge", "0.98.0", self.paths, discovery=False),
                         [bridge + " --without-discovery"])
        line = jobs.commands("install_bridge", "0.98.0", self.paths, instance="line3",
                             upload="/tmp/canworks-bridge-upload.abc")[0]
        self.assertIn("install-bridge.sh --version 0.98.0 --instance line3 --config "
                      "/tmp/canworks-bridge-upload.abc --remove-config-dir --with-link line3", line)
        self.assertTrue(jobs.commands("uninstall_bridge", "0.98.0", self.paths, purge=True)[0].endswith(
            "--uninstall --purge"))
        self.assertEqual(jobs.commands("remove_all", "0.98.0", self.paths), [bridge + " --uninstall --purge"])
        for gone in ("install_plugin", "install_openplc", "uninstall_plugin", "install_openplc_bridge", "switch_runtime"):
            with self.subTest(gone=gone), self.assertRaises(jobs.JobError):
                jobs.commands(gone, "0.98.0", self.paths)
        for bad in (dict(version="0.98.0; rm -rf /"), dict(instance="a b"), dict(upload="/etc")):
            with self.subTest(bad=bad), self.assertRaises(jobs.JobError):
                args = dict(version="0.98.0", instance=None, upload=None)
                args.update(bad)
                jobs.commands("install_bridge", args["version"], self.paths, instance=args["instance"],
                              upload=args["upload"])

    def test_stop_other_bridges_first(self):
        # UI-4: Stop A and start B stops and disables A before B starts.
        up = "/tmp/canworks-bridge-upload.abc"
        lines = jobs.commands("bridge_config", "0.98.0", self.paths, instance="om2", upload=up,
                              bridge_prefix="/opt/canworks", stop=["vp2"])
        stop = lines.index("systemctl disable --now canworks-bridge@vp2.service")
        self.assertLess(stop, next(i for i, l in enumerate(lines) if l.startswith("systemctl restart")))
        self.assertGreater(stop, next(i for i, l in enumerate(lines) if "--check-only" in l))
        lines = jobs.commands("install_bridge", "0.98.0", self.paths, instance="om2", upload=up, stop=["vp2"])
        self.assertEqual(lines[0], "systemctl disable --now canworks-bridge@vp2.service")
        for bad in (["a b"], "vp2", [1]):
            with self.subTest(bad=bad), self.assertRaises(jobs.JobError):
                jobs.commands("bridge_config", "0.98.0", self.paths, instance="om2", upload=up,
                              bridge_prefix="/opt/canworks", stop=bad)
        with self.assertRaises(jobs.JobError):
            jobs.commands("link_off", "0.98.0", self.paths, stop=["vp2"])

    def test_link_commands(self):
        sh = "install-link.sh "
        on = jobs.commands("link_on", "0.98.0", self.paths, discovery=False,
                           link_config="/etc/canworks-bridge/cell/canworks.json", runtime_port="8443")[0]
        self.assertTrue(on.endswith(sh + "--version 0.98.0 --config /etc/canworks-bridge/cell/canworks.json "
                                         "--runtime-port 8443 --without-discovery"), on)
        self.assertTrue(jobs.commands("link_off", "0.98.0", self.paths)[0].endswith(sh + "--uninstall --keep-discovery"))
        self.assertTrue(jobs.commands("link_off", "0.98.0", self.paths, discovery=False)[0].endswith(sh + "--uninstall"))
        self.assertIn("systemctl restart canworks-link.service", jobs.commands("link_start", "0.98.0", self.paths))
        self.assertTrue(jobs.commands("discovery_on", "0.98.0", self.paths,
                                      link_config="/etc/canworks-bridge/packer/canworks.json", runtime_port="none")[0]
                        .endswith(sh + "--discovery-only --config /etc/canworks-bridge/packer/canworks.json "
                                       "--runtime-port none"))
        self.assertTrue(jobs.commands("discovery_off", "0.98.0", self.paths)[0].endswith(sh + "--remove-discovery"))
        for bad in (dict(link_config="/etc/passwd"), dict(link_config="/opt/canworks/lib/canworks.json"),
                    dict(link_config=None), dict(runtime_port="22; reboot")):
            with self.subTest(bad=bad), self.assertRaises(jobs.JobError):
                args = dict(link_config="/etc/canworks-bridge/cell/canworks.json", runtime_port="8443")
                args.update(bad)
                jobs.commands("link_on", "0.98.0", self.paths, **args)

    def test_adapter_commands(self):
        sh = ("release_script https://raw.githubusercontent.com/tonihoohoo/canworks/deploy-v0.131.0/scripts/"
              "install-adapter.sh --version 0.131.0")
        up = "/tmp/canworks-bridge-upload.abc"
        on = jobs.commands("adapter_on", "0.131.0", self.paths, upload=up, adapter="socketcan:can0", bitrate_kbit=500,
                           port=7536, allow_changes=True, user="pi")
        self.assertEqual(on, [sh + " --adapter socketcan:can0 --bitrate 500 --port 7536 --user pi --allow-changes "
                                   "--verifier-file /tmp/canworks-bridge-upload.abc/verifier", "rm -rf " + up])
        change = jobs.commands("adapter_change", "0.131.0", self.paths, discovery=False, adapter="socketcan:can0",
                               bitrate_kbit=250, port=7537, allow_changes=False, user="pi")
        self.assertEqual(change, [sh + " --adapter socketcan:can0 --bitrate 250 --port 7537 --user pi "
                                       "--without-discovery"])
        self.assertEqual(jobs.commands("adapter_off", "0.131.0", self.paths, adapter="slcan:/dev/ttyACM0"),
                         [sh + " --uninstall --adapter slcan:/dev/ttyACM0"])
        self.assertEqual(jobs.commands("remove_all", "0.131.0", self.paths, adapters=True)[0], sh + " --uninstall")
        good = dict(adapter="socketcan:can0", bitrate_kbit=500, port=7536, user="pi")
        for bad in (dict(adapter="socketcan:can0; reboot"), dict(adapter="remote:x"), dict(bitrate_kbit=333),
                    dict(port=22), dict(user="root"), dict(user="a b")):
            with self.subTest(bad=bad), self.assertRaises(jobs.JobError):
                jobs.commands("adapter_change", "0.131.0", self.paths, **dict(good, **bad))
        with self.assertRaises(jobs.JobError):  # the token's verifier is needed
            jobs.commands("adapter_on", "0.131.0", self.paths, **good)

    def test_adapter_commands_with_the_uploaded_file(self):
        # add-adapter-server-file: the PC uploaded the script and the file, so nothing is downloaded.
        up = "/tmp/canworks-bridge-upload.abc"
        sh = ("bash /tmp/canworks-bridge-upload.abc/install-adapter.sh --version 0.133.0 "
              "--file /tmp/canworks-bridge-upload.abc/canworks-adapter-0.133.0.pyz")
        on = jobs.commands("adapter_on", "0.133.0", self.paths, upload=up, uploaded=True, adapter="socketcan:can0",
                           bitrate_kbit=500, port=7536, allow_changes=True, user="pi")
        self.assertEqual(on, [sh + " --adapter socketcan:can0 --bitrate 500 --port 7536 --user pi --allow-changes "
                                   "--verifier-file /tmp/canworks-bridge-upload.abc/verifier", "rm -rf " + up])
        self.assertNotIn("release_script", " ".join(on))
        change = jobs.commands("adapter_change", "0.133.0", self.paths, upload=up, uploaded=True,
                               adapter="socketcan:can0", bitrate_kbit=250, port=7536, user="pi")
        self.assertEqual(change, [sh + " --adapter socketcan:can0 --bitrate 250 --port 7536 --user pi",
                                  "rm -rf " + up])
        off = jobs.commands("adapter_off", "0.133.0", self.paths, upload=up, uploaded=True, adapter="socketcan:can0")
        self.assertEqual(off, [sh + " --uninstall --adapter socketcan:can0", "rm -rf " + up])
        with self.assertRaises(jobs.JobError):  # uploaded needs the upload folder
            jobs.commands("adapter_off", "0.133.0", self.paths, uploaded=True, adapter="socketcan:can0")

    def test_bridge_config_needs_the_service(self):
        lines = jobs.commands("bridge_config", "0.98.0", self.paths, instance="line3",
                              upload="/tmp/canworks-bridge-upload.abc", bridge_prefix="/opt/canworks")
        r = subprocess.run(["sh", "-ec", lines[0]], stdout=subprocess.PIPE, text=True)
        if not os.path.exists("/etc/systemd/system/canworks-bridge@.service"):
            self.assertEqual(r.returncode, 3)
            self.assertIn("install the bridge first", r.stdout)

    def test_parse(self):
        out = jobs.parse("::canworks-job 20261021T120000Z-abcd install_bridge @1000\n"
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

    @unittest.skipUnless(HAVE_SH and shutil.which("flock") and shutil.which("bash"), "needs sh, flock and bash")
    def test_failed_download_fails_the_job(self):
        # A release script that cannot be downloaded (the tag is gone: curl -f exits 22) ends the job failed.
        d = tmpdir(self)
        bin_ = os.path.join(d, "bin")
        os.makedirs(bin_)
        with open(os.path.join(bin_, "curl"), "w") as f:
            f.write("#!/bin/sh\necho 'curl: (22) The requested URL returned error: 404' >&2\nexit 22\n")
        os.chmod(os.path.join(bin_, "curl"), 0o755)
        paths = jobs.Paths(log_dir=os.path.join(d, "log"), state_dir=os.path.join(d, "state"),
                           lock=os.path.join(d, "lock"))
        os.makedirs(paths.log_dir)
        job = "20261024T000000Z-abcd"
        for action in ("uninstall_bridge", "link_off"):
            with self.subTest(action=action):
                script = os.path.join(d, action + ".sh")
                with open(script, "w") as f:
                    f.write(jobs.job_script(job, action, jobs.commands(action, "0.98.0", paths) + ["echo after"],
                                            paths))
                if os.path.exists(paths.log(job)):
                    os.remove(paths.log(job))
                subprocess.run(["sh", script], env=dict(os.environ, PATH=bin_ + os.pathsep + os.environ["PATH"]),
                               check=True)
                with open(paths.log(job)) as f:
                    out = jobs.parse(f.read())
                self.assertEqual(out["exit"], 22)
                name = "install-bridge.sh" if action == "uninstall_bridge" else "install-link.sh"
                self.assertTrue(any(l.startswith("could not download %s 0.98.0" % name) for l in out["lines"]),
                                out["lines"])
                self.assertNotIn("after", out["lines"])
                self.assertIn("not on GitHub", jobs.hint(out["lines"]))
        # A downloaded script runs with the line's arguments.
        with open(os.path.join(bin_, "curl"), "w") as f:
            f.write('#!/bin/sh\nwhile [ "$1" != -o ]; do shift; done\necho \'echo "ran $*"\' > "$2"\n')
        os.remove(paths.log(job))
        with open(script, "w") as f:
            f.write(jobs.job_script(job, "link_off", jobs.commands("link_off", "0.98.0", paths), paths))
        subprocess.run(["sh", script], env=dict(os.environ, PATH=bin_ + os.pathsep + os.environ["PATH"]), check=True)
        with open(paths.log(job)) as f:
            out = jobs.parse(f.read())
        self.assertEqual((out["exit"], out["lines"]), (0, ["ran --uninstall --keep-discovery"]))

    def test_hints(self):
        self.assertIn("disk is full", jobs.hint(["cp: write error: No space left on device"]))
        self.assertIn("apt is locked", jobs.hint(["E: Could not get lock /var/lib/dpkg/lock-frontend"]))
        self.assertIn("github.com", jobs.hint(["curl: (6) Could not resolve host: github.com"]))
        self.assertIsNone(jobs.hint(["something else"]))


class Release(unittest.TestCase):
    def test_adapter_files(self):
        # add-adapter-server-file: the script and the file of a release, downloaded once on this PC.
        rel = os.path.join(tmpdir(self), "rel")
        os.makedirs(os.path.join(rel, "deploy-v0.133.0"))
        for name, text in (("install-adapter.sh", "#!/bin/bash\n"), ("canworks-adapter-0.133.0.pyz", "PK")):
            with open(os.path.join(rel, "deploy-v0.133.0", name), "w") as f:
                f.write(text)
        cache = os.path.join(tmpdir(self), "cache")
        with unittest.mock.patch.dict(os.environ, {"CANWORKS_RELEASES_DOWNLOAD": "file://" + rel}):
            got = release.adapter_files("0.133.0", cache)
            self.assertEqual([os.path.basename(p) for p in got], ["install-adapter.sh", "canworks-adapter-0.133.0.pyz"])
            with open(got[1]) as f:
                self.assertEqual(f.read(), "PK")
            self.assertIsNone(release.adapter_files("0.134.0", cache))  # no such release
        shutil.rmtree(rel)
        self.assertEqual(release.adapter_files("0.133.0", cache), got)  # kept: no second download

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
                      for n in ("systemctl", "ip", "curl", "sudo")}, **extra)
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
        self.assertNotIn("runtime", p)
        self.assertNotIn("plugin", p)
        self.assertIsNone(p["bridge"])
        self.assertIsNone(p["install_job"])
        self.assertEqual(p["can"][0]["ifname"], "can0")
        self.assertEqual(p["vcan"], [])

    def test_python_and_openssl(self):
        # What the adapter server file needs (add-adapter-server-file).
        self.stub("python3", 'echo 3.11.2')
        self.stub("openssl", 'exit 0')
        p = self.run_probe(CANWORKS_PROBE_PYTHON=os.path.join(self.bin, "python3"),
                           CANWORKS_PROBE_OPENSSL=os.path.join(self.bin, "openssl"))
        self.assertEqual((p["python3"], p["openssl"]), ("3.11.2", True))
        p = self.run_probe(CANWORKS_PROBE_PYTHON="/nonexistent/python3", CANWORKS_PROBE_OPENSSL="/nonexistent/openssl")
        self.assertEqual((p["python3"], p["openssl"]), (None, False))

    def test_link_and_discovery(self):
        self.write("etc/systemd/system/canworks-link.service", "")
        self.write("etc/canworks-link/link.json", '{"config": "/etc/canworks-bridge/cell/canworks.json", "peers": []}\n')
        self.write("etc/avahi/services/canworks.service", "")
        p = self.run_probe()
        self.assertEqual(p["link_config"], "/etc/canworks-bridge/cell/canworks.json")
        self.assertEqual(p["link"], "active")
        self.assertTrue(p["discovery"])

    def test_openplc_runtime_not_read(self):
        # device-install: the probe reads canworks only; no docker or sudo runs.
        self.write("etc/systemd/system/openplc-runtime.service", "[Service]\nWorkingDirectory=/home/pi/rt\n")
        self.write("var/lib/openplc-bootloader/runtime-spec.json", '{"version": "v4.3.1"}\n')
        log = os.path.join(self.root, "called")
        for name in ("docker", "sudo"):
            self.stub(name, 'echo "%s $*" >> %s\nexit 0' % (name, log))
        p = self.run_probe(CANWORKS_PROBE_UID="1000", PATH=self.bin + os.pathsep + os.environ.get("PATH", ""))
        self.assertNotIn("runtime", p)
        called = open(log).read() if os.path.exists(log) else ""
        self.assertNotIn("docker", called)
        self.assertNotIn("sudo -n cat", called)

    def test_bridge_version(self):
        self.write("opt/canworks/bin/canworks-bridge", "#!/bin/sh\necho canworks-bridge 0.32.0\n", 0o755)
        p = self.run_probe()
        self.assertEqual((p["bridge"]["version"], p["bridge"]["prefix"], p["bridge"]["unit"]),
                         ("0.32.0", "/opt/canworks", False))
        # The install writes the release's version next to the binary.
        self.write("opt/canworks/VERSION", "0.98.1\n")
        self.write("etc/systemd/system/canworks-bridge@.service", "")
        p = self.run_probe()
        self.assertEqual((p["bridge"]["version"], p["bridge"]["unit"]), ("0.98.1", True))

    def test_bridge_with_two_instances_and_a_job(self):
        self.write("opt/canworks/bin/canworks-bridge", "#!/bin/sh\necho canworks-bridge 0.97.0\n", 0o755)
        self.write("etc/canworks-bridge/line3/canworks.json", "{}")
        self.write("etc/canworks-bridge/line4/canworks.json", "{\"x\": 1}")
        # Copies made by hand are not instances (install-bridge.sh --instance takes [A-Za-z0-9_-] only).
        self.write("etc/canworks-bridge/line3.bak-271/canworks.json", "{}")
        self.write("etc/canworks-bridge/line3.trimmed/canworks.json", "{}")
        self.write("etc/canworks-bridge/no-config/README", "")
        self.write("var/log/canworks-install/20261020T100000Z-aaaa.log", "old\n")
        self.write("var/log/canworks-install/20261021T100000Z-bbbb.log",
                   "::canworks-job x @1\n::canworks-step 2/5 Building @2\n::canworks-exit 0 @3\n")
        p = self.run_probe()
        b = p["bridge"]
        self.assertEqual((b["version"], b["prefix"]), ("0.97.0", "/opt/canworks"))
        self.assertEqual([i["name"] for i in b["instances"]], ["line3", "line4"])
        self.assertEqual(b["instances"][0]["state"], "active")
        self.assertEqual(len(b["instances"][0]["sha256"] or "x" * 64), 64)
        if shutil.which("sha256sum"):
            # Every file of the instance, as the plan compares them with the files a job uploads.
            self.assertEqual(b["instances"][1]["files"], ["canworks.json " + service.file_sha256(
                os.path.join(self.root, "etc/canworks-bridge/line4/canworks.json"))])
        self.assertEqual(p["install_job"], {"id": "20261021T100000Z-bbbb", "state": "inactive", "result": "success",
                                            "exit": 0, "step": "2/5 Building", "log_size": 73})

    def test_what_running_bridges_use(self):
        # UI-4: the listen address, diagnostics port and real interfaces of each active instance, nothing else.
        self.write("opt/canworks/bin/canworks-bridge", "#!/bin/sh\necho canworks-bridge 0.97.0\n", 0o755)
        self.write("etc/canworks-bridge/vp2/canworks.json", json.dumps({
            "version": 2, "bridge": {"listen": "127.0.0.1:1502"},
            "diagnostics": {"token_verifier": "SCRAM-SHA-256$secret"},
            "networks": [{"name": "io", "adapter": {"interface": "can0"}},
                         {"name": "sim", "adapter": {"interface": "can1", "simulate": True}},
                         {"name": "usb", "adapter": {"type": "slcan", "device": "/dev/ttyACM0"}}]}))
        self.write("etc/canworks-bridge/old/canworks.json", "{}")
        self.stub("systemctl", 'case $1 in is-active) case "$2" in *vp2*) echo active ;; *) echo inactive ;; esac ;; '
                               'is-enabled) echo enabled ;; show) echo inactive ;; esac')
        p = self.run_probe()
        self.assertEqual(p["bridge_uses"], {"vp2": {"listen": "127.0.0.1:1502", "diag_port": 7531,
                                                    "interfaces": ["can0", "/dev/ttyACM0"]}})
        self.assertNotIn("secret", json.dumps(p))

    def test_adapter_servers(self):
        # add-devices-adapter-server: the units, their options and the connected PCs, without sudo.
        self.assertEqual(self.run_probe()["adapters"], [])
        self.write("etc/passwd", "root:x:0:0::/root:/bin/sh\nbench:x:1000:1000::/home/bench:/bin/bash\n")
        self.write("etc/systemd/system/canworks-adapter-can0.service",
                   "[Service]\nUser=bench\nExecStart=/opt/canworks-adapter/venv/bin/canworks-diag adapter-serve "
                   "--adapter socketcan:can0 --bitrate 500 --port 7536 --allow-changes\n")
        self.write("etc/avahi/services/canworks-adapter-can0.service", "")
        self.write("etc/systemd/system/canworks-adapter-dev-ttyACM0.service",
                   "[Service]\nUser=bench\nExecStart=/x/canworks-diag adapter-serve --adapter slcan:/dev/ttyACM0 "
                   "--bitrate 250 --port 7537\n")
        self.write("home/bench/.config/canworks/adapter-serve-7536.status.json",
                   json.dumps({"pid": 1, "port": 7536, "pcs": [{"address": "192.0.2.5", "connections": 2}]}))
        a = self.run_probe()["adapters"]
        self.assertEqual(a[0], {"unit": "canworks-adapter-can0.service", "state": "active",
                                "adapter": "socketcan:can0", "bitrate_kbit": 500, "port": 7536, "allow_changes": True,
                                "discovery": True, "user": "bench", "pcs": 1})
        self.assertEqual((a[1]["adapter"], a[1]["port"], a[1]["allow_changes"], a[1]["discovery"], a[1]["pcs"]),
                         ("slcan:/dev/ttyACM0", 7537, False, False, None))

    def test_shellcheck(self):
        if not shutil.which("shellcheck"):
            self.skipTest("no shellcheck")
        subprocess.run(["shellcheck", "-s", "sh", PROBE], check=True)


class NotSavedTests(unittest.TestCase):
    FOUND = [{"name": "plc1", "addresses": ["192.168.1.114"]},
             {"name": "bench", "addresses": ["192.168.1.20", "fe80::1"]},
             {"name": "other", "addresses": ["192.168.1.30"]},
             {"name": "lab", "addresses": ["192.168.1.40"]}]

    def test_saved_by_name_address_or_lookup_is_left_out(self):
        names = {"gw.example": {"192.168.1.40"}}
        out = service.not_saved(self.FOUND, ["plc1.local", "fe80::1", "gw.example"],
                                resolve=lambda h: names.get(h, set()))
        self.assertEqual([r["name"] for r in out], ["other"])
        self.assertEqual(service.not_saved(self.FOUND, [], resolve=lambda h: set()), self.FOUND)

    def test_a_slow_lookup_is_not_waited_for(self):
        def slow(h):
            time.sleep(2)
            return {"192.168.1.30"}
        t = time.monotonic()
        out = service.not_saved(self.FOUND[2:3], ["slow.example"], resolve=slow, timeout=0.2)
        self.assertEqual(out, self.FOUND[2:3])
        self.assertLess(time.monotonic() - t, 1)


if __name__ == "__main__":
    unittest.main()
