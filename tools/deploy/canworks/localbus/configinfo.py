"""What a local adapter takes from a canworks.json: the network's bit rate,
whether it is listen-only, and its nodes' names and expected identity (for
status and scan)."""

import json

from .. import bundle, contract


def from_config(cfg, config_path, network=None):
    """(bitrate in bit/s or None, {node_id: {"name", "expect"}}) of the network
    `network` (None: the config's only network). Raises ValueError."""
    from ..configurator.online import expected_identity
    net = contract.network_config(cfg, network)
    bitrate = (net.get("adapter") or {}).get("bitrate")
    try:
        paths = bundle.eds_files(cfg, config_path)
    except Exception:
        paths = {}
    nodes = {}
    for n in net.get("nodes") or []:
        try:
            nid = int(str(n.get("node_id")), 0)
        except ValueError:
            continue
        try:
            expect = expected_identity(n, paths.get(n.get("eds")))
        except Exception:
            expect = {}
        nodes[nid] = {"name": n.get("name") or "", "expect": expect}
    return (int(bitrate) if isinstance(bitrate, int) else None), nodes


def listen_only(cfg, network=None):
    """True when the network `network` (None: the config's only network) has
    adapter.listen_only: true: the adapter connects listen-only and sends
    nothing. Raises ValueError."""
    adapter = contract.network_config(cfg, network).get("adapter")
    return isinstance(adapter, dict) and adapter.get("listen_only") is True


def _read(config_path):
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def load(config_path, network=None):
    return from_config(_read(config_path), config_path, network)


def load_listen_only(config_path, network=None):
    return listen_only(_read(config_path), network)
