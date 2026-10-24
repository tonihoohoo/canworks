"""The Devices workspace's operations for the configurator's server: one
Devices object per configurator, SSH connections kept for two minutes after
their last use (so a probe, a start and the job's log need one login), and
every password used in the one call that gets it."""

import hashlib
import json
import os
import shutil
import tempfile
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait as _wait

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


def summary(instances, own=None):
    """One line on a device's bridge instances for the device list: the open
    project's, else the running ones by name and how many are stopped."""
    if own and any(i.get("name") == own for i in instances):
        return "This project's bridge"
    running = [i["name"] for i in instances if i.get("state") == "active"]
    stopped = len(instances) - len(running)
    if running:
        return " · ".join(["%s running" % ", ".join(running)] + (["%d stopped" % stopped] if stopped else []))
    if stopped:
        return "%d bridge%s stopped" % (stopped, "" if stopped == 1 else "s")
    return ""


def _resolve(host):
    try:
        return {a[4][0] for a in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)}
    except (OSError, UnicodeError):
        return set()


def not_saved(found, hosts, resolve=_resolve, timeout=1.0):
    """The discovered devices (online.runtimes_list's {name, addresses}) that
    are not in the device list: a device saved by its name (plc1.local, or
    the advertised name itself) or by any of its addresses is left out, and
    so is one a saved name resolves to, looked up within `timeout` seconds."""
    def bare(h):
        h = h.lower().rstrip(".")
        return h[:-6] if h.endswith(".local") else h
    names = {bare(h) for h in hosts if h}
    known = {h.strip("[]") for h in hosts if h}
    pool = ThreadPoolExecutor(max_workers=max(1, min(8, len(names))))
    try:
        futs = [pool.submit(resolve, h) for h in hosts if h]
        done, _ = _wait(futs, timeout=timeout)
        for f in done:
            known |= f.result()
    finally:
        pool.shutdown(wait=False)
    return [r for r in found if bare(r.get("name") or "") not in names
            and not known.intersection(r.get("addresses") or [])]


class Devices:
    def __init__(self, settings_folder, paths=None, probe_env=None, latest=None):
        self.store = store_mod.Store(settings_folder)
        self.paths = paths or jobs.Paths()
        self.probe_env = probe_env or {}  # the tests' fake device
        self._latest = latest  # the tests' newest release (a function)
        self.conns = {}
        self.lock = threading.Lock()
        self.running = {}  # device -> job id seen running by this configurator
        # Whether this PC keeps the token of the adapter server at (host, port):
        # the configurator's online.json (set by the server).
        self.has_token = lambda host, port: False

    def tokens(self, host, probe):
        """The ports of the device's adapter servers this PC has a token for."""
        return {a.get("port") for a in (probe or {}).get("adapters") or []
                if isinstance(a, dict) and self.has_token(host, a.get("port"))}

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

    def view(self, target, instance, config_path, pc_version, own_host=None, networks=None):
        """The device list: every device of this PC, each with one line on
        its bridge instances from its last probe (`summary`), the open
        project's own devices first (its runtime host `own_host`, its bridge
        `instance`)."""
        out = []
        sha = file_sha256(config_path) if config_path else None
        for d in self.store.devices():
            did = store_mod.device_id(d["host"], d.get("port"))
            item = {"id": did, "host": d["host"], "port": d.get("port") or 22, "user": d.get("user") or "",
                    "probe_at": d.get("probe_at"), "job": d.get("job"), "job_seconds": d.get("job_seconds")}
            if d.get("probe"):
                item["plan"] = plan_mod.plan(d["probe"], target, d.get("latest"), pc_version, instance, sha,
                                             networks, self.tokens(d["host"], d["probe"]))
                item["latest"] = d.get("latest")
            found = [i for i in ((d.get("probe") or {}).get("bridge") or {}).get("instances") or []
                     if isinstance(i, dict) and i.get("name")]
            bridges = [i["name"] for i in found]
            item["summary"] = summary(found, instance)
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
              refresh=False, networks=None):
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
               "plan": plan_mod.plan(probe, target, latest, pc_version, instance, sha, networks,
                                     self.tokens(self.store.get(did)["host"], probe)),
               "offer_key_login": by_password}
        return out

    def key_login(self, did):
        conn, _ = self.connection(did)
        ssh.add_key_login(conn, ssh.own_public_key(self.store))

    # -- jobs -------------------------------------------------------------
    def adapter_options(self, dev, probe, action, options):
        """The remote CAN adapter job's settings: the dialog's (adapter_on,
        adapter_change) or the server's own as the probe read them."""
        if action in ("adapter_on", "adapter_change"):
            out = {k: options.get(k) for k in ("adapter", "bitrate_kbit", "port")}
            out["allow_changes"] = options.get("allow_changes") is not False
            out["discovery"] = options.get("discovery") is not False
        else:
            a = next((x for x in probe.get("adapters") or [] if isinstance(x, dict)
                      and x.get("adapter") == options.get("adapter")), None)
            if not a:
                raise SshError("the device has no remote CAN adapter on %s: check it again" % options.get("adapter"))
            out = {"adapter": a["adapter"], "bitrate_kbit": a.get("bitrate_kbit"), "port": a.get("port"),
                   "allow_changes": bool(a.get("allow_changes")), "discovery": bool(a.get("discovery"))}
        if action == "adapter_on" and any(x.get("adapter") == out["adapter"]
                                          for x in probe.get("adapters") or [] if isinstance(x, dict)):
            raise SshError("%s is served already: use Change…" % out["adapter"])
        out["user"] = dev.get("user") or ""
        if action != "adapter_off" and (probe.get("sudo") == "none" or out["user"] in ("", "root")):
            raise SshError("The remote CAN adapter runs as the SSH user, never as root: log in as a user with "
                           "sudo rights.")
        return out

    def start(self, did, action, options, sudo_password, instance=None, config_dir=None, verifier=None):
        dev = self.store.get(did)
        probe = dev.get("probe") or {}
        version = dev.get("latest")
        if action not in jobs.ACTIONS:
            raise SshError("unknown action %r" % (action,))
        if action.startswith("uninstall") or action == "remove_all":
            version = version or (probe.get("bridge") or {}).get("version")
            if not plan_mod.version_tuple(version):
                raise SshError("the newest release could not be found, and the uninstall runs that release's scripts")
        else:
            why = plan_mod.blocked(probe, version)
            if why:
                raise SshError(why)
        options = options or {}
        adapter = {}
        if action in jobs.ADAPTER_ACTIONS:
            adapter = self.adapter_options(dev, probe, action, options)
            if action in ("adapter_on", "adapter_token") and not verifier:
                raise SshError("the token's verifier is missing")
            # Checked before anything goes to the device.
            jobs.adapter_commands(action, version, self.paths, upload="/tmp/canworks-bridge-upload.check", **adapter)
        conn, _ = self.connection(did)
        upload = None
        if action in ("adapter_on", "adapter_token"):
            # Only the verifier goes to the device; the token stays on this PC.
            tmp = tempfile.mkdtemp(prefix="canworks-verifier-")
            try:
                path = os.path.join(tmp, "verifier")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(verifier + "\n")
                upload = jobs.make_upload_dir(conn)
                conn.put_files(upload, [path])
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        if action in jobs.BRIDGE_ACTIONS and config_dir:
            files = config_files(config_dir)
            upload = jobs.make_upload_dir(conn)
            conn.put_files(upload, files)
        link = options.get("link") is not False
        if action == "install_bridge" and probe.get("link") is not None \
                and not (probe.get("link_config") or "").startswith("/etc/canworks-bridge/"):
            link = False  # the device's link serves another config: not repointed at a bridge
        discovery = options.get("discovery") is not False
        link_config = runtime_port = None
        if action.startswith("link_") or action.startswith("discovery_"):
            # The link's switches keep the other one as the device has it.
            discovery = probe.get("discovery") is True
            pick = options.get("link_instance") if isinstance(options.get("link_instance"), str) else instance
            serves = plan_mod.link_serves(probe, pick) or {}
            if action == "discovery_on" and serves.get("choose"):
                serves = plan_mod.link_serves(probe, serves["choose"][0])  # the advertisement names no instance
            if action in ("link_on", "discovery_on") and not serves.get("config"):
                raise SshError("which bridge config should the link serve?" if serves.get("choose")
                               else "the device has no config for the link to serve: install the bridge first")
            link_config, runtime_port = serves.get("config"), serves.get("runtime_port")
        if action in jobs.ADAPTER_ACTIONS:
            discovery = adapter.pop("discovery")
        lines = jobs.commands(action, version, self.paths, link=link,
                              discovery=discovery, purge=options.get("purge") is True,
                              adapters=bool(probe.get("adapters")), **adapter,
                              link_config=link_config, runtime_port=runtime_port,
                              instance=instance if action in jobs.BRIDGE_ACTIONS else None,
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

    def running_jobs(self):
        return [{"device": did, "job": job_id, "started": jobs.started_at(job_id)}
                for did, job_id in list(self.running.items())]
