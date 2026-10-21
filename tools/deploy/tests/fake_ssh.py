"""A device over SSH for the Devices tests (device-install): an in-process
paramiko server whose commands run with sh on this machine, a home folder per
user under a temp root, SFTP into real folders, and stand-ins for sudo (a
password on standard input, as sudo -S reads it), systemd-run and systemctl.
Units are processes in their own session; their state is a file."""

import os
import socket
import stat
import subprocess
import threading

import paramiko

SUDO = r"""#!/bin/sh
# sudo -k -S -p '' -v | -k -S -p '' CMD... | -n CMD...
mode=n validate=
while [ $# -gt 0 ]; do
    case $1 in
        -k) shift ;;
        -S) mode=S; shift ;;
        -n) mode=n; shift ;;
        -p) shift 2 ;;
        -v) validate=1; shift ;;
        *) break ;;
    esac
done
echo "sudo $mode${validate:+ -v} $*" >> "$FAKE_ROOT/sudo.log"
if [ "$mode" = S ]; then
    IFS= read -r pw
    if [ "$pw" != "$FAKE_SUDO_PASSWORD" ]; then echo "Sorry, try again." >&2; exit 1; fi
elif [ -z "$FAKE_SUDO_NOPASSWD" ]; then
    echo "sudo: a password is required" >&2; exit 1
fi
[ -n "$validate" ] && exit 0
exec "$@"
"""

SYSTEMD_RUN = r"""#!/bin/sh
unit=
while [ $# -gt 0 ]; do
    case $1 in
        --unit) unit=$2; shift 2 ;;
        --*) shift ;;
        *) break ;;
    esac
done
echo active > "$FAKE_UNITS/$unit.service"
setsid sh -c '"$@"; echo inactive > "$FAKE_UNITS/'"$unit"'.service"' unit "$@" </dev/null >/dev/null 2>&1 &
echo $! > "$FAKE_UNITS/$unit.service.pid"
"""

SYSTEMCTL = r"""#!/bin/sh
case $1 in
    show)
        f="$FAKE_UNITS/$5"
        if [ "$3" = Result ]; then echo success; elif [ -f "$f" ]; then cat "$f"; else echo inactive; fi ;;
    stop)
        f="$FAKE_UNITS/$2"
        if [ -f "$f.pid" ]; then kill -TERM -- "-$(cat "$f.pid")" 2>/dev/null; fi
        echo inactive > "$f" ;;
    is-active)
        if [ -f "$FAKE_UNITS/$2" ]; then cat "$FAKE_UNITS/$2"; else echo inactive; exit 3; fi ;;
    is-enabled)
        echo enabled ;;
esac
"""


def _script(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, 0o755)


class _Sftp(paramiko.SFTPServerInterface):
    """SFTP straight into this machine's files (only what put() needs)."""

    def _attrs(self, path):
        return paramiko.SFTPAttributes.from_stat(os.stat(path), os.path.basename(path))

    def stat(self, path):
        try:
            return self._attrs(path)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    lstat = stat

    def open(self, path, flags, attr):
        try:
            fd = os.open(path, flags | getattr(os, "O_BINARY", 0), 0o644)
            f = os.fdopen(fd, "wb" if flags & os.O_WRONLY else "rb")
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        h = paramiko.SFTPHandle(flags)
        h.filename = path
        h.readfile = h.writefile = f
        return h

    def chattr(self, path, attr):
        return paramiko.SFTP_OK


class _Interface(paramiko.ServerInterface):
    def __init__(self, device):
        self.device = device
        self.user = None

    def get_allowed_auths(self, username):
        return "publickey,password"

    def check_auth_password(self, username, password):
        if self.device.passwords.get(username) == password:
            self.user = username
            self.device.logins.append((username, "password"))
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, key):
        line = "%s %s" % (key.get_name(), key.get_base64())
        path = os.path.join(self.device.home(username), ".ssh", "authorized_keys")
        try:
            with open(path) as f:
                ok = any(entry.startswith(line + " ") or entry.strip() == line for entry in f)
        except OSError:
            ok = False
        if ok and username in self.device.passwords:
            self.user = username
            self.device.logins.append((username, "key"))
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel, command):
        threading.Thread(target=self.device.run, args=(channel, self.user, command.decode()), daemon=True).start()
        return True


class Device:
    """One device on 127.0.0.1 and a free port. `root` holds the users' homes,
    the stand-in commands (root/bin), the units' state (root/units) and the
    job folders (paths())."""

    def __init__(self, root, passwords=None, sudo_password="sudo-secret", host_key=None):
        self.root = root
        self.passwords = passwords if passwords is not None else {"pi": "ssh-secret"}
        self.sudo_password = sudo_password
        self.sudo_nopasswd = False
        self.host_key = host_key or paramiko.Ed25519Key.from_private_key_file(_new_key(root))
        self.logins = []
        self.commands = []
        self.bin = os.path.join(root, "bin")
        self.units = os.path.join(root, "units")
        for d in (self.bin, self.units):
            os.makedirs(d, exist_ok=True)
        _script(os.path.join(self.bin, "sudo"), SUDO)
        _script(os.path.join(self.bin, "systemd-run"), SYSTEMD_RUN)
        _script(os.path.join(self.bin, "systemctl"), SYSTEMCTL)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.transports = []
        self.closed = False
        threading.Thread(target=self._accept, daemon=True).start()

    def home(self, user):
        return os.path.join(self.root, "home", user)

    def paths(self):
        from canworks.devices import jobs
        return jobs.Paths(log_dir=os.path.join(self.root, "var", "log", "canworks-install"),
                          state_dir=os.path.join(self.root, "var", "lib", "canworks-install"),
                          lock=os.path.join(self.root, "run", "canworks-install.lock"),
                          systemd_run=os.path.join(self.bin, "systemd-run"),
                          systemctl=os.path.join(self.bin, "systemctl"))

    def _accept(self):
        while not self.closed:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            t = paramiko.Transport(conn)
            t.add_server_key(self.host_key)
            t.set_subsystem_handler("sftp", paramiko.SFTPServer, _Sftp)
            self.transports.append(t)
            try:
                t.start_server(server=_Interface(self))
            except (paramiko.SSHException, EOFError, OSError):
                continue

    def run(self, channel, user, command):
        self.commands.append(command)
        home = self.home(user)
        os.makedirs(home, exist_ok=True)
        os.makedirs(os.path.join(self.root, "run"), exist_ok=True)
        env = dict(os.environ, HOME=home, USER=user, FAKE_ROOT=self.root, FAKE_UNITS=self.units,
                   FAKE_SUDO_PASSWORD=self.sudo_password or "", FAKE_SUDO_NOPASSWD="1" if self.sudo_nopasswd else "",
                   PATH=self.bin + os.pathsep + os.environ.get("PATH", ""))
        p = subprocess.Popen(["sh", "-c", command], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, cwd=home, env=env)

        def pump_in():
            try:
                while True:
                    data = channel.recv(65536)
                    if not data:
                        break
                    p.stdin.write(data)
                    p.stdin.flush()
            except (OSError, BrokenPipeError):
                pass
            finally:
                try:
                    p.stdin.close()
                except OSError:
                    pass

        def pump_err():
            for data in iter(lambda: p.stderr.read1(65536), b""):
                channel.sendall_stderr(data)

        threads = [threading.Thread(target=pump_in, daemon=True), threading.Thread(target=pump_err, daemon=True)]
        for t in threads:
            t.start()
        try:
            for data in iter(lambda: p.stdout.read1(65536), b""):
                channel.sendall(data)
            threads[1].join(10)
            channel.send_exit_status(p.wait())
        except OSError:
            p.kill()
        finally:
            channel.close()

    def drop_connections(self):
        for t in self.transports:
            t.close()
        self.transports = []

    def close(self):
        self.closed = True
        self.drop_connections()
        self.sock.close()


def _new_key(root):
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, "host_ed25519")
    if not os.path.exists(path):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
        pem = ed25519.Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption())
        with open(path, "wb") as f:
            f.write(pem)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path
