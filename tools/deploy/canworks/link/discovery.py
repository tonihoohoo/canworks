"""Finding runtimes on the local network: the device advertises
_canworks._tcp over mDNS/DNS-SD (an Avahi service file, `avahi_service`), the
PC tools browse for it with python-zeroconf rather than the operating
system's .local lookup, which is unreliable on Windows."""

import socket
import time
from xml.sax.saxutils import escape

SERVICE = "_canworks._tcp.local."
NOT_AVAILABLE = "discovery needs the zeroconf package"


def available():
    try:
        import zeroconf  # noqa: F401
    except Exception:
        return False
    return True


def avahi_service(diag_port=7531, runtime_port=8443, link_id=None, link_port=7533, name=None):
    """The /etc/avahi/services/canworks.service file. `name` None: Avahi's %h
    (the host name). runtime_port None on a bridge."""
    txt = ["v=1", "diag=%d" % diag_port]
    if runtime_port:
        txt.append("runtime=%d" % runtime_port)
    if link_id:
        txt += ["id=%s" % link_id, "link=%d" % link_port]
    records = "".join("    <txt-record>%s</txt-record>\n" % escape(t) for t in txt)
    return ('<?xml version="1.0" standalone="no"?>\n'
            '<!DOCTYPE service-group SYSTEM "avahi-service.dtd">\n'
            '<service-group>\n'
            '  <name replace-wildcards="yes">%s</name>\n'
            '  <service>\n'
            '    <type>_canworks._tcp</type>\n'
            '    <port>%d</port>\n'
            '%s'
            '  </service>\n'
            '</service-group>\n') % (escape(name) if name else "%h", diag_port, records)


def _txt(props):
    out = {}
    for k, v in (props or {}).items():
        try:
            out[k.decode("utf-8") if isinstance(k, bytes) else str(k)] = (
                v.decode("utf-8") if isinstance(v, bytes) else (v or ""))
        except UnicodeDecodeError:
            pass
    return out


def _int(text, default):
    try:
        return int(text)
    except (TypeError, ValueError):
        return default


def browse(timeout=2.0):
    """Runtimes that answer within `timeout` seconds: [{name, addresses,
    diag, runtime, id, link}], sorted by name. [] without zeroconf."""
    if not available():
        return []
    from zeroconf import ServiceBrowser, Zeroconf
    found = {}

    class Listener:
        def add_service(self, zc, type_, name):
            found[name] = None

        def update_service(self, zc, type_, name):
            found[name] = None

        def remove_service(self, zc, type_, name):
            found.pop(name, None)

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, SERVICE, Listener())
        time.sleep(timeout)
        out = []
        for name in list(found):
            info = zc.get_service_info(SERVICE, name, timeout=1000)
            if not info:
                continue
            txt = _txt(info.properties)
            addrs = info.parsed_scoped_addresses() if hasattr(info, "parsed_scoped_addresses") else [
                socket.inet_ntoa(a) for a in info.addresses if len(a) == 4]
            out.append({
                "name": name[:-len(SERVICE) - 1] if name.endswith("." + SERVICE) else name,
                "addresses": addrs, "diag": _int(txt.get("diag"), info.port),
                "runtime": _int(txt.get("runtime"), None), "id": txt.get("id") or None,
                "link": _int(txt.get("link"), None),
            })
        return sorted(out, key=lambda r: r["name"].lower())
    finally:
        zc.close()


def find_address(host, timeout=2.0):
    """The advertised runtime whose addresses include `host` (an IP or a name
    that resolves to one), else None."""
    try:
        ips = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except OSError:
        ips = {host}
    for r in browse(timeout):
        if ips & {a.split("%")[0] for a in r["addresses"]} or host.rstrip(".").lower() in (
                r["name"].lower(), r["name"].lower() + ".local"):
            return r
    return None
