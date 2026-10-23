#!/usr/bin/env python3
"""A PLC program on the local runtime, as the editor makes and uploads it
(test/local-runtime/run.sh, test/virtual-example/run.sh):

    program.py pingpong DIR           the ping-pong config as an OpenPLC
                                      through Modbus config in DIR
                                      (canworks.json, its EDS and simulation
                                      file, a diagnostics token), the
                                      editor's remote device (remote.json)
                                      and the program (project.st: the
                                      `canworks` list, canworks_in, a main
                                      that answers each pong with ping =
                                      pong + 1, canworks_out)
    program.py upload BUNDLE REMOTE   conf/modbus_master.json from the
                                      remote device (as the editor's Build
                                      writes it) added to the bundle of
                                      build_program.mjs, uploaded to the
                                      local runtime with the saved
                                      credentials; waits for the build and
                                      starts the PLC

Needs the PC tools (pip install tools/deploy).
"""

import base64
import hashlib
import hmac
import importlib.util
import io
import json
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TOKEN = "local-runtime-test"

from canworks import editorproject, localruntime, openplcmodbus, runtime  # noqa: E402
from canworks.configurator import server as srv  # noqa: E402

MAIN = """PROGRAM main
  VAR_EXTERNAL
    canworks : canworks_TYPE;
  END_VAR
  canworks.%s := canworks.%s + 1;
END_PROGRAM
"""


def verifier(token):
    """diag.token_verifier: SCRAM-SHA-256 (docs/diagnostics.md)."""
    salt = os.urandom(16)
    sp = hashlib.pbkdf2_hmac("sha256", token.encode(), salt, 4096)
    key = lambda name: hmac.new(sp, name, hashlib.sha256).digest()  # noqa: E731
    b = lambda x: base64.b64encode(x).decode()  # noqa: E731
    return "SCRAM-SHA-256$4096:%s$%s:%s" % (b(salt), b(hashlib.sha256(key(b"Client Key")).digest()),
                                           b(key(b"Server Key")))


def master_config(remote):
    """test/openplc_modbus/run.py's master_config (the editor's generator)."""
    spec = importlib.util.spec_from_file_location("openplc_modbus_run",
                                                  os.path.join(ROOT, "test", "openplc_modbus", "run.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.master_config(remote)


def with_external(st):
    head, rest = st.split("\n", 1)
    return "%s\n  VAR_EXTERNAL\n    canworks : canworks_TYPE;\n  END_VAR\n%s\n" % (head, rest)


def pingpong(work):
    src = os.path.join(ROOT, "config", "pingpong")
    for name in ("cpp-slave.eds", "simulation.json"):
        shutil.copy(os.path.join(src, name), work)
    with open(os.path.join(src, "canopen_config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    assert not cfg["networks"][0]["adapter"].get("simulate"), "the test needs a config with a real adapter"
    del cfg["bridge"]
    cfg = srv.Session().switch_target(cfg, "openplc_modbus")["config"]
    cfg["diagnostics"] = {"token_verifier": verifier(TOKEN)}
    path = os.path.join(work, "canworks.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    decls = editorproject.declarations(cfg, path)
    names = {d["name"] for d in decls}
    pong, ping = "pingpong_UNSIGNED32_sent_from_slave", "pingpong_UNSIGNED32_received_by_slave"
    assert {pong, ping} <= names, names
    with open(os.path.join(work, "remote.json"), "w", encoding="utf-8") as f:
        json.dump(openplcmodbus.remote_device(cfg, decls), f, indent=2)
    in_st, out_st = openplcmodbus.programs(cfg, decls)
    lst = openplcmodbus.global_list(decls)
    parts = ["TYPE canworks_TYPE :", "STRUCT"]
    parts += ["  %s : %s;" % (v["name"], v["type"]["value"]) for v in lst["variables"]]
    parts += ["END_STRUCT;", "END_TYPE", "", with_external(in_st), MAIN % (ping, pong), with_external(out_st),
              "CONFIGURATION config0\n  VAR_GLOBAL\n    canworks : canworks_TYPE;\n  END_VAR\n"
              "  RESOURCE res0 ON PLC\n    TASK task0(INTERVAL := T#20ms, PRIORITY := 0);\n"
              "    PROGRAM in0 WITH task0 : canworks_in;\n    PROGRAM main0 WITH task0 : main;\n"
              "    PROGRAM out0 WITH task0 : canworks_out;\n  END_RESOURCE\nEND_CONFIGURATION\n"]
    with open(os.path.join(work, "project.st"), "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


def upload(bundle, remote_path):
    with open(remote_path, encoding="utf-8") as f:
        remote = json.load(f)
    os.makedirs(os.path.join(bundle, "conf"), exist_ok=True)
    with open(os.path.join(bundle, "conf", "modbus_master.json"), "w", encoding="utf-8") as f:
        json.dump(master_config(remote), f, indent=2)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(bundle):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(root, name)
                z.write(full, os.path.relpath(full, bundle).replace(os.sep, "/"))
    saved = localruntime.target()
    client = runtime.Client("127.0.0.1:%d" % saved["port"], fingerprint=saved["fingerprint"])
    client.login(saved["user"], saved["password"])
    client.upload(data.getvalue())
    print("uploaded the program; the runtime builds it", flush=True)
    ok, logs = client.wait_for_build(lambda line: print("  " + line.rstrip(), flush=True))
    if not ok:
        raise SystemExit("the runtime's build failed")
    client.start_plc()
    print("the PLC is running", flush=True)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "pingpong":
        return pingpong(sys.argv[2])
    if len(sys.argv) == 4 and sys.argv[1] == "upload":
        return upload(sys.argv[2], sys.argv[3])
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
