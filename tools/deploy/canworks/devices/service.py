"""The Devices workspace's operations for the configurator's server: one
Devices object per configurator, SSH connections kept for two minutes after
their last use (so a probe, a start and the job's log need one login), and
every password used in the one call that gets it."""

import hashlib
import json
import os
import threading
import time

from . import jobs, plan as plan_mod, release, ssh, store as store_mod
from .ssh import SshError

IDLE_CLOSE_S = 120.0
PROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "device-probe.sh")
MAX_UPLOAD = 50 << 20


def probe_text():
    with open(PROBE, "rb") as f:
        return f.read()


def config_files(folder):
    """The regular files next to canworks.json, as install-bridge.sh copies them."""
    files = [os.path.join(folder, n) for n in sorted(os.listdir(folder))
             if os.path.isfile(os.path.join(folder, n)) and not n.startswith(".")]
    if not any(os.path.basename(f) == "canworks.json" for f in files):
        raise SshError("save the config first: %s has no canworks.json" % folder)
    if sum(os.path.getsize(f) for f in files) > MAX_UPLOAD:
        raise SshError("the config folder %s holds more than 50 MB; move other files out of it" % folder)
    return files


def file_sha256(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


class Devices:
    def __init__(self, settings_folder, paths=None, probe_env=None, latest=None):
        self.store = store_mod.Store(settings_folder)
        self.paths = paths or jobs.Paths()
        self.probe_env = probe_env or {}  # the tests' fake device
        self._latest = latest  # the tests' newest release (a function)
        self.conns = {}
        self.lock = threading.Lock()
        self.running = {}  # device -> job id seen running by this configurator

    # -- connections ------------------------------------------------------
    def connection(self, did, password=None, trust=None):
        dev = self.store.get(did)
        key = did
        with self.lock:
            self._close_idle()
            item = self.conns.get(key)
            if item and item[0].alive and password is None and trust is None:
                self.conns[key] = (item[0], time.monotonic())
                return item[0], False
        conn = ssh.connect(self.store, dev["host"], dev.get("user") or "", dev.get("port") or 22,
                           password=password, trust=trust)
        with self.lock:
            old = self.conns.pop(key, None)
            if old:
                old[0].close()
            self.conns[key] = (conn, time.monotonic())
        return conn, password is not None

    def _close_idle(self):
        now = time.monotonic()
        for key, (conn, at) in list(self.conns.items()):
            if now - at > IDLE_CLOSE_S or not conn.alive:
                conn.close()
                del self.conns[key]

    def close_all(self):
        with self.lock:
            for conn, _ in self.conns.values():
                conn.close()
            self.conns.clear()

    # -- devices ----------------------------------------------------------
    def latest(self, conn=None, refresh=False):
        if self._latest:
            return self._latest()
        v = release.latest(refresh=refresh)
        if not v and conn is not None:
            v = release.latest_on_device(conn)
        return v

    def view(self, target, instance, config_path, pc_version, runtimes=None, own_host=None):
        """The device list: every device of this PC, each with what it is to
        which project ("Runtime of line3" from `runtimes`, host -> project
        names whose runtime host it is; "Bridge of packer" from its last
        probe), the open project's own devices first (its runtime host
        `own_host`, its bridge `instance`)."""
        out = []
        sha = file_sha256(config_path) if config_path else None
        runtimes = runtimes or {}
        for d in self.store.devices():
            did = store_mod.device_id(d["host"], d.get("port"))
            item = {"id": did, "host": d["host"], "port": d.get("port") or 22, "user": d.get("user") or "",
                    "probe_at": d.get("probe_at"), "job": d.get("job"), "job_seconds": d.get("job_seconds")}
            if d.get("probe"):
                item["plan"] = plan_mod.plan(d["probe"], target, d.get("latest"), pc_version, instance, sha)
                item["latest"] = d.get("latest")
            bridges = [i.get("name") for i in ((d.get("probe") or {}).get("bridge") or {}).get("instances") or []
                       if isinstance(i, dict) and i.get("name")]
            item["tags"] = ["Runtime of %s" % n for n in runtimes.get(d["host"], [])] + ["Bridge of %s" % n for n in bridges]
            item["mine"] = bool((own_host and own_host == d["host"]) or (instance and instance in bridges))
            out.append(item)
        # The open project's devices first; otherwise as added.
        out.sort(key=lambda i: not i["mine"])
        return out

    def add(self, host, user="", port=None):
        return self.store.add(host, user, port)

    def remove(self, did):
        with self.lock:
            item = self.conns.pop(did, None)
        if item:
            item[0].close()
        self.store.remove(did)

    def forget_key(self, did):
        dev = self.store.get(did)
        return ssh.forget_host_key(self.store, dev["host"], dev.get("port") or 22)

    def probe(self, did, target, instance, config_path, pc_version, password=None, trust=None,
              refresh=False):
        conn, by_password = self.connection(did, password=password, trust=trust)
        env = "".join("%s=%s " % (k, ssh.quote(v)) for k, v in sorted(self.probe_env.items()))
        try:
            status, out, err = conn.run(env + "sh -s", stdin=probe_text(), timeout=60.0)
        except ssh.ConnectionLost:
            # A kept connection the device or the network dropped: once more on a new one.
            if by_password or trust is not None:
                raise
            conn, by_password = self.connection(did)
            status, out, err = conn.run(env + "sh -s", stdin=probe_text(), timeout=60.0)
        try:
            probe = json.loads(out)
            if not isinstance(probe, dict) or probe.get("probe") != 1:
                raise ValueError
        except ValueError:
            raise SshError("the device's answer could not be read (%s)" % (err.strip()[-300:] or "no output"))
        latest = self.latest(conn, refresh=refresh)
        # The newest release goes with the probe, so the list shows the same plan later.
        self.store.update(did, probe=probe, probe_at=time.time(), latest=latest)
        job = probe.get("install_job") or {}
        key = did
        if job.get("state") in ("active", "activating"):
            self.running[key] = job.get("id")
        sha = file_sha256(config_path) if config_path else None
        out = {"probe": probe, "latest": latest,
               "plan": plan_mod.plan(probe, target, latest, pc_version, instance, sha),
               "offer_key_login": by_password}
        return out

    def key_login(self, did):
        conn, _ = self.connection(did)
        ssh.add_key_login(conn, ssh.own_public_key(self.store))

    # -- jobs -------------------------------------------------------------
    def start(self, did, action, options, sudo_password, instance=None, config_dir=None):
        dev = self.store.get(did)
        probe = dev.get("probe") or {}
        version = dev.get("latest")
        if action not in jobs.ACTIONS:
            raise SshError("unknown action %r" % (action,))
        if action.startswith("uninstall") or action == "remove_all":
            version = version or ((probe.get("plugin") or {}).get("version")) or ((probe.get("bridge") or {}).get("version"))
            if not plan_mod.version_tuple(version):
                raise SshError("the newest release could not be found, and the uninstall runs that release's scripts")
        else:
            why = plan_mod.blocked(probe, version)
            if why:
                raise SshError(why)
        conn, _ = self.connection(did)
        upload = None
        if action in ("install_bridge", "bridge_config") and config_dir:
            files = config_files(config_dir)
            upload = jobs.make_upload_dir(conn)
            conn.put_files(upload, files)
        options = options or {}
        link = options.get("link") is not False
        if action == "install_bridge" and probe.get("link") is not None \
                and not (probe.get("link_config") or "").startswith("/etc/canworks-bridge/"):
            link = False  # the device's link serves the PLC: not repointed at a bridge
        lines = jobs.commands(action, version, self.paths, link=link,
                              discovery=options.get("discovery") is not False, purge=options.get("purge") is True,
                              instance=instance if action in ("install_bridge", "bridge_config") else None,
                              upload=upload, bridge_prefix=(probe.get("bridge") or {}).get("prefix"))
        job_id = jobs.start(conn, probe.get("sudo"), sudo_password, action, lines, self.paths)
        self.store.update(did, job={"id": job_id, "action": action, "version": version})
        self.running[did] = job_id
        return job_id

    def follow(self, did, job_id, offset):
        conn, _ = self.connection(did)
        out = jobs.follow(conn, job_id, offset, self.paths)
        key = did
        done = out.get("found") and (out.get("exit") is not None or out.get("state") in ("inactive", "failed", ""))
        if done and not out.get("more"):
            if self.running.get(key) == job_id:
                self.running.pop(key, None)
            dev = self.store.get(did)
            last = dev.get("job") or {}
            if last.get("id") == job_id and not last.get("done"):
                # Seen to its end: the page shows it as the last job no more.
                self.store.update(did, job=dict(last, done=True, exit=out.get("exit")))
            start, end = jobs.started_at(job_id), out.get("ended")
            if start and end and out.get("exit") == 0:
                # Per action: the page shows it as the typical time of the next job of that kind.
                action = (dev.get("job") or {}).get("action") if (dev.get("job") or {}).get("id") == job_id else None
                if action:
                    seconds = dict(dev.get("job_seconds") or {}) if isinstance(dev.get("job_seconds"), dict) else {}
                    seconds[action] = max(0, end - start)
                    self.store.update(did, job_seconds=seconds)
            elif out.get("exit") != 0:
                out["failure"] = jobs.failure(conn, job_id, self.paths)
        out["done"] = bool(done and not out.get("more"))
        return out

    def stop(self, did, job_id, sudo_password):
        dev = self.store.get(did)
        conn, _ = self.connection(did)
        jobs.stop(conn, (dev.get("probe") or {}).get("sudo"), sudo_password, job_id, self.paths)

    def runtime_user(self, did, user, password):
        conn, _ = self.connection(did)
        jobs.create_runtime_user(conn, user, password)

    def running_jobs(self):
        return [{"device": did, "job": job_id, "started": jobs.started_at(job_id)}
                for did, job_id in list(self.running.items())]
