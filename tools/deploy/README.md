# openplc-canopen-deploy

Adds a CANopen config and its EDS files to an OpenPLC editor build ("Build only" output or `openplc-cli compile`), checks them, and uploads the result to an OpenPLC Runtime v4. See [docs/deploy.md](../../docs/deploy.md).

On Windows, macOS or Linux without Python: install [uv](https://docs.astral.sh/uv/), download the wheel from the newest `deploy-v<version>` release, and run `uv tool install --python 3.12 <wheel>` ([docs/install-pc.md](../../docs/install-pc.md)). With Python already installed:

```sh
pipx install ./tools/deploy
openplc-canopen-deploy --help
```

`openplc-canopen-deploy --config canopen_config.json --export-dcf <dir>` writes each node's configuration as a CiA 306 DCF instead ([docs/deploy.md](../../docs/deploy.md#export-the-nodes-as-dcf-files)).

`openplc-canopen-deploy --config canopen_config.json --export-dbc bus.dbc` writes the network as a DBC file for CAN bus tools; `--dbc-sdo config` or `all` adds the SDO frames ([docs/deploy.md](../../docs/deploy.md#export-the-network-as-a-dbc-file)).

The package also installs `openplc-canopen-config` ([docs/configurator.md](../../docs/configurator.md)) and `openplc-canopen-diag` ([docs/diagnostics.md](../../docs/diagnostics.md)).

Tests: `python3 -m unittest discover -s tools/deploy/tests -t tools/deploy` from the repository root.
