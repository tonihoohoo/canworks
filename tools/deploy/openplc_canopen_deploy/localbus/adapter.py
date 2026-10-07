"""Opening a CAN adapter on this PC with python-can (canopen-local-bus).

An adapter is written TYPE:CHANNEL: slcan:COM5, slcan:/dev/tty.usbmodem14101,
socketcan:can0, or any other python-can interface (gs_usb:0, pcan:PCAN_USBBUS1,
...), which is passed through untested. `virtual:NAME` is python-can's
in-process bus, for tests.

open() is the one place an adapter is opened. With `listen_only` the
adapter receives without acknowledging or sending anything (bit rate
detection): slcan opens the channel in silent mode ('m1', then 'O') where
the firmware takes 'm1', else with 'L' instead of 'O', PCAN gets its
listen-only parameter, and a SocketCAN link is set listen-only with `ip`
(root or CAP_NET_ADMIN) and set back when the adapter is closed. Other
adapter types have no listen-only mode here.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time

SUPPORTED = ("slcan", "socketcan")  # tested; anything else python-can knows is passed through
TEST_ONLY = ("virtual",)
LISTEN_ONLY = ("slcan", "pcan", "socketcan", "virtual")  # the types open(listen_only=True) takes
SLCAN_KBIT = (10, 20, 50, 100, 125, 250, 500, 750, 1000)  # the rates python-can sets on slcan (S0-S8)
NO_LISTEN_ONLY = "the adapter's driver has no listen-only mode"
# The plugin's kUnconfirmedListenOnly: the request may be repeated with disturb_bus.
DISTURB_NEEDED = "disturb_bus needed"
UNCONFIRMED = ("the adapter did not answer its silent mode command, so it may not only listen: at a wrong bit rate "
               "it can send error frames that disturb the devices on the bus; " + DISTURB_NEEDED)

# USB IDs of adapters that run slcan firmware out of the box.
SLCAN_USB_IDS = {
    (0xAD50, 0x60C4): "CANable (slcan firmware)",
    (0x16D0, 0x117E): "CANable 2.0 (slcan firmware)",
}
# USB IDs of adapters that need another interface type.
OTHER_USB_IDS = {
    (0x1D50, 0x606F): ("gs_usb", "candleLight / gs_usb firmware (socketcan on Linux, gs_usb elsewhere)"),
}


class AdapterError(Exception):
    """kind: usage (bad spec or bit rate), busy (another tool has it open),
    unreachable (cannot be opened), unconfirmed (listen-only asked for, and
    the adapter does not confirm it: UNCONFIRMED)."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


class Spec:
    def __init__(self, kind, channel, options=None):
        self.kind, self.channel = kind, channel
        self.options = dict(options or {})

    def __str__(self):
        return "%s:%s" % (self.kind, self.channel)

    def __repr__(self):
        return "Spec(%r)" % str(self)

    def __eq__(self, other):
        return isinstance(other, Spec) and (self.kind, self.channel, self.options) == \
            (other.kind, other.channel, other.options)

    def __hash__(self):
        return hash((self.kind, self.channel))


def _interfaces():
    try:
        import can
        return set(can.VALID_INTERFACES)
    except ImportError:
        return set(SUPPORTED) | set(TEST_ONLY)


def _option_value(text):
    for conv in (lambda t: int(t, 0), float):
        try:
            return conv(text)
        except ValueError:
            pass
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    return text


def parse(text, options=()):
    """'TYPE:CHANNEL' (plus KEY=VALUE options) -> Spec. Raises AdapterError."""
    text = (text or "").strip()
    kind, sep, channel = text.partition(":")
    kind = kind.strip().lower()
    if not sep or not kind or not channel.strip():
        raise AdapterError("usage", "write the adapter as TYPE:CHANNEL, e.g. slcan:COM5, "
                                    "slcan:/dev/tty.usbmodem14101 or socketcan:can0")
    if kind not in _interfaces():
        raise AdapterError("usage", "unknown adapter type %r; python-can knows %s" % (
            kind, ", ".join(sorted(_interfaces()))))
    opts = {}
    for item in options or ():
        key, eq, value = str(item).partition("=")
        if not eq or not key.strip():
            raise AdapterError("usage", "--adapter-option %r: write KEY=VALUE" % item)
        opts[key.strip()] = _option_value(value.strip())
    return Spec(kind, channel.strip(), opts)


def untested(spec):
    return spec.kind not in SUPPORTED and spec.kind not in TEST_ONLY


# ---------------------------------------------------------------------------
# One tool per adapter


class _Lock:
    """An OS file lock named after the adapter, held while it is open, so a
    second tool (another configurator, a CLI) gets a clear message instead of
    sharing the adapter."""

    def __init__(self, spec):
        folder = os.path.join(tempfile.gettempdir(), "openplc-canopen-adapters")
        os.makedirs(folder, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(spec))
        self.path = os.path.join(folder, name + ".lock")
        self.fd = None

    def acquire(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self.fd = fd
        return True

    def release(self):
        if self.fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                try:
                    os.lseek(self.fd, 0, 0)
                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            os.close(self.fd)
        finally:
            self.fd = None


# ---------------------------------------------------------------------------
# SocketCAN link


def _link(interface):
    """(up, bitrate or None, kind) of a SocketCAN link from `ip`, or None
    when `ip` cannot tell."""
    try:
        out = subprocess.run(["ip", "-details", "-json", "link", "show", "dev", interface],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        raise AdapterError("unreachable", "no CAN interface %s on this PC%s" % (
            interface, ": " + out.stderr.strip() if out.stderr.strip() else ""))
    try:
        info = json.loads(out.stdout)[0]
    except (ValueError, IndexError, TypeError):
        return None
    flags = info.get("flags") or []
    linkinfo = info.get("linkinfo") or {}
    kind = linkinfo.get("info_kind")
    bitrate = ((linkinfo.get("info_data") or {}).get("bittiming") or {}).get("bitrate")
    return "UP" in flags, bitrate, kind


def _socketcan_up(interface, bitrate):
    """Use the link's own bit rate when it is up; bring it up at `bitrate`
    when it is down and this user may. Returns the bit rate in use."""
    link = _link(interface)
    if link is None:
        return bitrate
    up, rate, kind = link
    if up:
        return rate or bitrate
    cmd = ["ip", "link", "set", "dev", interface, "up"]
    if kind == "can":
        cmd += ["type", "can", "bitrate", str(bitrate)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as e:
        r = None
        err = str(e)
    else:
        err = r.stderr.strip()
    if r is None or r.returncode != 0:
        raise AdapterError("unreachable", "CAN interface %s is down and could not be brought up (%s); run "
                                          "'sudo %s' first" % (interface, err or "not permitted", " ".join(cmd)))
    return bitrate


def _ip(args):
    """Runs `ip ARGS`: '' or the error text."""
    try:
        r = subprocess.run(["ip"] + args, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as e:
        return str(e) or "ip failed"
    return "" if r.returncode == 0 else (r.stderr.strip() or "ip exited with status %d" % r.returncode)


def _socketcan_listen_only(interface, bitrate):
    """Sets the link to `bitrate` in listen-only mode and up. Returns a
    function that sets it back as it was (its bit rate, listen-only off, up
    or down), which returns '' or what failed."""
    link = _link(interface)
    if link is None:
        raise AdapterError("unreachable", "cannot read CAN interface %s's link settings ('ip' is missing or "
                                          "too old)" % interface)
    up, rate, kind = link
    if kind != "can":
        raise AdapterError("usage", "no bit rate on a virtual bus (%s is %s)" % (interface, kind or "not a CAN "
                                                                                "controller"))
    setting = ["link", "set", "dev", interface, "type", "can", "bitrate", str(bitrate), "listen-only", "on"]

    def restore():
        errors = [e for e in (_ip(["link", "set", "dev", interface, "down"]),
                              _ip(["link", "set", "dev", interface, "type", "can"] +
                                  (["bitrate", str(rate)] if rate else []) + ["listen-only", "off"]),
                              _ip(["link", "set", "dev", interface, "up"]) if up else "") if e]
        return "cannot set CAN interface %s back: %s" % (interface, errors[0]) if errors else ""

    err = _ip(["link", "set", "dev", interface, "down"]) or _ip(setting) or \
        _ip(["link", "set", "dev", interface, "up"])
    if not err:
        return restore
    restore()
    low = err.lower()
    if "not supported" in low:
        raise AdapterError("usage", "%s (%s: %s)" % (NO_LISTEN_ONLY, interface, err))
    if "not permitted" in low or "permission" in low:
        raise AdapterError("usage", "setting CAN interface %s listen-only needs root or CAP_NET_ADMIN (%s); run the "
                                    "tool with sudo for bit rate detection: at each rate it runs 'sudo ip %s'"
                           % (interface, err, " ".join(setting)))
    raise AdapterError("unreachable", "cannot set CAN interface %s listen-only at %d kbit/s: %s"
                       % (interface, bitrate // 1000, err))


def _slcan_bus(listen_only, disturb_bus=False):
    """python-can's slcan bus, opening the channel the way bit rate detection
    needs, also when it reopens it to change the bit rate.

    Listen-only: some slcan firmware takes 'L' and then receives nothing, so
    silent mode is asked for first: 'm1' (receive without acknowledging or
    sending), then 'O'. Firmware without 'm1' answers with an error (BEL) and
    gets 'L'. Some firmware answers no command at all and may ignore 'm1':
    then the channel stays closed and `unconfirmed` is set, unless
    `disturb_bus`. Closing sets the mode back with 'm0'. A normal open sends 'm0'
    before 'O' too, so a sweep that died in silent mode cannot leave the
    adapter mute."""
    from can.interfaces.slcan import slcanBus

    class Slcan(slcanBus):
        _silent = False
        unconfirmed = False

        def _ask(self, cmd):
            # Answers to the commands before (close, bit rate) are not
            # this one's: let them arrive and drop them first.
            while self._read(0.05) is not None:
                pass
            self._write(cmd)
            deadline = time.monotonic() + 0.2
            while True:
                reply = self._read(max(0.0, deadline - time.monotonic()))
                if reply is None:
                    return None  # some firmware answers nothing
                if len(reply) > 1 and reply[0] in "tTrR":
                    continue  # a received frame, not the answer
                return not reply.endswith("\a")

        def open(self):
            if listen_only:
                answer = self._ask("m1")
                self._silent = answer is not False  # 'm0' on close, also after an unanswered 'm1'
                if answer is None:
                    self.unconfirmed = True
                    if not disturb_bus:
                        return  # open() in adapter refuses it
                self._write("O" if self._silent else "L")
            else:
                self._ask("m0")
                self._write("O")

        def close(self):
            super().close()
            if self._silent:
                self._write("m0")
                self._silent = False

    return Slcan


# ---------------------------------------------------------------------------
# Opening


class Opened:
    """An open adapter: `bus` (a python-can Bus), the bit rate in use, and the
    lock that keeps other tools off it."""

    def __init__(self, spec, bus, bitrate, lock, listen_only=False, restore=None):
        self.spec, self.bus, self.bitrate, self._lock = spec, bus, bitrate, lock
        self.listen_only = listen_only
        self.restore = restore  # a listen-only SocketCAN link: sets the link back, '' or what failed

    def retune(self, bitrate):
        """Changes the bit rate without closing the adapter where the adapter
        can (slcan: no new serial connection). False: close and open again."""
        if self.spec.kind != "slcan" or not hasattr(self.bus, "set_bitrate"):
            return False
        try:
            self.bus.set_bitrate(bitrate)
        except Exception as e:
            raise AdapterError("unreachable", "cannot set adapter %s to %d kbit/s: %s" % (self.spec, bitrate // 1000,
                                                                                        e))
        self.bitrate = bitrate
        return True

    def close(self, restore=True):
        """Closes the adapter; a listen-only SocketCAN link is set back unless
        `restore` is False (a sweep sets it back once, at its end). Returns ''
        or why the link could not be set back."""
        try:
            self.bus.shutdown()
        except Exception:  # an adapter unplugged meanwhile
            pass
        err = ""
        if restore and self.restore:
            err = self.restore()
            self.restore = None
        self._lock.release()
        return err


def unsupported_rates(spec, rates_kbit):
    """The rates (kbit/s) of `rates_kbit` this adapter type cannot be set to:
    python-can's slcan driver has no 800 kbit/s, for one."""
    if spec.kind == "slcan":
        return [k for k in rates_kbit if k not in SLCAN_KBIT]
    return []


def open(spec, bitrate, listen_only=False, options=None, disturb_bus=False):  # noqa: A001 - the module's one entry point
    """Open `spec` (a Spec) at `bitrate` (bit/s), with `listen_only` without
    acknowledging or sending anything. An adapter that does not confirm
    listen-only is refused (kind unconfirmed) unless `disturb_bus`. Raises
    AdapterError."""
    if listen_only and spec.kind not in LISTEN_ONLY:
        raise AdapterError("usage", "%s (%s adapters; slcan, PCAN and SocketCAN have one)" % (NO_LISTEN_ONLY,
                                                                                              spec.kind))
    if not bitrate:
        raise AdapterError("usage", "the bit rate is needed: give --bitrate KBIT, or --config with the network's "
                                    "adapter.bitrate")
    try:
        import can
    except ImportError:
        raise AdapterError("unreachable", "python-can is not installed; reinstall the PC tools")
    lock = _Lock(spec)
    if not lock.acquire():
        raise AdapterError("busy", "adapter %s in use (another tool has it open)" % spec)
    kwargs = dict(spec.options)
    kwargs.update(options or {})
    restore = None
    try:
        if spec.kind == "socketcan":
            if not sys.platform.startswith("linux"):
                raise AdapterError("usage", "socketcan adapters exist on Linux only; use slcan:PORT on this PC")
            if listen_only:
                restore = _socketcan_listen_only(spec.channel, bitrate)
            else:
                bitrate = _socketcan_up(spec.channel, bitrate)
        elif spec.kind == "virtual":
            kwargs.setdefault("receive_own_messages", False)  # no listen-only on the in-process bus: tests
        else:
            kwargs["bitrate"] = bitrate
        if spec.kind == "slcan":
            bus = _slcan_bus(listen_only, disturb_bus)(channel=spec.channel, **kwargs)
            if bus.unconfirmed and not disturb_bus:
                bus.shutdown()
                raise AdapterError("unconfirmed", UNCONFIRMED)
        else:
            if listen_only and spec.kind == "pcan":
                kwargs["state"] = can.BusState.PASSIVE  # PCAN_LISTEN_ONLY on
            bus = can.Bus(interface=spec.kind, channel=spec.channel, **kwargs)
    except AdapterError:
        if restore:
            restore()
        lock.release()
        raise
    except Exception as e:  # python-can raises CanError, OSError, serial errors, ValueError, ...
        if restore:
            restore()
        lock.release()
        text = str(e) or e.__class__.__name__
        if spec.kind == "slcan" and ("busy" in text.lower() or "denied" in text.lower()):
            raise AdapterError("busy", "adapter %s in use (another program has the serial port open): %s"
                               % (spec, text))
        raise AdapterError("unreachable", "cannot open adapter %s: %s" % (spec, text))
    return Opened(spec, bus, bitrate, lock, listen_only, restore)


# ---------------------------------------------------------------------------
# What is plugged in


def _serial_ports():
    out = []
    try:
        from serial.tools import list_ports
    except ImportError:
        return out
    for p in list_ports.comports():
        vid, pid = getattr(p, "vid", None), getattr(p, "pid", None)
        if vid is None or pid is None:
            continue  # built-in serial ports (ttyS*); USB adapters have USB IDs
        entry = {"type": "slcan", "channel": p.device, "description": p.description or "",
                 "usb_id": "%04X:%04X" % (vid, pid) if vid is not None and pid is not None else None,
                 "known": None}
        if (vid, pid) in SLCAN_USB_IDS:
            entry["known"] = SLCAN_USB_IDS[(vid, pid)]
        elif (vid, pid) in OTHER_USB_IDS:
            entry["type"], entry["known"] = OTHER_USB_IDS[(vid, pid)]
        out.append(entry)
    return out


def _socketcan_links():
    out = []
    root = "/sys/class/net"
    if not sys.platform.startswith("linux") or not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        try:
            with _read(os.path.join(root, name, "type")) as f:
                kind = f.read().strip()
        except OSError:
            continue
        if kind == "280":  # ARPHRD_CAN
            out.append({"type": "socketcan", "channel": name, "description": "SocketCAN interface",
                        "usb_id": None, "known": "SocketCAN"})
    return out


def _read(path):
    import builtins
    return builtins.open(path, encoding="utf-8")


def _detected(interfaces):
    import logging
    out = []
    log = logging.getLogger("can")
    level = log.level
    log.setLevel(logging.CRITICAL)  # python-can logs every missing vendor driver while it looks
    try:
        import can
        configs = can.detect_available_configs(interfaces=list(interfaces))
    except Exception:
        return out
    finally:
        log.setLevel(level)
    for c in configs:
        kind, channel = c.get("interface"), c.get("channel")
        if kind and channel is not None and kind not in ("socketcan", "slcan", "virtual"):
            out.append({"type": kind, "channel": str(channel), "description": "found by python-can",
                        "usb_id": None, "known": None})
    return out


def list_adapters(probe=("pcan", "kvaser", "ixxat", "vector", "gs_usb")):
    """The adapters this PC has: serial ports (slcan candidates, known USB IDs
    marked), SocketCAN links on Linux, and what python-can finds for the
    other interfaces it has drivers for. Each: type, channel, description,
    usb_id, known (a name when the adapter is recognised), text (the
    --adapter value)."""
    out = _socketcan_links() + _serial_ports() + _detected(probe)
    for a in out:
        a["text"] = "%s:%s" % (a["type"], a["channel"])
    return out
