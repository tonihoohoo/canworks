#!/usr/bin/env python3
"""OpenPLC through Modbus end to end (add-openplc-modbus-target 5.1): the
pinned OpenPLC runtime's own Modbus master plugin against canworks-bridge.

    test/openplc_modbus/run.py --bridge build/bin/canworks-bridge --runtime DIR

DIR is a checkout of the pinned runtime (docker/local-runtime/runtime-version);
its plugin needs pymodbus (its requirements.txt). The example's two simulated
CANopen nodes run inside the bridge, so no CAN interface is needed.

The PC tools turn the example into an OpenPLC through Modbus config and write
the editor's remote device; the remote device becomes conf/modbus_master.json
as the editor's Build does (generate-modbus-master-config.ts); the runtime's
ModbusSlaveDevice thread polls the bridge with it, on an in-memory process
image in place of the runtime's. The test plays the PLC program's part on
that image (the header canworks_out writes, the values) and checks:

1. inputs come in: the map hash, the status block and the simulated values;
2. outputs go out: an output byte reaches the simulated node and comes back
   as its input (the node's simulation copies 0x6200:1 to 0x6000:1), and an
   SDO read through the PLC link's SDO registers reads it from the node;
3. the PLC stops as the runtime stops it (%Q zeroed for one more round,
   then the plugin's threads stop): with on_client_loss "hold" the node
   keeps the last real output, not the zeros;
4. a PLC built for another map (wrong hash in the header): the bridge takes
   no output from it.
"""

import argparse
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

from canworks import editorproject, modbusmap, openplcmodbus  # noqa: E402
from canworks.configurator import server as srv  # noqa: E402

IEC_BASE = 100
FAILS = []


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
        with open(os.path.join(EXAMPLE, "canworks.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        del cfg["bridge"]
        cfg = srv.Session().switch_target(cfg, "openplc_modbus")["config"]
        port = free_port()
        cfg["bridge"].update({"listen": "127.0.0.1:%d" % port, "on_client_loss": "hold", "openplc": {"poll_ms": 10}})
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
        print("    %d groups, %d requests per poll" % (len(groups), len(groups)), flush=True)
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

        print("3. the PLC stops", flush=True)
        stop_plc(master)
        time.sleep(0.5)
        check(plc.byte(in_row["byte"]) == 0x5A, "with on_client_loss hold the node keeps the last output, not the "
              "stop round's zeros (%#x)" % plc.byte(in_row["byte"]))
        log.flush()
        with open(log.name, encoding="utf-8", errors="replace") as f:
            held = "outputs held at their last values by the PLC link header (the PLC stopped)" in f.read()
        check(held, "the bridge took the stop from the header's running word")

        print("4. a PLC built for another map", flush=True)
        plc.put({0: 1, 1: (hash_ >> 16) ^ 1, 2: hash_ & 0xFFFF})
        plc.put(set_byte({}, out_row["byte"], 0x33, lambda reg: 0))
        master = start_plc()
        check(wait(lambda: plc.byte(4) == 4, 5.0), "the status block says map mismatch (state %d)" % plc.byte(4))
        time.sleep(0.5)
        check(plc.byte(in_row["byte"]) == 0x5A, "the bridge takes no output from it (%#x)" % plc.byte(in_row["byte"]))
        plc.put(header)
        check(wait(lambda: plc.byte(in_row["byte"]) == 0x33), "with the right hash its outputs go out again")
        stop_plc(master)
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
