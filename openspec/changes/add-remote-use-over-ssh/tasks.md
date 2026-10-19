# Tasks

## 1. Access rules

- [ ] 1.1 Tests: Host `127.0.0.1:<any port>`, `localhost:<any port>`, `[::1]:<any port>` accepted (case ignored); missing port, bad port, other names and `127.0.0.1.attacker.example` refused with 403.
- [ ] 1.2 `Handler._host_ok`: name check with any port, per design.
- [ ] 1.3 Cookie name `canopen_session_<port>` from the request's Host, set on the start-code redirect and read on every request; test with two servers and one cookie jar (neither logs the other out).

## 2. Terminal

- [ ] 2.1 No browser in an SSH session or on Linux without `DISPLAY`/`WAYLAND_DISPLAY`; `--browser` forces it; the "No browser here" help with user and host name. Tests with a patched environment and `webbrowser.open` stubbed.
- [ ] 2.2 Enter prints a new start address (stdin a terminal, or `--remote-child`); at most 16 unused codes kept, oldest dropped; tests that a new code works once and old sessions keep working.

## 3. `--ssh` helper

- [ ] 3.1 `canworks-config --ssh USER@HOST [PATH]` with `--no-browser`, repeatable `--ssh-option`, `--ssh-command`; hidden `--remote-child`.
- [ ] 3.2 Free local port, random remote port, `ssh -tt -o ExitOnForwardFailure=yes -L`, remote command through `sh -c` with `$HOME/.local/bin` on PATH; retry up to 5 times on "cannot listen".
- [ ] 3.3 Read the child's output: rewrite and open the address, pass other lines through, forward Enter; missing tools (exit 127) and missing `ssh` messages; lost connection exits non-zero.
- [ ] 3.4 Ctrl-C and page Quit end the remote configurator (pty hang-up); test that the child exits on SIGHUP.
- [ ] 3.5 Tests with a fake `ssh` on PATH that runs the remote command locally and forwards the port (Linux and macOS CI; Windows runs the argument and message tests).

## 4. Docs and version

- [ ] 4.1 `docs/configurator.md` "Use from another computer": the helper, the plain `ssh -L` route, what differs when the configurator runs elsewhere (files, USB adapters, Recent and settings are the other machine's; the editor on the browser's PC does not see projects there; CODESYS build needs CODESYS where the configurator runs).
- [ ] 4.2 README: one line under the PC tools with the `--ssh` command and a link to the section; `docs/install-pc.md` mentions installing on a Linux machine for remote use.
- [ ] 4.3 Bump the PC tools version (minor) and add release notes.

## 5. CI time

- [ ] 5.1 Compare the PR's CI wall and summed job time with the main baseline and note both in the PR.

## 6. Hardware / bench (manual)

- [ ] 6.1 Configurator on the bench Linux board over SSH from the Windows PC with `--ssh`: page opens, open a config folder, export downloads to the PC, Ctrl-C leaves no process on the board.
- [ ] 6.2 Same from the Mac, plus Enter for a new address after closing the tab.
- [ ] 6.3 Plain `canworks-config` in an SSH session on the board: no terminal errors, help lines printed.
