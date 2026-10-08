## 1. Timing

- [ ] 1.1 Before applying, check that no other pull request is open (today #39 and the `propose/add-machine-sim` branch). If any is, wait for it to merge, or agree with its thread to replay the rename on its branch (design Decision 6).

## 2. Rename script

- [ ] 2.1 Write `scripts/rename_to_opencan.py` with the mapping table from design Decision 1, using explicit patterns and excluding `openspec/changes/archive/**`, `LICENSE`, on-device names (`/opt/openplc-canopen`, `libcanopen_plugin.so`, plugin name `canopen`, `conf/canopen.json`, the editor hook module, `OPENPLC_CANOPEN_SIM_*`) and the alias definitions; add `--check`; verify that it is idempotent with a unit test in `.github/scripts/` tests (run twice, second run changes nothing).
- [ ] 2.2 Run the script and commit its output alone ("rename: script output"), including `openspec/specs/` and the package directory move.

## 3. Compatibility code (hand-written commit)

- [ ] 3.1 Alias entry points for the four old commands plus `openplc-canopen-runtime` (stderr hint, same main); verify with a deploy-tool test comparing stdout and exit status of old and new names.
- [ ] 3.2 Environment variable lookup helper (`OPENCAN_*` first, then `OPENPLC_CANOPEN_*`) used by every PC-tools read; verify with tests for the token and engine variables.
- [ ] 3.3 Settings folder copy-on-first-use in `userdirs.py`; verify with tests on all three platform layouts (temp HOME/APPDATA/XDG).
- [ ] 3.4 Local runtime: list of earlier container names, newest first; image name `opencan-plc-sim-runtime`; verify with `test_localruntime.py` cases for takeover from `openplc-canopen-sim-runtime` and from `openplc-canopen-runtime`.
- [ ] 3.5 Editor hook distribution `opencan-plc-editor-hook` depending on `opencan-plc`; check that `install-stock.sh` and the Docker spec still install to `/opt/openplc-canopen` and register `canopen`, with tests asserting both.

## 4. CI, release and docs

- [ ] 4.1 Workflows: wheel name, image name, package paths in `test_shard.py`, labels in `docker/local-runtime/Dockerfile`; add `rename_to_opencan.py --check` to the tools job (no new job, so CI time is unchanged); compare wall time with the median of the last 5 green main runs and state it in the PR.
- [ ] 4.2 README: new name in the title and intro ("CAN fieldbus toolkit for OpenPLC Runtime v4"), an "Upgrading from openplc-canopen" section (pip/uv uninstall + install, aliases, settings copy); update `docs/install-pc.md`, `docs/local-runtime.md`, `docs/install-stock.md` and the configurator page title.
- [ ] 4.3 Bump the PC tools to 0.41.0; the release notes text names the renamed wheel and image.
- [ ] 4.4 Run the banned-word check on the branch (`--files` and `--range origin/main..HEAD`).

## 5. After merge

- [ ] 5.1 Toni renames the repository to `opencan-plc` in GitHub Settings; then verify that the old clone URL redirects and the new docs links resolve.
- [ ] 5.2 After `deploy-v0.41.0` publishes, set the `opencan-plc-sim-runtime` package public; verify an anonymous `docker pull`.
- [ ] 5.3 Post the in-flight branch recipe (design Decision 6) in the project chat once, and update project memory with the new names.

## 6. Hardware check

- [ ] 6.1 On Toni's Mac: upgrade the tools from 0.40.0, check that `openplc-canopen-diag status` prints the hint and works against the Pi, the saved runtime and token are carried over, and `opencan-sim-runtime update` takes over the old local runtime with the same login.
