"""The CiA 309-3 gateway end to end (canopen-cia309-gateway): a Python client
(canworks.cia309) against the real plugin, loaded by canopen_host on a
simulated bus with the ping-pong device and a simulated LSS device without a
node ID, over the loopback port and through canworks-diag gateway; then the
same client against canworks-bridge with the Modbus bridge example while a
Modbus client writes, and alone (the output watchdog runs out).

usage: client_test.py BUILD_DIR REPO_DIR
Needs the deploy tool's package on PYTHONPATH (standard library only here).
"""

import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

from canworks import cia309, diag

FAILURES = []


def check(cond, what, detail=""):
    print(("ok   " if cond else "FAIL ") + what + ("" if cond or not detail else ": %s" % detail))
    sys.stdout.flush()
    if not cond:
        FAILURES.append(what)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_port(port, proc, wait=30.0):
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if proc.poll() is not None:
            return False
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return True
        except OSError:
            time.sleep(0.2)
    return False


def gateway(port):
    return cia309.Client.plain("127.0.0.1", port, timeout=10)


def diag_client(port, token):
    c = diag.Client("127.0.0.1", port, token, timeout=5.0)
    c.connect()
    return c


def until(fn, wait=10.0, step=0.2):
    end = time.monotonic() + wait
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def run_cli(*argv, token):
    env = dict(os.environ, CANWORKS_TOKEN=token)
    p = subprocess.run([sys.executable, "-m", "canworks.diag"] + list(argv), env=env, capture_output=True, text=True,
                       timeout=60)
    return p.returncode, p.stdout, p.stderr


def plugin_test(build, repo, work):
    print("==> The plugin (canopen_host) on a simulated bus")
    token = diag.new_token()
    dport, gport = free_port(), free_port()
    shutil.copy(os.path.join(repo, "config", "pingpong", "cpp-slave.eds"), work)
    shutil.copy(os.path.join(repo, "test", "fixtures", "eds", "lss-slave.eds"), work)
    shutil.copy(os.path.join(repo, "config", "rtd-sensor", "rtd8.eds"), work)
    with open(os.path.join(repo, "config", "pingpong", "canopen_config.json")) as f:
        cfg = json.load(f)
    cfg["adapter"] = {"type": "socketcan", "interface": "sim0", "bitrate": 125000, "simulate": True}
    # allow_changes for the simulator commands; the gateway has its own.
    cfg["master"]["diagnostics"] = {"token_verifier": diag.token_verifier(token), "port": dport, "bind": "127.0.0.1",
                                    "allow_changes": True}
    # A second node whose device name (0x1008, "RTD-8") is longer than an expedited transfer.
    cfg["nodes"].append({"node_id": 5, "name": "rtd", "eds": "rtd8.eds"})
    cfg["master"]["cia309"] = {"port": gport, "allow_changes": True}
    with open(os.path.join(work, "canopen_config.json"), "w") as f:
        json.dump(cfg, f, indent=2)
    with open(os.path.join(repo, "config", "pingpong", "simulation.json")) as f:
        sim = json.load(f)
    sim["extra_devices"] = [{"node": 0, "name": "newdev", "eds": "lss-slave.eds",
                             "identity": {"serial_number": 0x1234}}]
    with open(os.path.join(work, "simulation.json"), "w") as f:
        json.dump(sim, f, indent=2)
    log_path = os.path.join(work, "host.log")
    log = open(log_path, "w")
    proc = subprocess.Popen([os.path.join(build, "test", "canopen_host"),
                             os.path.join(build, "plugins", "libcanworks_plugin.so"),
                             os.path.join(work, "canopen_config.json"), "60"], stdout=log, stderr=subprocess.STDOUT)
    try:
        check(wait_port(gport, proc), "the plain gateway port listens")
        text = open(log_path).read()
        check(re.search(r"CiA 309-3 gateway listens on 127\.0\.0\.1:%d .*changes allowed.*networks 1 = the network"
                        % gport, text) is not None, "the log names the address, the changes and the numbering")
        g = gateway(gport)
        # Node 2 boots: wait for its device type to answer.
        check(until(lambda: not g.request("1 2 r 0x1000 0 u32").startswith("ERROR"), 20), "node 2 answers SDO")
        vendor = g.request("1 2 r 0x1018 1 u32")
        check(vendor.startswith("0x"), "SDO read of the vendor ID", vendor)
        check(until(lambda: not g.request("1 5 r 0x1000 0 u32").startswith("ERROR"), 20), "node 5 answers SDO")
        name = g.request("1 5 r 0x1008 0 vs")
        check(name == '"RTD-8"', "segmented read of the device name", name)
        check(cia309.error_code(g.request("1 2 r 0x2100 0 u8")) == 0x06020000, "a missing object: its abort code")
        check(cia309.error_code(g.request("1 2 r 0x1018")) == 101, "a syntax error: 101")
        # OPERATIONAL node: write and stop refused without allow_force.
        check(until(lambda: "pdo" in g.request("1 0 r p 5"), 10), "r p of node 2's TPDO 1 (gateway RPDO 5)")
        check(cia309.error_code(g.request("1 2 w 0x4000 0 u32 7")) == 102, "SDO write to an OPERATIONAL node refused")
        check(cia309.error_code(g.request("1 2 stop")) == 102, "NMT stop to an OPERATIONAL node refused")
        check(cia309.error_code(g.request("1 set heartbeat 100")) == 100, "set heartbeat not served: 100")
        check(cia309.error_code(g.request("1 9 stop")) == 107, "NMT to a node not in the configuration: 107")
        check(g.request("1 2 start") == "OK", "NMT start")
        check(cia309.error_code(g.request("1 r p 7")) in (102, 104), "a PDO number without a mapped TPDO")
        # EMCY from the simulated device, then its boot-up after a power cycle.
        code, _, err = run_cli("--runtime", "127.0.0.1:%d" % dport, "sim", "fault", "2", "emcy", "0x5030",
                               "--register", "1", token=token)
        check(code == 0, "simulator EMCY injected", err)
        try:
            note = g.wait_notification(r"^1 2 EMCY 5030 01", 5)
            check(True, "EMCY notification: " + note)
        except socket.timeout:
            check(False, "EMCY notification", g.notifications)
        run_cli("--runtime", "127.0.0.1:%d" % dport, "sim", "fault", "2", "power", "cycle", token=token)
        try:
            g.wait_notification(r"^1 2 BOOT_UP", 10)
            check(True, "boot-up notification")
        except socket.timeout:
            check(False, "boot-up notification", g.notifications)
        # LSS: find the device without a node ID, give it node ID 40, no store.
        found = g.request("1 _lss_fastscan 0 0 0 0 0 0 0 0", timeout=30)
        check(found.startswith("0x") and found.endswith("0x00001234"), "LSS fastscan finds the new device", found)
        check(g.request("1 lss_set_node 40") == "OK", "lss_set_node 40 (not stored)")
        check(until(lambda: not g.request("1 40 r 0x1000 0 u32").startswith("ERROR"), 10),
              "the device answers as node 40")
        text = open(log_path).read()
        line = next((l for l in text.splitlines() if "LSS set node ID 40" in l), "")
        check("by CiA 309-3 gateway client 127.0.0.1" in line and "(not stored)" in line,
              "the LSS change is logged as the gateway's, not stored", line)
        # Through the diagnostics channel: canworks-diag gateway.
        code, out, err = run_cli("--runtime", "127.0.0.1:%d" % dport, "gateway", "--exec", "1 2 r 0x1018 1 u32",
                                 token=token)
        check(code == 0 and out.strip() == vendor, "canworks-diag gateway --exec", out + err)
        code, out, err = run_cli("--runtime", "127.0.0.1:%d" % dport, "gateway", "--list", token=token)
        check(code == 0 and "1 = " in out, "canworks-diag gateway --list", out + err)
        # Status lists the plain session.
        code, out, err = run_cli("--runtime", "127.0.0.1:%d" % dport, "status", token=token)
        check(code == 0 and "CiA 309-3 gateway on 127.0.0.1:%d" % gport in out and "plain" in out,
              "status prints the gateway and its session", out)
        # Four sessions reading in a loop: the SYNC timing stays.
        c = diag_client(dport, token)
        before = c.status().get("sync") or {}
        c.close()
        g.close()
        stop = threading.Event()
        counts = []

        def reader():
            s = gateway(gport)
            n = 0
            while not stop.is_set():
                s.request("1 2 r 0x1018 1 u32")
                n += 1
            counts.append(n)
            s.close()

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        time.sleep(5)
        stop.set()
        for t in threads:
            t.join()
        c = diag_client(dport, token)
        after = c.status().get("sync") or {}
        c.close()
        check(sum(counts) > 40, "four sessions read in a loop", counts)
        period = cfg["master"]["sync_period_us"]
        check(after.get("late_pdos", 0) == before.get("late_pdos", 0), "no late PDOs while they read")
        check(after.get("max_us", 0) < 3 * period, "the SYNC interval stays (max %s us, period %s us)"
              % (after.get("max_us"), period))
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def modbus_write(sock, register, value, tid=[0]):
    tid[0] += 1
    req = struct.pack(">HHHBBHH", tid[0], 0, 6, 1, 6, register, value)
    sock.sendall(req)
    return sock.recv(64)


def bridge_test(build, repo, work):
    print("==> canworks-bridge with the Modbus bridge example")
    bwork = os.path.join(work, "bridge")
    os.makedirs(bwork)
    example = os.path.join(repo, "examples", "modbus-bridge")
    for name in os.listdir(example):
        if not name.startswith("."):
            shutil.copy(os.path.join(example, name), bwork)
    token = diag.new_token()
    dport, gport, mport = free_port(), free_port(), free_port()
    with open(os.path.join(bwork, "canworks.json")) as f:
        cfg = json.load(f)
    cfg["diagnostics"] = {"token_verifier": diag.token_verifier(token), "port": dport, "bind": "127.0.0.1"}
    cfg["cia309"] = {"port": gport}
    cfg["bridge"]["listen"] = "127.0.0.1:%d" % mport
    cfg["bridge"]["writers"] = ["127.0.0.1"]
    cfg["bridge"]["watchdog_ms"] = 1000
    with open(os.path.join(bwork, "canworks.json"), "w") as f:
        json.dump(cfg, f, indent=2)
    log_path = os.path.join(bwork, "bridge.log")
    log = open(log_path, "w")
    proc = subprocess.Popen([os.path.join(build, "bin", "canworks-bridge"), "--config",
                             os.path.join(bwork, "canworks.json")], stdout=log, stderr=subprocess.STDOUT)
    try:
        check(wait_port(gport, proc) and wait_port(mport, proc), "the bridge serves Modbus and the gateway")
        g = gateway(gport)
        check(until(lambda: not g.request("1 5 r 0x1000 0 u32").startswith("ERROR"), 20),
              "the gateway reads node 5 next to Modbus")
        m = socket.create_connection(("127.0.0.1", mport), timeout=5)
        for i in range(20):
            modbus_write(m, 1, i)
            g.request("1 5 r 0x1018 1 u32")
            time.sleep(0.1)
        c = diag_client(dport, token)
        st = c.request("status", network=diag.network_names(c)[0]) if c.several() else c.status()
        b = st.get("bridge") or {}
        c.close()
        check(b.get("state") == "running", "outputs run while the Modbus client writes", b.get("state"))
        check(len(b.get("cia309_sessions") or []) == 1, "the bridge status lists the gateway session",
              b.get("cia309_sessions"))
        m.close()
        # Only the gateway client now: the watchdog runs out as with no client.
        for i in range(25):
            g.request("1 5 r 0x1018 1 u32")
            time.sleep(0.1)
        c = diag_client(dport, token)
        b = (c.request("status", network=diag.network_names(c)[0]) if c.several() else c.status()).get("bridge") or {}
        c.close()
        check(b.get("state") == "outputs_off" and b.get("reason") == "watchdog",
              "the watchdog ran out with only the gateway client", b)
        check(g.request("1 5 r 0x1018 1 u32").startswith("0x"), "the gateway client keeps being served")
        g.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def main():
    build, repo = sys.argv[1], sys.argv[2]
    work = tempfile.mkdtemp(prefix="canworks-cia309-")
    try:
        plugin_test(build, repo, work)
        bridge_test(build, repo, work)
    except Exception as e:  # a crash is a failure with the logs kept
        check(False, "the test ran to the end", repr(e))
    if FAILURES:
        for name in ("host.log", "bridge/bridge.log"):
            p = os.path.join(work, name)
            if os.path.exists(p):
                print("==> %s (last 60 lines)" % name)
                print("".join(open(p).readlines()[-60:]))
        print("FAIL: %d check(s): %s" % (len(FAILURES), "; ".join(FAILURES)))
        return 1
    shutil.rmtree(work, ignore_errors=True)
    print("PASS: the CiA 309-3 gateway end to end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
