#!/usr/bin/env python3
"""node-red-canworks against the real canworks-bridge (nodered-blocks 4.3).

    test/nodered/run.py --bridge build/bin/canworks-bridge

The example bridge config with the mailboxes and Node-RED as a writer; its
two simulated CANopen nodes run inside the bridge, so no CAN interface is
needed. The PC tools write the flow; integration.js loads the package's
nodes on it (with the test harness in place of Node-RED) and starts,
restarts and stops the bridge itself. Needs node 18 or newer.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EXAMPLE = os.path.join(ROOT, "examples", "modbus-bridge")
sys.path.insert(0, os.path.join(ROOT, "tools", "deploy"))

from canworks import nodered  # noqa: E402

LONG_TEXT = "".join(chr(0x41 + i % 26) for i in range(1024))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bridge", required=True)
    args = ap.parse_args()
    work = tempfile.mkdtemp(prefix="canworks-nodered.")
    try:
        for name in ("rtd8.eds", "dio16.eds", "simulation.json"):
            shutil.copy(os.path.join(EXAMPLE, name), work)
        # A 1024-byte string on the digital node for the long SDO read.
        eds_path = os.path.join(work, "dio16.eds")
        with open(eds_path, encoding="utf-8") as f:
            eds = f.read()
        eds = eds.replace("[ManufacturerObjects]\nSupportedObjects=2\n",
                          "[ManufacturerObjects]\nSupportedObjects=3\n3=0x2100\n", 1)
        eds += ("\n[2100]\nParameterName=Long text\nObjectType=0x7\nDataType=0x0009\nAccessType=ro\n"
                "DefaultValue=%s\nPDOMapping=0\n" % LONG_TEXT)
        with open(eds_path, "w", encoding="utf-8") as f:
            f.write(eds)
        # The digital node copies its first output byte to its first input byte.
        sim_path = os.path.join(work, "simulation.json")
        with open(sim_path, encoding="utf-8") as f:
            sim = json.load(f)
        sim["networks"]["field"]["nodes"].setdefault("6", {}).setdefault("sources", {})["0x6000:1"] = {"expr": "[0x6200:1]"}
        with open(sim_path, "w", encoding="utf-8") as f:
            json.dump(sim, f, indent=2)
        with open(os.path.join(EXAMPLE, "canworks.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["bridge"].update({"listen": "127.0.0.1:%d" % free_port(), "writers": ["127.0.0.1"], "sdo_bridge_write": True,
                              "mailboxes": {"input_location": "%IB64", "output_location": "%QB64"}})
        cfg_path = os.path.join(work, "canworks.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        flow_path = os.path.join(work, "flow.json")
        nodered.export(cfg, flow_path, "integration")
        r = subprocess.run([args.bridge, "--config", cfg_path, "--check-only"], capture_output=True, text=True)
        if r.returncode:
            print("FAIL the bridge refuses the config:\n" + r.stdout + r.stderr)
            return 1
        rc = subprocess.call(["node", os.path.join(HERE, "integration.js"), os.path.abspath(args.bridge), cfg_path,
                              flow_path, LONG_TEXT])
        if rc:
            log = os.path.join(work, "bridge.log")
            if os.path.exists(log):
                with open(log, encoding="utf-8", errors="replace") as f:
                    print("---- bridge log (end)\n" + "".join(f.readlines()[-40:]))
        return rc
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
