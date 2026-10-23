"""Install jobs on the device: a small script run as root by systemd-run, so
it goes on when the SSH connection drops or the configurator stops. Its
output goes to /var/log/canworks-install/<id>.log (readable by the SSH user,
the last five kept); a lock lets one job run at a time.

The log carries the install scripts' "::canworks-step N/M text" lines with
the time they were seen appended (" @<epoch>"), and ends with
"::canworks-exit <status> @<epoch>"."""

import calendar
import posixpath
import re
import secrets
import time

from .ssh import SshError, quote

RAW = "https://raw.githubusercontent.com/tonihoohoo/canworks"
ACTIONS = ("install_bridge", "bridge_config", "uninstall_bridge", "remove_all", "link_on", "link_off", "link_start", "discovery_on", "discovery_off")
# The actions that start the open project's bridge with its saved config.
BRIDGE_ACTIONS = ("install_bridge", "bridge_config")
_CONFIG = re.compile(r"^/etc/canworks-bridge/[A-Za-z0-9_-]{1,64}/canworks\.json$")
MAX_CHUNK = 256 * 1024
_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{4}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_INSTANCE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_STEP = re.compile(r"^::canworks-step (\d+)/(\d+|\?) (.*?)(?: @(\d+))?$")


class JobError(SshError):
    pass


class NeedSudo(JobError):
    def __init__(self, wrong=False):
        super().__init__("sudo on the device did not accept the password." if wrong else
                         "sudo on the device needs the SSH user's password.")
        self.wrong = wrong


class Paths:
    """Where jobs live on the device (other folders only for the tests)."""

    def __init__(self, log_dir="/var/log/canworks-install", state_dir="/var/lib/canworks-install",
                 lock="/run/canworks-install.lock", raw=RAW, systemd_run="systemd-run", systemctl="systemctl"):
        self.log_dir, self.state_dir, self.lock, self.raw = log_dir, state_dir, lock, raw
        self.systemd_run, self.systemctl = systemd_run, systemctl

    def log(self, job_id):
        return posixpath.join(self.log_dir, job_id + ".log")


def new_id(now=None):
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now)) + "-" + secrets.token_hex(2)


def started_at(job_id):
    """The job's start time from its id (UTC), or None."""
    try:
        return calendar.timegm(time.strptime(job_id[:16], "%Y%m%dT%H%M%SZ"))
    except (ValueError, TypeError):
        return None


def check_id(job_id):
    if not isinstance(job_id, str) or not _ID.match(job_id):
        raise JobError("not an install job id: %r" % (job_id,))
    return job_id


def instance_name(folder_name):
    """A bridge instance name from the project folder's name."""
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", folder_name or "").strip("-")[:64]
    return name or "canworks"


def _fetch(paths, script, version):
    return "curl -LsSf %s | bash -s --" % quote("%s/deploy-v%s/scripts/%s" % (paths.raw, version, script))


def commands(action, version, paths, link=True, discovery=True, purge=False, instance=None, upload=None,
             bridge_prefix=None, link_config=None, runtime_port=None):
    """The root shell lines of one action, each running the release's
    install-bridge.sh or install-link.sh."""
    if action not in ACTIONS:
        raise JobError("unknown action %r" % (action,))
    if not isinstance(version, str) or not _VERSION.match(version):
        raise JobError("not a release version: %r" % (version,))
    if instance is not None and not _INSTANCE.match(instance):
        raise JobError("not a bridge instance name: %r" % (instance,))
    if upload is not None and not upload.startswith("/tmp/canworks-bridge-upload."):
        raise JobError("not an upload folder: %r" % (upload,))
    if link_config is not None and not _CONFIG.match(link_config):
        raise JobError("not a deployed config: %r" % (link_config,))
    if runtime_port not in (None, "none", "8443"):
        raise JobError("not a runtime port: %r" % (runtime_port,))
    v = quote(version)
    # The remote link and the advertisement (device-link-switches).
    link_sh = _fetch(paths, "install-link.sh", version)
    served = " --config %s --runtime-port %s" % (quote(link_config or ""), runtime_port or "8443")
    if action in ("link_on", "discovery_on") and not link_config:
        raise JobError("the link needs the config it serves")
    if action == "link_on":
        return [link_sh + " --version " + v + served + ("" if discovery else " --without-discovery")]
    if action == "link_off":
        return [link_sh + " --uninstall" + (" --keep-discovery" if discovery else "")]
    if action == "link_start":
        return ['echo "::canworks-step 1/1 Starting the remote link"', "systemctl restart canworks-link.service"]
    if action == "discovery_on":
        return [link_sh + " --discovery-only" + served]
    if action == "discovery_off":
        return [link_sh + " --remove-discovery"]
    bridge = _fetch(paths, "install-bridge.sh", version) + " --version " + v
    if action == "install_bridge":
        line = bridge
        if instance and upload:
            line += " --instance %s --config %s --remove-config-dir" % (quote(instance), quote(upload))
        if link and instance:
            line += " --with-link " + quote(instance)
        if not discovery:
            line += " --without-discovery"
        return [line]
    if action == "bridge_config":
        if not (instance and upload and bridge_prefix):
            raise JobError("starting a bridge needs its instance, config and installed bridge")
        b = quote(posixpath.join(bridge_prefix, "bin", "canworks-bridge"))
        dest = quote("/etc/canworks-bridge/" + instance)
        unit = quote("canworks-bridge@%s.service" % instance)
        up = quote(upload)
        return ["[ -f /etc/systemd/system/canworks-bridge@.service ] || { echo 'The bridge service is not "
                "installed on this device (no canworks-bridge@.service): install the bridge first.'; exit 3; }",
                'echo "::canworks-step 1/2 Checking the config"',
                "%s --config %s/canworks.json --check-only" % (b, up),
                'echo "::canworks-step 2/2 Starting the bridge %s"' % instance,
                "mkdir -p %s" % dest,
                "for f in %s/*; do [ -f \"$f\" ] && install -m 0644 \"$f\" %s/; done" % (up, dest),
                "rm -rf %s" % up,
                "systemctl enable %s >/dev/null" % unit,
                "systemctl restart %s" % unit,
                'echo "==> Started %s"' % unit.strip("'")]
    if action == "uninstall_bridge":
        return [bridge + " --uninstall" + (" --purge" if purge else "")]
    # remove_all: the bridge, its configs and the remote link; nothing that is not canworks.
    return [bridge + " --uninstall --purge"]


def job_script(job_id, action, lines, paths):
    """The script systemd-run runs as root."""
    body = "\n".join("    " + line for line in lines)
    return """#!/bin/sh
# canworks install job {id} ({action}), started by the configurator's Devices workspace.
exec >>{log} 2>&1
exec 9>{lock}
if ! flock -n 9; then
    echo "Another install is running on this device."
    echo "::canworks-exit 75"
    exit 75
fi
echo "::canworks-job {id} {action} @$(date +%s)"
{{
  (
    set -e
{body}
  )
  echo "::canworks-exit $?"
}} 2>&1 | while IFS= read -r line || [ -n "$line" ]; do
    case $line in
        "::canworks-step "*|"::canworks-exit "*) printf '%s @%s\\n' "$line" "$(date +%s)" ;;
        *) printf '%s\\n' "$line" ;;
    esac
done
""".format(id=job_id, action=action, log=quote(paths.log(job_id)), lock=quote(paths.lock), body=body)


def launch_script(job_id, script, paths):
    """Root shell text that writes the job, keeps the last five logs and
    starts the job's unit."""
    state = posixpath.join(paths.state_dir, job_id + ".sh")
    return """set -e
umask 022
mkdir -p {logs} {states}
chmod 755 {logs}
: > {log}
chmod 644 {log}
cat > {state} <<'CANWORKS_JOB_EOF'
{script}CANWORKS_JOB_EOF
n=0
for f in {logs}/*.log; do [ -f "$f" ] && n=$((n + 1)); done
for f in {logs}/*.log; do
    [ "$n" -gt 5 ] || break
    rm -f "$f" {states}/"$(basename "$f" .log).sh"
    n=$((n - 1))
done
{run} --unit {unit} --collect --quiet /bin/sh {state}
echo "::canworks-started {id}"
""".format(logs=quote(paths.log_dir), states=quote(paths.state_dir), log=quote(paths.log(job_id)),
           state=quote(state), script=script, run=paths.systemd_run, unit=quote("canworks-install-" + job_id),
           id=job_id)


def _check_password(password):
    if password is not None and (not isinstance(password, str) or "\n" in password or "\r" in password):
        raise NeedSudo(wrong=True)


def as_root(conn, sudo_mode, password, script, timeout=120.0):
    """Runs `script` (sh text) as root: directly for root, `sudo -n` without a
    password, else `sudo -S` with `password` on standard input (checked first,
    alone, so a wrong one never meets the script). Returns (status, out, err)."""
    if sudo_mode == "none":
        return conn.run("sh -s", stdin=script.encode("utf-8"), timeout=timeout)
    if sudo_mode == "nopasswd":
        return conn.run("sudo -n sh -s", stdin=script.encode("utf-8"), timeout=timeout)
    if sudo_mode == "unavailable":
        raise JobError("The SSH user cannot use sudo: log in as root or as a user with sudo rights.")
    _check_password(password)
    if not password:
        raise NeedSudo()
    status, _, _ = conn.run("sudo -k -S -p '' -v", stdin=(password + "\n").encode("utf-8"), timeout=30.0)
    if status != 0:
        raise NeedSudo(wrong=True)
    return conn.run("sudo -k -S -p '' sh -s", stdin=(password + "\n" + script).encode("utf-8"), timeout=timeout)


def start(conn, sudo_mode, password, action, lines, paths, job_id=None):
    """Writes and starts the job; returns its id."""
    job_id = job_id or new_id()
    script = job_script(job_id, action, lines, paths)
    status, out, err = as_root(conn, sudo_mode, password, launch_script(job_id, script, paths))
    if status != 0 or ("::canworks-started %s" % job_id) not in out:
        raise JobError("the install job did not start on the device: %s" % ((err or out).strip()[-400:] or status))
    return job_id


def make_upload_dir(conn):
    status, out, err = conn.run("mktemp -d /tmp/canworks-bridge-upload.XXXXXX")
    path = out.strip()
    if status != 0 or not path.startswith("/tmp/canworks-bridge-upload."):
        raise JobError("could not make an upload folder on the device: %s" % (err.strip() or out.strip()))
    return path


def parse(text):
    """Steps, the exit status and the plain log lines of a piece of job log."""
    steps, lines, exit_status, started, ended = [], [], None, None, None
    for line in text.splitlines():
        if line.startswith("::canworks-step "):
            m = _STEP.match(line)
            if m:
                steps.append({"n": int(m.group(1)), "of": None if m.group(2) == "?" else int(m.group(2)),
                              "text": m.group(3), "at": int(m.group(4)) if m.group(4) else None})
            continue
        if line.startswith("::canworks-exit "):
            try:
                exit_status = int(line.split()[1])
            except (IndexError, ValueError):
                exit_status = 1
            m = re.search(r" @(\d+)$", line)
            ended = int(m.group(1)) if m else None
            continue
        if line.startswith("::canworks-job "):
            m = re.search(r" @(\d+)$", line)
            started = int(m.group(1)) if m else None
            continue
        lines.append(line)
    return {"steps": steps, "lines": lines, "exit": exit_status, "started": started, "ended": ended}


def follow(conn, job_id, offset, paths):
    """The job's log from byte `offset` on (at most 256 KiB at a time), its
    unit state, and the new offset."""
    check_id(job_id)
    offset = max(0, int(offset or 0))
    cmd = ("f={log}; if [ ! -f \"$f\" ]; then echo '::none'; exit 0; fi; "
           "echo \"::state $({ctl} show -p ActiveState --value {unit} 2>/dev/null)\"; "
           "tail -c +{start} \"$f\" | head -c {max}").format(
        log=quote(paths.log(job_id)), ctl=paths.systemctl, unit=quote("canworks-install-%s.service" % job_id),
        start=offset + 1, max=MAX_CHUNK)
    status, out, err = conn.run(cmd, raw=True)
    if status != 0:
        raise JobError("could not read the job's log: %s" % err.decode("utf-8", "replace").strip())
    head, _, rest = out.partition(b"\n")
    if head == b"::none":
        return {"found": False, "offset": offset, "state": None}
    state = head.decode("utf-8", "replace")[len("::state "):].strip() or None
    # Only whole lines: a line still being written comes with the next read.
    cut = rest.rfind(b"\n") + 1 if len(rest) < MAX_CHUNK or b"\n" in rest else len(rest)
    chunk = rest[:cut]
    out = parse(chunk.decode("utf-8", "replace"))
    out.update(found=True, offset=offset + len(chunk), state=state,
               more=len(rest) >= MAX_CHUNK)
    return out


# What to do about the failures the install scripts name, by a line of the log.
HINTS = (
    (re.compile(r"Another install is running"), "Another install is running on this device: wait until it ends, "
     "then check again."),
    (re.compile(r"No space left on device"), "The device's disk is full: free some space (the build needs about "
     "2 GB) and start again."),
    (re.compile(r"Could not get lock|dpkg was interrupted|is held by process"), "Another program is installing "
     "packages on the device (apt is locked): wait until it ends and start again."),
    (re.compile(r"could not reach|could not download|cannot download|Could not resolve host|"
                r"Temporary failure (in name resolution|resolving)"), "The device lost its connection to github.com "
     "during the install: check its network and start again."),
)


def hint(lines):
    """One sentence for a failure the scripts name, or None."""
    for line in reversed(lines):
        for pattern, text in HINTS:
            if pattern.search(line):
                return text
    return None


def failure(conn, job_id, paths, count=20):
    """The last `count` log lines of a failed job (without the step and exit
    lines) and the hint for them."""
    check_id(job_id)
    status, out, _ = conn.run("tail -c 65536 %s" % quote(paths.log(job_id)))
    lines = parse(out if status == 0 else "")["lines"]
    if len(lines) > count:
        lines = lines[-count:]
    return {"tail": lines, "hint": hint(lines)}


def stop(conn, sudo_mode, password, job_id, paths):
    check_id(job_id)
    status, _, err = as_root(conn, sudo_mode, password, "%s stop %s\n" % (
        paths.systemctl, quote("canworks-install-%s.service" % job_id)), timeout=60.0)
    if status != 0:
        raise JobError("could not stop the install job: %s" % err.strip())

