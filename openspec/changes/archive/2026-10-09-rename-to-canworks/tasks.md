## 1. Timing

- [x] 1.1 Before applying, check that no other pull request is open. If any is, wait for it to merge, or agree with its thread to replay the rename on its branch (design Decision 4).

## 2. Rename script

- [x] 2.1 Write `scripts/rename_to_canworks.py` with the mapping from design Decision 1: path moves (package, hook, schemas, library) and explicit text patterns, excluding `openspec/changes/archive/**`, `LICENSE` and the CANopen-specific names (`canopen-*` capabilities, CANopen example configs, CANopen block names); add `--check`. Verify with a unit test that it is idempotent (second run changes nothing) and leaves a CANopen capability path untouched.
- [x] 2.2 Run the script and commit its output alone ("rename: script output"), including `openspec/specs/`.

## 3. Hand edits (second commit)

- [x] 3.1 Remove the `openplc-canopen-runtime` alias entry point and its local-runtime takeover code for the 0.30 name (no compatibility layer); update `test_localruntime.py`.
- [x] 3.2 `install-stock.sh` and `docker_spec.py`: remove a leftover `canopen` line, `/opt/openplc-canopen` and old runtime-spec entries, one line each; verify in the Docker-mode stub test and the stock install test.
- [x] 3.3 Check that config examples, schema `$id`s and the editor hook's folder lookup (`canworks/canworks.json`) all agree; run the full local suite (C++ ctest, deploy tool, editor hook, configurator page tests).

## 4. CI, release and docs

- [x] 4.1 Workflows: wheel and image names, package paths in `test_shard.py`, labels in `docker/local-runtime/Dockerfile`; `rename_to_canworks.py --check` in the tools job (no new job). State the CI wall time against the median of the last 5 green main runs in the PR.
- [x] 4.2 README: title "canworks", tagline "Open CAN toolkit: configure, commission, diagnose, trace and simulate CANopen and J1939 networks, with runtime plugins for OpenPLC", a short "Renamed from openplc-canopen" note (reinstall tools, re-run the installer, rename the project folder); update `docs/` and the configurator page title.
- [x] 4.3 Bump the PC tools to 0.42.0; release notes name the new wheel and image.
- [x] 4.4 Run the banned-word check on the branch (`--files` and `--range origin/main..HEAD`).

## 5. After merge

- [ ] 5.1 The owner renames the repository to `canworks` in GitHub Settings; then verify that the old clone URL redirects.
- [ ] 5.2 After `deploy-v0.42.0` publishes, set the `canworks-sim-runtime` package public; verify an anonymous `docker pull`.
- [ ] 5.3 Post the in-flight branch recipe once in the project chat; update project memory with the new names.

## 6. Bench

- [ ] 6.1 Reinstall the PC tools on the engineering PC; re-run `install-stock.sh` on the bench PLC (check that the cleanup lines appear and only `canworks` is in `plugins.conf`); rename the template project's `canopen/` folder to `canworks/`, redeploy, and check that the nodes boot and the configurator connects.
