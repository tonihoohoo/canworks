# Tasks

## 1. Tests first

- [ ] 1.1 `test/pc-tools/test_install_scripts.py`: `install-bridge.sh --dry-run` outside a checkout (script copied alone to a temp folder) resolves the newest release from the redirect, builds the tarball URL, honours `--version`, passes other options through; `--ssh` with `--port`/`--identity` builds the expected `ssh -t` line pinned to the version; `--instance`/`--config` over `--ssh` builds the `ssh` (mktemp), `scp` and `ssh -t` lines; `--instance` without `--config` (and the reverse) and a bad `NAME` are refused before anything runs. Fails on main.
- [ ] 1.2 Same for `install-bridge.ps1 -DryRun` under `pwsh` when present.
- [ ] 1.3 Checkout mode with `--binary` and a recording `CANWORKS_SYSTEMCTL`: an active instance is restarted after the install, an inactive one is not; `--instance line1 --config DIR` copies the files, runs `--check-only` (stub binary), enables and restarts `canworks-bridge@line1`; a failing check exits non-zero without enable/restart.
- [ ] 1.4 Prefix: with `CANWORKS_DEFAULT_PREFIX` pointing at a folder whose venv the host cannot run, no `--prefix` installs into the fallback and says so; explicit `--prefix` still refuses.
- [ ] 1.5 `shellcheck` list in the tools shard includes `scripts/install-bridge.sh`.

## 2. Scripts

- [ ] 2.1 `scripts/install-bridge.sh`: wrap in `main "$@"`; mode choice (checkout, release, ssh); release lookup and download copied from `install-runtime.sh`; root check before download; `CANWORKS_PLUGIN_VERSION` for release builds; `--dry-run`.
- [ ] 2.2 `--instance`/`--config` on the device (copy, `--check-only`, enable + restart) and over `--ssh` (mktemp, `scp`, internal `--remove-config-dir`).
- [ ] 2.3 Restart active `canworks-bridge@` instances after an update.
- [ ] 2.4 Prefix fallback to `/opt/canworks-bridge` without `--prefix`; updates and `--uninstall` find it.
- [ ] 2.5 `scripts/install-bridge.ps1` (PowerShell 5.1, built-in OpenSSH and scp).
- [ ] 2.6 `scripts/install-runtime.sh`: export `CANWORKS_PLUGIN_VERSION`; check that `install-stock.sh` carries it into the native and the managed Docker build.
- [ ] 2.7 `bridge-image.yml` still builds the image from the checkout (CI).

## 3. Docs

- [ ] 3.1 `docs/modbus-bridge.md` Install: one line on the device, from macOS/Linux and from Windows over SSH, with `--instance`/`--config`; pinned and download-first forms; key-based SSH note; checkout route and container image kept, the image named as the fast route.
- [ ] 3.2 README install section and `tools/deploy/release-notes.md`: the bridge line next to the runtime line (update `test/pc-tools/test_release_notes.py` if it checks the lines).

## 4. Hardware

- [ ] 4.1 From the Windows PC, `install-bridge.ps1 -Ssh` onto the Pi with `-Instance` and a config on the Pi's CAN interface: installs under `/opt/canworks-bridge` (Docker runtime there), `canworks-bridge --version` prints the release, the instance runs, logs that the interface is owned by the runtime's plugin and leaves that network off, and its Modbus port answers from the PC.
- [ ] 4.2 Re-run the same line (update): the instance is restarted. Then `-Options --uninstall,--purge`; nothing of the bridge is left and `/opt/canworks` is unchanged. Clean PLC start afterwards.
- [ ] 4.3 From the Mac, `install-bridge.sh --ssh ... --dry-run` prints the expected command lines (no second install on the Pi).

## 5. Release

- [ ] 5.1 Minor bump of the tools package.
- [ ] 5.2 CI time: wall and summed job time against the baseline, stated in the PR.
