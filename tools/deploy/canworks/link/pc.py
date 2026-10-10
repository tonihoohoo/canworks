"""The PC side of the remote link: this user's link key, remembered
runtimes, pairing with the diagnostics token, and sockets to a runtime's
`diag` or `runtime` target over the link.

The PC tools stay synchronous: iroh runs on an asyncio loop in a daemon
thread, and a caller gets an ordinary socket (one end of a socket pair whose
other end the loop copies to and from the link stream)."""

import asyncio
import atexit
import base64
import hmac
import json
import os
import queue
import socket
import threading

from .. import diag
from ..userdirs import config_dir
from . import ALPN, DEFAULT_LINK_PORT, UNAVAILABLE, available, protocol
from .protocol import LinkError, LineReader, encode

CONNECT_TIMEOUT = 15.0
DIRECT_HEAD_START = 0.3   # seconds the direct path gets before the link starts
CHUNK = 256 * 1024


def link_dir():
    return os.path.join(config_dir(), "link")


# ---------------------------------------------------------------------------
# This PC's key and the remembered runtimes


def _key_path():
    return os.path.join(link_dir(), "secret.key")


def load_key():
    """This user's link secret key, made on first use, readable only by the user."""
    import iroh
    path = _key_path()
    try:
        with open(path, "rb") as f:
            data = f.read()
        if len(data) == 32:
            return data
    except FileNotFoundError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = iroh.SecretKey.generate().to_bytes()
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)
    return data


def my_id():
    import iroh
    return str(iroh.SecretKey.from_bytes(load_key()).public())


_store_lock = threading.Lock()


def _runtimes_path():
    return os.path.join(link_dir(), "runtimes.json")


def runtimes():
    """Remembered runtimes: [{name, hosts, id, link_addrs, relay, relays,
    internet, paired, diag_port, runtime_port, last_path}]."""
    try:
        with open(_runtimes_path(), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return []
    items = doc.get("runtimes") if isinstance(doc, dict) else None
    return [r for r in items or [] if isinstance(r, dict) and isinstance(r.get("name"), str)]


def _save(items):
    os.makedirs(link_dir(), exist_ok=True)
    tmp = _runtimes_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"runtimes": items}, f, indent=2)
    os.replace(tmp, _runtimes_path())


def find(text):
    """The remembered runtime named `text`, or with `text` among its hosts."""
    key = (text or "").strip()
    if key.startswith("link:"):
        key = key[5:]
    low = key.lower()
    for r in runtimes():
        if r["name"].lower() == low or low in (h.lower() for h in r.get("hosts") or []):
            return r
    return None


def remember(name, **fields):
    """Add or update the runtime `name` (matched by name, then link ID)."""
    with _store_lock:
        items = runtimes()
        hit = None
        for r in items:
            if r["name"].lower() == name.lower() or (fields.get("id") and r.get("id") == fields["id"]):
                hit = r
                break
        if hit is None:
            hit = {"name": name, "hosts": [], "paired": False}
            items.append(hit)
        hosts = list(hit.get("hosts") or [])
        for h in fields.pop("hosts", []) or []:
            if h and h not in hosts:
                hosts.insert(0, h)
        hit["hosts"] = hosts[:8]
        for k, v in fields.items():
            if v is not None:
                hit[k] = v
        _save(items)
        return dict(hit)


def forget(name):
    with _store_lock:
        items = runtimes()
        keep = [r for r in items if r["name"].lower() != name.lower()]
        if len(keep) == len(items):
            return False
        _save(keep)
        return True


# ---------------------------------------------------------------------------
# The loop thread and the endpoints


class _Loop:
    def __init__(self):
        self.loop = None
        self.lock = threading.Lock()

    def get(self):
        with self.lock:
            if self.loop is None:
                self.loop = asyncio.new_event_loop()
                t = threading.Thread(target=self.loop.run_forever, name="canworks-link", daemon=True)
                t.start()
            return self.loop

    def run(self, coro, timeout=None):
        fut = asyncio.run_coroutine_threadsafe(coro, self.get())
        try:
            return fut.result(timeout)
        except TimeoutError:
            fut.cancel()
            raise LinkError("unreachable", "the link did not connect in %g s" % timeout)
        except asyncio.TimeoutError:
            fut.cancel()
            raise LinkError("unreachable", "the link did not connect in %g s" % timeout)


LOOP = _Loop()
_endpoints = {}     # internet (bool) -> iroh Endpoint
_conns = {}         # runtime name -> iroh Connection


async def _close_all():
    for c in list(_conns.values()):
        try:
            c.close(0, b"bye")
        except Exception:
            pass
    for ep in list(_endpoints.values()):
        try:
            await ep.close()
        except Exception:
            pass


@atexit.register
def _shutdown():
    """Close the link before the interpreter tears down the iroh bindings
    (their finalizers fail noisily otherwise)."""
    if LOOP.loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(_close_all(), LOOP.loop).result(2)
    except Exception:
        pass
    _conns.clear()
    _endpoints.clear()
    import gc
    gc.collect()


async def _endpoint(internet):
    import iroh
    key = load_key()
    ep = _endpoints.get((internet, key))
    if ep is not None and not ep.is_closed():
        return ep
    opts = dict(secret_key=key)
    if internet:
        opts["preset"] = iroh.preset_n0()
    else:
        opts["preset"] = iroh.preset_minimal()
        opts["relay_mode"] = iroh.RelayMode.disabled()
    ep = await iroh.Endpoint.bind(iroh.EndpointOptions(**opts))
    _endpoints[(internet, key)] = ep
    return ep


def _device_addr(entry):
    import iroh
    return iroh.EndpointAddr(iroh.EndpointId.from_string(entry["id"]),
                             entry.get("relay") if entry.get("internet") else None,
                             list(entry.get("link_addrs") or []))


async def _connection(entry, fresh=False):
    """An iroh connection to the runtime `entry`, reused while it is open."""
    internet = bool(entry.get("internet"))
    ep = await _endpoint(internet)
    key = (entry["name"], ep.id().to_bytes())
    conn = _conns.get(key)
    if conn is not None and not fresh:
        try:
            if conn.close_reason() is None:
                return conn
        except Exception:
            pass
    try:
        conn = await ep.connect(_device_addr(entry), ALPN)
    except Exception as e:
        raise LinkError("unreachable", "cannot reach %s over the link: %s" % (entry["name"], _err(e)))
    conn.local_id = ep.id().to_bytes()
    _conns[key] = conn
    return conn


def _err(e):
    try:
        return e.message()
    except Exception:
        return str(e) or e.__class__.__name__


def path_of(conn):
    """("LAN" | "internet direct" | "internet relayed", round trip in ms or
    None): a direct path to a private or link-local address is the LAN."""
    try:
        for p in conn.paths():
            if p.is_selected:
                if p.is_relay:
                    return "internet relayed", p.rtt_ms
                return ("LAN" if protocol.is_lan_address(p.remote_addr) else "internet direct"), p.rtt_ms
    except Exception:
        pass
    return "internet", None


async def _open(conn, head):
    bi = await conn.open_bi()
    send, recv = bi.send(), bi.recv()
    await send.write_all(encode(head))
    reader = LineReader(recv)
    answer = await reader.line()
    return send, reader, answer


# ---------------------------------------------------------------------------
# Sockets over the link


async def _bridge(send, reader, sock):
    r, w = await asyncio.open_connection(sock=sock)

    async def up():
        try:
            while True:
                data = await r.read(CHUNK)
                if not data:
                    break
                await send.write_all(data)
        except Exception:
            pass
        finally:
            try:
                await send.finish()
            except Exception:
                pass

    async def down():
        rest = reader.rest()
        try:
            if rest:
                w.write(rest)
                await w.drain()
            while True:
                data = await reader.recv.read(CHUNK)
                if not data:
                    break
                w.write(data)
                await w.drain()
        except Exception:
            pass
        finally:
            try:
                w.close()
            except Exception:
                pass

    await asyncio.gather(up(), down(), return_exceptions=True)


async def _open_target(entry, target):
    for attempt in (0, 1):
        conn = await _connection(entry, fresh=attempt == 1)
        try:
            send, reader, answer = await _open(conn, {"t": target})
            break
        except Exception as e:
            if attempt:
                raise LinkError("unreachable", "the link to %s failed: %s" % (entry["name"], _err(e)))
    if not answer.get("ok"):
        why = str(answer.get("error") or "refused")
        kind = "unpaired" if why == "not paired" else "refused"
        raise LinkError(kind, "%s refused the link: %s" % (entry["name"], why))
    mine, theirs = socket.socketpair()
    theirs.setblocking(False)
    asyncio.ensure_future(_bridge(send, reader, theirs))
    return mine, path_of(conn)


def link_socket(entry, target="diag", timeout=CONNECT_TIMEOUT):
    """(socket, path, rtt_ms) to `target` of the remembered runtime `entry`."""
    if not available():
        raise LinkError("unavailable", UNAVAILABLE)
    if not entry.get("id"):
        raise LinkError("unpaired", "%s has no link ID yet: connect to it once on its local network" % entry["name"])
    sock, (path, rtt) = LOOP.run(_open_target(entry, target), timeout)
    return sock, path, rtt


def open_socket(host, port, timeout, target="diag"):
    """A connected socket to (host, port), by the automatic path choice:
    direct first, and the link when `host` is a remembered, paired runtime and
    the direct path has not connected after DIRECT_HEAD_START seconds.
    "link:NAME" uses only the link. Returns (socket, path, rtt_ms); raises
    OSError (direct) or LinkError like the path that failed last."""
    if host.startswith("link:"):
        entry = find(host)
        if not entry:
            raise LinkError("unpaired", "no remembered runtime %r (canworks-diag link list)" % host[5:])
        return link_socket(entry, target, max(timeout, CONNECT_TIMEOUT))
    entry = find(host)
    if entry and host.lower() == entry["name"].lower() and entry.get("hosts"):
        host = entry["hosts"][0]   # a remembered name: its last direct address
    if not entry or not entry.get("paired") or not entry.get("id") or not available():
        return socket.create_connection((host, port), timeout=timeout), "LAN", None
    results = queue.Queue()
    direct_done = threading.Event()
    state = {"won": False}
    lock = threading.Lock()

    def offer(item):
        """Hand a connected path to the caller, or close it when another won."""
        with lock:
            if not state["won"]:
                state["won"] = True
                results.put(("ok", item))
                return
        try:
            item[0].close()
        except OSError:
            pass

    def direct():
        try:
            offer((socket.create_connection((host, port), timeout=timeout), "LAN", None))
        except OSError as e:
            results.put(("err", e))
        direct_done.set()

    def link():
        direct_done.wait(DIRECT_HEAD_START)
        with lock:
            if state["won"]:
                results.put(("skip", None))
                return
        try:
            offer(link_socket(entry, target, max(timeout, CONNECT_TIMEOUT)))
        except LinkError as e:
            results.put(("err", e))

    for f in (direct, link):
        threading.Thread(target=f, daemon=True).start()
    errors = []
    for _ in range(2):
        try:
            kind, item = results.get(timeout=max(timeout, CONNECT_TIMEOUT) + 1)
        except queue.Empty:
            break
        if kind == "ok":
            return item
        if kind == "err":
            errors.append(item)
    raise errors[-1] if errors else OSError("%s is unreachable" % host)


# ---------------------------------------------------------------------------
# Pairing and managing


async def _login(conn, head, token):
    """Send `head` with a nonce, run SCRAM; the final answer."""
    import iroh
    cnonce = protocol.new_nonce()
    send, reader, first = await _open(conn, dict(head, nonce=cnonce))
    if not first.get("ok"):
        raise LinkError("refused", str(first.get("error") or "refused"))
    salt_b64, snonce, it = first.get("salt"), first.get("nonce"), first.get("iterations")
    try:
        salt = base64.b64decode(salt_b64, validate=True)
    except (ValueError, TypeError):
        raise LinkError("protocol", "unexpected login answer")
    if not isinstance(snonce, str) or not snonce.startswith(cnonce) or not isinstance(it, int) \
            or not diag.SCRAM_MIN_ITERATIONS <= it <= diag.SCRAM_MAX_ITERATIONS:
        raise LinkError("protocol", "unexpected login answer")
    cbind = protocol.channel_binding(conn.remote_id().to_bytes(), conn.local_id)
    auth = protocol.auth_message(cnonce, snonce, salt_b64, it, cbind)
    proof, want = diag.scram_client(token, salt, it, auth)
    await send.write_all(encode({"proof": diag._b64(proof)}))
    final = await reader.line()
    try:
        await send.finish()
    except Exception:
        pass
    if not final.get("ok"):
        why = str(final.get("error") or "refused")
        raise LinkError("token" if why == "wrong token" else "refused", why)
    try:
        got = base64.b64decode(final.get("signature") or "", validate=True)
    except (ValueError, TypeError):
        got = b""
    if not hmac.compare_digest(got, want):
        raise LinkError("impostor", "the runtime could not prove it knows this project's token")
    return final


async def _pair(entry, token):
    conn = await _connection(entry, fresh=True)
    return await _login(conn, {"t": "pair", "name": socket.gethostname()}, token)


def pair(entry, token, timeout=CONNECT_TIMEOUT):
    """Pair this PC with the runtime `entry` (needs id and link_addrs, or
    internet); remembers the answer. Returns the updated entry."""
    if not available():
        raise LinkError("unavailable", UNAVAILABLE)
    info = LOOP.run(_pair(entry, token), timeout)
    return _remember_info(entry, info, paired=True)


def _remember_info(entry, info, paired=None):
    addrs = info.get("addrs") or []
    return remember(entry["name"], id=info.get("id") or entry.get("id"), link_addrs=addrs or entry.get("link_addrs"),
                    relay=info.get("relay"), relays=info.get("relays"), internet=bool(info.get("internet")),
                    paired=paired if paired is not None else entry.get("paired"))


async def _simple(entry, head):
    conn = await _connection(entry)
    send, reader, answer = await _open(conn, head)
    try:
        await send.finish()
    except Exception:
        pass
    return answer


def refresh(entry, timeout=CONNECT_TIMEOUT):
    """Ask a paired runtime for its current addresses and settings."""
    answer = LOOP.run(_simple(entry, {"t": "info"}), timeout)
    if not answer.get("ok"):
        raise LinkError("unpaired" if answer.get("error") == "not paired" else "refused", str(answer.get("error")))
    return _remember_info(entry, answer)


def unpair(entry, timeout=CONNECT_TIMEOUT):
    """Remove this PC from the runtime's paired PCs (no token needed)."""
    answer = LOOP.run(_simple(entry, {"t": "unpair"}), timeout)
    remember(entry["name"], paired=False)
    return bool(answer.get("ok"))


async def _manage(entry, token, op, pc=None):
    conn = await _connection(entry)
    head = {"t": "manage", "op": op}
    if pc:
        head["pc"] = pc
    return await _login(conn, head, token)


def paired_pcs(entry, token, timeout=CONNECT_TIMEOUT):
    """(list of {id, name, paired, last_seen, via}, this PC's id)."""
    answer = LOOP.run(_manage(entry, token, "list"), timeout)
    return answer.get("pcs") or [], answer.get("you")


def remove_pc(entry, token, pc_id, timeout=CONNECT_TIMEOUT):
    return bool(LOOP.run(_manage(entry, token, "remove", pc_id), timeout).get("removed"))


# ---------------------------------------------------------------------------
# After a direct login: remember the runtime and pair this PC


_after = {}   # (host, port) -> {"thread", "note"}


def after_login(host, port, token, wait=False):
    """Called after a successful direct login to (host, port) with `token`:
    in the background, find the runtime's link ID by discovery, remember it,
    and pair this PC when it is not paired yet. Loopback hosts are skipped."""
    if not token or host.startswith("link:") or _is_loopback(host) or os.environ.get("CANWORKS_LINK") == "off":
        return None
    key = (host, port)
    job = _after.get(key)
    if job is None:
        job = {"note": None}
        job["thread"] = threading.Thread(target=_after_job, args=(host, port, token, job), daemon=True)
        _after[key] = job
        job["thread"].start()
    if wait:
        job["thread"].join(wait if isinstance(wait, (int, float)) else 10)
    return job


def _is_loopback(host):
    try:
        import ipaddress
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def _after_job(host, port, token, job):
    from . import discovery
    try:
        entry = find(host)
        r = discovery.find_address(host)   # a direct query first: needs no zeroconf
        if r is None and not entry:
            return
        if r is not None:
            ips = [a for a in r["addresses"] if ":" not in a.split("%")[0]] or r["addresses"]
            link_addrs = ["%s:%d" % (a, r.get("link") or DEFAULT_LINK_PORT) for a in ips] if r.get("id") else None
            entry = remember(r["name"], hosts=[host], id=r.get("id"), link_addrs=link_addrs,
                             diag_port=r.get("diag") or port, runtime_port=r.get("runtime"))
        else:
            entry = remember(entry["name"], hosts=[host])
        if not entry.get("id") or not available():
            return
        if entry.get("paired"):
            try:
                refresh(entry)
            except LinkError as e:
                if e.kind == "unpaired":
                    remember(entry["name"], paired=False)
            return
        try:
            entry = pair(entry, token)
            job["note"] = "This PC is now paired with %s%s." % (
                entry["name"], " and can reach it from other networks" if entry.get("internet") else "")
        except LinkError as e:
            if e.kind != "refused" or "local network" not in str(e):
                job["note"] = "Pairing with %s failed: %s" % (entry["name"], e)
    except Exception as e:  # never break the caller's session
        job["note"] = None
        _ = e
