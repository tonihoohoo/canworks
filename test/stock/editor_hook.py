#!/usr/bin/env python3
"""The CANopen editor hook (tools/editor-hook) against the upstream runtime's
own modules (canopen-editor-upload).

  editor_hook.py --runtime-dir <upstream runtime> [--canopen-check <exe>]

Loader (each in a fresh interpreter, with the hook installed the way its .pth
does it, before any runtime module is imported):
  - stock modules: update_plugin_configurations is patched, one "active" line
  - a runtime copy whose update_plugin_configurations, staged snapshot or
    plcapp_management module is gone: nothing patched, one error line

Uploads, in one interpreter like the webserver, following handle_upload_file
and the real run_compile with stub compile scripts:
  a) editor upload, snapshot with canworks/  -> enabled before SUCCESS, from the snapshot
  b) deploy-tool bundle (+ another snapshot) -> enabled with the uploaded config
  c) snapshot without canworks/               -> disabled
  d) no snapshot                             -> disabled
  e) a) with a failed build                  -> disabled, nothing taken from the snapshot
Exit status 0 when all hold.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOK_PATHS = [os.path.join(REPO, "tools", "editor-hook"), os.path.join(REPO, "tools", "deploy")]
RTD = os.path.join(REPO, "config", "rtd-sensor")
EDS = "rtd8.eds"


def canopen_entry(plugins_conf):
    with open(plugins_conf, encoding="utf-8") as f:
        for line in f:
            if line.startswith("canworks,"):
                name, path, enabled, ptype, config, *_ = line.rstrip("\n").split(",")
                return {"path": path, "enabled": enabled == "1", "config": config}
    return None


# --- Inputs -------------------------------------------------------------------

def zip_dir(src, out):
    with zipfile.ZipFile(out, "w") as z:
        for root, _, files in os.walk(src):
            for f in files:
                p = os.path.join(root, f)
                z.write(p, os.path.relpath(p, src))
    return out


def make_inputs(work):
    sys.path.insert(0, os.path.join(REPO, "tools", "deploy"))
    from tests.helpers import editor_bundle

    ethercat = {"slaves": []}
    plain = zip_dir(editor_bundle(os.path.join(work, "in", "plain"), {"ethercat.json": ethercat}),
                    os.path.join(work, "in", "plain.zip"))
    editor_bundle(os.path.join(work, "in", "src"), {"ethercat.json": ethercat})
    deployed = os.path.join(work, "in", "deployed.zip")
    subprocess.run([sys.executable, "-m", "canworks", "--bundle", os.path.join(work, "in", "src"),
                    "--config", os.path.join(REPO, "config", "pingpong", "canopen_config.json"),
                    "--check-only", "--output", deployed],
                   env=dict(os.environ, PYTHONPATH=os.path.join(REPO, "tools", "deploy")),
                   check=True, stdout=subprocess.DEVNULL)

    with open(os.path.join(RTD, "canopen_config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    with open(os.path.join(RTD, EDS), "rb") as f:
        eds = f.read()

    def snapshot(name, files):
        path = os.path.join(work, "in", name)
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("project.json", "{}")
            z.writestr("devices/configuration.json", "{}")
            for n, data in files.items():
                z.writestr(n, data)
        return path

    with_canopen = snapshot("with-canopen.zip", {"canworks/canworks.json": json.dumps(cfg), "canworks/" + EDS: eds})
    without = snapshot("without-canopen.zip", {})
    return {"plain": plain, "deployed": deployed, "snap_canopen": with_canopen, "snap_plain": without}


def runtime_copy(runtime, work, name, edit):
    """A copy of the runtime's webserver package with one file changed."""
    root = os.path.join(work, name)
    shutil.copytree(os.path.join(runtime, "webserver"), os.path.join(root, "webserver"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    edit(os.path.join(root, "webserver"))
    return root


def replace_in(path, old, new):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if old not in text:
        raise SystemExit("FAIL: test setup: %r not in %s" % (old, path))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))


# --- Child: runs inside a fresh interpreter -------------------------------------

def child_env(work):
    os.environ.setdefault("OPENPLC_RUNTIME_DIR", os.path.join(work, "state", "run"))
    os.environ.setdefault("OPENPLC_PERSISTENT_DATA_DIR", os.path.join(work, "state", "data"))


def child_loader(args):
    import importlib
    child_env(args.work)
    import canworks_hook  # what canworks_hook.pth runs
    canworks_hook.install()
    sys.path.insert(0, args.runtime_dir)
    if args.find_spec_only:
        importlib.util.find_spec("webserver.app")
        print(json.dumps({"patched": False}))
        return 0
    import webserver.plcapp_management as pm
    try:
        from webserver.plcapp_management import update_plugin_configurations  # as app.py does
    except ImportError:
        update_plugin_configurations = None
    print(json.dumps({"patched": getattr(getattr(pm, "update_plugin_configurations", None),
                                         "_canworks_hook", False),
                      "imported_name_patched": getattr(update_plugin_configurations,
                                                       "_canworks_hook", False)}))
    return 0


class StubRuntimeManager:
    def stop_plc(self):
        return "OK"

    def status_plc(self):
        return "STATUS:STOPPED"

    def reset_crash_tracking(self):
        pass


def child_uploads(args):
    child_env(args.work)
    import canworks_hook
    canworks_hook.install()
    sys.path.insert(0, args.runtime_dir)
    import webserver.plcapp_management as pm
    from webserver import project_snapshot
    from webserver.plcapp_management import (BuildStatus, analyze_zip, apply_retain_conf, apply_vpp_plugin_conf,
                                             build_state, run_compile, safe_extract, update_plugin_configurations)
    inputs = json.loads(args.inputs)

    work = os.path.join(args.work, "runtime")
    os.makedirs(os.path.join(work, "scripts"))
    os.makedirs(os.path.join(work, "lib"))
    os.chdir(work)
    lib = os.path.join(work, "lib", "libcanworks_plugin.so")
    with open("plugins.conf", "w") as f:
        f.write("canworks,%s,0,1,%s,\n" % (lib, os.path.join(work, "lib", "canworks.json")))
    with open(os.path.join("scripts", "compile-clean.sh"), "w") as f:
        f.write("echo cleaned\n")

    # Records plugins.conf at the moment the status turns SUCCESS.
    at_success = {}

    class Watched(type(build_state)):
        def __setattr__(self, key, value):
            if key == "status" and value == BuildStatus.SUCCESS:
                at_success["canworks"] = canopen_entry("plugins.conf")
            super().__setattr__(key, value)

    build_state.__class__ = Watched

    def upload(program, snapshot, build_ok=True):
        """handle_upload_file, then run_compile on the same thread."""
        with open(os.path.join("scripts", "compile.sh"), "w") as f:
            f.write("echo building\nexit %d\n" % (0 if build_ok else 1))
        at_success.clear()
        build_state.clear()
        safe, valid = analyze_zip(program)
        assert safe, program
        extract = "core/generated"
        project_snapshot.clear()
        shutil.rmtree(extract, ignore_errors=True)
        safe_extract(program, extract, valid)
        apply_vpp_plugin_conf(extract)
        apply_retain_conf(extract)
        update_plugin_configurations(extract)
        if snapshot:
            with open(snapshot, "rb") as f:
                project_snapshot.stage(f.read(), project_snapshot.normalize_metadata(
                    {"formatVersion": 1, "projectName": "rtd-monitor"}))
        build_state.status = BuildStatus.COMPILING
        run_compile(StubRuntimeManager(), cwd=extract)
        return {"status": build_state.status.name, "canworks": canopen_entry("plugins.conf"),
                "at_success": at_success.get("canworks"), "logs": list(build_state.logs),
                "conf": sorted(os.path.relpath(os.path.join(r, n), extract)
                               for r, _, files in os.walk(os.path.join(extract, "conf")) for n in files),
                "lib_config": open(os.path.join(work, "lib", "canworks.json")).read()
                if os.path.exists(os.path.join(work, "lib", "canworks.json")) else None}

    results = {}
    for name, program, snapshot, ok in (("a", "plain", "snap_canopen", True),
                                         ("c", "plain", "snap_plain", True),
                                         ("b", "deployed", "snap_canopen", True),
                                         ("e", "plain", "snap_canopen", False),
                                         ("a2", "plain", "snap_canopen", True),
                                         ("d", "plain", None, True)):
        results[name] = upload(inputs[program], inputs[snapshot] if snapshot else None, ok)
        results[name]["generated_conf"] = os.path.abspath(os.path.join("core", "generated", "conf"))
        if name == "a" and args.canopen_check:
            e = results[name]["canworks"]
            env = dict(os.environ, CANWORKS_GENERATED_CONF=results[name]["generated_conf"])
            r = subprocess.run([args.canopen_check, "--no-dcfgen", e["config"]], env=env,
                               capture_output=True, text=True)
            results[name]["check"] = {"code": r.returncode, "out": r.stdout + r.stderr}
    print(json.dumps(results))
    return 0


# --- Parent ---------------------------------------------------------------------

def run_child(args, work, *extra, runtime=None):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(HOOK_PATHS),
               CANWORKS_PYTHON=sys.executable)
    cmd = [sys.executable, __file__, "--child", "--runtime-dir", runtime or args.runtime_dir, "--work", work]
    if args.canopen_check:
        cmd += ["--canopen-check", args.canopen_check]
    p = subprocess.run(cmd + list(extra), env=env, capture_output=True, text=True)
    hook_lines = [l for l in p.stderr.splitlines() if l.startswith("[canworks editor hook]")]
    if p.returncode != 0:
        print(p.stdout + p.stderr)
        raise SystemExit("FAIL: child exited with %d" % p.returncode)
    return json.loads(p.stdout.strip().splitlines()[-1]), hook_lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-dir", required=True)
    ap.add_argument("--canopen-check")
    ap.add_argument("--child", action="store_true")
    ap.add_argument("--work")
    ap.add_argument("--inputs")
    ap.add_argument("--find-spec-only", action="store_true")
    args = ap.parse_args()
    args.runtime_dir = os.path.abspath(args.runtime_dir)
    if args.canopen_check:
        args.canopen_check = os.path.abspath(args.canopen_check)
    if args.child:
        return child_uploads(args) if args.inputs else child_loader(args)

    work = tempfile.mkdtemp(prefix="editor-hook-")
    failures = []

    def expect(cond, what):
        print("    %s %s" % ("ok  " if cond else "FAIL", what))
        if not cond:
            failures.append(what)

    print("loader:")
    n = [0]

    def loader(name, runtime=None, *extra):
        n[0] += 1
        return run_child(args, os.path.join(work, "loader%d" % n[0]), *extra, runtime=runtime)

    out, lines = loader("stock")
    expect(out["patched"] and out["imported_name_patched"], "stock runtime: patched, also the name app.py imports")
    expect(len(lines) == 1 and "INFO: active" in lines[0], "stock runtime: one 'active' line %s" % lines)

    broken = {
        "update_plugin_configurations is missing": lambda d: replace_in(
            os.path.join(d, "plcapp_management.py"), "def update_plugin_configurations(", "def renamed_function("),
        "no longer takes generated_dir": lambda d: replace_in(
            os.path.join(d, "plcapp_management.py"), "def update_plugin_configurations(generated_dir",
            "def update_plugin_configurations(gen_dir"),
        "_STAGED_BLOB": lambda d: replace_in(os.path.join(d, "project_snapshot.py"), "_STAGED_BLOB", "_STAGED_ZIP"),
    }
    for i, (reason, edit) in enumerate(broken.items()):
        rt = runtime_copy(args.runtime_dir, work, "broken%d" % i, edit)
        out, lines = loader("broken", rt)
        expect(not out["patched"], "runtime without %s: not patched" % reason)
        expect(len(lines) == 1 and "ERROR: inactive" in lines[0] and reason in lines[0],
               "runtime without %s: one error naming it %s" % (reason, lines))
    rt = runtime_copy(args.runtime_dir, work, "nomodule",
                      lambda d: os.remove(os.path.join(d, "plcapp_management.py")))
    out, lines = loader("nomodule", rt, "--find-spec-only")
    expect(len(lines) == 1 and "ERROR: inactive" in lines[0] and "webserver.plcapp_management not found" in lines[0],
           "runtime without plcapp_management: one error at app start %s" % lines)

    print("uploads:")
    inputs = make_inputs(work)
    r, lines = run_child(args, os.path.join(work, "uploads"), "--inputs", json.dumps(inputs))
    expect(len(lines) == 1, "one hook line in the webserver log %s" % lines)

    def log_has(res, text):
        return any(text in l for l in res["logs"])

    for name in ("a", "a2"):
        a = r[name]
        expect(a["status"] == "SUCCESS", "%s: build SUCCESS" % name)
        expect(a["at_success"] and a["at_success"]["enabled"], "%s: canopen enabled when status turned SUCCESS" % name)
        expect(log_has(a, "[INFO] CANopen: config taken from the project snapshot (canworks/canworks.json, 1 EDS file)"),
               "%s: build log names the snapshot" % name)
        expect(sorted(a["conf"]) == ["conf/canworks.json", "conf/canworks/eds/" + EDS, "conf/ethercat.json"],
               "%s: conf/ holds the config and EDS %s" % (name, a["conf"]))
        expect(a["lib_config"] and json.loads(a["lib_config"])["nodes"][0]["eds"] == "canworks/eds/" + EDS,
               "%s: config next to the library names canworks/eds/%s" % (name, EDS))
    if "check" in r["a"]:
        c = r["a"]["check"]
        expect(c["code"] == 0 and os.path.join(r["a"]["generated_conf"], "canworks", "eds") in c["out"],
               "a: canopen_check loads the config with its EDS from core/generated/conf")
        if c["code"] != 0:
            print(c["out"])

    b = r["b"]
    deployed_cfg = json.loads(zipfile.ZipFile(inputs["deployed"]).read("conf/canworks.json"))
    expect(b["status"] == "SUCCESS" and b["canworks"]["enabled"], "b: canopen enabled")
    expect(json.loads(b["lib_config"]) == deployed_cfg, "b: with the uploaded config, not the snapshot's")
    expect(not log_has(b, "config taken from the project snapshot")
           and log_has(b, "the upload carries conf/canworks.json"), "b: snapshot not used")

    c = r["c"]
    expect(c["status"] == "SUCCESS" and not c["canworks"]["enabled"], "c: canopen disabled")
    expect(log_has(c, "Disabled plugin 'canworks' (no config file found)"), "c: log says no config was found")
    expect(not any("CANopen:" in l for l in c["logs"]), "c: no hook messages")

    e = r["e"]
    expect(e["status"] == "FAILED" and not e["canworks"]["enabled"], "e: build FAILED, canopen disabled")
    expect(not log_has(e, "config taken from the project snapshot") and "conf/canworks.json" not in e["conf"],
           "e: nothing taken from the snapshot")

    d = r["d"]
    expect(d["status"] == "SUCCESS" and not d["canworks"]["enabled"], "d: no snapshot, canopen disabled")

    shutil.rmtree(work, ignore_errors=True)
    print("OK" if not failures else "%d failure(s)" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
