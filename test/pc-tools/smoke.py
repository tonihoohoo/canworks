#!/usr/bin/env python3
"""Runs the installed PC tools once each, as a user would after `uv tool install`.

Usage: smoke.py VERSION  (the commands must be on PATH)."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import http.cookiejar
import urllib.request

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONFIG = os.path.join(REPO, "config", "rtd-sensor", "canopen_config.json")


def tool(name):
    path = shutil.which(name)
    if not path:
        sys.exit("smoke: %s is not on PATH" % name)
    return path


def run(*args):
    print("$ " + " ".join(args), flush=True)
    r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    print(r.stdout, end="", flush=True)
    if r.returncode != 0:
        sys.exit("smoke: exit %d" % r.returncode)
    return r.stdout


def configurator(out):
    env = dict(os.environ, CANWORKS_CONFIG_DIR=os.path.join(out, "config-dir"))
    p = subprocess.Popen([tool("canworks-config"), "--no-browser"], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, universal_newlines=True, env=env)
    try:
        deadline = time.time() + 60
        url = None
        while time.time() < deadline and url is None:
            line = p.stdout.readline()
            if not line:
                break
            print(line, end="", flush=True)
            m = re.search(r"(http://127\.0\.0\.1:\d+/\?token=\S+)", line)
            url = m and m.group(1)
        if not url:
            sys.exit("smoke: the configurator printed no URL")
        # The URL sets the session cookie and redirects to /; no proxy for 127.0.0.1.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                             urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        with opener.open(url, timeout=30) as r:
            page = r.read().decode("utf-8")
        if r.status != 200 or "<html" not in page.lower():
            sys.exit("smoke: the configurator page did not load (%s)" % r.status)
        print("configurator page: %d bytes" % len(page), flush=True)
    finally:
        p.terminate()
        p.wait(30)


def main(argv):
    if len(argv) != 1:
        sys.exit(__doc__.strip())
    version = argv[0]
    out = tempfile.mkdtemp(prefix="pc-tools-smoke-")
    try:
        deploy = tool("canworks-deploy")
        for name in ("canworks-deploy", "canworks-config", "canworks-diag"):
            text = run(tool(name), "--version") if name != "canworks-diag" else run(tool(name), "--help")
            if name != "canworks-diag" and version not in text:
                sys.exit("smoke: %s is not version %s" % (name, version))
        run(deploy, "--config", CONFIG, "--export-dcf", os.path.join(out, "dcf"))
        if not os.path.isfile(os.path.join(out, "dcf", "node_5.dcf")):
            sys.exit("smoke: no node_5.dcf")
        run(deploy, "--config", CONFIG, "--export-dbc", os.path.join(out, "bus.dbc"))
        if os.path.getsize(os.path.join(out, "bus.dbc")) == 0:
            sys.exit("smoke: empty bus.dbc")
        configurator(out)
    finally:
        shutil.rmtree(out, ignore_errors=True)
    print("smoke: ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
