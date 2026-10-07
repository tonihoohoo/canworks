## 1. Command and names

- [x] 1.1 Rename the image repository, container and volume constants in `localruntime.py` to `openplc-canopen-sim-runtime`, add the `openplc-canopen-sim-runtime` entry point and keep `openplc-canopen-runtime` as the alias that prints the rename line; update every message and help text naming the command (`cli.py`, `diag.py`, configurator page); verify with unit tests of the alias (same exit status, one stderr line).
- [x] 1.2 Save the data volume name in `local-runtime.json` and use it in every subcommand; take over a container named `openplc-canopen-runtime` in `start` and `update` (stop, remove, recreate under the new name on its volume) and report both-containers in `start`/`status`; verify with fake-engine unit tests for takeover, both containers and fresh install.
- [x] 1.3 Bump the PC tools version (next free minor after what `main` carries when this is applied).

## 2. Image, CI and release

- [x] 2.1 Change the image title label in `docker/local-runtime/Dockerfile` and the image name in `release-deploy.yml`; keep the "never overwrite an existing version tag" check on the new name.
- [x] 2.2 Update `test/local-runtime/run.sh` and `local-runtime.yml` to the new command, and add a takeover step: start a container under the old name with the old volume, then `update` with the new command and check the fingerprint and login are unchanged; verify green on the PR.
- [ ] 2.3 After the first release with this change: check an anonymous pull of `ghcr.io/tonihoohoo/openplc-canopen-sim-runtime:<version>`, and set the package to public once if it is not.

## 3. Fixes from the first hardware run

- [x] 3.1 Plugin version in the image from `CANOPEN_PLUGIN_VERSION` (CMake reads it before `git describe`; the Dockerfile passes the tools version), checked by the end-to-end test; the forced-simulation wording of the simulated-network warnings; `logs` on one stream (unit test).

## 4. Docs

- [x] 4.1 Update `docs/local-runtime.md` (new command and image, a short "Renamed in <version>" note with the takeover and the alias), README, `docs/install-pc.md`, `docs/deploy.md` and `tools/deploy/README.md`.

## 5. Hardware check (manual)

- [ ] 5.1 On the Mac with Colima: with a local runtime still running from tools 0.30.x, upgrade the tools, run `openplc-canopen-sim-runtime update`, and check that the uploaded program's user and fingerprint survive and that `openplc-canopen-runtime status` still works with the rename line.
