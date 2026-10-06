"""The editor hook's extra duties on the managed Docker install.

The bootloader creates a new runtime container for every runtime version
change (and on repair), and the runtime then recreates plugins.conf from
plugins_default.conf, without our `canopen` line. So, in Docker mode only:

- after each upload, record the `canopen` line the runtime wrote
  (<prefix>/lib/plugins-line, on the host through the bind mount);
- at webserver start, put that line back when plugins.conf has none, or a
  disabled one when nothing was recorded yet;
- when the plugin was built for another runtime version than the one running
  (<prefix>/lib/runtime-version, written by scripts/install-stock.sh), keep
  `canopen` disabled: a library built in another image may not even load.

Standard library only: this runs inside the runtime's webserver.
"""

import os

NAME = "canopen"
STAMP = "runtime-version"
RECORD = "plugins-line"


def lib_dir(prefix):
    return os.path.join(prefix, "lib")


def disabled_line(prefix):
    lib = lib_dir(prefix)
    return "%s,%s,0,1,%s," % (NAME, os.path.join(lib, "libcanopen_plugin.so"), os.path.join(lib, "canopen.json"))


def read_stamp(prefix):
    """The runtime version the plugin was built for, or None."""
    try:
        with open(os.path.join(lib_dir(prefix), STAMP), encoding="utf-8") as f:
            first = f.readline().strip()
    except OSError:
        return None
    return first or None


def version_problem(prefix, running):
    """None when the plugin matches the running runtime, else the reason."""
    built = read_stamp(prefix)
    if built is None:
        return ("the CANopen plugin has no build stamp (%s); re-run scripts/install-stock.sh"
                % os.path.join(lib_dir(prefix), STAMP))
    if not running:
        return "RUNTIME_VERSION is not set in the runtime container; cannot check the CANopen plugin's build"
    if built != running:
        return ("the CANopen plugin was built for runtime %s but the runtime is %s; "
                "re-run scripts/install-stock.sh to rebuild it" % (built, running))
    return None


def _is_ours(line):
    return line.split(",", 1)[0].strip() == NAME


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def write_lines(path, lines):
    # In place, as the runtime does (the file may be bind-mounted).
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def canopen_line(plugins_conf):
    try:
        for line in read_lines(plugins_conf):
            if _is_ours(line):
                return line
    except OSError:
        pass
    return None


def set_line(plugins_conf, line):
    """Replaces any canopen line with `line` (appended at the end)."""
    lines = [l for l in read_lines(plugins_conf) if not _is_ours(l)]
    write_lines(plugins_conf, lines + [line])


def disable(line):
    fields = line.split(",")
    if len(fields) >= 3:
        fields[2] = "0"
    return ",".join(fields)


def record(prefix, plugins_conf):
    """Saves the runtime's canopen line after an upload. Returns it, or None."""
    line = canopen_line(plugins_conf)
    if line is None:
        return None
    path = os.path.join(lib_dir(prefix), RECORD)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(line + "\n")
    os.replace(tmp, path)
    return line


def recorded(prefix):
    try:
        with open(os.path.join(lib_dir(prefix), RECORD), encoding="utf-8") as f:
            line = f.readline().strip()
    except OSError:
        return None
    return line if _is_ours(line) else None


def at_start(prefix, plugins_conf, default_conf, running):
    """Webserver start: makes plugins.conf carry the right canopen line.

    Returns [(level, text)] to log."""
    messages = []
    if not os.path.exists(plugins_conf):
        if not os.path.exists(default_conf):
            return [("ERROR", "neither %s nor %s exists; CANopen line not restored" % (plugins_conf, default_conf))]
        # What the runtime itself does when plugins.conf is missing.
        with open(default_conf, encoding="utf-8") as src:
            text = src.read()
        with open(plugins_conf, "w", encoding="utf-8") as dst:
            dst.write(text)
    problem = version_problem(prefix, running)
    current = canopen_line(plugins_conf)
    if problem:
        line = disable(current or recorded(prefix) or disabled_line(prefix))
        if current != line:
            set_line(plugins_conf, line)
        messages.append(("ERROR", problem + "; CANopen stays off"))
        return messages
    if current is None:
        line = recorded(prefix)
        if line:
            messages.append(("INFO", "restored the canopen line from the last upload: " + line))
        else:
            line = disabled_line(prefix)
            messages.append(("INFO", "added a disabled canopen line (no upload has set it yet)"))
        set_line(plugins_conf, line)
    return messages


def after_upload(prefix, plugins_conf, running):
    """After the runtime applied an upload's plugin configuration.

    Returns [(level, text)] for the build log."""
    problem = version_problem(prefix, running)
    current = canopen_line(plugins_conf)
    if problem:
        if current is not None and current != disable(current):
            set_line(plugins_conf, disable(current))
        return [("ERROR", "CANopen: " + problem + "; CANopen stays off")]
    record(prefix, plugins_conf)
    return []
