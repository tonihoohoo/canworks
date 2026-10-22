## 1. Stamp and skip

- [x] 1.1 `install-stock.sh`: compute the stamp (version as `write_version` would write it, protocols, native runtime commit or Docker image id of the spec's image) before any step that changes the device
- [x] 1.2 Skip check: stamp equal, plugin library present, native `canworks` line in `plugins.conf` or Docker spec entries present, version not `unknown` or `-dirty`; on a skip print the one line, run `setup_j1939_module` and `setup_remote_access` with matching step lines, exit 0
- [x] 1.3 Remove the stamp when a full install starts; write it last, after the plugin, hook, `plugins.conf` (native) or spec and container recreate (Docker)
- [x] 1.4 `--force` option in `install-stock.sh`; help lines in `install-runtime.sh` and `install-runtime.ps1` (pass-through already works)
- [x] 1.5 `--uninstall` removes the stamp with `<prefix>/lib/`

## 2. Devices page

- [x] 2.1 Check that an install job with zero or one step line ends as done on the device page and in the status bar; fix if not (the view handles any number of steps; a skipped run now says the version was already installed and the PLC keeps its program, instead of "Until then the PLC has no program")

## 3. Tests

- [x] 3.1 `test/stock/run.sh`: second run with the same checkout skips (no rebuild, `plugins.conf` unchanged, plugin stays enabled), `--force` rebuilds; run that changes the runtime commit rebuilds
- [x] 3.2 `test/docker/test_install_docker.py`: second run does not recreate the runtime container; `--force` does; a changed image id rebuilds
- [x] 3.3 `test/pc-tools/test_install_scripts.py`: `--force` passes through `install-runtime.sh` and `.ps1`, also over `--ssh`
- [x] 3.4 `-dirty` and `unknown` versions never skip (unit check of the stamp function)

## 4. Docs and release

- [x] 4.1 `docs/install-stock.md` and README: re-running the same release changes nothing; `--force`
- [x] 4.2 Tools minor version bump (0.112.0); the release notes are a per-release template with no change list, so no line there
- [ ] 4.3 CI wall and summed job time against the baseline, in the PR

## 5. Hardware

- [ ] 5.1 Pi (Docker): `install-runtime.sh` of the new release, upload a program, run the same line again: no container recreate, PLC keeps running, node OPERATIONAL; `--force` recreates as before. After the first full install also check that `/opt/canworks/lib/canworks-sim` and the `/usr/local/bin/canworks-sim` link are gone (follow-up of the simulator naming change)
