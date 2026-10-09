#!/usr/bin/env python3
"""Runs the stock runtime's own upload handling on deploy-tool bundles
(canopen-stock-install: "Enabled by uploads").

  upload_rules.py --runtime-dir <upstream runtime> --deployed <zip> --plain <zip> [--canopen-check <exe>]

For each zip, in a scratch copy of the runtime's working directory, it calls
the runtime's analyze_zip, safe_extract and update_plugin_configurations
(webserver/plcapp_management.py) exactly as /api/upload-file does, then reads
plugins.conf back:
  deployed bundle -> canopen enabled, canworks.json copied next to the library;
                     with --canopen-check, the copied config loads with its
                     EDS files from core/generated/conf/
  plain bundle    -> canopen disabled
Exit status 0 when both hold.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile


def canopen_entry(plugins_conf):
    with open(plugins_conf, encoding="utf-8") as f:
        for line in f:
            if line.startswith("canworks,"):
                name, path, enabled, ptype, config, *_ = line.rstrip("\n").split(",")
                return {"path": path, "enabled": enabled == "1", "type": ptype, "config": config}
    return None


def upload(pm, zip_path, workdir):
    """What handle_upload_file does with the zip, minus the compile."""
    pm.build_state.clear()
    safe, valid = pm.analyze_zip(zip_path)
    if not safe:
        raise SystemExit("FAIL: the runtime's analyze_zip rejects %s" % zip_path)
    extract = os.path.join("core", "generated")
    shutil.rmtree(extract, ignore_errors=True)
    pm.safe_extract(zip_path, extract, valid)
    pm.update_plugin_configurations(extract)
    for line in pm.build_state.logs:
        if "canworks" in line or "Found" in line:
            print("    runtime: " + line.rstrip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-dir", required=True)
    ap.add_argument("--deployed", required=True)
    ap.add_argument("--plain", required=True)
    ap.add_argument("--canopen-check")
    args = ap.parse_args()
    runtime = os.path.abspath(args.runtime_dir)
    deployed, plain = os.path.abspath(args.deployed), os.path.abspath(args.plain)
    check = os.path.abspath(args.canopen_check) if args.canopen_check else None

    work = tempfile.mkdtemp(prefix="upload-rules-")
    # The runtime's config module creates its state dirs (/var/run/runtime,
    # /var/lib/openplc-runtime) at import; keep them in scratch so this runs
    # without root.
    os.environ.setdefault("OPENPLC_RUNTIME_DIR", os.path.join(work, "state", "run"))
    os.environ.setdefault("OPENPLC_PERSISTENT_DATA_DIR", os.path.join(work, "state", "data"))
    sys.path.insert(0, runtime)
    import webserver.plcapp_management as pm  # noqa: E402  (the runtime's own code)

    os.chdir(work)
    shutil.copy(os.path.join(runtime, "plugins.conf"), "plugins.conf")
    before = canopen_entry("plugins.conf")
    if not before:
        raise SystemExit("FAIL: no canworks line in %s/plugins.conf (run scripts/install-stock.sh)" % runtime)
    print("installed: %s" % before)
    failures = 0

    print("upload of the deployed bundle:")
    upload(pm, deployed, work)
    e = canopen_entry("plugins.conf")
    expected_config = os.path.join(os.path.dirname(e["path"]), "canworks.json")
    print("    plugins.conf: %s" % e)
    if not e["enabled"] or e["config"] != expected_config or not os.path.isfile(expected_config):
        print("FAIL: canopen should be enabled with %s" % expected_config)
        failures += 1
    elif check:
        env = dict(os.environ, CANOPEN_GENERATED_CONF=os.path.join(work, "core", "generated", "conf"))
        r = subprocess.run([check, "--no-dcfgen", e["config"]], env=env, capture_output=True, text=True)
        print("    " + r.stdout.strip().replace("\n", "\n    "))
        if r.returncode != 0 or os.path.join(work, "core/generated/conf/canworks/eds") not in r.stdout:
            print("FAIL: the deployed config does not load with its EDS from core/generated/conf")
            failures += 1

    print("upload of a bundle without conf/canworks.json:")
    upload(pm, plain, work)
    e = canopen_entry("plugins.conf")
    print("    plugins.conf: %s" % e)
    if e["enabled"]:
        print("FAIL: canopen should be disabled")
        failures += 1

    shutil.rmtree(work, ignore_errors=True)
    print("OK" if not failures else "%d failure(s)" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
