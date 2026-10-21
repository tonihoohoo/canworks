"""SSH to a device from the configurator's own process (paramiko), the same on
Windows, macOS and Linux: the user's agent and keys, ~/.ssh/config aliases,
host keys trusted only after the user saw them (kept in the settings folder's
known_hosts, never replaced silently), a password only when no key works, and
this PC's own canworks key for key login."""

import base64
import getpass
import hashlib
import os
import posixpath
import shlex
import socket
import threading
import time

CONNECT_TIMEOUT_S = 10.0


class SshError(Exception):
    """A connection or command problem, said for people."""


class ConnectionLost(SshError):
    """A kept connection that died under a command: the caller may connect again."""


class NeedTrust(SshError):
    def __init__(self, host, fingerprint, key_type):
        super().__init__("%s is new to this PC. Its key is %s." % (host, fingerprint))
        self.fingerprint = fingerprint
        self.key_type = key_type


class KeyChanged(SshError):
    def __init__(self, host, fingerprint):
        super().__init__("The device's key changed (it now shows %s). If %s was reinstalled, forget its key "
                         "and connect again; otherwise do not connect." % (fingerprint, host))
        self.fingerprint = fingerprint


class NeedPassword(SshError):
    def __init__(self, user, host, wrong=False):
        super().__init__(("The password for %s@%s was not accepted." if wrong else
                          "No SSH key of this PC logs in to %s@%s: give the password.") % (user, host))
        self.wrong = wrong


def _paramiko():
    try:
        import paramiko
    except ImportError:
        raise SshError("the PC tools were installed without paramiko, which the Devices workspace needs: "
                       "install the PC tools with the one-line installer, or pip install paramiko")
    return paramiko


def fingerprint(key):
    """OpenSSH's SHA256 form of a host key: SHA256:base64 without padding."""
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def host_entry(host, port):
    return host if port == 22 else "[%s]:%d" % (host, port)


def resolve(host, user, port):
    """host, user, port and extra key files after ~/.ssh/config (Host aliases)."""
    paramiko = _paramiko()
    out = {"hostname": host, "user": user or "", "port": port or 22, "keys": []}
    path = os.path.expanduser("~/.ssh/config")
    if os.path.isfile(path):
        try:
            cfg = paramiko.SSHConfig.from_path(path).lookup(host)
        except Exception:  # a config paramiko cannot read: go on without it
            cfg = {}
        out["hostname"] = cfg.get("hostname") or host
        if not user and cfg.get("user"):
            out["user"] = cfg["user"]
        if port in (None, 22) and cfg.get("port"):
            try:
                out["port"] = int(cfg["port"])
            except ValueError:
                pass
        out["keys"] = [os.path.expanduser(k) for k in cfg.get("identityfile") or [] if os.path.isfile(os.path.expanduser(k))]
    out["user"] = out["user"] or getpass.getuser()
    return out


class Connection:
    """One logged-in SSH connection; commands run with sh on the device."""

    def __init__(self, client, label):
        self.client = client
        self.label = label
        self.lock = threading.Lock()

    @property
    def alive(self):
        t = self.client.get_transport()
        return bool(t and t.is_active())

    def run(self, command, stdin=b"", timeout=60.0, raw=False):
        """Runs `command`; returns (exit status, stdout, stderr) as text (as
        bytes with `raw`)."""
        with self.lock:
            try:
                chan = self.client.get_transport().open_session(timeout=CONNECT_TIMEOUT_S)
                chan.settimeout(timeout)
                chan.exec_command(command)
                if stdin:
                    chan.sendall(stdin)
                chan.shutdown_write()
                out, err = bytearray(), bytearray()
                deadline = time.monotonic() + timeout
                while True:
                    got = False
                    if chan.recv_ready():
                        out += chan.recv(65536)
                        got = True
                    if chan.recv_stderr_ready():
                        err += chan.recv_stderr(65536)
                        got = True
                    if not got:
                        if chan.exit_status_ready():
                            break
                        if time.monotonic() > deadline:
                            raise socket.timeout()
                        time.sleep(0.01)
                status = chan.recv_exit_status()
                chan.close()
            except (socket.timeout, TimeoutError):
                raise SshError("%s did not answer in time" % self.label)
            except (OSError, EOFError, AttributeError) as e:
                self.close()
                raise ConnectionLost("the connection to %s was lost (%s)" % (self.label, str(e) or type(e).__name__))
            except _paramiko().SSHException as e:
                t = self.client.get_transport()
                if not (t and t.is_active()) or "not active" in str(e):
                    self.close()
                    raise ConnectionLost("the connection to %s was lost (%s)" % (self.label, e))
                raise SshError("SSH to %s: %s" % (self.label, e))
        if raw:
            return status, bytes(out), bytes(err)
        return status, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    def put_files(self, remote_dir, files):
        """Copies local `files` into the existing `remote_dir` (SFTP)."""
        with self.lock:
            try:
                sftp = self.client.open_sftp()
                try:
                    for f in files:
                        sftp.put(f, posixpath.join(remote_dir, os.path.basename(f)))
                finally:
                    sftp.close()
            except (OSError, _paramiko().SSHException) as e:
                raise SshError("could not copy the files to %s: %s" % (self.label, e))

    def close(self):
        try:
            self.client.close()
        except Exception:
            pass


def _load_key(path):
    paramiko = _paramiko()
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return cls.from_private_key_file(path)
        except (paramiko.SSHException, ValueError, OSError):
            continue
    return None


def connect(store, host, user="", port=22, password=None, trust=None, timeout=CONNECT_TIMEOUT_S):
    """Logs in to the device. Raises NeedTrust for a key this PC has not
    trusted (unless `trust` is that key's fingerprint, which then is kept),
    KeyChanged for a different key, NeedPassword when no key works."""
    paramiko = _paramiko()
    where = resolve(host, user, port)
    entry = host_entry(where["hostname"], where["port"])
    label = "%s@%s" % (where["user"], host)

    class Policy(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            fp = fingerprint(key)
            if trust and trust == fp:
                client.get_host_keys().add(entry, key.get_name(), key)
                _save_host_keys(client, store.known_hosts)
                return
            raise NeedTrust(host, fp, key.get_name())

    client = paramiko.SSHClient()
    if os.path.isfile(store.known_hosts):
        try:
            client.load_host_keys(store.known_hosts)
        except (OSError, paramiko.SSHException):
            pass
    client.set_missing_host_key_policy(Policy())
    keys = list(where["keys"])
    own = _load_key(store.key_path) if os.path.isfile(store.key_path) else None
    try:
        client.connect(where["hostname"], port=where["port"], username=where["user"],
                       password=password, pkey=own, key_filename=keys or None,
                       allow_agent=True, look_for_keys=True, timeout=timeout, banner_timeout=timeout,
                       auth_timeout=timeout)
    except NeedTrust:
        client.close()
        raise
    except paramiko.BadHostKeyException as e:
        client.close()
        raise KeyChanged(host, fingerprint(e.key))
    except paramiko.AuthenticationException:
        client.close()
        raise NeedPassword(where["user"], host, wrong=password is not None)
    except (socket.timeout, TimeoutError):
        client.close()
        raise SshError("%s did not answer on SSH port %d" % (host, where["port"]))
    except socket.gaierror:
        client.close()
        raise SshError("%s is not known on this network (check the name, or use its address)" % host)
    except paramiko.SSHException as e:
        client.close()
        if password is None and "No authentication methods available" in str(e):
            # No agent and no key file on this PC: the password is the way in.
            raise NeedPassword(where["user"], host)
        raise SshError("cannot connect to %s on SSH port %d: %s" % (host, where["port"], e))
    except (OSError, EOFError) as e:
        client.close()
        raise SshError("cannot connect to %s on SSH port %d: %s" % (host, where["port"], e))
    return Connection(client, label)


def _save_host_keys(client, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    client.save_host_keys(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def forget_host_key(store, host, port=22):
    paramiko = _paramiko()
    where = resolve(host, "", port)
    if not os.path.isfile(store.known_hosts):
        return False
    keys = paramiko.HostKeys(store.known_hosts)
    entry = host_entry(where["hostname"], where["port"])
    if entry not in keys:
        return False
    del keys[entry]
    keys.save(store.known_hosts)
    return True


def own_public_key(store):
    """This PC's canworks key (made once, readable by this user only) as an
    authorized_keys line."""
    paramiko = _paramiko()
    if not os.path.isfile(store.key_path):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
        pem = ed25519.Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption())
        os.makedirs(os.path.dirname(store.key_path), exist_ok=True)
        fd = os.open(store.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
    key = paramiko.Ed25519Key.from_private_key_file(store.key_path)
    return "%s %s canworks@%s" % (key.get_name(), key.get_base64(), socket.gethostname().split(".")[0] or "pc")


def add_key_login(conn, public_line):
    """Adds this PC's key to the device user's authorized_keys, once."""
    status, _, err = conn.run(
        'umask 077; read -r K; mkdir -p "$HOME/.ssh" && touch "$HOME/.ssh/authorized_keys" && '
        '{ grep -qxF "$K" "$HOME/.ssh/authorized_keys" || printf "%s\\n" "$K" >> "$HOME/.ssh/authorized_keys"; }',
        stdin=(public_line + "\n").encode("ascii"))
    if status != 0:
        raise SshError("could not add the key to ~/.ssh/authorized_keys on the device: %s" % err.strip())


def quote(text):
    return shlex.quote(str(text))
