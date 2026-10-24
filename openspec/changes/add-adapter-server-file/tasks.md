## 1. The file

- [ ] 1.1 `scripts/build-adapter-pyz.py` (wheel + constraints → pruned canworks, python-can, pyserial and their pure-Python deps, no `.so`/`__pycache__`, `__main__.py` with the 3.11 check, compressed zipapp); unit test of the contents and the size limit
- [ ] 1.2 `serve._command()`: run from a zip → `[sys.executable, realpath]`; test with a built file
- [ ] 1.3 Release workflow: build the file from the release wheel and constraints, attach `canworks-adapter-<version>.pyz` and `install-adapter.sh`; check the asset list in the release test

## 2. Install script

- [ ] 2.1 `install-adapter.sh`: python3 3.11+ and openssl checks, `--file`, download of the file, version from `--version`, atomic install, old venv removed, no pip/venv/apt; uninstall removes the file with the last server
- [ ] 2.2 `test/adapter/install_test.sh` and `test/pc-tools/test_install_scripts.py`: stub download, uploaded file without network, missing openssl, old Python, uninstall one/all; shellcheck

## 3. Devices

- [ ] 3.1 `device-probe.sh`: `python3` version and `openssl`; fake-root tests
- [ ] 3.2 `plan.py`: adapter-only block check (no device internet, no 2 GB), the row's missing-Python/openssl sentence; tests
- [ ] 3.3 `configurator/server.py` + `devices/release.py`: download script and file on the PC (cache per version), upload with the verifier, `jobs.adapter_commands` runs the uploaded script with `--file`; device fetch fallback; tests with the in-process SSH server

## 4. CI

- [ ] 4.1 File test in an existing job, path-filtered: build, run on Python 3.11 `-I` with `virtual`, full-tools client status/scan/SDO read/send/trace, fail on a module outside stdlib + file, size ≤ 2 MB; CI time kept

## 5. Docs and version

- [ ] 5.1 README (remote adapter line: one file, Python 3.11 and openssl), `docs/pc-adapter.md` (copy and run the file; service from the file), `docs/devices.md` (what the device needs, no internet needed)
- [ ] 5.2 Minor version bump; regenerate the version-stamped goldens

## 6. Hardware checks (Linux device with can0; Mac or Windows PC)

- [ ] 6.1 Devices Turn on on the device (old venv there): job uploads, installs the file, removes the venv; Connect from this PC; scan lists the nodes; install time noted
- [ ] 6.2 Same with the device cut off from the internet (LAN only), if Toni approves changing the device's network for the test
- [ ] 6.3 By hand: copy the file with scp, `python3 canworks-adapter-X.pyz adapter-serve --adapter socketcan:can0 --bitrate 500`, PC scans; Turn off leaves can0 free
