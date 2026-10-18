PC tools {version} for Windows, macOS and Linux (x86_64 and ARM64). No Python needed: see [docs/install-pc.md](https://github.com/{repo}/blob/deploy-v{version}/docs/install-pc.md).

**Install or update** with one line, which installs [uv](https://docs.astral.sh/uv/) if needed and then this release: `curl -LsSf https://raw.githubusercontent.com/{repo}/main/scripts/install-pc.sh | sh -s -- --version {version}` (macOS, Linux) or `& ([scriptblock]::Create((irm https://raw.githubusercontent.com/{repo}/main/scripts/install-pc.ps1))) -Version {version}` (Windows PowerShell); without the version it installs the newest release. By hand: install uv, download `canworks-{version}-py3-none-any.whl` below (one file for every operating system), then run `uv tool install --compile-bytecode --python 3.12 canworks-{version}-py3-none-any.whl`. This puts these commands on PATH: `canworks-config` (configurator), `canworks-deploy` (deploy tool), `canworks-diag` (diagnostics and trace), `canworks-sim-runtime` (local simulator runtime), `canworks-j1939-sim` (J1939 simulator) and `canworks-link` (remote link service, for the runtime host).

**Also in this release**
- `canworks.stlib`: the canworks function block library for OpenPLC Editor (CANopen, CiA 402, CAN and J1939 blocks; [docs/plc-library.md](https://github.com/{repo}/blob/deploy-v{version}/docs/plc-library.md)).
- `ghcr.io/{owner}/canworks-sim-runtime:{version}` (amd64 and arm64): the local simulator runtime, no hardware needed; `canworks-sim-runtime start` pulls it ([docs/local-runtime.md](https://github.com/{repo}/blob/deploy-v{version}/docs/local-runtime.md)).
- `ghcr.io/{owner}/canworks-bridge:{version}` (amd64 and arm64): the Modbus TCP bridge ([docs/modbus-bridge.md](https://github.com/{repo}/blob/deploy-v{version}/docs/modbus-bridge.md)).

Only the newest four releases are kept. To install an older version, see "Older versions" in docs/install-pc.md.
