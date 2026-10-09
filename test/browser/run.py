#!/usr/bin/env python3
"""The configurator in Chromium against the real plugin (fix-gui-test-findings
task 8.4, canopen-ci "Browser run against the real plugin").

  test/browser/run.py [--build-dir build] [--out DIR] [--headed]

Starts canopen_host with libcanworks_plugin.so on a copy of
examples/virtual-plant with CANWORKS_FORCE_SIMULATE=1, so every network runs
on the plugin's simulated bus with simulated devices and no CAN interface is
needed, and the plugin's diagnostics channel on a free port of 127.0.0.1.
Starts canworks-config (this checkout's tools/deploy) on the copy and drives
it with Playwright through these steps:

  connect      Online view: host and the example's token, connected
  nodes        the node table shows nodes 5, 6 and 7 OPERATIONAL
  od           node 6: SDO read of 0x2000:0, a write, the read gives it back
  sim-fault    Simulation: heartbeat stop on node 6, its status bit goes FALSE
               online; cleared, node 6 is OPERATIONAL with its bit TRUE again
  tpdo-timeout TPDO stop 1 on node 5: online, its TPDO 1 timed out (the
               timeout line and the node's input PDO timeout table); cleared
  trace        a live trace started, stopped and downloaded (pcapng)
  power-cycle  Power off and on of node 5: node 5 is OPERATIONAL again, and
               5 s later the status and an SDO read still answer
  host-stop    canopen_host stops within 5 s of SIGTERM

A failed step is reported with a screenshot in --out and the run goes on
(a step that needs the connection is skipped without one). Exits 0 when
every step passed, 1 otherwise. The stand-in PLC program of canopen_host
does not run the example's ST program.

Needs a build of canworks_plugin and canopen_host, Python Playwright and a
Chromium: CANWORKS_CHROMIUM names its executable, else Playwright's own
(python -m playwright install chromium). docs/development.md, "The plugin
and the configurator without a CAN interface".
"""

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EXAMPLE = os.path.join(ROOT, "examples", "virtual-plant")
TOKEN = "virtual-plant-demo"  # the example's documented demo token

STEP_TIMEOUT_MS = 15000


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Run:
    def __init__(self, args):
        self.args = args
        self.out = args.out
        self.failed = []
        self.passed = []
        self.host = self.config = None

    # -- processes -----------------------------------------------------------
    def start(self):
        work = self.work = tempfile.mkdtemp(prefix="canworks-browser-")
        self.project = os.path.join(work, "virtual-plant")
        shutil.copytree(EXAMPLE, self.project)
        cfg_path = os.path.join(self.project, "canworks", "canworks.json")
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        self.port = free_port()
        cfg["diagnostics"]["port"] = self.port
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        build = self.args.build_dir
        host_cmd = [os.path.join(build, "test", "canopen_host"), os.path.join(build, "plugins", "libcanworks_plugin.so"),
                    cfg_path, "3600"]
        self.host_log = open(os.path.join(self.out, "host.log"), "w")
        self.host = subprocess.Popen(host_cmd, stdout=self.host_log, stderr=subprocess.STDOUT,
                                     env=dict(os.environ, CANWORKS_FORCE_SIMULATE="1"))
        env = dict(os.environ, CANWORKS_CONFIG_DIR=os.path.join(work, "settings"),
                   PYTHONPATH=os.pathsep.join(filter(None, [os.path.join(ROOT, "tools", "deploy"),
                                                            os.environ.get("PYTHONPATH")])))
        self.config_log = open(os.path.join(self.out, "configurator.log"), "w")
        self.config = subprocess.Popen(
            [sys.executable, "-c", "import sys; from canworks.configurator.server import main; sys.exit(main())",
             "--no-browser", self.project], stdout=subprocess.PIPE, stderr=self.config_log, text=True, env=env)
        line = self.config.stdout.readline()
        m = re.search(r"(http://\S+)", line)
        if not m:
            raise SystemExit("canworks-config did not start: %r (see %s)" % (line, self.config_log.name))
        self.url = m.group(1)
        # The diagnostics channel is up once the plugin started its networks.
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.host.poll() is not None:
                raise SystemExit("canopen_host exited with %s (see %s)" % (self.host.returncode, self.host_log.name))
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
                return
            except OSError:
                time.sleep(0.5)
        raise SystemExit("the plugin's diagnostics port %d did not open in 30 s (see %s)" % (self.port, self.host_log.name))

    def stop_host(self):
        """SIGTERM; True when the host stopped within 5 s."""
        if self.host is None or self.host.poll() is not None:
            return True
        self.host.send_signal(signal.SIGTERM)
        try:
            self.host.wait(5)
            return True
        except subprocess.TimeoutExpired:
            self.host.kill()
            self.host.wait()
            return False

    def stop(self):
        self.stop_host()
        if self.config is not None and self.config.poll() is None:
            self.config.terminate()
            try:
                self.config.wait(5)
            except subprocess.TimeoutExpired:
                self.config.kill()
        shutil.rmtree(self.work, ignore_errors=True)

    # -- steps ---------------------------------------------------------------
    def step(self, name, fn):
        print("== %s" % name, flush=True)
        t = time.time()
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - every failure is reported, the run goes on
            shot = os.path.join(self.out, "%s.png" % name)
            try:
                self.page.screenshot(path=shot, full_page=True)
            except Exception:  # noqa: BLE001
                shot = None
            msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
            print("FAIL %s: %s%s" % (name, msg, " (screenshot %s)" % shot if shot else ""), flush=True)
            self.failed.append(name)
            return False
        print("ok   %s (%.1f s)" % (name, time.time() - t), flush=True)
        self.passed.append(name)
        return True

    def view(self, name):
        self.page.click('#side button[data-view="%s"]' % name)

    def online_row(self, node):
        return 'tr[data-online-node="%d"]' % node

    def wait_row(self, node, state=None, status=None, text=None):
        """Waits for the online node table's row of `node` to show the NMT
        state, the status bit ("TRUE"/"FALSE") and a text."""
        try:
            self.page.wait_for_function(
                """([sel, state, status, text]) => {
                  const r = document.querySelector(sel);
                  if (!r) return false;
                  const c = r.querySelectorAll("td");
                  return (!state || c[2].innerText.trim() === state) && (!status || c[3].innerText.trim().startsWith(status))
                    && (!text || r.innerText.includes(text));
                }""", arg=[self.online_row(node), state, status, text], timeout=STEP_TIMEOUT_MS)
        except Exception:
            want = ", ".join(x for x in (state, status and "status bit " + status, text and repr(text)) if x)
            row = self.page.locator(self.online_row(node))
            shows = " | ".join(row.inner_text().split()) if row.count() else "no row"
            raise AssertionError("node %d: no %s within %d s; the row shows: %s; connection: %s" % (
                node, want, STEP_TIMEOUT_MS // 1000, shows, self.conn())) from None

    def conn(self):
        c = self.page.locator("#online-conn")
        return " ".join(c.inner_text().split()) if c.count() else "?"

    def sdo_read(self, node, index, subindex, type_):
        """An SDO read in the node's panel of the online view: the value's text."""
        pg = self.page
        self.view("online")
        try:
            pg.wait_for_selector(self.online_row(node), timeout=STEP_TIMEOUT_MS)
        except Exception:
            raise AssertionError("node %d: not in the online node table after %d s; connection: %s" % (
                node, STEP_TIMEOUT_MS // 1000, self.conn())) from None
        pg.click(self.online_row(node))
        sdo = '[data-online="sdo"] '
        pg.fill(sdo + 'input[data-online="index"]', index)
        pg.fill(sdo + 'input[data-online="subindex"]', str(subindex))
        pg.select_option(sdo + 'select[data-online="type"]', type_)
        pg.click(sdo + 'button[data-online="read"]')
        result = sdo + '[data-online="sdo-result"]'
        try:
            pg.wait_for_selector(result + " :is(strong, .field-msg)", timeout=STEP_TIMEOUT_MS)
        except Exception:
            raise AssertionError("node %d: no answer to the SDO read of %s:%s in %d s (%s); connection: %s" % (
                node, index, subindex, STEP_TIMEOUT_MS // 1000, pg.inner_text(result), self.conn())) from None
        if not pg.locator(result + " strong").count():
            raise AssertionError("node %d: SDO read of %s:%s: %s" % (node, index, subindex, pg.inner_text(result)))
        return pg.inner_text(result + " strong").split(" ")[0]

    def sim_device(self, node):
        pg = self.page
        self.view("simulation")
        pg.click('button[data-sim-tab="live"]')
        pg.click('tr[data-sim-device="%d"]' % node)
        pg.wait_for_selector('#sim-device h2:has-text("%d")' % node)

    def sim_fault(self, node, kind, fields=None):
        pg = self.page
        self.sim_device(node)
        pg.click('button[data-sim-fault="%s"]' % kind)
        if fields is not None:
            for k, v in fields.items():
                pg.fill('[data-sim-form="%s"] input[data-sim-field="%s"]' % (kind, k), v)
            pg.click('[data-sim-form="%s"] button[data-sim="inject"]' % kind)
        pg.wait_for_selector("#banner:has-text('injected')")

    def sim_clear(self, node, fault):
        pg = self.page
        self.sim_device(node)
        pg.click('#sim-active-faults button[data-sim-clear="%s"]' % fault)
        pg.wait_for_selector('#sim-active-faults button[data-sim-clear="%s"]' % fault, state="detached")

    def connect(self):
        pg = self.page
        pg.goto(self.url)
        pg.wait_for_selector("#editor:not([hidden])")
        self.view("online")
        pg.fill('input[data-online="host"]', "127.0.0.1:%d" % self.port)
        pg.click('button[data-online="connect"]')
        pg.wait_for_selector('#modal input[aria-label="Access token"]')
        pg.fill('#modal input[aria-label="Access token"]', TOKEN)
        pg.click('#modal button[data-value="set"]')
        pg.wait_for_selector("#online-conn.ok", timeout=STEP_TIMEOUT_MS)
        pg.wait_for_selector("text=changes allowed")

    def nodes(self):
        for node in (5, 6, 7):
            self.wait_row(node, state="OPERATIONAL", status="TRUE")

    def od(self):
        pg = self.page
        sdo = '[data-online="sdo"] '
        before = self.sdo_read(6, "0x2000", 0, "UNSIGNED16")
        value = "42" if before != "42" else "43"
        pg.fill(sdo + 'input[data-online="value"]', value)
        pg.click(sdo + 'button[data-online="write"]')
        # The config writes 0x2000 at boot and an SDO variable writes it: the page asks first.
        pg.click('#modal button[data-value="write"]')
        pg.wait_for_selector(sdo + '[data-online="sdo-result"]:has-text("Written.")')
        after = self.sdo_read(6, "0x2000", 0, "UNSIGNED16")
        if after != value:
            raise AssertionError("node 6: wrote %s to 0x2000:0, read back %s" % (value, after))

    def sim_fault_step(self):
        self.sim_fault(6, "heartbeat")
        self.view("online")
        self.wait_row(6, status="FALSE")
        self.sim_clear(6, "heartbeat")
        self.view("online")
        self.wait_row(6, state="OPERATIONAL", status="TRUE")

    def tpdo_timeout(self):
        pg = self.page
        self.sim_fault(5, "tpdo_stop", {"tpdo": "1"})
        try:
            self.view("online")
            self.wait_row(5, text="TPDO 1 timed out")
            pg.click(self.online_row(5))
            pg.wait_for_selector('[data-online="pdo-timeouts"] tr[data-pdo-timeout-row="1"]:has-text("timed out")',
                                 timeout=STEP_TIMEOUT_MS)
        finally:
            self.sim_clear(5, "tpdo_stop")
        self.view("online")
        pg.click(self.online_row(5))
        pg.wait_for_selector('[data-online="pdo-timeouts"] tr[data-pdo-timeout-row="1"]:has-text("receiving")',
                             timeout=STEP_TIMEOUT_MS)

    def trace(self):
        pg = self.page
        self.view("trace")
        pg.wait_for_selector("#trace-source:not(:has-text('Loading'))")
        pg.click("[data-trace=start]")
        pg.wait_for_selector("#trace-source:has-text('recording')", timeout=STEP_TIMEOUT_MS)
        pg.wait_for_function("() => /[1-9][\\d,.]* frames/.test(document.querySelector('[data-trace=stats]').innerText)",
                             timeout=STEP_TIMEOUT_MS)
        pg.click("[data-trace=stop]")
        pg.wait_for_selector("#trace-source:has-text('stopped')", timeout=STEP_TIMEOUT_MS)
        pg.select_option("select[data-trace=export-format]", "pcapng")
        with pg.expect_download() as dl:
            pg.click("[data-trace=export]")
        path = os.path.join(self.out, dl.value.suggested_filename)
        dl.value.save_as(path)
        size = os.path.getsize(path)
        if size < 100:
            raise AssertionError("the downloaded trace %s has %d bytes" % (path, size))

    def power_cycle(self):
        self.sim_fault(5, "power_off")
        self.view("online")
        self.wait_row(5, status="FALSE")
        self.sim_fault(5, "power_on")
        self.view("online")
        self.wait_row(5, state="OPERATIONAL", status="TRUE")
        # A bus thread that hangs after the power on leaves the diagnostics
        # without an answer a moment later.
        self.page.wait_for_timeout(5000)
        self.sdo_read(5, "0x1018", 1, "UNSIGNED32")
        self.wait_row(5, state="OPERATIONAL", status="TRUE")

    def host_stop(self):
        if not self.stop_host():
            raise AssertionError("canopen_host did not stop within 5 s of SIGTERM (killed)")

    def run(self):
        from playwright.sync_api import sync_playwright

        self.start()
        exe = os.environ.get("CANWORKS_CHROMIUM")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not self.args.headed, **({"executable_path": exe} if exe else {}))
            context = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
            self.page = context.new_page()
            self.page.set_default_timeout(10000)
            self.errors = []
            self.page.on("pageerror", lambda e: self.errors.append(str(e)))
            if self.step("connect", self.connect):
                self.step("nodes", self.nodes)
                self.step("od", self.od)
                self.step("sim-fault", self.sim_fault_step)
                self.step("tpdo-timeout", self.tpdo_timeout)
                self.step("trace", self.trace)
                self.step("power-cycle", self.power_cycle)
            else:
                self.failed += ["nodes", "od", "sim-fault", "tpdo-timeout", "trace", "power-cycle"]
            self.step("host-stop", self.host_stop)
            if self.errors:
                print("FAIL page errors: %s" % "; ".join(self.errors), flush=True)
                self.failed.append("page errors")
            context.close()
            browser.close()
        print("passed: %s" % (", ".join(self.passed) or "none"))
        print("failed: %s" % (", ".join(self.failed) or "none"))
        return 1 if self.failed else 0


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--build-dir", default=os.path.join(ROOT, "build"), help="the cmake build (default: build)")
    p.add_argument("--out", help="folder for the logs, screenshots and the downloaded trace (default: a new temporary one)")
    p.add_argument("--headed", action="store_true", help="show the browser")
    args = p.parse_args()
    args.build_dir = os.path.abspath(args.build_dir)
    args.out = os.path.abspath(args.out) if args.out else tempfile.mkdtemp(prefix="canworks-browser-out-")
    os.makedirs(args.out, exist_ok=True)
    print("logs and screenshots in %s" % args.out, flush=True)
    r = Run(args)
    try:
        code = r.run()
    finally:
        r.stop()
    sys.exit(code)


if __name__ == "__main__":
    main()
