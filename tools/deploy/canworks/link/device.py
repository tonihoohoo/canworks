"""canworks-link: the remote link's device service (docs/remote-access.md).

  canworks-link run               the service (canworks-link.service)
  canworks-link id                this device's link ID
  canworks-link list              paired PCs
  canworks-link allow ID [--name NAME]
  canworks-link revoke ID|NAME

It accepts iroh connections. A paired PC may open streams to the targets
`diag` (the diagnostics port) and `runtime` (the runtime's HTTPS port), both
on 127.0.0.1 only, plus `info`, `manage` and `unpair`; a PC that is not paired
may only open `pair`, which runs the SCRAM login against the deployed
config's token_verifier. diagnostics.remote_link in that config decides
whether relays are used (internet) and where pairing is accepted (pairing).

Settings live in /etc/canworks-link (--dir): secret.key, paired.json and
link.json, which the installer writes:
  {"config": "<the deployed canworks.json>", "port": 7533, "runtime_port": 8443}
runtime_port null on a bridge (no runtime HTTPS to forward)."""

import argparse
import asyncio
import json
import os
import socket
import sys
import time

from . import ALPN, DEFAULT_LINK_PORT, DIAG_PORT, RUNTIME_PORT, UNAVAILABLE, available
from . import protocol
from .protocol import LinkError, LineReader, encode

DEFAULT_DIR = "/etc/canworks-link"
MAX_PEERS = 4
MAX_STREAMS = 16
IDLE_S = 600
WATCH_S = 2.0
PAIR_DELAY_S = 1.0
PAIR_FAILS_PER_MIN = 10
LOG_EVERY_S = 60.0
CHUNK = 256 * 1024


def _now():
    return time.time()


def log(msg):
    print("link: " + msg, flush=True)


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        log("cannot read %s: %s" % (path, e))
        return default


def _write_json(path, doc, mode=0o644):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    try:
        os.chmod(tmp, mode)
    except OSError:
        pass
    os.replace(tmp, path)


def load_key(path):
    """The device's secret key (32 bytes), made on first use with mode 0600."""
    import iroh
    try:
        with open(path, "rb") as f:
            data = f.read()
        if len(data) == 32:
            return data
        log("%s is not a 32-byte key; making a new one" % path)
    except FileNotFoundError:
        pass
    data = iroh.SecretKey.generate().to_bytes()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)
    return data


def link_id(key):
    import iroh
    return str(iroh.SecretKey.from_bytes(key).public())


def deployed_settings(path):
    """(token_verifier or None, diagnostics port, remote_link dict) from a
    deployed canworks.json (version 1 or 2); defaults when it is missing."""
    doc = _read_json(path, None) if path else None
    d = None
    if isinstance(doc, dict):
        d = doc.get("diagnostics")
        if d is None and isinstance(doc.get("master"), dict):
            d = doc["master"].get("diagnostics")
    if not isinstance(d, dict):
        return None, DIAG_PORT, {}
    rl = d.get("remote_link") if isinstance(d.get("remote_link"), dict) else {}
    port = d.get("port") if isinstance(d.get("port"), int) else DIAG_PORT
    verifier = d.get("token_verifier") if isinstance(d.get("token_verifier"), str) else None
    return verifier, port, rl


def remote_settings(rl):
    """(internet, relays, pairing) from a remote_link object, with defaults."""
    internet = rl.get("internet") is True
    relays = [u for u in rl.get("relays") or [] if isinstance(u, str) and u.startswith("https://")]
    pairing = rl.get("pairing") if rl.get("pairing") in protocol.PAIRING_SCOPES else "lan"
    return internet, relays, pairing


class Paired:
    """paired.json: [{id, name, paired, last_seen, via}]."""

    def __init__(self, path):
        self.path = path
        self.pcs = []
        self.mtime = None
        self.reload()

    def reload(self):
        try:
            self.mtime = os.stat(self.path).st_mtime
        except OSError:
            self.mtime = None
        doc = _read_json(self.path, {"pcs": []})
        pcs = doc.get("pcs") if isinstance(doc, dict) else None
        self.pcs = [p for p in pcs or [] if isinstance(p, dict) and isinstance(p.get("id"), str)]

    def changed(self):
        try:
            m = os.stat(self.path).st_mtime
        except OSError:
            m = None
        return m != self.mtime

    def save(self):
        _write_json(self.path, {"pcs": self.pcs}, 0o600)
        try:
            self.mtime = os.stat(self.path).st_mtime
        except OSError:
            self.mtime = None

    def find(self, who):
        for p in self.pcs:
            if who in (p["id"], p.get("name")):
                return p
        return None

    def ids(self):
        return {p["id"] for p in self.pcs}

    def add(self, pc_id, name, via):
        p = self.find(pc_id)
        if p:
            p.update(name=name or p.get("name"), via=via)
        else:
            self.pcs.append({"id": pc_id, "name": name or pc_id[:10], "paired": int(_now()), "last_seen": None,
                             "via": via})
        self.save()

    def remove(self, who):
        p = self.find(who)
        if not p:
            return None
        self.pcs.remove(p)
        self.save()
        return p


class _RateLog:
    def __init__(self):
        self.last = {}

    def __call__(self, key, msg):
        t = _now()
        if t - self.last.get(key, -1e9) >= LOG_EVERY_S:
            self.last[key] = t
            log(msg)


class Service:
    """The link service. `bind` overrides the UDP address (tests)."""

    def __init__(self, directory=DEFAULT_DIR, bind=None, name=None):
        self.dir = directory
        self.settings = _read_json(os.path.join(directory, "link.json"), {})
        self.config_path = self.settings.get("config")
        self.port = int(self.settings.get("port") or DEFAULT_LINK_PORT)
        self.runtime_port = self.settings.get("runtime_port", RUNTIME_PORT)
        self.bind = bind or "0.0.0.0:%d" % self.port
        self.name = name or self.settings.get("name") or socket.gethostname()
        self.key = load_key(os.path.join(directory, "secret.key"))
        self.id = link_id(self.key)
        self.paired = Paired(os.path.join(directory, "paired.json"))
        self.verifier, self.diag_port, rl = deployed_settings(self.config_path)
        self.internet, self.relays, self.pairing = remote_settings(rl)
        self.config_mtime = self._config_mtime()
        self.endpoint = None
        self.conns = {}          # pc id -> set of connections
        self.streams = {}        # pc id -> open stream count
        self.fails = {}          # pc id -> time of the last failed pairing
        self.fail_times = []     # failed pairings in the last minute
        self.ratelog = _RateLog()
        self.stopping = False
        self.restart = False     # stopped to apply new internet settings (systemd starts it again)
        self.ready = None

    # -- settings -----------------------------------------------------------
    def _config_mtime(self):
        try:
            return os.stat(self.config_path).st_mtime if self.config_path else None
        except OSError:
            return None

    def info(self):
        addr = self.endpoint.addr() if self.endpoint else None
        return {"name": self.name, "id": self.id, "internet": self.internet, "relays": self.relays,
                "addrs": addr.direct_addresses() if addr else [], "relay": addr.relay_url() if addr else None,
                "pairing": self.pairing, "runtime": self.runtime_port is not None}

    async def _bind(self):
        import iroh
        opts = dict(secret_key=self.key, alpns=[ALPN], bind_addr=self.bind)
        if self.internet:
            opts["preset"] = iroh.preset_n0()
            if self.relays:
                opts["relay_mode"] = iroh.RelayMode.custom_from_urls(self.relays)
        else:
            opts["preset"] = iroh.preset_minimal()
            opts["relay_mode"] = iroh.RelayMode.disabled()
        self.endpoint = await iroh.Endpoint.bind(iroh.EndpointOptions(**opts))
        log("listening as %s, internet %s%s, pairing %s" % (
            self.id[:10], "on" if self.internet else "off",
            " (relays %s)" % ", ".join(self.relays) if self.internet and self.relays else
            " (public relays)" if self.internet else "", self.pairing))

    async def watch(self):
        while not self.stopping:
            await asyncio.sleep(WATCH_S)
            try:
                await self._check_files()
            except Exception as e:  # keep watching; a failed rebind is retried at the next change
                log("applying a changed config failed: %s" % e)

    async def _check_files(self):
        m = self._config_mtime()
        if m != self.config_mtime:
            self.config_mtime = m
            self.verifier, self.diag_port, rl = deployed_settings(self.config_path)
            internet, relays, pairing = remote_settings(rl)
            self.pairing = pairing
            if (internet, relays) != (self.internet, self.relays):
                # iroh frees the UDP port only when the endpoint object is
                # gone, so the service exits and systemd starts it again
                # (Restart=always) with the new settings.
                log("config changed: internet %s; restarting" % ("on" if internet else "off"))
                self.restart = True
                await self.stop()
        if self.paired.changed():
            self.paired.reload()
            self._drop_unpaired()

    def _drop_unpaired(self):
        ids = self.paired.ids()
        for pc in list(self.conns):
            if pc not in ids:
                for c in list(self.conns.pop(pc, ())):
                    try:
                        c.close(2, b"not paired")
                    except Exception:
                        pass
                log("PC %s removed; its sessions were closed" % pc[:10])

    # -- connections --------------------------------------------------------
    async def run(self):
        await self._bind()
        self.ready = asyncio.get_running_loop().create_future() if self.ready is None else self.ready
        if not self.ready.done():
            self.ready.set_result(True)
        watcher = asyncio.ensure_future(self.watch())
        try:
            while not self.stopping:
                ep = self.endpoint
                if ep is None:                # being rebound
                    await asyncio.sleep(0.05)
                    continue
                inc = await ep.accept_next()
                if inc is None:
                    if self.stopping:
                        break
                    if ep is self.endpoint:   # closed for good
                        break
                    continue                  # rebound: accept on the new endpoint
                asyncio.ensure_future(self._accept(inc))
        finally:
            watcher.cancel()

    async def stop(self):
        self.stopping = True
        if self.endpoint:
            await self.endpoint.close()

    def _path(self, conn):
        """("direct"|"relayed", remote address) of the selected path."""
        try:
            for p in conn.paths():
                if p.is_selected:
                    return ("relayed" if p.is_relay else "direct"), p.remote_addr
        except Exception:
            pass
        return "unknown", ""

    async def _accept(self, inc):
        try:
            conn = await (await inc.accept()).connect()
        except Exception:
            return
        pc = str(conn.remote_id())
        paired = pc in self.paired.ids()
        if paired and pc not in self.conns and len(self.conns) >= MAX_PEERS:
            conn.close(3, b"too many peers")
            return
        if paired:
            self.conns.setdefault(pc, set()).add(conn)
            p = self.paired.find(pc)
            kind, where = self._path(conn)
            log("PC %s connected (%s %s)" % (p.get("name") or pc[:10], kind, where))
        try:
            while True:
                try:
                    bi = await conn.accept_bi()
                except Exception:
                    break
                asyncio.ensure_future(self._stream(conn, pc, bi))
        finally:
            if pc in self.conns:
                self.conns[pc].discard(conn)
                if not self.conns[pc]:
                    del self.conns[pc]
                    p = self.paired.find(pc)
                    if p:
                        p["last_seen"] = int(_now())
                        try:
                            self.paired.save()
                        except OSError:
                            pass
                    log("PC %s disconnected" % ((p or {}).get("name") or pc[:10]))

    async def _stream(self, conn, pc, bi):
        send, recv = bi.send(), bi.recv()
        reader = LineReader(recv)
        try:
            head = await asyncio.wait_for(reader.line(), 10)
        except Exception:
            await _finish(send)
            return
        target = head.get("t")
        paired = pc in self.paired.ids()
        try:
            if target == "pair":
                await self._pair(conn, pc, head, reader, send)
            elif not paired:
                self.ratelog(("unpaired", pc), "refused unpaired %s" % pc[:10])
                await send.write_all(encode({"ok": False, "error": "not paired"}))
            elif target in ("diag", "runtime"):
                await self._forward(pc, target, reader, send)
            elif target == "info":
                await send.write_all(encode(dict(self.info(), ok=True)))
            elif target == "unpair":
                p = self.paired.remove(pc)
                await send.write_all(encode({"ok": True}))
                log("PC %s unpaired itself" % ((p or {}).get("name") or pc[:10]))
                self._drop_unpaired()
            elif target == "manage":
                await self._manage(conn, pc, head, reader, send)
            else:
                await send.write_all(encode({"ok": False, "error": "unknown target"}))
        except LinkError:
            pass
        except Exception as e:  # a stream must never take the service down
            log("stream error: %s" % e)
        finally:
            await _finish(send)

    async def _forward(self, pc, target, reader, send):
        port = self.diag_port if target == "diag" else self.runtime_port
        if port is None:
            await send.write_all(encode({"ok": False, "error": "no runtime here"}))
            return
        if self.streams.get(pc, 0) >= MAX_STREAMS:
            await send.write_all(encode({"ok": False, "error": "too many streams"}))
            return
        try:
            r, w = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            what = "diagnostics not listening" if target == "diag" else "runtime not listening"
            await send.write_all(encode({"ok": False, "error": what}))
            return
        self.streams[pc] = self.streams.get(pc, 0) + 1
        try:
            await send.write_all(encode({"ok": True}))
            await pump(reader, send, r, w, is_paired=lambda: pc in self.paired.ids())
        finally:
            self.streams[pc] -= 1

    def _pair_refusal(self, conn, pc):
        if not self.verifier:
            return "no token configured"
        if self.pairing == "off":
            return "pairing is off on this runtime"
        if self.pairing == "lan":
            kind, where = self._path(conn)
            if kind != "direct" or not protocol.is_lan_address(where):
                return "pairing only on the local network"
        t = _now()
        if t - self.fails.get(pc, -1e9) < PAIR_DELAY_S:
            return "too many tries; wait a second"
        self.fail_times = [x for x in self.fail_times if t - x < 60]
        if len(self.fail_times) >= PAIR_FAILS_PER_MIN:
            return "too many failed pairings; try again in a minute"
        return None

    async def _login(self, conn, pc, head, reader, send):
        """The SCRAM exchange; True when the PC proved the token."""
        import iroh
        cnonce = head.get("nonce")
        v = protocol.diag.parse_verifier(self.verifier or "")
        if not isinstance(cnonce, str) or not v:
            await send.write_all(encode({"ok": False, "error": "bad request"}))
            return False
        it, salt, _, _ = v
        snonce = cnonce + protocol.new_nonce()
        salt_b64 = protocol.diag._b64(salt)
        await send.write_all(encode({"ok": True, "salt": salt_b64, "iterations": it, "nonce": snonce}))
        msg = await asyncio.wait_for(reader.line(), 30)
        cbind = protocol.channel_binding(iroh.EndpointId.from_string(self.id).to_bytes(),
                                         iroh.EndpointId.from_string(pc).to_bytes())
        auth = protocol.auth_message(cnonce, snonce, salt_b64, it, cbind)
        sig = protocol.server_check(self.verifier, auth, msg.get("proof"))
        if not sig:
            t = _now()
            self.fails[pc] = t
            self.fail_times.append(t)
            self.ratelog(("fail", pc), "pairing failed for %s (wrong token)" % pc[:10])
            await send.write_all(encode({"ok": False, "error": "wrong token"}))
            return False
        return sig

    async def _pair(self, conn, pc, head, reader, send):
        why = self._pair_refusal(conn, pc)
        if why:
            if why == "pairing only on the local network":
                self.ratelog(("scope", pc), "refused pairing from %s: not on the local network" % pc[:10])
            await send.write_all(encode({"ok": False, "error": why}))
            return
        sig = await self._login(conn, pc, head, reader, send)
        if not sig:
            return
        name = str(head.get("name") or "")[:64]
        kind, _ = self._path(conn)
        self.paired.add(pc, name, "lan" if kind == "direct" else kind)
        self.conns.setdefault(pc, set()).add(conn)
        log("paired PC %s (%s)" % (name or pc[:10], self.pairing if self.pairing == "anywhere" else "lan"))
        await send.write_all(encode(dict(self.info(), ok=True, signature=sig)))

    async def _manage(self, conn, pc, head, reader, send):
        sig = await self._login(conn, pc, head, reader, send)
        if not sig:
            return
        op = head.get("op")
        if op == "remove":
            p = self.paired.remove(str(head.get("pc") or ""))
            if p:
                log("PC %s removed by %s" % (p.get("name") or p["id"][:10], pc[:10]))
                self._drop_unpaired()
            await send.write_all(encode({"ok": True, "signature": sig, "removed": bool(p)}))
        else:
            await send.write_all(encode({"ok": True, "signature": sig, "pcs": self.paired.pcs, "you": pc}))


async def _finish(send):
    try:
        await send.finish()
    except Exception:
        pass


async def pump(reader, send, r, w, is_paired=lambda: True, idle=IDLE_S):
    """Copy between an iroh stream (reader, send) and a TCP connection (r, w)
    until both directions end, the stream is idle for `idle` seconds, or the
    PC is no longer paired."""
    last = [_now()]

    async def up():  # TCP -> stream
        try:
            while True:
                data = await r.read(CHUNK)
                if not data:
                    break
                last[0] = _now()
                await send.write_all(data)
        except Exception:   # the PC went away or the TCP side reset
            pass
        await _finish(send)

    async def down():  # stream -> TCP
        try:
            rest = reader.rest()
            if rest:
                w.write(rest)
                await w.drain()
            while True:
                data = await reader.recv.read(CHUNK)
                if not data:
                    break
                last[0] = _now()
                w.write(data)
                await w.drain()
            w.write_eof()
        except Exception:
            pass

    tasks = [asyncio.ensure_future(up()), asyncio.ensure_future(down())]
    try:
        while True:
            done, _ = await asyncio.wait(tasks, timeout=min(30, idle), return_when=asyncio.ALL_COMPLETED)
            if len(done) == 2:
                break
            if _now() - last[0] >= idle or not is_paired():
                break
    except Exception:
        pass
    finally:
        for t in tasks:
            t.cancel()
        try:
            w.close()
        except Exception:
            pass


def parser():
    p = argparse.ArgumentParser(prog="canworks-link", description="The remote link's device service "
                                "(docs/remote-access.md).")
    p.add_argument("--dir", default=DEFAULT_DIR, help="settings directory (default %(default)s)")
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("run", help="run the service")
    sp.add_parser("id", help="print this device's link ID")
    sp.add_parser("list", help="list paired PCs")
    a = sp.add_parser("allow", help="pair a PC by its link ID (canworks-diag link id on the PC)")
    a.add_argument("id")
    a.add_argument("--name", default="")
    r = sp.add_parser("revoke", help="remove a paired PC and close its sessions")
    r.add_argument("who", metavar="ID|NAME")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if not available():
        print("canworks-link: " + UNAVAILABLE, file=sys.stderr)
        return 2
    import iroh
    if args.cmd == "run":
        svc = Service(args.dir)
        try:
            asyncio.run(svc.run())
        except KeyboardInterrupt:
            pass
        return 0
    if args.cmd == "id":
        print(link_id(load_key(os.path.join(args.dir, "secret.key"))))
        return 0
    paired = Paired(os.path.join(args.dir, "paired.json"))
    if args.cmd == "list":
        if not paired.pcs:
            print("no paired PCs")
        for p in paired.pcs:
            seen = time.strftime("%Y-%m-%d %H:%M", time.localtime(p["last_seen"])) if p.get("last_seen") else "never"
            print("%-20s %s  paired %s, last seen %s" % (
                p.get("name") or "-", p["id"], time.strftime("%Y-%m-%d", time.localtime(p.get("paired") or 0)), seen))
        return 0
    if args.cmd == "allow":
        try:
            iroh.EndpointId.from_string(args.id)
        except Exception:
            print("canworks-link: %r is not a link ID (canworks-diag link id prints the PC's)" % args.id,
                  file=sys.stderr)
            return 2
        paired.add(args.id, args.name, "manual")
        print("paired %s" % (args.name or args.id))
        return 0
    if args.cmd == "revoke":
        p = paired.remove(args.who)
        if not p:
            print("canworks-link: no paired PC %r" % args.who, file=sys.stderr)
            return 1
        print("removed %s" % (p.get("name") or p["id"]))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
