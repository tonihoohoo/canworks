"""The remote link (docs/remote-access.md): reach a runtime from other
networks over iroh, a peer-to-peer QUIC library that dials by public key,
punches through NAT and falls back to a relay.

The device side (`canworks-link`, device.py) accepts paired PCs only and
forwards their streams to the diagnostics port and the runtime's HTTPS port
on 127.0.0.1. The PC side (pc.py) remembers runtimes, pairs with the
diagnostics token and gives the PC tools a local socket to either target.

iroh is optional: on a platform without its wheel, `available()` is false
and the tools connect directly as before."""

ALPN = b"canworks/link/1"
DEFAULT_LINK_PORT = 7533   # the device's UDP port, advertised over mDNS
DIAG_PORT = 7531
RUNTIME_PORT = 8443

# Stream targets: the first line of every stream names one.
FORWARD_TARGETS = ("diag", "runtime")
CONTROL_TARGETS = ("pair", "manage", "info", "unpair")

UNAVAILABLE = ("the remote link is not available on this platform (no iroh package for it); "
               "connect directly or through a VPN instead")


def available():
    """Whether the iroh package can be imported here."""
    try:
        import iroh  # noqa: F401
    except Exception:
        return False
    return True
