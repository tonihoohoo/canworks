#!/usr/bin/env python3
"""Install Debian packages on a CI runner without waiting on a stalled mirror.

  apt_install.py [--no-install-recommends] [--timeout S] [--retries N] PACKAGE...

Packages that dpkg reports installed are left alone; when none is missing the
package lists are not refreshed and nothing is downloaded. Otherwise
`apt-get update` and `apt-get install` run as root under `timeout S` with short
network timeouts and retries inside apt. A failed or timed-out attempt is
retried (after `dpkg --configure -a`, in case it was stopped mid-install) up to
N more times. Exits non-zero when the last attempt fails.
"""

import argparse
import subprocess
import sys
import time

APT_OPTIONS = ["-o", "Acquire::http::Timeout=20", "-o", "Acquire::https::Timeout=20",
               "-o", "Acquire::Retries=3", "-o", "DPkg::Lock::Timeout=60"]


def installed(package, run=subprocess.run):
    r = run(["dpkg-query", "-W", "-f=${Status}", package], capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "install ok installed"


def missing(packages, run=subprocess.run):
    return [p for p in packages if not installed(p, run)]


def attempt_commands(packages, timeout, no_recommends):
    limit = ["sudo", "timeout", "-k", "10", str(timeout)]
    update = limit + ["apt-get", *APT_OPTIONS, "update", "-qq"]
    install = (limit + ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", *APT_OPTIONS, "install", "-y", "-qq"]
               + (["--no-install-recommends"] if no_recommends else []) + list(packages))
    return [update, install]


def install(packages, timeout=180, retries=1, no_recommends=False, run=subprocess.run, sleep=time.sleep):
    todo = missing(packages, run)
    if not todo:
        print(f"apt_install: already installed: {' '.join(packages)}", flush=True)
        return 0
    print(f"apt_install: installing {' '.join(todo)}", flush=True)
    for n in range(retries + 1):
        if n:
            print(f"apt_install: attempt {n} failed, retrying", flush=True)
            sleep(5)
            run(["sudo", "dpkg", "--configure", "-a"])
        start = time.monotonic()
        rc = 0
        for cmd in attempt_commands(todo, timeout, no_recommends):
            rc = run(cmd).returncode
            if rc:
                break
        print(f"apt_install: attempt {n + 1} {'ok' if rc == 0 else f'failed ({rc})'} "
              f"after {time.monotonic() - start:.0f} s", flush=True)
        if rc == 0:
            return 0
    return 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--no-install-recommends", action="store_true")
    p.add_argument("--timeout", type=int, default=180, help="seconds per apt-get call (default 180)")
    p.add_argument("--retries", type=int, default=1, help="attempts after the first (default 1)")
    p.add_argument("packages", nargs="+")
    a = p.parse_args(argv)
    return install(a.packages, a.timeout, a.retries, a.no_install_recommends)


if __name__ == "__main__":
    sys.exit(main())
