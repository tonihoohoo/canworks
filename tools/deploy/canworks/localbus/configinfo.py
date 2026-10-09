"""What a local adapter takes from a canworks.json: the network's bit rate and
its nodes' names and expected identity (for status and scan)."""

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


def load(config_path, network=None):
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    return from_config(cfg, config_path, network)
