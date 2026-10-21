## Why

The Mac hardware check of the Devices workspace (6.3) could not install a project's bridge on a device that runs the canworks plugin under the managed Docker runtime:

- The plugin's virtual environment in `/opt/canworks` carries an old `canworks-bridge` console script. The probe took it for an installed bridge, with the plugin's `VERSION`, so the page offered only **Start this project's bridge**.
- That start job failed with a bare exit status, because there is no `canworks-bridge@.service` unit.
- Uninstalling a bridge would also have removed the plugin's can-j1939 boot entry, and in a prefix shared with the plugin, the plugin's `VERSION` file.

## What Changes

- Probe: a `canworks-bridge` in the plugin's own prefix with no bridge unit is not a bridge. The bridge object says whether its template unit is installed (`unit`).
- Plan: a bridge without its unit gets **Install and start this project's bridge**, and its row says "no service". A bridge with a development version (not a release) gets **Update … → X**.
- Start job: it checks the unit first and says "install the bridge first".
- `install-bridge.sh --uninstall` keeps `<prefix>/VERSION` when the prefix holds the plugin, and keeps the can-j1939 boot entry while the plugin is installed. `install-stock.sh` keeps that entry while the bridge unit is installed.

## Impact

`device-probe.sh`, `plan.py`, `jobs.py`, `scripts/install-bridge.sh`, `scripts/install-stock.sh`, tests, docs/devices.md. PC tools 0.98.3.
