# Proposal: add-remote-use-over-ssh

## Why

Toni (2026-10-19) wants to install the PC tools on a Linux machine and use the configurator from a web browser on another computer. Today `canworks-config` listens on 127.0.0.1 only, and the explore found:

- **An SSH tunnel almost works.** `ssh -L 8765:127.0.0.1:8765 host canworks-config --no-browser --port 8765` works, but the DNS-rebinding guard accepts only `Host: 127.0.0.1:<server port>`, so a tunnel with a different local port (the usual case, and the only choice when that port is taken on the PC) gets 403 "requests must address 127.0.0.1".
- **On a machine without a screen** the configurator still tries to open a browser. Over SSH on a headless Linux board this printed "Terminal initialisation failed - unknown terminal type?" twice, and nothing says how to reach the page from another computer.
- **A closed tab means a restart.** The start address works once; there is no way to get a new one from the running configurator.
- **Two configurators on one PC log each other out.** The session cookie has one fixed name, and browsers share cookies across ports of the same host, so a tunnelled configurator and a local one (or two local ones) overwrite each other's cookie.
- Almost everything else already works with the browser on another computer: the folder dialog lists the server machine's folders, EDS and backup files are picked through the browser, and exports download to the browser.

SSH is the right way in: it already authenticates the user, encrypts, and is how the runtime and bridge installers reach Linux devices (`--ssh`). Nothing new listens on the network.

## What Changes

- The rebinding guard accepts `127.0.0.1`, `localhost` and `[::1]` with **any port**, so any `ssh -L` port works. Other names stay refused.
- The session cookie's name includes the port the browser uses, so configurators on different ports keep their own sessions.
- **No display, no browser:** on Linux with neither `DISPLAY` nor `WAYLAND_DISPLAY` set, or in an SSH session, the configurator does not try to open a browser and prints how to reach it from another computer (the `canworks-config --ssh` line and the plain `ssh -L` line, with this machine's user and name filled in).
- **New start address while running:** pressing Enter in the configurator's terminal prints a new one-time start address (and opens it when a browser can be opened). The old session cookie keeps working.
- **`canworks-config --ssh USER@HOST [PATH]`** on the PC with the browser: starts the configurator on the other machine over one SSH connection with a port forward, and opens the page in the local browser. Ctrl-C stops both. Enter gets a new start address through the same connection. It needs only an `ssh` client (built into Windows 10+, macOS and Linux) and the PC tools on both machines.
- README and `docs/configurator.md` get a "Use from another computer" section, including what is different when the configurator runs elsewhere (files, USB adapters and Recent are the other machine's; the OpenPLC Editor on the browser's PC does not see projects on the other machine; Build into a CODESYS project needs CODESYS on the machine running the configurator).

No config format, plugin or runtime change. No network listener: the configurator still listens on loopback only.

## Non-goals

- A built-in listener on other interfaces (`--listen`) with HTTPS and a login, for browsers without SSH (tablet, locked-down PC). Possible later; the page can write any folder the user can and command CAN devices, so it would need its own careful change.
- Reaching the configurator through the iroh remote link.

## Capabilities

### Modified Capabilities
- `canopen-configurator`: Local access only (any loopback port, cookie per port), and new requirements for use from another computer over SSH, a new start address while running, and no browser launch without a display.
