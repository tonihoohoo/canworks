## 1. Devices workspace

- [x] 1.1 Probe: skip the plugin venv's console script without a bridge unit; report `unit`
- [x] 1.2 Plan: install a bridge without its unit; update a development build
- [x] 1.3 Start job checks the unit first

## 2. Scripts

- [x] 2.1 install-bridge.sh --uninstall keeps the plugin's VERSION and can-j1939 boot entry
- [x] 2.2 install-stock.sh keeps the can-j1939 boot entry while the bridge is installed

## 3. Tests, docs, release

- [x] 3.1 Probe, plan, job, bridge install and Docker install tests
- [x] 3.2 docs/devices.md; PC tools 0.98.3

## 4. Hardware

- [x] 4.1 Mac, Pi with the plugin: Install and start this project's bridge, Modbus answers, Uninstall leaves the plugin and its can-j1939 boot entry
