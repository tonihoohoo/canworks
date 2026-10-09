"""The simulation file (canworks/simulation.json, docs/simulator.md): loading,
the JSON Schema, and the checks the schema cannot express, given the config
it belongs to and the EDS files of its devices.

The expression language of value sources and conditions is parsed here with
the grammar of docs/simulator.md ("Expressions"), the same as the simulator's
own parser (plugin/src/canopen/sim); test/fixtures/sim/expressions.json holds both to it.
"""

import json
import math
import os
import random
import re

import jsonschema
from jsonschema.exceptions import best_match

from . import contract
from . import eds as eds_mod
from . import simmachine as machine_mod

SUPPORTED_VERSION = 2
FILE_NAME = "simulation.json"
_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "schema")
_schemas = {}

VISIBLE_STRING = 0x0009
DELAY_MAX_S = 600.0


def version(data):
    """The file's schema_version (1 when left out)."""
    v = data.get("schema_version", 1) if isinstance(data, dict) else 1
    return v if isinstance(v, int) and not isinstance(v, bool) else 1


def bodies(data):
    """(json path parts, part) of the parts that hold nodes, extra_devices
    and scenarios: the file itself in version 1, each network's section in
    version 2."""
    if not isinstance(data, dict):
        return []
    if version(data) >= 2:
        nets = data.get("networks")
        return [(["networks", k], v) for k, v in nets.items() if isinstance(v, dict)] if isinstance(nets, dict) else []
    return [([], data)]


def section_name(net):
    """The name a version 2 file's section uses for a network of
    contract.networks(): its name, or its interface (as the plugin)."""
    if net["name"]:
        return net["name"]
    iface = net["adapter"].get("interface") if isinstance(net["adapter"], dict) else None
    return iface if isinstance(iface, str) else ""


def schema(version=SUPPORTED_VERSION):
    if version not in _schemas:
        with open(os.path.join(_SCHEMA_DIR, "canworks-sim.v%d.schema.json" % version), encoding="utf-8") as f:
            _schemas[version] = json.load(f)
    return _schemas[version]


def default_path(config_path):
    """Where the simulation file of a config lies: next to it."""
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), FILE_NAME)


class SimFileError(Exception):
    pass


def load(path):
    """The parsed file; SimFileError when it cannot be read or is not JSON."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        raise SimFileError("cannot read %s: %s" % (path, e.strerror or e))
    except ValueError as e:
        raise SimFileError("%s: not valid JSON (%s)" % (path, e))


def parse_object(text):
    """(index, subindex) of "0xIIII:S" / "0xIIII"; ValueError otherwise."""
    t = str(text).strip()
    m = re.match(r"^0[xX]([0-9A-Fa-f]{1,4})(?::(0[xX][0-9A-Fa-f]{1,2}|[0-9]{1,3}))?$", t)
    if not m:
        raise ValueError("%r is not an object (write 0xIIII:S)" % text)
    index = int(m.group(1), 16)
    sub = int(m.group(2), 0) if m.group(2) else 0
    if sub > 255:
        raise ValueError("%r: subindex %d is above 255" % (text, sub))
    return index, sub


def object_key(index, subindex):
    return "0x%04X:%d" % (index, subindex)


# ---------------------------------------------------------------------------
# Expressions


class ExprError(Exception):
    """An error in an expression, at a 0-based position in its text."""

    def __init__(self, position, message):
        super().__init__(message)
        self.position = position
        self.message = message

    def __str__(self):
        return "position %d: %s" % (self.position, self.message)


class EvalError(Exception):
    """Division by zero or a value that is not a finite number: the object
    keeps its previous value."""


NAMES = ("t", "dt", "pi", "prev", "true", "false")
# Function -> (least, most) arguments; most None: any number.
FUNCTIONS = {
    "abs": (1, 1), "floor": (1, 1), "ceil": (1, 1), "round": (1, 1), "sqrt": (1, 1), "exp": (1, 1),
    "log": (1, 1), "sin": (1, 1), "cos": (1, 1),
    "min": (2, None), "max": (2, None), "clamp": (3, 3),
    "if": (3, 3), "bit": (2, 2), "setbit": (3, 3),
    "noise": (1, 1), "lag": (2, 2), "delay": (2, 2), "rate_limit": (2, 2), "integrate": (1, 1),
    "hold": (2, 2), "edge": (1, 1),
}
# Functions that use the previous tick's value: a reference cycle through
# one of them is allowed.
CYCLE_BREAKERS = ("lag", "delay", "integrate")
STATEFUL = ("noise", "lag", "delay", "rate_limit", "integrate", "hold", "edge")

# Binary operators by precedence level, lowest first. `**` is handled apart
# (right to left, below the unary operators).
LEVELS = [("||",), ("&&",), ("|",), ("^",), ("&",), ("==", "!="), ("<", "<=", ">", ">="), ("<<", ">>"),
          ("+", "-"), ("*", "/", "%")]
_OPERATORS = sorted({op for level in LEVELS for op in level} | {"**", "!", "~", "(", ")", ","},
                    key=len, reverse=True)
_NUMBER = re.compile(r"0[xX][0-9A-Fa-f]+|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class Node:
    """A node of the expression tree. kind: num, name, ref, unary, binary,
    call. ref: device (None: the own device), index, subindex."""

    __slots__ = ("kind", "pos", "value", "args", "device", "index", "subindex")

    def __init__(self, kind, pos, value=None, args=(), device=None, index=None, subindex=None):
        self.kind, self.pos, self.value, self.args = kind, pos, value, list(args)
        self.device, self.index, self.subindex = device, index, subindex

    def __repr__(self):
        if self.kind == "ref":
            return "[%s/0x%04X:%d]" % (self.device, self.index, self.subindex)
        if self.kind in ("num", "name"):
            return repr(self.value)
        return "%s(%s)" % (self.value, ", ".join(map(repr, self.args)))


def _tokens(text):
    """(kind, text or value, position) tokens; kind: num, name, ref, op, end."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            m = _NUMBER.match(text, i)
            s = m.group(0)
            value = int(s, 16) if s[:2].lower() == "0x" else float(s)
            out.append(("num", value, i))
            i = m.end()
            continue
        if c.isalpha() or c == "_":
            m = _NAME.match(text, i)
            out.append(("name", m.group(0), i))
            i = m.end()
            continue
        if c == "[":
            end = text.find("]", i)
            if end < 0:
                raise ExprError(i, "object reference without its closing ']'")
            out.append(("ref", text[i + 1:end], i))
            i = end + 1
            continue
        for op in _OPERATORS:
            if text.startswith(op, i):
                out.append(("op", op, i))
                i += len(op)
                break
        else:
            raise ExprError(i, "unexpected character '%s'" % c)
    out.append(("end", None, n))
    return out


def _parse_ref(body, pos):
    """(device, index, subindex) of the text between [ and ]."""
    device = None
    inner = body.strip()
    if "/" in inner:
        dev, _, inner = inner.partition("/")
        dev, inner = dev.strip(), inner.strip()
        if re.match(r"^[0-9]+$", dev):
            device = int(dev)
            if not 1 <= device <= 127:
                raise ExprError(pos, "device %s: a node ID is 1-127" % dev)
        elif re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", dev):
            device = dev
        else:
            raise ExprError(pos, "'%s' is not a node ID or a device name" % dev)
    try:
        index, sub = parse_object(inner)
    except ValueError:
        raise ExprError(pos, "[%s] is not an object: write [0xIIII:S] or [NODE/0xIIII:S]" % body)
    return device, index, sub


class _Parser:
    def __init__(self, text, resolve):
        self.text = text
        self.toks = _tokens(text)
        self.i = 0
        self.resolve = resolve

    def peek(self):
        return self.toks[self.i]

    def take(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def unexpected(self, tok):
        kind, value, pos = tok
        if kind == "end":
            return ExprError(pos, "unexpected end of the expression")
        if kind == "num":
            return ExprError(pos, "unexpected number '%s'" % _NUMBER.match(self.text, pos).group(0))
        if kind == "ref":
            return ExprError(pos, "unexpected object reference [%s]" % value)
        return ExprError(pos, "unexpected '%s'" % value)

    def parse(self):
        if self.peek()[0] == "end":
            raise ExprError(0, "empty expression")
        node = self.binary(0)
        if self.peek()[0] != "end":
            tok = self.peek()
            if tok == ("op", ")", tok[2]):
                raise ExprError(tok[2], "unexpected ')' without its '('")
            raise self.unexpected(tok)
        return node

    def binary(self, level):
        if level == len(LEVELS):
            return self.power()
        left = self.binary(level + 1)
        while True:
            kind, op, pos = self.peek()
            if kind != "op" or op not in LEVELS[level]:
                return left
            self.take()
            right = self.binary(level + 1)
            left = Node("binary", pos, op, (left, right))

    def power(self):
        base = self.unary()
        kind, op, pos = self.peek()
        if kind == "op" and op == "**":
            self.take()
            return Node("binary", pos, "**", (base, self.power()))
        return base

    def unary(self):
        kind, op, pos = self.peek()
        if kind == "op" and op in ("-", "!", "~"):
            self.take()
            return Node("unary", pos, op, (self.unary(),))
        if kind == "op" and op == "+":
            self.take()
            return self.unary()
        return self.primary()

    def primary(self):
        tok = self.take()
        kind, value, pos = tok
        if kind == "num":
            return Node("num", pos, value)
        if kind == "ref":
            device, index, sub = _parse_ref(value, pos)
            problem = self.resolve(device, index, sub) if self.resolve else None
            if problem:
                raise ExprError(pos, problem)
            return Node("ref", pos, args=(), device=device, index=index, subindex=sub)
        if kind == "name":
            if self.peek()[:2] == ("op", "("):
                return self.call(value, pos)
            if value not in NAMES:
                raise ExprError(pos, "unknown name '%s' (names: %s)" % (value, ", ".join(NAMES)))
            return Node("name", pos, value)
        if kind == "op" and value == "(":
            node = self.binary(0)
            close = self.peek()
            if close[:2] != ("op", ")"):
                if close[0] == "end":
                    raise ExprError(close[2], "expected ')' before the end of the expression")
                raise ExprError(close[2], "expected ')' here")
            self.take()
            return node
        raise self.unexpected(tok)

    def call(self, name, pos):
        if name not in FUNCTIONS:
            raise ExprError(pos, "unknown function '%s'" % name)
        self.take()  # (
        args = []
        if self.peek()[:2] != ("op", ")"):
            while True:
                args.append(self.binary(0))
                kind, op, p = self.peek()
                if kind == "op" and op == ",":
                    self.take()
                    continue
                if kind == "op" and op == ")":
                    break
                if kind == "end":
                    raise ExprError(p, "expected ')' to close %s( before the end of the expression" % name)
                raise ExprError(p, "expected ',' or ')' in the arguments of %s" % name)
        self.take()  # )
        least, most = FUNCTIONS[name]
        if len(args) < least or (most is not None and len(args) > most):
            if most is None:
                want = "at least %d arguments" % least
            else:
                want = "%d argument%s" % (least, "" if least == 1 else "s")
            raise ExprError(pos, "%s takes %s, not %d" % (name, want, len(args)))
        if name == "delay" and _constant(args[1]):
            s = _const_value(args[1])
            if s is not None and not 0 <= s <= DELAY_MAX_S:
                raise ExprError(pos, "delay of %g s: the dead time is 0-%d s" % (s, DELAY_MAX_S))
        return Node("call", pos, name, args)


def _constant(node):
    if node.kind == "num":
        return True
    if node.kind == "name":
        return node.value in ("pi", "true", "false")
    if node.kind == "ref":
        return False
    if node.kind == "call" and node.value in STATEFUL:
        return False
    return all(_constant(a) for a in node.args)


def _const_value(node):
    try:
        return Evaluator(node).eval({})
    except EvalError:
        return None


def parse(text, resolve=None):
    """The expression's tree; ExprError with the position otherwise.

    resolve(device, index, subindex) -> None when the object exists, else
    the message (an unknown device or object); device None is the own
    device, an int a node ID, a str an extra device's name."""
    return _Parser(text, resolve).parse()


def references(tree):
    """[(ref node, through a lag/delay/integrate)] of an expression tree."""
    out = []

    def walk(node, broken):
        if node.kind == "ref":
            out.append((node, broken))
        inner = broken or (node.kind == "call" and node.value in CYCLE_BREAKERS)
        for a in node.args:
            walk(a, inner)

    walk(tree, False)
    return out


def _round(x):
    """Half away from zero."""
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)


def _int(x):
    if math.isnan(x) or math.isinf(x):
        raise EvalError("not a finite number")
    return int(x)


class Evaluator:
    """Evaluates a tree tick after tick; stateful functions keep their state
    per call site. On the first tick lag, rate_limit and delay give their
    input, integrate x * dt, hold 0 unless its condition is already true,
    edge 1 when its condition is already true."""

    def __init__(self, tree, rng=None):
        self.tree = tree
        self.state = {}
        self.rng = rng or random.Random()

    def eval(self, ctx):
        """ctx: t, dt, prev, and read(device, index, subindex) -> value."""
        v = self._eval(self.tree, ctx)
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            raise EvalError("not a finite number")
        return v

    def _eval(self, n, ctx):
        k = n.kind
        if k == "num":
            return n.value
        if k == "name":
            if n.value == "pi":
                return math.pi
            if n.value == "true":
                return 1
            if n.value == "false":
                return 0
            return ctx.get(n.value, 0)
        if k == "ref":
            read = ctx.get("read")
            return read(n.device, n.index, n.subindex) if read else 0
        if k == "unary":
            x = self._eval(n.args[0], ctx)
            if n.value == "-":
                return -x
            if n.value == "!":
                return 1 if x == 0 else 0
            return ~_int(x)
        if k == "binary":
            return self._binary(n, ctx)
        return self._call(n, ctx)

    def _binary(self, n, ctx):
        op = n.value
        a = self._eval(n.args[0], ctx)
        if op == "&&":
            return 1 if a != 0 and self._eval(n.args[1], ctx) != 0 else 0
        if op == "||":
            return 1 if a != 0 or self._eval(n.args[1], ctx) != 0 else 0
        b = self._eval(n.args[1], ctx)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            if b == 0:
                raise EvalError("division by zero")
            r = a / b
            return r
        if op == "%":
            if b == 0:
                raise EvalError("division by zero")
            return math.fmod(a, b)
        if op == "**":
            try:
                r = float(a) ** float(b)
            except (OverflowError, ZeroDivisionError):
                raise EvalError("not a finite number")
            if isinstance(r, complex):
                raise EvalError("not a finite number")
            return r
        if op in ("==", "!=", "<", "<=", ">", ">="):
            return 1 if {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op] else 0
        x, y = _int(a), _int(b)
        if op == "&":
            return x & y
        if op == "|":
            return x | y
        if op == "^":
            return x ^ y
        if not 0 <= y <= 63:
            raise EvalError("shift by %d" % y)
        return x << y if op == "<<" else x >> y

    def _call(self, n, ctx):
        f = n.value
        if f == "if":
            return self._eval(n.args[1], ctx) if self._eval(n.args[0], ctx) != 0 else self._eval(n.args[2], ctx)
        args = [self._eval(a, ctx) for a in n.args]
        dt = ctx.get("dt", 0) or 0
        st = self.state.get(id(n))
        try:
            if f == "abs":
                return abs(args[0])
            if f == "floor":
                return math.floor(args[0])
            if f == "ceil":
                return math.ceil(args[0])
            if f == "round":
                return _round(args[0])
            if f == "sqrt":
                return math.sqrt(args[0])
            if f == "exp":
                return math.exp(args[0])
            if f == "log":
                return math.log(args[0])
            if f == "sin":
                return math.sin(args[0])
            if f == "cos":
                return math.cos(args[0])
        except (ValueError, OverflowError):
            raise EvalError("not a finite number")
        if f == "min":
            return min(args)
        if f == "max":
            return max(args)
        if f == "clamp":
            return min(max(args[0], args[1]), args[2])
        if f == "bit":
            return (_int(args[0]) >> _int(args[1])) & 1 if 0 <= _int(args[1]) <= 63 else 0
        if f == "setbit":
            x, b = _int(args[0]), _int(args[1])
            if not 0 <= b <= 63:
                return x
            return x | (1 << b) if args[2] != 0 else x & ~(1 << b)
        if f == "noise":
            return self.rng.uniform(-args[0], args[0])
        if f == "lag":
            x, tau = args
            y = x if st is None else (x if tau <= 0 else st + (x - st) * min(1.0, dt / tau))
            self.state[id(n)] = y
            return y
        if f == "rate_limit":
            x, r = args
            y = x if st is None else st + max(-abs(r) * dt, min(abs(r) * dt, x - st))
            self.state[id(n)] = y
            return y
        if f == "integrate":
            y = (st or 0) + args[0] * dt
            self.state[id(n)] = y
            return y
        if f == "delay":
            # The newest sample at least s old; before there is one, the oldest.
            x, s = args
            t = ctx.get("t", 0)
            hist = st if st is not None else []
            hist.append((t, x))
            while len(hist) > 1 and hist[1][0] <= t - s:
                hist.pop(0)
            self.state[id(n)] = hist
            return hist[0][1]
        if f == "hold":
            x, c = args
            last_c, held = st if st is not None else (0, 0)
            if c != 0 and last_c == 0:
                held = x
            self.state[id(n)] = (c, held)
            return held
        if f == "edge":
            last = st if st is not None else 0
            self.state[id(n)] = args[0]
            return 1 if args[0] != 0 and last == 0 else 0
        raise EvalError("unknown function %s" % f)


def evaluate(text, ctx=None, resolve=None):
    """Parses and evaluates once (the first tick)."""
    return Evaluator(parse(text, resolve)).eval(ctx or {})


# ---------------------------------------------------------------------------
# What is simulated in a config


def simulated(cfg):
    """(network simulated, [node IDs of simulated nodes]) of a config."""
    adapter = cfg.get("adapter") if isinstance(cfg, dict) else None
    network = isinstance(adapter, dict) and adapter.get("simulate") is True
    nodes = []
    for n in (cfg.get("nodes") or []) if isinstance(cfg, dict) else []:
        if not isinstance(n, dict):
            continue
        sim = n.get("simulate")
        if (sim is True) or (sim is None and network):
            nodes.append(contract._uint(n.get("node_id")))
    return network, [n for n in nodes if n is not None]


def describe_simulated(cfg):
    """A sentence naming what a config simulates, or None. With several
    networks, one part per network that simulates something, headed by its
    name."""
    nets = contract.networks(cfg) if isinstance(cfg, dict) else []
    if len(nets) <= 1:
        return _describe_one(cfg)
    parts = []
    for net in nets:
        iface = net["adapter"].get("interface")
        if net["role"] == "slave":
            text = ("the slave runs on simulated bus %s" % iface) if net["adapter"].get("simulate") is True else None
        else:
            # The plugin's own slave on the same simulated bus serves its node ID.
            served = {}
            if net["adapter"].get("simulate") is True and isinstance(iface, str) and iface:
                for other in nets:
                    nid = (other["slave"] or {}).get("node_id")
                    if other["role"] == "slave" and other["adapter"].get("simulate") is True \
                            and other["adapter"].get("interface") == iface and isinstance(nid, int) \
                            and not isinstance(nid, bool):
                        served[nid] = other["name"]
            text = _describe_one({"adapter": net["adapter"], "nodes": net["nodes"]}, served)
        if text:
            parts.append("network %s: %s" % (net["name"], text))
    return "; ".join(parts) or None


def several_networks(cfg):
    """True when the config has more than one network (a version 2 file)."""
    return isinstance(cfg, dict) and len(contract.networks(cfg)) > 1


def _describe_one(cfg, served=None):
    served = served or {}
    network, nodes = simulated(cfg)
    ids = ", ".join(str(n) for n in nodes)
    if network:
        all_nodes = [contract._uint(n.get("node_id")) for n in cfg.get("nodes") or [] if isinstance(n, dict)]
        text = "the network is simulated; no CAN interface is used"
        for nid in sorted(n for n in all_nodes if n in served):
            text += "; node %d is slave network %s on the same simulated bus" % (nid, served[nid])
        absent = [str(n) for n in all_nodes if n not in nodes and n not in served]
        if not nodes:
            if not served:
                return text + " (no node is simulated: every configured node stays absent)"
            if absent:
                text += " (no node is simulated: node%s %s stay%s absent)" % (
                    "s" if len(absent) > 1 else "", ", ".join(absent), "" if len(absent) > 1 else "s")
            return text
        if absent:
            text += "; node%s %s %s simulated, node%s %s stay%s absent" % (
                "s" if len(nodes) > 1 else "", ids, "are" if len(nodes) > 1 else "is",
                "s" if len(absent) > 1 else "", ", ".join(absent), "" if len(absent) > 1 else "s")
        return text
    if nodes:
        adapter = cfg.get("adapter") if isinstance(cfg.get("adapter"), dict) else {}
        iface = adapter.get("interface") or cfg.get("interface") or "?"
        if len(nodes) == 1:
            return "node %s is a simulated device on the real network %s" % (ids, iface)
        return "nodes %s are simulated devices on the real network %s" % (ids, iface)
    return None


# ---------------------------------------------------------------------------
# Checks


def _resolve_path(value, base):
    return value if os.path.isabs(value) else os.path.join(base, value)


def referenced_files(data, path):
    """{"eds": {value: absolute path}, "csv": {...}, "machine": {...}} of the
    files a (schema-valid) simulation file names, relative to the file."""
    base = os.path.dirname(os.path.abspath(path))
    out = {"eds": {}, "csv": {}, "machine": {}}
    if not isinstance(data, dict):
        return out
    for _, body in bodies(data):
        for d in body.get("extra_devices") or []:
            if isinstance(d, dict) and isinstance(d.get("eds"), str) and d["eds"]:
                out["eds"][d["eds"]] = _resolve_path(d["eds"], base)
        if version(data) >= 2 and isinstance(body.get("machine"), str) and body["machine"]:
            out["machine"][body["machine"]] = _resolve_path(body["machine"], base)
    for _, src in _all_sources(data):
        csv = src.get("csv") if isinstance(src, dict) else None
        if isinstance(csv, dict) and isinstance(csv.get("file"), str) and csv["file"]:
            out["csv"][csv["file"]] = _resolve_path(csv["file"], base)
    return out


def _all_sources(data):
    """(json path parts, source) of every value source: devices' and
    scenario steps', in every part of the file."""
    for at, body in bodies(data):
        for parts, src in _body_sources(body):
            yield at + parts, src


def _body_sources(data):
    for key, nd in (data.get("nodes") or {}).items():
        if isinstance(nd, dict):
            for obj, src in (nd.get("sources") or {}).items():
                yield ["nodes", key, "sources", obj], src
    for i, d in enumerate(data.get("extra_devices") or []):
        if isinstance(d, dict):
            for obj, src in (d.get("sources") or {}).items():
                yield ["extra_devices", i, "sources", obj], src
    for name, sc in (data.get("scenarios") or {}).items():
        if isinstance(sc, dict):
            for parts, step in _steps(sc.get("steps") or [], ["scenarios", name, "steps"]):
                for obj, src in (step.get("source") or {}).items() if isinstance(step.get("source"), dict) else ():
                    if src is not None:
                        yield parts + ["source", obj], src


def _steps(steps, at):
    for i, st in enumerate(steps):
        if not isinstance(st, dict):
            continue
        yield at + [i], st
        rep = st.get("repeat")
        if isinstance(rep, dict):
            for item in _steps(rep.get("steps") or [], at + [i, "repeat", "steps"]):
                yield item


def rewrite(data, path, eds_value, csv_value, machine_value=None):
    """A copy of the file with each extra device's eds and each CSV file
    renamed: eds_value(abs path) and csv_value(abs path) give the new
    values; machine_value(value, abs path) a section's machine file (None:
    kept)."""
    files = referenced_files(data, path)
    out = json.loads(json.dumps(data))
    for _, body in bodies(out):
        for d in body.get("extra_devices") or []:
            d["eds"] = eds_value(files["eds"][d["eds"]])
        if machine_value is not None and version(out) >= 2 and body.get("machine") in files["machine"]:
            body["machine"] = machine_value(body["machine"], files["machine"][body["machine"]])
    for _, src in _all_sources(out):
        csv = src.get("csv") if isinstance(src, dict) else None
        if isinstance(csv, dict):
            csv["file"] = csv_value(files["csv"][csv["file"]])
    return out


class _Device:
    def __init__(self, label, eds=None, eds_name="", cfg_node=None, extra=None):
        self.label = label
        self.eds = eds
        self.eds_name = eds_name
        self.cfg_node = cfg_node
        self.extra = extra
        self.writers = {}  # (index, sub) -> writer text

    def has(self, index, sub):
        return self.eds is None or self.eds.find(index, sub) is not None

    def sub(self, index, sub):
        return self.eds.find(index, sub) if self.eds is not None else None


def _master_writers(n, eds, node_id):
    """{(index, sub): writer} for the objects the master writes in a node."""
    u = contract._uint
    out = {}
    for j, p in enumerate(n.get("rx_pdos") or []):
        number = u(p.get("number", j + 1)) or j + 1
        label = "RPDO %d" % number
        for e in p.get("entries") or []:
            out.setdefault((u(e.get("index")), u(e.get("subindex", 0)) or 0), label)
        if eds is not None:
            info = eds_mod.mapping_info(eds, 0x1600 + number - 1)
            if eds.has(0x1600 + number - 1) and eds_mod.uses_device_mapping(p, info) and info["has_default"]:
                for v in info["defaults"]:
                    if v >> 16 >= 0x0008:
                        out.setdefault((v >> 16, (v >> 8) & 0xFF), label)
    for s in n.get("sdo") or []:
        out.setdefault((u(s.get("index")), u(s.get("subindex", 0)) or 0), "startup SDO")
    for v in n.get("sdo_variables") or []:
        if v.get("direction") == "write":
            entry = {"index": u(v.get("index")), "subindex": u(v.get("subindex", 0)) or 0}
            out.setdefault((entry["index"], entry["subindex"]),
                           contract.sdo_variable_label(entry, v.get("name", "")))
    if n.get("config_check") is True:
        for sub in (1, 2):
            out.setdefault((0x1020, sub), "config_check")
    return out


def check(data, path, cfg=None, config_path=None, eds_paths=None):
    """Checks a parsed simulation file. `path` names it in messages and is
    the base of its relative paths; `cfg` is the parsed config it belongs
    to (already checked), its EDS files found through eds_paths ({eds value:
    file}) or relative to config_path. Returns a contract.Result."""
    r = contract.Result()

    def err(where, msg, paths=None):
        r.add("error", "%s: %s%s" % (path, where + ": " if where else "", msg),
              paths if paths is not None else [where])

    def warn(where, msg, paths=None):
        r.add("warning", "%s: %s%s" % (path, where + ": " if where else "", msg),
              paths if paths is not None else [where])

    if not isinstance(data, dict):
        err("", "top level must be a JSON object")
        return r
    version = 1
    if "schema_version" in data:
        v = data["schema_version"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            err("", "field 'schema_version' must be 1 or higher")
            return r
        if v > SUPPORTED_VERSION:
            err("", "schema_version %d is not supported; the highest supported version is %d"
                % (v, SUPPORTED_VERSION))
            return r
        version = v

    s = schema(version)
    for e in sorted(jsonschema.Draft202012Validator(s).iter_errors(data),
                    key=lambda e: list(map(str, e.absolute_path))):
        first = e
        while e.context:
            fitting = [c for c in e.context if c.validator != "type"]
            e = best_match(fitting or e.context)
        where = contract.json_path(list(e.absolute_path))
        msg = contract.plain_schema_message(first, s)
        if e.validator == "additionalProperties" and isinstance(e.instance, dict):
            unknown = sorted(k for k in e.instance if k not in (e.schema.get("properties") or {}))
            msg = "unknown field%s %s" % ("s" if len(unknown) > 1 else "", ", ".join("'%s'" % k for k in unknown))
        elif e.validator == "oneOf" and "is valid under each of" in msg and isinstance(e.instance, dict):
            keys = [k for alt in e.validator_value for k in alt.get("required", []) if k in e.instance]
            msg = "give only one of %s" % ", ".join("'%s'" % k for k in dict.fromkeys(keys))
        err(where, msg)
    if r.errors:
        return r
    if version >= 2:
        # One section per network (as the plugin): each checked against its
        # own network's nodes, messages naming the section.
        nets = contract.networks(cfg) if isinstance(cfg, dict) else []
        names = [section_name(n) for n in nets]
        for name, body in data["networks"].items():
            at = "networks.%s" % name

            def s_err(where, msg, paths=None, at=at):
                err(at + "." + where if where else at, msg,
                    [at + "." + p if p else at for p in (paths if paths is not None else [where])])

            def s_warn(where, msg, paths=None, at=at):
                warn(at + "." + where if where else at, msg,
                     [at + "." + p if p else at for p in (paths if paths is not None else [where])])

            net_cfg = None
            if isinstance(cfg, dict):
                if name not in names:
                    err(at, "there is no network '%s' in the configuration (networks: %s)"
                        % (name, ", ".join(n or "unnamed" for n in names)))
                    continue
                net = nets[names.index(name)]
                net_cfg = {"adapter": net["adapter"], "master": net["master"], "nodes": net["nodes"]}
            _check_body(body, path, net_cfg, config_path, eds_paths, s_err, s_warn, network=name)
        return r
    if several_networks(cfg):
        # As the plugin: a version 1 file serves a configuration with one network.
        warn("", "not used: a version 1 simulation file serves a configuration with one network only (version 2 "
                 "has a section per network under 'networks'); the simulated devices of a configuration with "
                 "several networks run with their default behaviour")
        return r
    if isinstance(cfg, dict) and contract.version_of(cfg) != 1:
        try:
            cfg = contract.network_config(cfg)
        except ValueError:
            pass
    _check_body(data, path, cfg, config_path, eds_paths, err, warn)
    return r


def _check_body(data, path, cfg, config_path, eds_paths, err, warn, network=None):
    """The checks of one part (a version 1 file or a version 2 section)
    against one network's config (or None)."""
    base = os.path.dirname(os.path.abspath(path))
    devices = {}  # node ID or name -> _Device
    by_name = {}
    master_id = None
    u = contract._uint
    if isinstance(cfg, dict):
        master_id = u((cfg.get("master") or {}).get("node_id"))
        cfg_base = os.path.dirname(os.path.abspath(config_path)) if config_path else base
        eds_cache = {}
        for n in cfg.get("nodes") or []:
            nid = u(n.get("node_id"))
            value = n.get("eds")
            file = (eds_paths or {}).get(value) or (_resolve_path(value, cfg_base) if value else None)
            if value not in eds_cache:
                try:
                    eds_cache[value] = eds_mod.Eds.read(file) if file else None
                except (OSError, eds_mod.EdsError):
                    eds_cache[value] = None
            eds = eds_cache[value]
            label = "node %d" % nid + (" (%s)" % n["name"] if n.get("name") else "")
            dev = _Device(label, eds, value or "", cfg_node=n)
            dev.writers = _master_writers(n, eds, nid)
            devices[nid] = dev

    # Extra devices.
    extra_devs = []
    for i, d in enumerate(data.get("extra_devices") or []):
        w = "extra_devices[%d]" % i
        nid, name = d["node"], d.get("name")
        label = "extra device %s" % (name or nid) + (" (node %d)" % nid if name and nid else "")
        if nid == 0 and not name:
            err(w, "a device without a node ID (node 0) needs a 'name'", [w + ".name"])
        if name:
            if name in by_name:
                err(w, "the name '%s' is already used by extra_devices[%d]" % (name, by_name[name]), [w + ".name"])
            else:
                by_name[name] = i
        if nid:
            if master_id is not None and nid == master_id:
                err(w, "node ID %d is the master's node ID" % nid, [w + ".node"])
            elif nid in devices and devices[nid].extra is None:
                err(w, "node ID %d is a node of the configuration; give its behaviour under nodes.\"%d\"" % (nid, nid),
                    [w + ".node"])
            elif nid in devices:
                err(w, "node ID %d is already used by another extra device" % nid, [w + ".node"])
        file = _resolve_path(d["eds"], base)
        eds = None
        if not os.path.isfile(file):
            err(w, "%s: EDS file %s not found (eds: \"%s\")" % (label, file, d["eds"]), [w + ".eds"])
        else:
            try:
                eds = eds_mod.Eds.read(file)
            except (OSError, eds_mod.EdsError) as e:
                err(w, "%s: EDS file %s cannot be parsed: %s" % (label, file, e), [w + ".eds"])
        dev = _Device(label, eds, d["eds"], extra=d)
        if nid and nid not in devices:
            devices[nid] = dev
        if name:
            devices.setdefault(name, dev)
        extra_devs.append(dev)

    # Node entries.
    node_entries = []
    for key, nd in (data.get("nodes") or {}).items():
        nid = int(key)
        w = "nodes.%s" % key
        dev = devices.get(nid)
        if dev is None:
            if cfg is None:
                err(w, "node %d is not an extra device of this file" % nid)
            else:
                err(w, "node %d is neither a node of the configuration nor an extra device" % nid)
            continue
        node_entries.append((["nodes", key], nd, dev))
    for i, d in enumerate(data.get("extra_devices") or []):
        node_entries.append((["extra_devices", i], d, extra_devs[i]))

    expr_sources = {}  # (device id, index, sub) -> (tree, path, text)
    for parts, nd, dev in node_entries:
        dev_key = id(dev)
        for obj, src in (nd.get("sources") or {}).items():
            at = parts + ["sources", obj]
            tree = _check_source(src, obj, dev, at, devices, err, base)
            if tree is not None:
                index, sub = parse_object(obj)
                expr_sources[(dev_key, index, sub)] = (tree, at, src["expr"], dev)
        for k, f in enumerate(nd.get("faults") or []):
            _check_fault(f, dev, parts + ["faults", k], err)

    # Reference cycles among the devices' expression sources.
    _check_cycles(expr_sources, devices, err)

    # The machine file.
    machine = _check_machine(data, base, cfg, devices, network, err, warn)

    # Scenarios.
    for name, sc in (data.get("scenarios") or {}).items():
        for at, step in _steps(sc.get("steps") or [], ["scenarios", name, "steps"]):
            _check_step(step, at, devices, err, warn, base, machine)


class _Machine:
    """The machine a section names, for its scenarios: `data` None when the
    file did not pass its checks (its elements are then not checked)."""

    def __init__(self, network, value=None, data=None):
        self.network, self.value, self.data = network, value, data

    def missing(self):
        """The message for a machine step or condition without a machine."""
        if self.value is None:
            return "%s has no machine (its section names no machine file)" % (
                "network %s" % self.network if self.network else "this network")
        return None


def _check_machine(data, base, cfg, devices, network, err, warn):
    """Loads and checks the machine file a section names: the schema, the
    checks the schema cannot express, and the machine against the network.
    Returns a _Machine."""
    value = data.get("machine")
    if not isinstance(value, str) or not value:
        return _Machine(network)
    label = ("network %s: " % network if network else "") + "machine " + value
    file = _resolve_path(value, base)
    if not os.path.isfile(file):
        err("machine", "%s: machine file %s not found (machine: \"%s\")" % (label, file, value))
        return _Machine(network, value)
    try:
        m = machine_mod.load(file)
    except machine_mod.MachineFileError as e:
        err("machine", "%s: %s" % (label, e))
        return _Machine(network, value)
    problems = machine_mod.schema_problems(m)
    if not problems:
        problems = machine_mod.structure_problems(m)
    for where, msg in problems:
        err("machine", "%s: %s%s" % (label, where + ": " if where else "", msg))
    if problems:
        return _Machine(network, value)
    ok = True
    if isinstance(cfg, dict):
        network_simulated, nodes = simulated(cfg)
        for level, where, msg in machine_mod.config_problems(m, devices, network_simulated, set(nodes), label):
            if level == "warning":
                warn("machine", msg)
            else:
                ok = False
                err("machine", "%s: %s" % (label, msg))
    return _Machine(network, value, m if ok else None)


def _where(parts):
    return contract.json_path(parts)


def _object_problem(dev, obj):
    """(index, sub, None) or (None, None, message) for an object of a device."""
    try:
        index, sub = parse_object(obj)
    except ValueError as e:
        return None, None, str(e)
    if not dev.has(index, sub):
        return index, sub, "%s: object %s is not in %s" % (dev.label, object_key(index, sub), dev.eds_name)
    return index, sub, None


def value_problem(type_name, value):
    """Why a set or override value does not fit an object of a data type
    (an EDS type name such as "INTEGER16"), or None. Numbers with a
    fraction are rounded for an integer object, as the simulator does."""
    if type_name == "VISIBLE_STRING":
        return None if isinstance(value, str) else "a VISIBLE_STRING object takes text, not %s" % json.dumps(value)
    if type_name not in contract.CO_TYPES:
        return None
    if isinstance(value, str):
        return "%s does not fit %s: give a number" % (json.dumps(value), type_name)
    if isinstance(value, float) and not math.isfinite(value):
        return "%s does not fit %s" % (json.dumps(value), type_name)
    if type_name in ("REAL32", "REAL64"):
        return None
    number = int(value) if isinstance(value, bool) else round(value)
    if contract.sdo_value(number, type_name)[1]:
        return "%s does not fit %s" % (json.dumps(value), type_name)
    return None


def _value_problem(o, value):
    if o is None:
        return None
    return value_problem("VISIBLE_STRING" if o.data_type == VISIBLE_STRING else o.type_name, value)


def _resolver(devices, own):
    def resolve(device, index, sub):
        if device is None:
            dev = own
            if dev is None:
                return "[%s] names no device: write [NODE/%s]" % (object_key(index, sub), object_key(index, sub))
        else:
            dev = devices.get(device)
            if dev is None:
                if isinstance(device, int):
                    return "unknown device %d: not a node of the configuration nor an extra device" % device
                return "unknown device '%s': no extra device has this name" % device
        if not dev.has(index, sub):
            return "%s: object %s is not in %s" % (dev.label, object_key(index, sub), dev.eds_name)
        return None
    return resolve


def _check_source(src, obj, dev, at, devices, err, base):
    """Checks one value source; the expression tree for an expr source."""
    w = _where(at)
    index, sub, problem = _object_problem(dev, obj)
    if problem:
        err(w, problem)
        return None
    writer = dev.writers.get((index, sub))
    if writer:
        err(w, "%s: %s is written by the master (%s); a value source cannot drive it (an override makes the device "
               "ignore the master)" % (dev.label, object_key(index, sub), writer))
    o = dev.sub(index, sub)
    is_string = o is not None and o.data_type == VISIBLE_STRING
    kinds = [k for k in src if k not in ("noise", "tick_ms")]
    kind = kinds[0] if kinds else None
    if is_string and kind != "constant":
        err(w, "%s: object %s is a VISIBLE_STRING, which takes only a constant" % (dev.label, object_key(index, sub)))
    if kind == "constant" and isinstance(src["constant"], str) and o is not None and not is_string:
        err(w, "%s: object %s is not a VISIBLE_STRING; its constant must be a number"
            % (dev.label, object_key(index, sub)))
    if kind == "csv":
        file = _resolve_path(src["csv"]["file"], base)
        if not os.path.isfile(file):
            err(w + ".csv.file", "CSV file %s not found (file: \"%s\")" % (file, src["csv"]["file"]))
    if kind == "expr":
        try:
            return parse(src["expr"], _resolver(devices, dev))
        except ExprError as e:
            err(w + ".expr", "expression %r, position %d: %s" % (src["expr"], e.position, e.message))
    return None


def _check_cycles(expr_sources, devices, err):
    graph = {}
    for key, (tree, at, text, dev) in expr_sources.items():
        edges = []
        for ref, broken in references(tree):
            if broken:
                continue
            target = dev if ref.device is None else devices.get(ref.device)
            tk = (id(target), ref.index, ref.subindex)
            if tk in expr_sources:
                edges.append((tk, ref.pos))
        graph[key] = edges
    reported = set()
    state = {}

    def label(k):
        return "%s %s" % (expr_sources[k][3].label, object_key(k[1], k[2]))

    def visit(k, stack):
        state[k] = 1
        stack.append(k)
        for nxt, pos in graph[k]:
            if state.get(nxt) == 1:
                cycle = stack[stack.index(nxt):]
                sig = frozenset(cycle)
                if sig not in reported:
                    reported.add(sig)
                    first = cycle[0]
                    tree, at, text, _ = expr_sources[first]
                    p = next((p for n2, p in graph[first] if n2 == (cycle[1] if len(cycle) > 1 else first)), 0)
                    err(_where(at) + ".expr", "expression %r, position %d: reference cycle %s without lag, delay or "
                        "integrate on the way" % (text, p, " -> ".join(label(c) for c in cycle + [first])))
            elif state.get(nxt) is None:
                visit(nxt, stack)
        stack.pop()
        state[k] = 2

    for k in sorted(graph, key=lambda k: _where(expr_sources[k][1])):
        if state.get(k) is None:
            visit(k, [])


def _check_fault(f, dev, at, err):
    w = _where(at)
    for kind in ("sdo_abort", "sdo_delay"):
        obj = (f.get(kind) or {}).get("object") if isinstance(f.get(kind), dict) else None
        if obj is not None:
            _, _, problem = _object_problem(dev, obj)
            if problem:
                err(w + "." + kind + ".object", problem)
    if "emcy" in f and dev.eds is not None and not dev.eds.has(0x1014):
        err(w + ".emcy", "%s cannot send EMCY: %s has no object 0x1014 (COB-ID EMCY)" % (dev.label, dev.eds_name))
    if "tpdo_stop" in f and dev.eds is not None:
        n = f["tpdo_stop"]
        if not dev.eds.has(0x1800 + n - 1):
            err(w + ".tpdo_stop", "%s: TPDO %d does not exist in %s (no object 0x%04X)"
                % (dev.label, n, dev.eds_name, 0x1800 + n - 1))
    if "drive_input" in f and dev.eds is not None and not dev.eds.has(0x6041):
        err(w + ".drive_input", "%s: drive_input needs a CiA 402 drive (no statusword 0x6041 in %s)"
            % (dev.label, dev.eds_name))


def _check_condition(cond, at, step_dev, devices, err, machine=None):
    w = _where(at)
    if "machine" in cond:
        problem = machine.missing() if machine else "this network has no machine"
        if problem:
            err(w + ".machine", problem)
        elif machine.data is not None and cond["machine"] not in machine_mod.value_names(machine.data):
            err(w + ".machine", "the machine has no value \"%s\" (%s)"
                % (cond["machine"], ", ".join(machine_mod.value_names(machine.data))))
        return
    if "expr" in cond:
        try:
            parse(cond["expr"], _resolver(devices, step_dev))
        except ExprError as e:
            err(w + ".expr", "expression %r, position %d: %s" % (cond["expr"], e.position, e.message))
        return
    dev = devices.get(cond["node"])
    if dev is None:
        err(w + ".node", "unknown device %r: not a node of the configuration nor an extra device" % cond["node"])
        return
    _, _, problem = _object_problem(dev, cond["object"])
    if problem:
        err(w + ".object", problem)


def _check_step(step, at, devices, err, warn, base, machine=None):
    w = _where(at)
    dev = None
    if "machine" in step:
        problem = machine.missing() if machine else "this network has no machine"
        if not problem and machine.data is not None:
            if "fault" in step:
                problem = machine_mod.fault_element_problem(machine.data, step["machine"], step["fault"])
            else:
                problem = machine_mod.clear_element_problem(machine.data, step["machine"], step["clear"])
        if problem:
            err(w + ".machine", problem)
        return
    if "node" in step:
        dev = devices.get(step["node"])
        if dev is None:
            err(w + ".node", "unknown device %r: not a node of the configuration nor an extra device" % step["node"])
            return
    for key in ("set", "override"):
        for obj in step.get(key) or {}:
            if dev is None:
                continue
            index, sub, problem = _object_problem(dev, obj)
            if problem:
                err(w + "." + key, problem)
                continue
            problem = _value_problem(dev.sub(index, sub), step[key][obj])
            if problem:
                err(w + "." + key, "%s: %s of %s: %s" % (dev.label, key, object_key(index, sub), problem))
            elif key == "override" and (index, sub) in dev.writers:
                warn(w + ".override", "%s: object %s is written by the master (%s); the override makes the device "
                     "ignore it" % (dev.label, object_key(index, sub), dev.writers[(index, sub)]))
    if isinstance(step.get("release"), list) and dev is not None:
        for obj in step["release"]:
            _, _, problem = _object_problem(dev, obj)
            if problem:
                err(w + ".release", problem)
    if isinstance(step.get("source"), dict) and dev is not None:
        for obj, src in step["source"].items():
            if src is None:
                _, _, problem = _object_problem(dev, obj)
                if problem:
                    err(w + ".source", problem)
            else:
                _check_source(src, obj, dev, at + ["source", obj], devices, err, base)
    if "fault" in step and dev is not None:
        _check_fault(step["fault"], dev, at + ["fault"], err)
    for key in ("wait", "expect"):
        if key in step:
            _check_condition(step[key], at + [key], dev, devices, err, machine)


def check_file(path, cfg=None, config_path=None, eds_paths=None):
    """Loads and checks a simulation file: (data or None, contract.Result)."""
    try:
        data = load(path)
    except SimFileError as e:
        r = contract.Result()
        r.add("error", str(e), [""])
        return None, r
    return data, check(data, path, cfg, config_path, eds_paths)
