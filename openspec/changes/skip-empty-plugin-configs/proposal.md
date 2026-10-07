## Why

OpenPLC Editor 4.3.2 writes an empty `conf/ethercat.json` (zero bytes) into every build, even when the project uses no EtherCAT. The deploy tool's address clash check reads every `conf/*.json` in the bundle, fails to parse the empty file and prints `warning: conf/ethercat.json: not readable JSON (...); its locations are not checked` on every `--project` deploy, on every system. The warning is harmless but it is noise that teaches users to ignore real warnings.

## What Changes

- The clash check treats a plugin config that is empty or only whitespace as a config with no locations and skips it without a warning.
- A file with content that is not valid JSON keeps the existing warning, since its locations really are not checked.
- The configurator's location scan of an editor project applies the same rule to empty `.json` files, so both tools agree.

## Capabilities

### New Capabilities

### Modified Capabilities
- `canopen-deploy`: the address clash check skips empty plugin configs quietly.

## Impact

- `tools/deploy/openplc_canopen_deploy/clash.py`, `tools/deploy/openplc_canopen_deploy/configurator/scan.py`, their tests.
- Deploy tool patch version bump (next free version at apply time).
- No config, plugin or runtime change. README not affected unless it mentions the warning.
