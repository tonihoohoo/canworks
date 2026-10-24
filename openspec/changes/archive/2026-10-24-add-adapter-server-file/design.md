## Context

`canworks-diag adapter-serve` (canopen-remote-adapter) serves a Linux device's CAN adapter to PCs. The server does the CANopen work on the device: each connection gets its own `LocalBus` (SDO, LSS, scan, PDO test, trace, cyclic sends, bit rate check), and the PC sends JSON requests over TLS with the SCRAM login. So the server needs the canworks Python code, but only a small part of its dependencies.

Today `install-adapter.sh` makes `/opt/canworks-adapter/venv` (installing `python3-venv` with apt when needed) and pip-installs the release wheel with the locked dependencies from GitHub and PyPI. The Devices job fetches the script itself with `curl` from the release tag on the device. So the device needs internet, and it gets about 118 MB of packages.

Measured in the explore (tools 0.131.2, virtual adapter, client with the full tools):

| Install | Size | Works |
|---|---|---|
| venv with the wheel and all locked dependencies (site-packages) | 118 MB | yes |
| wheel `--no-deps` + python-can | 5.5 MB | yes: status, scan, LSS, SDO, NMT, send, trace, PDO test |
| zipapp, canworks without configurator, library, nodered_package, codesys, builtin_notes | 1.1 MB | yes, with `python3 -I` and no packages |

At start the server imports, outside the standard library: `can` (python-can) and its `wrapt`, `typing_extensions` and `packaging`. `wrapt`'s C extension is optional (it falls back to pure Python when the `.so` is missing). The import chain `localbus.pdo → pdotest → parameters → edslint → _lely_dcf` and `contract → raw` pulls those packages in, so they stay in the file.

## Goals / Non-Goals

**Goals:** one file per release, no pip, venv, apt or network on the device, fast install, the same server and protocol as today, Devices working for a device without internet.

**Non-Goals:** devices without Python (bundled interpreter), a native server, our own certificate code, systemd-less installs from Devices, reorganising imports to make the file smaller.

## Decisions

### A zipapp built from the release wheel
`scripts/build-adapter-pyz.py WHEEL CONSTRAINTS OUT` unpacks the wheel, drops `configurator/`, `library/`, `nodered_package/`, `codesys/` and `builtin_notes/`, installs python-can and pyserial with their dependencies at the constraints' versions into the same folder with `pip install --target --no-compile --only-binary=:all:`, removes compiled extensions and `__pycache__`, writes `__main__.py`, and makes the file with `zipapp` (compressed, shebang `/usr/bin/env python3`). `__main__.py` checks `sys.version_info >= (3, 11)` before importing canworks and then calls `canworks.diag.main()`, so the file is `canworks-diag` and also runs local diagnostics on the device (`python3 FILE --adapter socketcan:can0 scan`).

Alternatives: a venv with `--no-deps` and python-can (still needs pip and network, and `python3-venv` on Debian); PyInstaller or a bundled interpreter (tens of MB per architecture, non-goal).

The file runs as a zip: the server reads no package data files at run time (checked by the CI test with `python3 -I`, which fails on a missing file too).

### Keep the `openssl` command
`serve.make_context()` makes a fresh self-signed P-256 certificate at every start with `openssl req -x509`. The standard library cannot make certificates, and our own ECDSA and DER code would be security code that must not have mistakes. The command is on Raspberry Pi OS, Debian and most Linux systems; the script and the probe check for it and say so in one sentence.

### The service runs the file
`serve._command()` returns the installed `canworks-diag` or `python -m canworks.diag` today. When `sys.argv[0]` is a zip file (`zipfile.is_zipfile` on the real path) it returns `[sys.executable, realpath]`. `install-adapter.sh` runs the installed copy (`python3 /opt/canworks-adapter/canworks-adapter.pyz adapter-serve … --install-service`), so the unit points at the installed file, not the upload.

### Install script
The venv step becomes: check `python3` (3.11+) and `openssl`; read the installed file's version (`python3 FILE --version`); when it differs, copy `--file` or download `canworks-adapter-X.pyz` from the release into place (0644, root-owned, atomic `mv`); remove `venv/`. The rest (dialout, `--install-service`, uninstall, step lines) stays. `CANWORKS_ADAPTER_DOWNLOAD` replaces the download for the tests, as `CANWORKS_ADAPTER_PIP` does now.

### Devices uploads the files
The configurator already uploads the token's verifier with SFTP (`ssh.put_files`). It now also downloads `install-adapter.sh` from the release tag and `canworks-adapter-X.pyz` from the release assets on the PC (HTTPS from github.com, cached per version in the settings folder), uploads them to the same upload folder, and the job runs `bash UPLOAD/install-adapter.sh --version X --file UPLOAD/canworks-adapter-X.pyz …`. One path for every device, so a device with internet uses it too. When the PC cannot download, the job keeps today's `curl` fetch on the device. `plan.blocked()` gets an adapter-only variant without the device internet and 2 GB checks; systemd, sudo and a running job still block.

### Probe
Two keys: `python3` (the `python3 -c` version string, or null) and `openssl` (true or false). The plan reads them for the row's sentence. Older stored probes without the keys count as unknown and do not block.

## Risks / Trade-offs

- [A trimmed Python lacks a standard library module that python-can imports (for example `sqlite3` on a minimal embedded build)] → the CI test lists the stdlib modules the file imports; the doc names them; the error is Python's own ImportError at start, which the job log shows.
- [python-can or its dependencies change across lock updates] → built from the release's constraints, and the CI test runs on every change of the lock file too (the release workflow is in its paths).
- [The release gets one more asset per version] → about 1 MB; retention removes it with the release.
- [Devices now downloads on the PC] → small and cached; a PC behind a TLS-inspecting proxy uses the same `UV_SYSTEM_CERTS` note as updates, else the device fallback.

## Migration Plan

Clean cut. The next Turn on or Change on a device with the old venv installs the file and removes the venv. The bench device's current server (venv) is replaced in the hardware check.

## Open Questions

None.
