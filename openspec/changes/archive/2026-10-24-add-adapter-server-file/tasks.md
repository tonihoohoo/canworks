## 1. The file

- [x] 1.1 `scripts/build-adapter-pyz.py` (wheel + constraints → pruned canworks, python-can, pyserial and their pure-Python deps, no `.so`/`__pycache__`, `__main__.py` with the 3.11 check, compressed zipapp); unit test of the contents and the size limit
- [x] 1.2 `serve._command()`: run from a zip → `[sys.executable, realpath]`; test with a built file
- [x] 1.3 Release workflow: build the file from the release wheel and constraints, attach `canworks-adapter-<version>.pyz` and `install-adapter.sh`; check the asset list in the release test

## 2. Install script

- [x] 2.1 `install-adapter.sh`: python3 3.11+ and openssl checks, `--file`, download of the file, version from `--version`, atomic install, old venv removed, no pip/venv/apt; uninstall removes the file with the last server
- [x] 2.2 `test/adapter/install_test.sh` and `test/pc-tools/test_install_scripts.py`: stub download, uploaded file without network, missing openssl, old Python, uninstall one/all; shellcheck

## 3. Devices

- [x] 3.1 `device-probe.sh`: `python3` version and `openssl`; fake-root tests
- [x] 3.2 `plan.py`: adapter-only block check (no device internet, no 2 GB), the row's missing-Python/openssl sentence (no Turn on/Add/Change/New token then); tests
- [x] 3.3 `configurator/server.py` + `devices/release.py`: download script and file on the PC (cache per version), upload with the verifier, `jobs.adapter_commands` runs the uploaded script with `--file`; device fetch fallback; tests with the in-process SSH server

## 4. CI

- [x] 4.1 File test in an existing job, path-filtered: build, run on Python 3.11 `-I` with `virtual`, full-tools client status/scan/SDO read/send/trace, fail on a module outside stdlib + file, size ≤ 2 MB; CI time kept
- [ ] 4.2 CI time: wall and summed job time against the main baseline, in the PR description

## 5. Docs and version

- [x] 5.1 README (remote adapter line: one file, Python 3.11 and openssl), `docs/pc-adapter.md` (copy and run the file; service from the file), `docs/devices.md` (what the device needs, no internet needed), `docs/install-pc.md`, release notes template
- [x] 5.2 Minor version bump (0.133.0); regenerate the version-stamped goldens

## 6. Hardware checks (Linux device with can0; Mac or Windows PC)

- [x] 6.1 Devices Turn on on the device (old venv there): job uploads, installs the file, removes the venv; Connect from this PC; scan lists the nodes; install time noted
  - 2026-10-24, tools 0.133.0 on a Mac, Linux device with can0 at 500 kbit/s next to a running bridge: Turn on (Allow changes, Advertise) took 4 s; the PC uploaded install-adapter.sh and the file, nothing was downloaded on the device; the folder holds only canworks-adapter.pyz (same sha256 as the release asset), the unit runs `/usr/bin/python3 /opt/canworks-adapter/canworks-adapter.pyz adapter-serve ...`; Connect from this PC (read-only) and scan found the nodes. The device had no old venv (an earlier Turn off removed it), so venv removal rests on test/adapter/install_test.sh.
  - Seen, not part of this change: the row shows off until Check again after the job; Connect from this PC needs a second Connect click; a scan that hit a reconnect and a bit rate refusal left the page at Scanning... 0 of 127.
- [x] 6.2 Same with the device cut off from the internet (LAN only), if Toni approves changing the device's network for the test
  - 2026-10-24, tools 0.133.2, Toni approved: default route removed on the device (curl to github.com failed, SSH over the LAN worked); Turn off took 2 s and left can0 free (service inactive, no adapter process); Turn on took 3 s with no download step in the job log and the row showed running · changes allowed; the route was put back. The device's DHCP client restored the route once by itself mid-test, so it was removed again before Turn on.
- [x] 6.3 By hand: copy the file with scp, `python3 canworks-adapter-X.pyz adapter-serve --adapter socketcan:can0 --bitrate 500`, PC scans; Turn off leaves can0 free
  - 2026-10-24, tools 0.133.2: the release's file copied with scp and run by hand read-only on port 7540 next to the service on 7536; `canworks-diag --adapter remote:HOST:7540 status` connected read-only and `scan --force` (another master on the bus) found the nodes in 1.6 s; then stopped and removed. The hand run keeps its token in the shared adapter-serve.json under its port.
