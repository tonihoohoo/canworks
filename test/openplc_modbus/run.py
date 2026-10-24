#!/usr/bin/env python3
"""The OpenPLC connection end to end (add-openplc-modbus-target 5.1, modbus-connections): the
pinned OpenPLC runtime's own Modbus master plugin against canworks-bridge.

    test/openplc_modbus/run.py --bridge build/bin/canworks-bridge --runtime DIR

DIR is a checkout of the pinned runtime (docker/local-runtime/runtime-version);
its plugin needs pymodbus (its requirements.txt). The example's two simulated
CANopen nodes run inside the bridge, so no CAN interface is needed.

The PC tools turn the example into a config with an OpenPLC connection and write
the editor's remote device; the remote device becomes conf/modbus_master.json
as the editor's Build does (generate-modbus-master-config.ts); the runtime's
ModbusSlaveDevice thread polls the bridge with it, on an in-memory process
image in place of the runtime's. The test plays the PLC program's part on
that image (the header canworks_out writes, the values) and checks:

1. inputs come in: the map hash, the status block and the simulated values;
2. outputs go out: an output byte reaches the simulated node and comes back
   as its input (the node's simulation copies 0x6200:1 to 0x6000:1), and an
   SDO read through the PLC link's SDO registers reads it from the node;
3. the function blocks' mailboxes: an SDO read through a request mailbox
   and a CAN receiver's frames in the receive mailbox, written and read as
   the library's blocks do, and a 1024-byte SDO read (a long string the test
   adds to the digital node) in its first 128 bytes and FETCHes;
4. the PLC stops as the runtime stops it (%Q zeroed for one more round,
   then the plugin's threads stop): with on_client_loss "hold" the node
   keeps the last real output, not the zeros;
5. a PLC built for another map (wrong hash in the header): the bridge takes
   no output from it;
6. the example with a J1939 network too (examples/j1939's, on a CAN
   interface this test does not open): the bridge accepts the config, and
   the remote device and the runtime's model of its modbus_master.json
   cover the J1939 signals;
7. the receive rate (faster-mailboxes): with the nodes' TPDOs on a 2 ms
   SYNC and a receiver for every frame, a PLC that drains and acknowledges
   each batch at once gets full batches (9 CAN records with one receive
   block, 21 with two) and at least 400 and 900 frames/s at the 10 ms poll
   and 10 ms mailbox poll, and at least 70 with one block at the default
   50 ms mailbox poll (mailbox-poll).
"""

import argparse
import copy
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EXAMPLE = os.path.join(ROOT, "examples", "modbus-bridge")
sys.path.insert(0, os.path.join(ROOT, "tools", "deploy"))

from canworks import editorproject, mailboxlayout, modbusmap, openplcmodbus  # noqa: E402
from canworks.configurator import server as srv  # noqa: E402

IEC_BASE = 100
LONG_TEXT = "".join(chr(0x41 + i % 26) for i in range(1024))
FAILS = []



def openplc_config(cfg):
    """`cfg` on the Modbus bridge with an OpenPLC connection, as the
    configurator's Use with canworks-bridge and Add connection make it, and
    the default mailboxes, which the example's main uses (mailboxes-on-demand:
    the configurator offers them once the program declares the blocks)."""
    s = srv.Session()
    cfg = s.switch_target(cfg, "bridge", openplc=False)["config"]
    cfg = s.add_connection(cfg, {"kind": "openplc"})["config"]
    cfg["bridge"]["mailboxes"] = {"input_location": "%IB0", "output_location": "%QB0"}
    return modbusmap.pack(cfg)

def check(ok, text):
    print("    %s %s" % ("ok  " if ok else "FAIL", text), flush=True)
    if not ok:
        FAILS.append(text)


def wait(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def master_config(remote):
    """conf/modbus_master.json from the remote device, as the editor's Build
    makes it (generateModbusMasterConfig)."""
    t = remote["modbusTcpConfig"]
    points = [{"fc": int(g["functionCode"]), "offset": "0x%04X" % int(g["offset"]),
               "iec_location": g["ioPoints"][0]["iecLocation"], "len": g["length"],
               "cycle_time_ms": g["cycleTime"], "error_handling": g.get("errorHandling", "keep-last-value")}
              for g in t["ioGroups"]]
    return [{"name": remote["name"], "protocol": "MODBUS",
             "config": {"type": "SLAVE", "transport": "tcp", "host": t["host"], "port": t["port"],
                        "timeout_ms": t["timeout"], "slave_id": t["slaveId"], "io_points": points}}]


class Image:
    """The process image in place of the runtime's SafeBufferAccess: the
    word tables (%IW and %QW), which are all the remote device uses. Its
    answers carry the runtime's own status text ("Success")."""

    def __init__(self, config_path):
        self.config_path = config_path
        self.lock = threading.RLock()
        self.words = {"I": {}, "Q": {}}

    def acquire_mutex(self):
        self.lock.acquire()
        return True, "OK"

    def release_mutex(self):
        self.lock.release()
        return True, "OK"

    def get_config_path(self):
        return self.config_path, "OK"

    def read_int_input(self, idx, thread_safe=True):
        return self.words["I"].get(idx, 0), "Success"

    def write_int_input(self, idx, value, thread_safe=True):
        self.words["I"][idx] = value & 0xFFFF
        return True, "Success"

    def read_int_output(self, idx, thread_safe=True):
        return self.words["Q"].get(idx, 0), "Success"

    def write_int_output(self, idx, value, thread_safe=True):
        self.words["Q"][idx] = value & 0xFFFF
        return True, "Success"

    def __getattr__(self, name):
        raise AttributeError("the remote device uses only %%IW and %%QW, not %s" % name)


class Plc:
    """The program's side: bridge registers by number through the remote
    device's groups (register -> %IW/%QW word)."""

    def __init__(self, image, remote):
        self.image = image
        self.at = {"I": {}, "Q": {}}
        for g in remote["modbusTcpConfig"]["ioGroups"]:
            area = "I" if g["functionCode"] == "4" else "Q"
            first = int(g["ioPoints"][0]["iecLocation"][3:])
            for k in range(g["length"]):
                self.at[area][int(g["offset"]) + k] = first + k

    def get(self, reg):
        with self.image.lock:
            return self.image.words["I"].get(self.at["I"][reg], 0)

    def put(self, values):
        """Writes {register: word} at once, as one scan does."""
        with self.image.lock:
            for reg, v in values.items():
                self.image.words["Q"][self.at["Q"][reg]] = v & 0xFFFF

    def byte(self, nbyte):
        w = self.get(nbyte // 2)
        return (w >> 8) & 0xFF if nbyte % 2 == 0 else w & 0xFF  # even byte: high byte (bridge byte order)


def set_byte(words, nbyte, value, current):
    reg = nbyte // 2
    w = words.get(reg, current(reg))
    w = (w & 0x00FF) | (value << 8) if nbyte % 2 == 0 else (w & 0xFF00) | value
    words[reg] = w
    return words


def with_j1939(work):
    """Step 6: the example with examples/j1939's network as an config with an
    OpenPLC connection, checked by the bridge, the remote device and the model."""
    with open(os.path.join(EXAMPLE, "canworks.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    with open(os.path.join(ROOT, "examples", "j1939", "canworks.json"), encoding="utf-8") as f:
        net = json.load(f)["networks"][0]
    shutil.copy(os.path.join(ROOT, "examples", "j1939", net["j1939"]["dbc"]), work)
    del cfg["bridge"]
    cfg["networks"].append(net)
    cfg = openplc_config(cfg)
    path = os.path.join(work, "with-j1939.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return cfg, path


def receive_rate(bridge_bin, cfg, work, mm, model_cls, logger, blocks, seconds=3.0, mailbox_poll=None):
    """Step 7 for 1 or 2 receive blocks: (frames/s, batches, full batches,
    what went wrong or "")."""
    cfg = copy.deepcopy(cfg)
    cfg["networks"][0]["master"]["sync_period_us"] = 2000
    cfg["bridge"]["mailboxes"]["receive_blocks"] = blocks
    cfg["bridge"]["connections"][0].pop("mailbox_poll_ms", None)
    if mailbox_poll:
        cfg["bridge"]["connections"][0]["mailbox_poll_ms"] = mailbox_poll
    cfg["bridge"]["listen"] = "127.0.0.1:%d" % free_port()
    cfg = modbusmap.pack(cfg)
    tag = "%d-%s" % (blocks, mailbox_poll or "default")
    path = os.path.join(work, "rate-%s.json" % tag)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    remote = openplcmodbus.remote_device(cfg, editorproject.declarations(cfg, path), IEC_BASE)
    conf = os.path.join(work, "modbus_master_rate_%s.json" % tag)
    with open(conf, "w", encoding="utf-8") as f:
        json.dump(master_config(remote), f, indent=2)
    model = model_cls()
    model.import_config_from_file(conf)
    model.validate()
    log = open(os.path.join(work, "bridge-rate-%s.log" % tag), "w")
    proc = subprocess.Popen([bridge_bin, "--config", path], stdout=log, stderr=subprocess.STDOUT)
    image = Image(conf)
    plc = Plc(image, remote)
    hash_ = modbusmap.map_hash(cfg)
    plc.put({0: 1, 1: hash_ >> 16, 2: hash_ & 0xFFFF})
    master = mm.ModbusSlaveDevice(model.devices[0], image, logger)
    master.start()
    try:
        if not wait(lambda: (plc.get(0) << 16 | plc.get(1)) == hash_ and plc.byte(4) == 1):
            return 0, 0, 0, "the bridge never ran for the PLC (status %d)" % plc.byte(4)
        mb = cfg["bridge"]["mailboxes"]
        rsp, req = int(mb["input_location"][3:]) // 2, int(mb["output_location"][3:]) // 2
        rx, ack = rsp + 72, req + 72
        # RX_OPEN: CAN, every standard frame (ALL_IDS), DEPTH 256.
        plc.put({req: 1, req + 1: 0x0800, req + 2: 0x0104, req + 3: 256, req + 4: 0, req + 5: 0, req + 6: 0, req + 7: 0})
        if not wait(lambda: plc.get(rsp) == 1 and plc.get(rsp + 1) == 0x0200):
            return 0, 0, 0, "the receiver did not open (%#06x)" % plc.get(rsp + 1)
        full = mailboxlayout.records_per_batch("can", blocks)
        seq, frames, batches, fulls = None, 0, 0, 0
        warm = time.monotonic() + 0.5
        while time.monotonic() < warm + seconds:
            now_seq = plc.get(rx)
            if now_seq != seq and plc.get(rx + 3):
                seq = now_seq
                n = plc.get(rx + 3) // 10
                plc.put({ack: seq, ack + 1: 0, ack + 2: 0})
                if time.monotonic() >= warm:
                    frames += n
                    batches += 1
                    fulls += n == full
            time.sleep(0.001)
        return frames / seconds, batches, fulls, ""
    finally:
        master.stop()
        master.join(10)
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bridge", required=True)
    ap.add_argument("--runtime", required=True, help="the pinned runtime's source")
    args = ap.parse_args()

    plugins = os.path.join(os.path.abspath(args.runtime), "core", "src", "drivers", "plugins", "python")
    sys.path.insert(0, plugins)
    from modbus_master import modbus_master_plugin as mm  # noqa: E402  (the runtime's own)
    from shared import PluginLogger  # noqa: E402
    from shared.plugin_config_decode.modbus_master_config_model import ModbusMasterConfig  # noqa: E402

    work = tempfile.mkdtemp(prefix="canworks-openplc-modbus.")
    bridge = None
    threads = []
    try:
        print("== config", flush=True)
        for name in ("rtd8.eds", "dio16.eds", "simulation.json"):
            shutil.copy(os.path.join(EXAMPLE, name), work)
        # A 1024-byte string on the digital node for the long SDO read.
        with open(os.path.join(work, "dio16.eds"), encoding="utf-8") as f:
            eds = f.read()
        eds = eds.replace("[ManufacturerObjects]\nSupportedObjects=2\n",
                          "[ManufacturerObjects]\nSupportedObjects=3\n3=0x2100\n", 1)
        eds += ("\n[2100]\nParameterName=Long text\nObjectType=0x7\nDataType=0x0009\nAccessType=ro\n"
                "DefaultValue=%s\nPDOMapping=0\n" % LONG_TEXT)
        with open(os.path.join(work, "dio16.eds"), "w", encoding="utf-8") as f:
            f.write(eds)
        with open(os.path.join(EXAMPLE, "canworks.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        del cfg["bridge"]
        cfg = openplc_config(cfg)
        port = free_port()
        cfg["bridge"].update({"listen": "127.0.0.1:%d" % port, "on_client_loss": "hold"})
        cfg["bridge"]["connections"][0]["poll_ms"] = 10
        # The mailbox steps run at the data poll; step 7 also tries the default.
        cfg["bridge"]["connections"][0]["mailbox_poll_ms"] = 10
        # The digital node copies its first output byte to its first input byte.
        sim_path = os.path.join(work, "simulation.json")
        with open(sim_path, encoding="utf-8") as f:
            sim = json.load(f)
        sim["networks"]["field"]["nodes"].setdefault("6", {}).setdefault("sources", {})["0x6000:1"] = {"expr": "[0x6200:1]"}
        with open(sim_path, "w", encoding="utf-8") as f:
            json.dump(sim, f, indent=2)
        cfg_path = os.path.join(work, "canworks.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        r = subprocess.run([args.bridge, "--config", cfg_path, "--check-only"], capture_output=True, text=True)
        check(r.returncode == 0, "the bridge accepts the config" + ("" if r.returncode == 0 else ": " + r.stdout + r.stderr))

        rows = {row["name"]: row for row in json.loads(modbusmap.to_json(cfg, modbusmap.register_map(cfg)))["registers"]}
        decls = editorproject.declarations(cfg, cfg_path)
        remote = openplcmodbus.remote_device(cfg, decls, IEC_BASE)
        conf_path = os.path.join(work, "modbus_master.json")
        with open(conf_path, "w", encoding="utf-8") as f:
            json.dump(master_config(remote), f, indent=2)
        groups = remote["modbusTcpConfig"]["ioGroups"]
        print("    %d groups, %s" % (len(groups), openplcmodbus.requests_text(
            openplcmodbus.layout(cfg, decls, IEC_BASE)[0], openplcmodbus.settings(cfg))), flush=True)
        model = ModbusMasterConfig()
        model.import_config_from_file(conf_path)
        model.validate()
        check(len(model.devices) == 1, "the runtime reads the editor's modbus_master.json")
        hash_ = modbusmap.map_hash(cfg)

        print("== bridge and the runtime's Modbus master", flush=True)
        log = open(os.path.join(work, "bridge.log"), "w")
        bridge = subprocess.Popen([args.bridge, "--config", cfg_path], stdout=log, stderr=subprocess.STDOUT)
        image = Image(conf_path)
        plc = Plc(image, remote)
        logger = PluginLogger("MODBUS_MASTER", None)

        def start_plc():
            t = mm.ModbusSlaveDevice(model.devices[0], image, logger)
            t.start()
            threads.append(t)
            return t

        def stop_plc(t):
            # A PLC stop as runtime v4.3.1 does it: %Q zeroed, one more
            # round (it waits 500 ms), then stop_loop stops the threads.
            with image.lock:
                image.words["Q"] = {}
            time.sleep(0.5)
            t.stop()
            t.join(10)

        header = {0: 1, 1: hash_ >> 16, 2: hash_ & 0xFFFF}
        plc.put(header)
        master = start_plc()

        print("1. inputs", flush=True)
        check(wait(lambda: (plc.get(0) << 16 | plc.get(1)) == hash_), "the map hash 0x%08x reaches %%IW%d-%d"
              % (hash_, IEC_BASE, IEC_BASE + 1))
        check(wait(lambda: plc.byte(4) == 1), "the status block says running (state %d)" % plc.byte(4))
        rtd1 = rows["rtd.0x7130:1"]["address"]
        check(wait(lambda: 200 <= plc.get(rtd1) <= 260), "the simulated rtd value comes in (%d)" % plc.get(rtd1))
        counter = plc.get(3)
        check(wait(lambda: plc.get(3) != counter, 2.0), "the bridge's alive counter moves")

        print("2. outputs", flush=True)
        out_row, in_row = rows["dio.0x6200:1"], rows["dio.0x6000:1"]
        plc.put(set_byte({}, out_row["byte"], 0x5A, lambda reg: 0))
        check(wait(lambda: plc.byte(in_row["byte"]) == 0x5A), "an output byte reaches the node and comes back as its "
              "input (%#x)" % plc.byte(in_row["byte"]))
        sdo_q = int(cfg["bridge"]["sdo_bridge_location"]["request"][3:])
        sdo_i = int(cfg["bridge"]["sdo_bridge_location"]["response"][3:])
        # Request: counter, command 1 read, network 0, node 6, sub 1, index 0x6200.
        plc.put({sdo_q // 2: 1, sdo_q // 2 + 1: 0x0100, sdo_q // 2 + 2: 0x0601, sdo_q // 2 + 3: 0x6200})
        check(wait(lambda: plc.get(sdo_i // 2) == 1 and plc.byte(sdo_i + 2) == 2),
              "an SDO read through the PLC link's SDO registers ends done (status %d)" % plc.byte(sdo_i + 2))
        value = plc.get(sdo_i // 2 + 4) << 16 | plc.get(sdo_i // 2 + 5)
        check(value == 0x5A, "it reads the output from the node (%#x)" % value)

        print("3. the function blocks' mailboxes", flush=True)
        # What CO_SDO_READ_BYTES and CAN_RECEIVE write and read (bridge-plc-blocks).
        mb = cfg["bridge"]["mailboxes"]
        rsp, req = int(mb["input_location"][3:]) // 2, int(mb["output_location"][3:]) // 2
        rx, ack = rsp + 72, req + 72  # one request mailbox, then the receive mailbox
        # SDO_READ (op 3) on network 0: node 6 sub 1, index 0x6200, kind 3 (bytes), timeout 1000 ms.
        plc.put({req: 1, req + 1: 0x0300, req + 2: 0x0601, req + 3: 0x6200, req + 4: 0x0300, req + 5: 1000,
                 req + 6: 0, req + 7: 0})
        check(wait(lambda: plc.get(rsp) == 1 and plc.get(rsp + 1) >> 8 >= 2),
              "an SDO read through the request mailbox ends (state %d, ERROR_ID %d)"
              % (plc.get(rsp + 1) >> 8, plc.get(rsp + 1) & 0xFF))
        size = plc.get(rsp + 2) << 16 | plc.get(rsp + 3)
        check((plc.get(rsp + 1), size, plc.get(rsp + 8) >> 8) == (0x0200, 1, 0x5A),
              "it reads the output byte from the node (size %d, first byte %#x)" % (size, plc.get(rsp + 8) >> 8))
        # SDO_READ of the 1024-byte string (node 6 0x2100:0): its first 128
        # bytes in the answer, the rest in FETCHes (op 2, offset in A0).
        def text(n):
            return "".join(chr(plc.byte(2 * (rsp + 8) + i)) for i in range(n))

        plc.put({req: 3, req + 1: 0x0300, req + 2: 0x0600, req + 3: 0x2100, req + 4: 0x0300, req + 5: 2000,
                 req + 6: 0, req + 7: 0})
        t0 = time.monotonic()
        check(wait(lambda: plc.get(rsp) == 3 and plc.get(rsp + 1) >> 8 >= 2),
              "a 1024-byte SDO read through the request mailbox ends (state %d, ERROR_ID %d)"
              % (plc.get(rsp + 1) >> 8, plc.get(rsp + 1) & 0xFF))
        took = time.monotonic() - t0
        size = plc.get(rsp + 2) << 16 | plc.get(rsp + 3)
        got = text(128)
        call = 3
        for offset in range(128, 1024, 128):
            call += 1
            plc.put({req: call, req + 1: 0x0200, req + 2: offset})
            wait(lambda: plc.get(rsp) == call and plc.get(rsp + 1) >> 8 >= 2)
            got += text(128)
        check((plc.get(rsp + 1), size, got) == (0x0200, 1024, LONG_TEXT),
              "it reads all 1024 bytes in 8 parts (size %d, %d matching, %.0f ms for the read)"
              % (size, sum(a == b for a, b in zip(got, LONG_TEXT)), took * 1000))
        call += 1
        # RX_OPEN (op 8): a CAN receiver for the rtd node's TPDO 1 (0x185, mask 0x7FF).
        plc.put({req: call, req + 1: 0x0800, req + 2: 0x0100, req + 3: 0, req + 4: 0, req + 5: 0x185, req + 6: 0,
                 req + 7: 0x7FF})
        check(wait(lambda: plc.get(rsp) == call and plc.get(rsp + 1) == 0x0200), "a CAN receiver opens (state %d, "
              "ERROR_ID %d)" % (plc.get(rsp + 1) >> 8, plc.get(rsp + 1) & 0xFF))
        slot = plc.get(rsp + 2)

        def present():
            return (plc.get(rx + 1) << 16 | plc.get(rx + 2)) >> slot & 1

        check(wait(present, 5.0), "a batch in the receive mailbox carries the receiver's records")
        first = rx + 25
        check((plc.get(first) >> 8, plc.get(first) >> 4 & 0xF, plc.get(first + 3) << 16 | plc.get(first + 4))
              == (slot, 1, 0x185), "its first record is a CAN frame 0x185 (header %#06x)" % plc.get(first))
        seq = plc.get(rx)
        plc.put({ack: seq, ack + 1: 0, ack + 2: 0})
        check(wait(lambda: plc.get(rx) != seq, 5.0), "after the acknowledgement the next batch comes")

        print("4. the PLC stops", flush=True)
        stop_plc(master)
        time.sleep(0.5)
        check(plc.byte(in_row["byte"]) == 0x5A, "with on_client_loss hold the node keeps the last output, not the "
              "stop round's zeros (%#x)" % plc.byte(in_row["byte"]))
        log.flush()
        with open(log.name, encoding="utf-8", errors="replace") as f:
            held = "outputs held at their last values by the PLC link header (the PLC stopped)" in f.read()
        check(held, "the bridge took the stop from the header's running word")

        print("5. a PLC built for another map", flush=True)
        plc.put({0: 1, 1: (hash_ >> 16) ^ 1, 2: hash_ & 0xFFFF})
        plc.put(set_byte({}, out_row["byte"], 0x33, lambda reg: 0))
        master = start_plc()
        check(wait(lambda: plc.byte(4) == 4, 5.0), "the status block says map mismatch (state %d)" % plc.byte(4))
        time.sleep(0.5)
        check(plc.byte(in_row["byte"]) == 0x5A, "the bridge takes no output from it (%#x)" % plc.byte(in_row["byte"]))
        plc.put(header)
        check(wait(lambda: plc.byte(in_row["byte"]) == 0x33), "with the right hash its outputs go out again")
        stop_plc(master)

        print("6. with a J1939 network", flush=True)
        cfg5, path5 = with_j1939(work)
        r = subprocess.run([args.bridge, "--config", path5, "--check-only"], capture_output=True, text=True)
        check(r.returncode == 0, "the bridge accepts the config" + ("" if r.returncode == 0 else ": " + r.stdout + r.stderr))
        decls5 = editorproject.declarations(cfg5, path5)
        remote5 = openplcmodbus.remote_device(cfg5, decls5, IEC_BASE)
        regs = {("I" if g["functionCode"] == "4" else "Q", int(g["offset"]) + k)
                for g in remote5["modbusTcpConfig"]["ioGroups"] for k in range(g["length"])}
        j1939 = [it for it in modbusmap.collect(cfg5) if it.network == cfg5["networks"][-1]["name"]]
        missing = [it.name for it in j1939 if any((it.loc.area, b // 2) not in regs
                                                  for b in range(it.loc.index, it.loc.index + (it.nbytes or 1)))]
        check(bool(j1939) and not missing, "the remote device's registers hold the %d J1939 values%s"
              % (len(j1939), " (not: %s)" % ", ".join(missing) if missing else ""))
        conf5 = os.path.join(work, "modbus_master_j1939.json")
        with open(conf5, "w", encoding="utf-8") as f:
            json.dump(master_config(remote5), f, indent=2)
        model5 = ModbusMasterConfig()
        model5.import_config_from_file(conf5)
        model5.validate()
        check(len(model5.devices) == 1, "the runtime reads its modbus_master.json")

        print("7. the receive rate", flush=True)
        for blocks, mpoll, least in ((1, 10, 400), (2, 10, 900), (1, None, 70)):
            fps, batches, fulls, why = receive_rate(args.bridge, cfg, work, mm, ModbusMasterConfig, logger, blocks,
                                                    mailbox_poll=mpoll)
            check(batches > 0 and fulls >= batches - 1 and fps >= least,
                  "%d receive block(s): %.0f frames/s at the 10 ms poll and %s mailbox poll, %d of %d batches full "
                  "(%d records), at least %d expected%s"
                  % (blocks, fps, "%d ms" % mpoll if mpoll else "the default", fulls, batches,
                     mailboxlayout.records_per_batch("can", blocks), least, ": " + why if why else ""))
    finally:
        for t in threads:
            t.stop()
        if bridge:
            bridge.terminate()
            try:
                bridge.wait(10)
            except subprocess.TimeoutExpired:
                bridge.kill()
        if FAILS and os.path.exists(os.path.join(work, "bridge.log")):
            with open(os.path.join(work, "bridge.log")) as f:
                print("== bridge log\n" + f.read()[-4000:])
        shutil.rmtree(work, ignore_errors=True)
    print("%d failed" % len(FAILS) if FAILS else "all passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
