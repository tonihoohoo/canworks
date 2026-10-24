"""canworks-bridge config upload (modbus-bridge, put_config): a running bridge
takes a new config over its diagnostics channel, refuses one that does not
pass its checks, and goes back to the previous files when the new config
does not start. The files are replaced atomically: one that cannot be
written puts the others back. The status says how the previous run ended
(modbus-bridge "Unclean stop reported"), and a full config folder is named
as such ("Full or read-only config folder"). With several CANopen networks
(PLANT_DIR, the virtual plant) a stop is clean, every network sends its stop
NMT, an upload is applied, and a network whose interface drops does not end
the process (modbus-bridge "Clean stop with several networks").

usage: upload_test.py CANWORKS_BRIDGE EXAMPLE_DIR [PLANT_DIR]
Needs the deploy tool's package on PYTHONPATH (stdlib only here).
"""

import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time

from canworks import diag

FAILURES = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILURES.append(what)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def files_of(folder, cfg):
    out = {"canworks.json": json.dumps(cfg, indent=2).encode()}
    for name in ("rtd8.eds", "dio16.eds", "simulation.json"):
        with open(os.path.join(folder, name), "rb") as f:
            out[name] = f.read()
    return out


def connect(port, token, wait=15.0, network=None):
    end = time.monotonic() + wait
    while True:
        try:
            c = diag.Client("127.0.0.1", port, token, timeout=5.0, network=network)
            c.connect()
            return c
        except diag.DiagError:
            if time.monotonic() > end:
                raise
            time.sleep(0.3)


def wait_upload(port, token, number, wait=30.0, network=None):
    end = time.monotonic() + wait
    while time.monotonic() < end:
        time.sleep(0.5)
        try:
            c = connect(port, token, 2.0, network)
            up = (c.status().get("bridge") or {}).get("last_upload") or {}
            c.close()
        except diag.DiagError:
            continue
        if up.get("number") == number:
            return up
    return {}


def status(port, token, network=None):
    c = connect(port, token, network=network)
    st = c.status().get("bridge") or {}
    c.close()
    return st


def start(bridge, work, extra_env=None):
    log = open(os.path.join(work, "bridge.log"), "a")
    env = dict(os.environ, **(extra_env or {}))
    return subprocess.Popen([bridge, "--config", os.path.join(work, "canworks.json")], stdout=log,
                            stderr=subprocess.STDOUT, env=env)


def modbus(port, pdu):
    """One Modbus TCP request (unit 1); the answer's PDU."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(struct.pack(">HHHB", 1, 0, len(pdu) + 1, 1) + pdu)
        head = b""
        while len(head) < 7:
            head += s.recv(7 - len(head))
        n = struct.unpack(">H", head[4:6])[0] - 1
        body = b""
        while len(body) < n:
            body += s.recv(n - len(body))
        return body


def write_regs(port, addr, words):
    return modbus(port, struct.pack(">BHHB", 16, addr, len(words), 2 * len(words)) +
                  b"".join(struct.pack(">H", w) for w in words))[:1] == b"\x10"


def read_regs(port, function, addr, n):
    r = modbus(port, struct.pack(">BHH", function, addr, n))
    return list(struct.unpack(">%dH" % n, r[2:])) if r[:1] == bytes([function]) else []


def multi_network_checks(bridge, plant):
    """The virtual plant (CANopen networks io, motion and host, and a slave):
    SIGTERM exits 0 after every master network's stop NMT; an upload is
    applied; the first network's interface going down (the tests' stand-in
    for a simulated interface, CANWORKS_TEST_IFACE_DOWN) leaves the bridge
    running and a write to the second network applied."""
    work = tempfile.mkdtemp(prefix="canworks-plant-")
    proc = None
    try:
        for name in os.listdir(plant):
            if not name.startswith("."):
                shutil.copy(os.path.join(plant, name), work)
        token = diag.new_token()
        dport, mport = free_port(), free_port()
        cfg_path = os.path.join(work, "canworks.json")
        with open(cfg_path) as f:
            cfg = json.load(f)
        cfg["diagnostics"] = {"token_verifier": diag.token_verifier(token), "port": dport, "bind": "127.0.0.1",
                              "allow_changes": True, "allow_config_upload": True}
        cfg["bridge"]["listen"] = "127.0.0.1:%d" % mport
        cfg["bridge"]["watchdog_ms"] = 0
        with open(cfg_path, "w") as f:
            json.dump(cfg, f, indent=2)
        down = os.path.join(work, "iface-down")
        env = {"CANWORKS_FORCE_SIMULATE": "1", "CANWORKS_TEST_IFACE_DOWN": down}
        log_path = os.path.join(work, "bridge.log")
        masters = [n["name"] for n in cfg["networks"] if n.get("role") != "slave" and n.get("nodes")]

        def stop_lines():
            text = open(log_path).read()
            return [m for m in masters if "%s: PLC stop: NMT" % m in text]

        net = cfg["networks"][0]["name"]
        proc = start(bridge, work, env)
        status(dport, token, net)
        time.sleep(3)  # every network's session runs
        proc.terminate()
        rc = proc.wait(20)
        proc = None
        check(rc == 0, "a bridge with %d CANopen networks stops with exit 0 (exit status %s)" % (len(masters), rc))
        check(stop_lines() == masters, "every network sends its stop NMT (%s of %s)" % (stop_lines(), masters))
        check(not os.path.exists(os.path.join(work, ".canworks", "running")), "the run marker is removed")

        # An upload: applied on the restart, nothing staged left behind.
        proc = start(bridge, work, env)
        check(status(dport, token, net).get("last_stop") == "clean", "the next start says clean")
        time.sleep(2)
        new = json.loads(json.dumps(cfg))
        new["bridge"]["unit_id"] = 1
        new["bridge"]["max_clients"] = 9
        files = {}
        for name in os.listdir(work):
            path = os.path.join(work, name)
            if os.path.isfile(path) and name not in ("bridge.log", "iface-down"):
                with open(path, "rb") as f:
                    files[name] = f.read()
        files["canworks.json"] = json.dumps(new, indent=2).encode()
        c = connect(dport, token, network=net)
        res = c.put_config(files)
        c.close()
        up = wait_upload(dport, token, res.get("upload"), network=net)
        check(up.get("result") == "started", "the upload with several networks is applied (%s)" % up)
        check(proc.poll() is None, "the bridge runs after the upload (exit status %s)" % proc.poll())
        with open(cfg_path) as f:
            check(json.load(f)["bridge"].get("max_clients") == 9, "the uploaded config file is in place")
        check(not os.path.exists(os.path.join(work, ".canworks-upload")), "no staged upload is left")

        # The first network's interface goes down; a write to the second.
        if proc.poll() is not None:
            return
        first = cfg["networks"][0]
        with open(down, "w") as f:
            f.write(first["adapter"]["interface"] + "\n")
        end = time.monotonic() + 10
        while "went down" not in open(log_path).read() and time.monotonic() < end:
            time.sleep(0.1)
        check("CAN interface %s went down" % first["adapter"]["interface"] in open(log_path).read(),
              "network %s reports its interface lost" % first["name"])
        hash_words = read_regs(mport, 4, 0, 2)
        ok = len(hash_words) == 2
        for i in range(20):  # 2 s of writes while the first network's session restarts
            ok = write_regs(mport, 0, [1] + hash_words) and write_regs(mport, 7, [1234 + i]) and ok
            time.sleep(0.1)
        check(proc.poll() is None, "the bridge keeps running after an interface drops (exit status %s)" % proc.poll())
        check(ok and read_regs(mport, 3, 7, 1) == [1253], "the write to the second network is applied")
        os.unlink(down)
        proc.terminate()
        rc = proc.wait(20)
        proc = None
        check(rc == 0, "and stops with exit 0 (exit status %s)" % rc)
    finally:
        if proc:
            proc.kill()
            proc.wait(10)
        if FAILURES:
            with open(os.path.join(work, "bridge.log")) as f:
                print(f.read()[-6000:])
        shutil.rmtree(work, ignore_errors=True)


def disk_checks(bridge, example):
    """A config folder below the free-space floor: refused with the disk
    message when the generated files must be written, started when they are
    cached. The floor is raised for the test instead of filling a disk."""
    work = tempfile.mkdtemp(prefix="canworks-disk-")
    try:
        for name in os.listdir(example):
            if not name.startswith("."):
                shutil.copy(os.path.join(example, name), work)
        cfg_path = os.path.join(work, "canworks.json")
        with open(cfg_path) as f:
            cfg = json.load(f)
        cfg["bridge"]["listen"] = "127.0.0.1:%d" % free_port()
        with open(cfg_path, "w") as f:
            json.dump(cfg, f, indent=2)
        full = dict(os.environ, CANWORKS_TEST_MIN_FREE_BYTES=str(1 << 62))

        def run(env):
            """Exit status, or None while it still runs after 8 s; and the log."""
            p = subprocess.Popen([bridge, "--config", cfg_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, env=env)
            try:
                out, _ = p.communicate(timeout=8)
                return p.returncode, out
            except subprocess.TimeoutExpired:
                p.terminate()
                out, _ = p.communicate(timeout=10)
                return None, out

        rc, out = run(full)
        check(rc == 1 and "no space left in" in out and "generated files" in out,
              "a full folder without cached files is named as full")
        check("deploy tool must be installed" not in out, "a full folder is not blamed on the deploy tool")
        rc, out = run(dict(os.environ))
        check(rc is None, "the same folder with room starts")
        rc, out = run(full)
        check(rc is None, "a full folder with cached files starts")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    bridge, example = sys.argv[1], sys.argv[2]
    work = tempfile.mkdtemp(prefix="canworks-upload-")
    proc = None
    try:
        for name in os.listdir(example):
            if not name.startswith("."):
                shutil.copy(os.path.join(example, name), work)
        token = diag.new_token()
        dport, mport = free_port(), free_port()
        with open(os.path.join(work, "canworks.json")) as f:
            cfg = json.load(f)
        cfg["diagnostics"] = {"token_verifier": diag.token_verifier(token), "port": dport, "bind": "127.0.0.1",
                              "allow_changes": True, "allow_config_upload": True}
        cfg["bridge"]["listen"] = "127.0.0.1:%d" % mport
        with open(os.path.join(work, "canworks.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        proc = start(bridge, work)
        c = connect(dport, token)
        check((c.status().get("bridge") or {}).get("last_stop") == "unknown", "a first start says unknown")
        check(c.info.get("host") == "bridge", "the hello names the host")
        check(c.info.get("allow_config_upload") is True, "the hello says uploads are allowed")

        # A config that passes: the bridge restarts on it.
        new = json.loads(json.dumps(cfg))
        new["bridge"]["watchdog_ms"] = 500
        res = c.put_config(files_of(work, new))
        c.close()
        check(res.get("restarting") is True and res.get("upload") == 1, "put_config accepted")
        up = wait_upload(dport, token, 1)
        check(up.get("result") == "started", "the uploaded config runs")
        with open(os.path.join(work, "canworks.json")) as f:
            check(json.load(f)["bridge"]["watchdog_ms"] == 500, "the config file was replaced")

        # A config the checks refuse: the running one stays.
        bad = json.loads(json.dumps(new))
        bad["bridge"]["status_location"] = "%IB1"
        c = connect(dport, token)
        try:
            c.put_config(files_of(work, bad))
            check(False, "a rejected config is refused")
        except diag.DiagError as e:
            check("the uploaded config was rejected" in str(e) and "overlap in input" in str(e),
                  "a rejected config is refused with the reasons")
        c.close()
        with open(os.path.join(work, "canworks.json")) as f:
            check(json.load(f)["bridge"]["watchdog_ms"] == 500, "the running config file stays")

        # A config that names an EDS the upload leaves out: the answer names it.
        missing = files_of(work, new)
        del missing["rtd8.eds"]
        c = connect(dport, token)
        try:
            c.put_config(missing)
            check(False, "an upload without its EDS is refused")
        except diag.DiagError as e:
            check("rtd8.eds" in str(e), "an upload without its EDS names the missing file")
        c.close()

        # A config that passes but does not start (its Modbus port is taken):
        # the previous files come back and run.
        taken = socket.socket()
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        nostart = json.loads(json.dumps(new))
        nostart["bridge"]["listen"] = "127.0.0.1:%d" % taken.getsockname()[1]
        c = connect(dport, token)
        res = c.put_config(files_of(work, nostart))
        c.close()
        up = wait_upload(dport, token, res.get("upload"))
        taken.close()
        check(up.get("result") == "restored", "a config that does not start is rolled back")
        with open(os.path.join(work, "canworks.json")) as f:
            check(json.load(f)["bridge"]["listen"] == "127.0.0.1:%d" % mport, "the previous config file is back")
        c = connect(dport, token)
        st = c.status().get("bridge") or {}
        c.close()
        check(st.get("listen") == "127.0.0.1:%d" % mport, "the previous config runs again")

        # A file that cannot be put in place (its temporary name is taken by
        # a folder): every file already replaced comes back.
        blocked = os.path.join(work, ".simulation.json.canworks-new")
        os.mkdir(blocked)
        changed = json.loads(json.dumps(new))
        changed["bridge"]["watchdog_ms"] = 700
        c = connect(dport, token)
        res = c.put_config(files_of(work, changed))
        c.close()
        up = wait_upload(dport, token, res.get("upload"))
        os.rmdir(blocked)
        check(up.get("result") == "restored" and "simulation.json" in (up.get("detail") or ""),
              "a file that cannot be written rolls the upload back, naming it")
        with open(os.path.join(work, "canworks.json")) as f:
            check(json.load(f)["bridge"]["watchdog_ms"] == 500, "the files replaced before it are back")
        check(status(dport, token).get("watchdog_ms") == 500, "the previous config runs")
        check(not [n for n in os.listdir(work) if n.endswith(".canworks-new")], "no temporary file is left")

        # How the previous run ended.
        proc.terminate()
        proc.wait(10)
        check(not os.path.exists(os.path.join(work, ".canworks", "running")), "a clean stop removes the run marker")
        proc = start(bridge, work)
        check(status(dport, token).get("last_stop") == "clean", "a start after a clean stop says clean")
        # The bridge answers status before it writes the run marker, the last
        # step of its start: a kill before that leaves nothing to report.
        marker = os.path.join(work, ".canworks", "running")
        end = time.monotonic() + 10
        while not os.path.exists(marker) and time.monotonic() < end:
            time.sleep(0.05)
        proc.kill()
        proc.wait(10)
        proc = start(bridge, work)
        check(status(dport, token).get("last_stop") == "unclean", "a start after a kill says unclean")
        check("did not stop cleanly" in open(os.path.join(work, "bridge.log")).read(), "and logs it")
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if FAILURES:
            with open(os.path.join(work, "bridge.log")) as f:
                print(f.read()[-6000:])
        shutil.rmtree(work, ignore_errors=True)
    disk_checks(bridge, example)
    if len(sys.argv) > 3:
        multi_network_checks(bridge, sys.argv[3])
    print("%d failure(s)" % len(FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
