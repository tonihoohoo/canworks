# Design: add-remote-use-over-ssh

## Rebinding guard

`Handler._host_ok` today compares Host with `127.0.0.1:<server_port>` and `localhost:<server_port>`. DNS rebinding works by making an attacker's name resolve to 127.0.0.1, so the browser sends the attacker's name in Host; the name is what the guard must check, not the port. New rule: split Host into name and port (port required, digits, 1-65535); the name must be `127.0.0.1`, `localhost` or `[::1]`, case ignored. Everything else stays 403. The session cookie and token header checks are unchanged, so a local process still needs the token.

## Cookie per port

Browsers do not scope cookies by port, so `canopen_session` from a configurator on port A is overwritten by one on port B (both sides' tabs then get 403). The cookie name becomes `canopen_session_<port>`, where `<port>` is the port in the request's Host (the port the browser used, which behind a tunnel is the local forward port). Set on the start-code redirect, read the same way. No migration: sessions last one run.

## No browser without a display

`webbrowser.open` on a Linux box without a display falls back to text browsers (the "Terminal initialisation failed" lines seen on a headless Linux board). Skip it when `os.name == "posix"`, not macOS, and neither `DISPLAY` nor `WAYLAND_DISPLAY` is set, or when `SSH_CONNECTION` is set on any OS. Then print, after the address line:

```
No browser here. From another computer:
  canworks-config --ssh alice@linuxbox [PATH]
or
  ssh -L 8765:127.0.0.1:<port> alice@linuxbox   and open the address with port 8765
```

User from `getpass.getuser()`, name from `socket.gethostname()`. `--no-browser` keeps its meaning; a new `--browser` forces the launch.

## New start address

A thread reads stdin lines when stdin is a terminal (or, for the helper, when started with `--remote-child`, see below). Each Enter adds a new code (`Server.url`) and prints `canworks configurator: <url>`. Codes stay one-time. A pending-codes cap (16, oldest dropped) keeps Enter-spamming from growing the set.

## `canworks-config --ssh USER@HOST`

Runs on the PC with the browser:

1. Pick a free local port L (bind 127.0.0.1:0) and a random remote port R in 20000-59999.
2. Start `ssh -tt -o ExitOnForwardFailure=yes -L L:127.0.0.1:R USER@HOST <remote command>` where the remote command is `sh -c 'PATH="$HOME/.local/bin:$PATH" exec canworks-config --remote-child --port R [PATH]'` (uv puts tools in `~/.local/bin`, which a non-interactive SSH shell often lacks on PATH). `--ssh-command` overrides the remote command for unusual installs. Extra `ssh` options go after `--ssh-option` (repeatable), for example a key or a jump host.
3. Read the child's output. On `cannot listen on 127.0.0.1:R` pick another R and retry (up to 5). On `command not found` or exit 127, say the PC tools are not installed on HOST and show the one-line installer.
4. When `canworks configurator: http://127.0.0.1:R/?code=...` arrives, rewrite the port to L and open it locally (or print it with `--no-browser`). Pass other lines through.
5. Enter in the helper's terminal is forwarded to the child, which prints a new address; the helper rewrites and opens it the same way.
6. Ctrl-C or the page's Quit: the helper ends ssh; the remote pty hangs up and the child stops (SIGHUP). If ssh drops, the helper says the connection was lost and exits non-zero.

`--remote-child` means: never open a browser, never print the "No browser here" help, read Enter from stdin, and use line-buffered output. It is hidden from `--help`.

Password prompts and host key questions from ssh go straight to the user's terminal (`-tt`, inherited stdin until the address line arrives). Windows: OpenSSH client is `ssh.exe` in System32 on Windows 10+; the helper looks it up on PATH and says how to add the optional feature when it is missing.

## Why not a network listener

It would put a page that can browse and write the user's files and send SDOs, NMT and raw frames on the LAN. It would need TLS (self-signed with a printed fingerprint), a login that survives restarts, an allow-list of host names, rate limits and a folder root. SSH already gives all of that. Left out until a viewer that cannot run SSH is a real need.

## Risks

- Remote PATH differences: covered by the `$HOME/.local/bin` prefix and `--ssh-command`.
- A shell that is not POSIX on the remote (fish): `PATH=... cmd` fails there. The helper runs the command through `sh -c '<cmd>'` to be shell-independent.
- Other users on the remote machine can connect to 127.0.0.1:R, as they can to a local configurator today; the session token still blocks them.
