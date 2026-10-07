#!/usr/bin/env python3
"""Install Debian packages on a CI runner without waiting on a stalled mirror.

  apt_install.py [--debs DIR] [--no-install-recommends] [--timeout S] [--retries N] PACKAGE...

Packages that dpkg reports installed are left alone; when none is missing the
package lists are not refreshed and nothing is downloaded.

With --debs, DIR holds the .deb files of an earlier install (CI caches it per
runner image): they are installed with `dpkg -i`, without the network. When
that is not enough, or without --debs, `apt-get update` and `apt-get install`
run as root under `timeout S` with short network timeouts and retries inside
apt, keeping what they download in DIR for the cache. A failed or timed-out
attempt is retried (after `dpkg --configure -a`, in case it was stopped
mid-install) up to N more times. Exits non-zero when the last attempt fails.
"""

import argparse
import glob
import os
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


def limit(timeout):
    return ["sudo", "timeout", "-k", "10", str(timeout)]


def attempt_commands(packages, timeout, no_recommends, debs=None):
    keep = (["-o", f"Dir::Cache::Archives={debs}", "-o", "APT::Keep-Downloaded-Packages=true"]
            if debs else [])
    update = limit(timeout) + ["apt-get", *APT_OPTIONS, "update", "-qq"]
    install = (limit(timeout) + ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", *APT_OPTIONS, *keep,
                                 "install", "-y", "-qq", "-f"]
               + (["--no-install-recommends"] if no_recommends else []) + list(packages))
    return [update, install]


def from_debs(debs, timeout, run):
    files = sorted(glob.glob(os.path.join(debs, "*.deb")))
    if not files:
        return False
    start = time.monotonic()
    rc = run(limit(timeout) + ["env", "DEBIAN_FRONTEND=noninteractive", "dpkg", "-i", *files]).returncode
    print(f"apt_install: {len(files)} cached .deb files {'installed' if rc == 0 else f'failed ({rc})'} "
          f"in {time.monotonic() - start:.0f} s", flush=True)
    return rc == 0


def install(packages, timeout=180, retries=1, no_recommends=False, debs=None, run=subprocess.run,
            sleep=time.sleep):
    todo = missing(packages, run)
    if not todo:
        print(f"apt_install: already installed: {' '.join(packages)}", flush=True)
        return 0
    if debs:
        os.makedirs(os.path.join(debs, "partial"), exist_ok=True)
        if from_debs(debs, timeout, run):
            todo = missing(todo, run)
            if not todo:
                return 0
        else:
            run(["sudo", "dpkg", "--configure", "-a"])
    print(f"apt_install: installing {' '.join(todo)}", flush=True)
    for n in range(retries + 1):
        if n:
            print(f"apt_install: attempt {n} failed, retrying", flush=True)
            sleep(5)
            run(["sudo", "dpkg", "--configure", "-a"])
        start = time.monotonic()
        rc = 0
        for cmd in attempt_commands(todo, timeout, no_recommends, debs):
            rc = run(cmd).returncode
            if rc:
                break
        print(f"apt_install: attempt {n + 1} {'ok' if rc == 0 else f'failed ({rc})'} "
              f"after {time.monotonic() - start:.0f} s", flush=True)
        if rc == 0:
            if debs:
                run(["sudo", "chown", "-R", str(os.getuid()), debs])  # the cache step reads it as the runner user
            return 0
    return 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--debs", help="directory of cached .deb files (installed first, filled by apt)")
    p.add_argument("--no-install-recommends", action="store_true")
    p.add_argument("--timeout", type=int, default=120, help="seconds per apt-get or dpkg call (default 120)")
    p.add_argument("--retries", type=int, default=2, help="attempts after the first (default 2)")
    p.add_argument("packages", nargs="+")
    a = p.parse_args(argv)
    debs = os.path.abspath(os.path.expanduser(a.debs)) if a.debs else None
    return install(a.packages, a.timeout, a.retries, a.no_install_recommends, debs)


if __name__ == "__main__":
    sys.exit(main())
