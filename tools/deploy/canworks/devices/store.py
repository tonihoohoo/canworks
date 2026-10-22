"""devices.json in the settings folder: each project folder's devices (host,
port, SSH user, last probe, last job) and nothing secret. The host keys this
PC trusts are in known_hosts next to it, the PC's own key in
canworks_ed25519."""

import json
import os
import re
import threading
import time

from ..userdirs import replace_file

FILE = "devices.json"
KNOWN_HOSTS = "known_hosts"
KEY = "canworks_ed25519"

_HOST = re.compile(r"^[A-Za-z0-9_.:%\[\]-]{1,253}$")
_USER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,31}$")
# What a device record may hold: anything else (a password above all) is dropped.
FIELDS = ("host", "port", "user", "probe", "probe_at", "latest", "job", "job_seconds", "added_at")


class DeviceError(ValueError):
    """A device setting refused; `field` names the field it is about."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


def device_id(host, port):
    return host if port in (None, 22) else "%s:%d" % (host, port)


def check_host(host):
    host = (host or "").strip()
    if not _HOST.match(host) or host.startswith("-"):
        raise DeviceError("Give the device's host name or address, such as line3.local or 192.168.1.20.", field="host")
    return host


def check_user(user):
    user = (user or "").strip()
    if user and not _USER.match(user):
        raise DeviceError("The SSH user name may have letters, digits, ., - and _ only.", field="user")
    return user


def check_port(port):
    if port in (None, ""):
        return 22
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise DeviceError("The SSH port is a number from 1 to 65535.", field="port")
    return port


class Store:
    lock = threading.Lock()

    def __init__(self, folder):
        self.folder = folder
        self.path = os.path.join(folder, FILE)

    @property
    def known_hosts(self):
        return os.path.join(self.folder, KNOWN_HOSTS)

    @property
    def key_path(self):
        return os.path.join(self.folder, KEY)

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _store(self, data):
        os.makedirs(self.folder, exist_ok=True)
        tmp = "%s.%d.%d.tmp" % (self.path, os.getpid(), threading.get_ident())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        replace_file(tmp, self.path)

    def devices(self, project):
        items = (self.load().get("projects") or {}).get(project) or []
        return [dict(d) for d in items if isinstance(d, dict) and d.get("host")]

    def get(self, project, did):
        for d in self.devices(project):
            if device_id(d["host"], d.get("port")) == did:
                return d
        raise DeviceError("no device %s in this project" % did)

    def add(self, project, host, user="", port=None):
        host, user, port = check_host(host), check_user(user), check_port(port)
        did = device_id(host, port)
        with self.lock:
            data = self.load()
            items = data.setdefault("projects", {}).setdefault(project, [])
            for d in items:
                if device_id(d.get("host"), d.get("port")) == did:
                    if user:
                        d["user"] = user
                    break
            else:
                items.append({"host": host, "port": port, "user": user, "added_at": time.time()})
            self._store(data)
        return did

    def update(self, project, did, **values):
        with self.lock:
            data = self.load()
            for d in (data.get("projects") or {}).get(project) or []:
                if device_id(d.get("host"), d.get("port")) == did:
                    for k, v in values.items():
                        if k not in FIELDS:
                            raise DeviceError("not a device field: %s" % k)
                        if v is None:
                            d.pop(k, None)
                        else:
                            d[k] = v
                    self._store(data)
                    return dict(d)
        raise DeviceError("no device %s in this project" % did)

    def remove(self, project, did):
        with self.lock:
            data = self.load()
            items = (data.get("projects") or {}).get(project) or []
            data.setdefault("projects", {})[project] = [
                d for d in items if device_id(d.get("host"), d.get("port")) != did]
            self._store(data)
