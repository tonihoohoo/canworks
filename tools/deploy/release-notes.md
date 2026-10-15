PC tools {version} for Windows, macOS and Linux (x86_64 and ARM64). No Python needed: see [docs/install-pc.md](https://github.com/{repo}/blob/deploy-v{version}/docs/install-pc.md).

**Install**: install [uv](https://docs.astral.sh/uv/), download `canworks-{version}-py3-none-any.whl` below (one file for every operating system), then run `uv tool install --python 3.12 canworks-{version}-py3-none-any.whl`. This puts these commands on PATH: `canworks-config` (configurator), `canworks-deploy` (deploy tool), `canworks-diag` (diagnostics and trace), `canworks-sim-runtime` (local simulator runtime), `canworks-j1939-sim` (J1939 simulator) and `canworks-link` (remote link service, for the runtime host).

**Also in this release**
- `canworks.stlib`: the SDO function block library for OpenPLC Editor ([docs/plc-sdo.md](https://github.com/{repo}/blob/deploy-v{version}/docs/plc-sdo.md)).
- `ghcr.io/{owner}/canworks-sim-runtime:{version}` (amd64 and arm64): the local simulator runtime, no hardware needed; `canworks-sim-runtime start` pulls it ([docs/local-runtime.md](https://github.com/{repo}/blob/deploy-v{version}/docs/local-runtime.md)).
- `ghcr.io/{owner}/canworks-bridge:{version}` (amd64 and arm64): the Modbus TCP bridge ([docs/modbus-bridge.md](https://github.com/{repo}/blob/deploy-v{version}/docs/modbus-bridge.md)).

Only the newest four releases are kept. To install an older version, see "Older versions" in docs/install-pc.md.
