## MODIFIED Requirements

### Requirement: Local access only
The configurator SHALL listen only on the loopback interface and SHALL reject any request that does not carry the random session token it generated at start. It SHALL refuse requests whose Host names anything other than `127.0.0.1`, `localhost` or `[::1]`, with any port, so that a page on another site cannot reach it through DNS rebinding while a port forward to a different local port still works. The session cookie's name SHALL include the port in the request's Host, so configurators reached on different ports keep separate sessions. The page SHALL load no resource from the network. The configurator's own outgoing connections SHALL go only to the runtime host and port the user entered for online access, and only while the user has the online view or scan open.

#### Scenario: Request from another host
- **WHEN** another machine on the LAN connects to the configurator's port
- **THEN** the connection is refused because nothing listens on a non-loopback address

#### Scenario: Request without the token
- **WHEN** a local process sends a save request without the session token
- **THEN** the request is rejected and nothing is written

#### Scenario: Offline editing makes no connection
- **WHEN** the user edits and saves a config without opening the online view or scan
- **THEN** the configurator opens no network connection

#### Scenario: Port forward to another local port
- **WHEN** the configurator listens on port 8765 and the browser reaches it through `ssh -L 9000:127.0.0.1:8765` at `http://127.0.0.1:9000/` with a fresh start address
- **THEN** the page opens and works

#### Scenario: Rebinding name refused
- **WHEN** a request arrives with `Host: attacker.example:8765`
- **THEN** it is refused with 403 and nothing else happens

#### Scenario: Two configurators in one browser
- **WHEN** one configurator is open at port 9000 and another at port 9001 in the same browser
- **THEN** both pages keep working and neither is logged out by the other

## ADDED Requirements

### Requirement: No browser launch without a display
The configurator SHALL NOT try to open a browser when it runs in an SSH session, or on Linux with neither `DISPLAY` nor `WAYLAND_DISPLAY` set, unless started with `--browser`. It SHALL then print, after the start address, how to open the page from another computer: the `canworks-config --ssh USER@HOST` command and the plain `ssh -L` command, with this machine's user name and host name filled in.

#### Scenario: Started over SSH on a headless Linux machine
- **WHEN** the user runs `canworks-config` in an SSH session on a Linux machine without a display
- **THEN** no browser or text browser is started, no terminal errors appear, and the output shows the start address followed by the two ways to open it from another computer

### Requirement: New start address while running
While the configurator runs in a terminal, pressing Enter SHALL print a new one-time start address (and open it when the configurator opens browsers). Each address SHALL work once; earlier sessions SHALL keep working. At most 16 unused addresses SHALL be kept, the oldest dropped first.

#### Scenario: Tab closed
- **WHEN** the user closes the configurator's tab and presses Enter in its terminal
- **THEN** a new address is printed, opening it shows the page with the same open folder, and the old address is still refused

### Requirement: Use from another computer over SSH
`canworks-config --ssh USER@HOST [PATH] [--no-browser] [--ssh-option OPT]... [--ssh-command CMD]` SHALL start the configurator on HOST over one SSH connection with a port forward from a free port on the local 127.0.0.1, and SHALL open the page in the local browser (print it with `--no-browser`). It SHALL find `canworks-config` in the remote user's `~/.local/bin` even when that is not on the SSH session's PATH, and SHALL retry with another remote port when the one it picked is taken. SSH password and host key prompts SHALL reach the user's terminal. Enter SHALL give a new start address through the same connection. Ctrl-C, or Quit on the page, SHALL stop the configurator on HOST and close the connection. It SHALL listen only on the local 127.0.0.1 and SHALL open nothing on HOST but the SSH connection. When the PC tools are missing on HOST, it SHALL say so and show the installer command; when no `ssh` client is found, it SHALL say how to install one.

#### Scenario: Configurator on a Linux machine, browser on the PC
- **WHEN** the user runs `canworks-config --ssh alice@linuxbox ~/projects/line3` on a Windows PC and enters the SSH password
- **THEN** the PC's browser opens the configurator with linuxbox's folder `~/projects/line3`, the folder dialog lists linuxbox's folders, and exports download to the PC

#### Scenario: Stopped from the PC
- **WHEN** the user presses Ctrl-C in the helper's terminal
- **THEN** the configurator on linuxbox stops and nothing of it keeps running there

#### Scenario: Tools not installed on the other machine
- **WHEN** linuxbox has no `canworks-config`
- **THEN** the helper says the PC tools are not installed on linuxbox, shows the one-line installer, and exits non-zero

#### Scenario: Connection lost
- **WHEN** the SSH connection drops while the page is open
- **THEN** the helper says the connection to linuxbox was lost and exits non-zero, and the configurator on linuxbox stops
