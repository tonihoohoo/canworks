"""Opening a CAN adapter on this PC with python-can (canopen-local-bus).

An adapter is written TYPE:CHANNEL: slcan:COM5, slcan:/dev/tty.usbmodem14101,
socketcan:can0, or any other python-can interface (gs_usb:0, pcan:PCAN_USBBUS1,
...), which is passed through untested. `virtual:NAME` is python-can's
in-process bus, for tests.

open() is the one place an adapter is opened. With `listen_only` the
adapter receives without acknowledging or sending anything while the bit
rate check listens (core.check_bitrate): slcan opens the channel in silent
mode ('m1', then 'O') where the firmware takes 'm1', else with 'L', and
gs_usb starts its channel listen-only when the device has that mode. Other
adapter types open normally.
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
SLCAN_KBIT = (10, 20, 50, 100, 125, 250, 500, 750, 1000)  # the rates python-can sets on slcan (S0-S8)

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
    unreachable (cannot be opened), bitrate (the bit rate check refused it)."""

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
        folder = os.path.join(tempfile.gettempdir(), "canworks-adapters")
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


# ---------------------------------------------------------------------------
# slcan


def _slcan_bus(listen_only):
    """python-can's slcan bus, opened listen-only for the bit rate check when
    asked, and switched to normal mode afterwards on the same serial port.

    Listen-only: some slcan firmware takes 'L' and then receives nothing, so
    silent mode is asked for first: 'm1' (receive without acknowledging or
    sending), then 'O'. Firmware without 'm1' answers with an error (BEL) and
    gets 'L'. Firmware that answers nothing is opened normally ('O'): the
    check then receives in normal mode. A normal open sends 'm0' before 'O',
    so a check that died in silent mode cannot leave the adapter mute. open()
    does nothing while the channel is open: python-can 4.6 opens it in
    set_bitrate() and then once more, and commands to an open channel on a
    busy bus meet a stream of frames."""
    from can.interfaces.slcan import slcanBus

    class Slcan(slcanBus):
        _silent = False  # 'm1' taken: 'm0' when leaving it
        _listen = False  # opened with 'L'
        _open = False

        def _ask(self, cmd):
            # Answers to the commands before (close, bit rate) are not
            # this one's: let them arrive and drop them first (for a
            # bounded time: an open channel on a busy bus never goes quiet).
            drain = time.monotonic() + 0.3
            while time.monotonic() < drain and self._read(0.05) is not None:
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
            if self._open:
                return
            self._open = True
            if listen_only:
                answer = self._ask("m1")
                self._silent = answer is True
                self._listen = answer is False
                self._write("L" if self._listen else "O")
            else:
                self._ask("m0")
                self._write("O")

        def normal(self):
            """Leaves listen-only: closes the channel, 'm0', opens it again."""
            if not (self._silent or self._listen):
                return
            self._write("C")
            if self._silent:
                self._ask("m0")
            self._silent = self._listen = False
            self._write("O")

        def close(self):
            super().close()
            self._open = False
            if self._silent:
                self._write("m0")
                self._silent = False

    return Slcan


# ---------------------------------------------------------------------------
# gs_usb (candleLight)

# gs_usb device mode flags (the device's feature bits are the same).
GS_LISTEN_ONLY = 1 << 0
GS_ONE_SHOT = 1 << 3
GS_HW_TIMESTAMP = 1 << 4
GS_BERR_REPORTING = 1 << 12
GS_MODE_RESET, GS_MODE_START = 0, 1
GS_BREQ_MODE = 2
SAMPLE_POINTS = (87.5, 85.0, 80.0, 75.0)
USB_STALL = ("does not answer (USB stall): unplug it and plug it in again")


def _gs_usb_options(spec, kwargs):
    """gs_usb. The gs_usb package resets the USB device and then detaches a
    kernel driver when libusb reports one; on macOS libusb reports one after
    the reset and detaching needs root ("Access denied"), though there is no
    driver to detach. And python-can's gs_usb opened by number opens and
    starts the adapter once more when it closes it, after which some adapters
    receive nothing until they are plugged in again. So the detach is skipped
    outside Linux (macOS and Windows have no gs_usb kernel driver), the
    adapter numbered CHANNEL is opened by its USB bus and address, and
    python-can's own start is held back while the bus is built: open() sets
    the timing and starts the channel itself, in the mode it needs."""
    from gs_usb.gs_usb import GsUsb
    if not getattr(GsUsb, "_canworks_patched", False):
        start = GsUsb.start

        def patched_start(self, *args, **kw):
            if getattr(GsUsb, "_canworks_hold", False):
                return None  # open() starts the channel
            dev = self.gs_usb
            if not sys.platform.startswith("linux"):
                dev.is_kernel_driver_active = lambda interface: False
            try:
                return start(self, *args, **kw)
            finally:
                if not sys.platform.startswith("linux"):
                    del dev.is_kernel_driver_active

        GsUsb.start = patched_start
        GsUsb._canworks_patched = True
    if "index" in kwargs or "bus" in kwargs or "address" in kwargs:
        return
    try:
        index = int(spec.channel)
    except ValueError:
        raise AdapterError("usage", "write a gs_usb adapter as gs_usb:N, N its number from 'adapters' (0 for the "
                                    "first)")
    devices = GsUsb.scan()
    if index >= len(devices):
        raise AdapterError("unreachable", "no gs_usb adapter %d on this PC (%d found)" % (index, len(devices)))
    kwargs["bus"], kwargs["address"] = devices[index].bus, devices[index].address


def gs_usb_timing(cap, bitrate):
    """(prop_seg, phase_seg1, phase_seg2, sjw, brp) for `bitrate` within the
    device's own limits (`cap`: the gs_usb device capability), trying the
    sample points 87.5, 85, 80 and 75 %; None when none fits."""
    fclk = cap.fclk_can
    t1min, t1max = getattr(cap, "tseg1_min", 1), getattr(cap, "tseg1_max", 16)
    t2min, t2max = getattr(cap, "tseg2_min", 1), getattr(cap, "tseg2_max", 8)
    sjwmax = getattr(cap, "sjw_max", 4)
    bmin, bmax = getattr(cap, "brp_min", 1), getattr(cap, "brp_max", 1024)
    binc = max(1, getattr(cap, "brp_inc", 1))
    for sp in SAMPLE_POINTS:
        best = None
        for brp in range(max(1, bmin), bmax + 1, binc):
            if fclk % (bitrate * brp):
                continue
            nbt = fclk // (bitrate * brp)  # time quanta per bit, sync segment included
            if nbt < 8:
                break
            tseg2 = nbt - round(nbt * sp / 100.0)
            tseg1 = nbt - 1 - tseg2
            if not (t1min <= tseg1 <= t1max and t2min <= tseg2 <= t2max):
                continue
            err = abs((nbt - tseg2) * 100.0 / nbt - sp)
            if err <= 2.5 and (best is None or err < best[0]):
                best = (err, (1, tseg1 - 1, tseg2, min(tseg2, sjwmax), brp))
        if best:
            return best[1]
    return None


def _gs_usb_mode(dev, flags):
    """Starts the channel with `flags` (those the device has), on the open
    USB handle: no USB reset."""
    from gs_usb.gs_usb_structures import DeviceMode
    flags &= dev.device_capability.feature
    dev.gs_usb.ctrl_transfer(0x41, GS_BREQ_MODE, 0, 0, DeviceMode(GS_MODE_START, flags).pack())
    dev.device_flags = flags  # read() and send() size the frames by the timestamp flag


def _gs_usb_reset(dev):
    """Puts the channel in reset mode; never raises."""
    try:
        from gs_usb.gs_usb_structures import DeviceMode
        dev.gs_usb.ctrl_transfer(0x41, GS_BREQ_MODE, 0, 0, DeviceMode(GS_MODE_RESET, 0).pack())
    except Exception:  # unplugged, or stalled
        pass


def _gs_usb_release(bus):
    """Lets go of a closed gs_usb adapter's USB interface, so this process
    can open it again (python-can's gs_usb leaves it claimed)."""
    try:
        import usb.util
        usb.util.dispose_resources(bus.gs_usb.gs_usb)
    except Exception:  # pyusb missing, or the adapter unplugged meanwhile
        pass


def _stalled(e):
    return getattr(e, "errno", None) == 32 or "pipe error" in str(e).lower()


def _gs_usb_open(spec, bitrate, listen_only, kwargs):
    """python-can's gs_usb bus with the timing set from the device's limits
    and the channel started (listen-only when asked and the device has it).
    A USB stall resets the USB device and tries once more."""
    import can
    from gs_usb.gs_usb import GsUsb
    _gs_usb_options(spec, kwargs)
    for attempt in (1, 2):
        bus = None
        try:
            GsUsb._canworks_hold = True
            try:
                # python-can computes its own timing for the rate it is given
                # (sample point 87.5 % only) and sets it; ours follows, with
                # the device's limits, before the channel starts.
                bus = can.Bus(interface="gs_usb", channel=spec.channel, bitrate=500000, **kwargs)
            finally:
                GsUsb._canworks_hold = False
            dev = bus.gs_usb
            timing = gs_usb_timing(dev.device_capability, bitrate)
            if timing is None:
                raise AdapterError("usage", "adapter %s cannot run at %d kbit/s (no bit timing within its limits)"
                                   % (spec, bitrate // 1000))
            dev.set_timing(*timing)
            flags = GS_HW_TIMESTAMP | GS_BERR_REPORTING | (GS_LISTEN_ONLY if listen_only else 0)
            _gs_usb_mode(dev, flags)
            if hasattr(bus, "_bitrate"):
                bus._bitrate = bitrate
            return bus
        except AdapterError:
            _gs_usb_shut(bus)
            raise
        except Exception as e:
            _gs_usb_shut(bus)
            if not _stalled(e):
                raise
            if attempt == 2:
                raise AdapterError("unreachable", "adapter %s %s" % (spec, USB_STALL))
            _usb_reset(kwargs)


def _gs_usb_shut(bus):
    if bus is None:
        return
    _gs_usb_reset(bus.gs_usb)
    try:
        bus.shutdown()
    except Exception:
        pass
    _gs_usb_release(bus)


def _usb_reset(kwargs):
    """Resets the gs_usb device at kwargs' USB bus and address."""
    try:
        import usb.core
        dev = usb.core.find(bus=kwargs.get("bus"), address=kwargs.get("address"))
        if dev is not None:
            dev.reset()
            time.sleep(0.5)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Opening

# How an adapter tells that a frame it sent got out (the bit rate check's
# probe): its own echo (gs_usb), no error frame afterwards (adapters that
# report error frames), or not at all (slcan and the untested types).
CONFIRM_ECHO, CONFIRM_NO_ERRORS = "echo", "no errors"


class Opened:
    """An open adapter: `bus` (a python-can Bus), the bit rate in use, and the
    lock that keeps other tools off it. `echoes`: the adapter hands back each
    frame it sent (not a received frame); `confirm`: how a sent frame is
    known to be out (CONFIRM_ECHO, CONFIRM_NO_ERRORS or None)."""

    def __init__(self, spec, bus, bitrate, lock, listen_only=False):
        self.spec, self.bus, self.bitrate, self._lock = spec, bus, bitrate, lock
        self.listen_only = listen_only
        self.echoes = spec.kind == "gs_usb" or (spec.kind == "virtual" and bool(spec.options.get(
            "receive_own_messages")))
        if self.echoes:
            self.confirm = CONFIRM_ECHO
        elif spec.kind in ("socketcan", "virtual"):
            self.confirm = CONFIRM_NO_ERRORS
        else:
            self.confirm = None

    def set_mode(self, listen_only=False, one_shot=False):
        """Changes the adapter's mode on the open handle: listen-only off
        (slcan, gs_usb), one-shot (gs_usb: a frame nobody acknowledges is not
        sent again). Raises AdapterError."""
        try:
            if self.spec.kind == "gs_usb" and hasattr(self.bus, "gs_usb"):
                dev = self.bus.gs_usb
                _gs_usb_reset(dev)
                _gs_usb_mode(dev, GS_HW_TIMESTAMP | GS_BERR_REPORTING | (GS_LISTEN_ONLY if listen_only else 0) |
                             (GS_ONE_SHOT if one_shot else 0))
            elif self.spec.kind == "slcan" and not listen_only and hasattr(self.bus, "normal"):
                self.bus.normal()
        except Exception as e:
            if self.spec.kind == "gs_usb":
                _gs_usb_reset(self.bus.gs_usb)
            if _stalled(e):
                raise AdapterError("unreachable", "adapter %s %s" % (self.spec, USB_STALL))
            raise AdapterError("unreachable", "cannot set adapter %s's mode: %s" % (self.spec, e))
        self.listen_only = listen_only

    def close(self):
        """Closes the adapter (a gs_usb channel is put in reset mode first)."""
        if self.spec.kind == "gs_usb" and hasattr(self.bus, "gs_usb"):
            _gs_usb_shut(self.bus)
        else:
            try:
                self.bus.shutdown()
            except Exception:  # an adapter unplugged meanwhile
                pass
        self._lock.release()


def open(spec, bitrate, listen_only=False, options=None, shared=False):  # noqa: A001 - the module's one entry point
    """Open `spec` (a Spec) at `bitrate` (bit/s). With `listen_only` the
    adapter receives without acknowledging or sending where it has such a
    mode (slcan, gs_usb; others open normally); the bit rate check leaves it
    with Opened.set_mode(). With `shared`, a SocketCAN link or the in-process
    virtual bus is opened without the one-tool lock, as several programs can
    use those at once (J1939 simulators side by side on vcan0). Raises
    AdapterError."""
    if not bitrate:
        raise AdapterError("usage", "the bit rate is needed: give --bitrate KBIT, or --config with the network's "
                                    "adapter.bitrate")
    if spec.kind == "slcan" and bitrate // 1000 not in SLCAN_KBIT:
        raise AdapterError("usage", "adapter %s cannot run at %d kbit/s (slcan has %s kbit/s)" % (
            spec, bitrate // 1000, ", ".join(str(k) for k in SLCAN_KBIT)))
    try:
        import can
    except ImportError:
        raise AdapterError("unreachable", "python-can is not installed; reinstall the PC tools")
    lock = _Lock(spec)
    unlocked = shared and spec.kind in ("socketcan", "virtual")  # release() is then a no-op
    if not unlocked and not lock.acquire():
        raise AdapterError("busy", "adapter %s in use (another tool has it open)" % spec)
    kwargs = dict(spec.options)
    kwargs.update(options or {})
    try:
        if spec.kind == "socketcan":
            if not sys.platform.startswith("linux"):
                raise AdapterError("usage", "socketcan adapters exist on Linux only; use slcan:PORT on this PC")
            bitrate = _socketcan_up(spec.channel, bitrate)
            listen_only = False
        elif spec.kind == "virtual":
            kwargs.setdefault("receive_own_messages", False)
            listen_only = False
        elif spec.kind != "gs_usb":
            kwargs["bitrate"] = bitrate
        if spec.kind == "slcan":
            bus = _slcan_bus(listen_only)(channel=spec.channel, **kwargs)
        elif spec.kind == "gs_usb":
            bus = _gs_usb_open(spec, bitrate, listen_only, kwargs)
        else:
            listen_only = False
            bus = can.Bus(interface=spec.kind, channel=spec.channel, **kwargs)
    except AdapterError:
        lock.release()
        raise
    except Exception as e:  # python-can raises CanError, OSError, serial errors, ValueError, ...
        lock.release()
        text = str(e) or e.__class__.__name__
        if spec.kind == "slcan" and ("busy" in text.lower() or "denied" in text.lower()):
            raise AdapterError("busy", "adapter %s in use (another program has the serial port open): %s"
                               % (spec, text))
        raise AdapterError("unreachable", "cannot open adapter %s: %s" % (spec, text))
    return Opened(spec, bus, bitrate, lock, listen_only)


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


def _usb_adapters():
    """gs_usb adapters by USB ID, numbered as python-can's gs_usb driver
    numbers them (its channel), which cannot list them itself. On Linux they
    are SocketCAN links instead. Needs pyusb and libusb."""
    out = []
    if sys.platform.startswith("linux"):
        return out
    try:
        import usb.core
        devices = list(usb.core.find(find_all=True))
    except Exception:  # no pyusb, or no libusb backend
        return out
    index = 0
    for d in devices:
        kind = OTHER_USB_IDS.get((d.idVendor, d.idProduct))
        if not kind or kind[0] != "gs_usb":
            continue
        out.append({"type": "gs_usb", "channel": str(index), "description": "USB device",
                    "usb_id": "%04X:%04X" % (d.idVendor, d.idProduct), "known": kind[1]})
        index += 1
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
    marked), SocketCAN links on Linux, gs_usb adapters by USB ID elsewhere,
    and what python-can finds for the other interfaces it has drivers for. Each: type, channel, description,
    usb_id, known (a name when the adapter is recognised), text (the
    --adapter value)."""
    out = _socketcan_links() + _serial_ports() + _usb_adapters() + _detected(probe)
    for a in out:
        a["text"] = "%s:%s" % (a["type"], a["channel"])
    return out
