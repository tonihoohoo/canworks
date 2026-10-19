# Proposal: add-remote-adapter

## Why

Toni (2026-10-19) wants to commission with the PC tools on his own PC while the CAN bus is at another machine: "use just commission tool remotely, so you would use remote machine's CAN". The configurator, its project folders, EDS files and the OpenPLC Editor stay on the PC; only the bus is elsewhere.

What exists:
- A machine that runs the canworks runtime already gives this: the online view works over the runtime's bus through the encrypted diagnostics channel (TLS + SCRAM) and, from other networks, the remote link.
- A plain Linux machine with a CAN adapter and no runtime gives nothing. `--adapter` passes any python-can type through, so `socketcand` on the machine and `--adapter socketcand:can0` might work, but it is untested, socketcand has no login and no encryption (anyone on the LAN can send frames), every SDO segment and LSS step would cross the network, and the listen-only bit rate check cannot work through it.
- The commissioning backend (`LocalBus`) already has the diagnostics client's interface and answers the same operations, so a server that puts `LocalBus` behind the diagnostics protocol makes the existing Commission, online, parameters and trace pages work on a remote adapter. The bus timing (SDO, LSS, scan, the bit rate check) stays on the machine with the adapter; only operation results cross the network.

## What Changes

- New command on the machine with the adapter: `canworks-diag adapter-serve --adapter TYPE:CHANNEL --bitrate KBIT [--port 7536] [--bind ADDR] [--allow-changes]`. It serves the adapter with the diagnostics protocol: TLS with a fresh self-signed certificate and the SCRAM login bound to it, the same as the plugin. The bit rate is fixed by the server (never guessed); the server opens the adapter and runs the bit rate check when the first PC logs in, and closes it when the last one leaves. Up to 4 PCs share it.
- **The token:** the first start makes a token, prints it once and keeps only its verifier (in the user's settings folder, readable only by the user). `--new-token` replaces it. A wrong token is delayed and rate-limited like the remote link's pairing.
- **Changes are double opt-in:** the server refuses SDO writes, NMT, LSS, frames and PDO test unless started with `--allow-changes`, and the PC still has its own Allow changes switch per session, as with a local adapter.
- **Running without a terminal:** `sudo canworks-diag adapter-serve --install-service ...` writes and starts a systemd service with the same options (running as the user who ran sudo, with only the capability to bring the CAN interface up), and `--remove-service` takes it away. The service advertises itself on the LAN (`_canworks._tcp`, TXT `kind=adapter`) so the PC finds it.
- **On the PC:** `canworks-diag --adapter remote:HOST[:PORT]` and the configurator's connect panel get **Adapter on another machine** next to the USB adapter in Commission a device, and as a target with a config: the found adapter servers and a host field, the token prompt (the token kept on this PC like a runtime token), and Connect. The connection bar shows `adapter can0 on HOST` and the round trip.
- Reaching it from another network: through an SSH port forward (documented); the remote link is not extended.
- Docs: `docs/pc-adapter.md` "An adapter on another machine", README line, `docs/install-pc.md` (installing on the Linux machine with the one-line installer).

## Non-goals

- Running the configurator itself on the other machine (explored in this thread first; set aside by Toni for this).
- Remote adapters through the iroh remote link, and Windows/macOS as the serving machine (Linux only; python-can adapters elsewhere are passed through untested).

## Capabilities

### New Capabilities
- `canopen-remote-adapter`: the adapter server, its login, limits, service install, and the PC side.

### Modified Capabilities
- `canopen-configurator`: Connect panel gains Adapter on another machine.
