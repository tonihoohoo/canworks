## Context

`node-red-canworks` (nodered-blocks) is installed from a `.tgz` that the PC tools write (`--export-nodered-package`). Flows come from `canworks-deploy --export-nodered`: one tab with a **canworks bridge** config node that holds the bridge address, poll period, layout and map hash. The node ids are derived from the export name (`sha1("canworks-node-red:<name>:<key>")`), so a re-export of the same config keeps them. The bridge image `ghcr.io/tonihoohoo/canworks-bridge:<version>` contains the bridge and the deploy tool in `/opt/canworks/venv` (for the EDS lint).

`examples/modbus-bridge` is the simulated plant that the CODESYS and truST examples also use. Its temperature channels 1 and 2 are a sine of 20.0 to 26.0 °C (30 s) and a ramp of 30.0 to 36.0 °C. The digital module is CiA 401 (0x1000 = 0xF0191), so the simulator loops 0x6200 back to 0x6000 by default. The truST thread confirmed this live with the unchanged `simulation.json`.

## Goals / Non-Goals

**Goals:** a dashboard on the shared plant that runs with one command on Mac, Windows and Linux; the package and flow always at the bridge's version; nothing committed that goes stale when the config changes; the same tags and logic as the CODESYS and truST examples.

**Non-Goals:** an automatic dashboard export, Node-RED or Docker in CI, simulator control from the dashboard.

## Decisions

### Dashboard 2.0
`@flowfuse/node-red-dashboard` is the maintained dashboard; the classic `node-red-dashboard` is marked "No longer maintained" on npm. The version is pinned in the start script (1.34.0 today) so the example does not change under the user. Dashboard 2.0 comes from npm, the same way Node-RED itself does; the canworks package stays `.tgz` only.

### Only the dashboard tab is committed
The canworks tab carries the layout and map hash. If it were committed, every config or map change would need a regenerated file and a golden update with each version bump. Instead, `dashboard.json` holds only the dashboard tab and the `ui-base`, `ui-page`, `ui-group` and `ui-theme` config nodes. Its canworks nodes point at the bridge node id of the export named `plant` (`plant_node-red.json`). At start the canworks flow is exported from the config, and the two arrays are joined into Node-RED's flows file. The check in CI makes sure the id and the topics match.

Alternative: commit the whole flow and regenerate it with a test (rejected: stale files and goldens on every version bump). Another alternative: a new `--nodered-extra FILE` export option (rejected: a new tool feature for one example).

### Compose: setup, bridge, node-red
```
setup     bridge image, entrypoint overridden: copies canworks.json, simulation.json and the EDS files to
          the plant volume, canworks-deploy --export-nodered-package /share and --config
          /example/canworks.json --export-nodered /share/plant_node-red.json; exits
bridge    bridge image, default command on the plant volume at /etc/canworks-bridge (the bridge
          writes .canworks/ next to its config, so not the read-only example folder);
          ports 1880:1880 (Node-RED's, see below)
node-red  nodered/node-red:4.1, network_mode "service:bridge", depends_on setup (completed) and bridge,
          entrypoint start.sh
```
- `network_mode: service:bridge` puts Node-RED in the bridge's network namespace. Node-RED reaches the bridge at `127.0.0.1:1502` on Linux and on Docker Desktop alike. The bridge's `writers` stay `["127.0.0.1"]`, and Modbus is not exposed outside the pair. The published port 1880 sits on `bridge` because the namespace belongs to it.
- No `--network host` and no `NET_ADMIN`: the plant is simulated in-process.
- `CANWORKS_VERSION` (default `latest`) tags both bridge services, so `setup` exports the package and flow at the same version as the running bridge.
- `start.sh` (in the folder, mounted) runs on every start. When the `/data` volume does not have the package version from `/share` yet, it runs `npm install` on the `.tgz` and the pinned dashboard there. When `/data/.canworks-flow` is missing, it joins `/share/plant_node-red.json` and `/example/dashboard.json` with a short `node -e` into `flows.json` (replacing the sample flow the image puts in a new `/data` volume) and writes the marker. Then it starts Node-RED with the image's own entrypoint. After that the user's own changes to the flow persist. The README says to remove the volume (`docker compose down -v`) to start over after changing the config.

### Names on the PDO entries
The config names the PDO entries as the CODESYS example does: `temp1`, `temp2` (0x7130:1/2), `in0`, `in1` (0x6000:1/2) and `out0`, `out1` (0x6200:1/2). A named entry's register map name is `<node>.<name>`, so `msg.topic` is `rtd.temp1` ... `dio.out1`, and the PLC examples' tags are `rtd_temp1` ... `dio_out1`; the dashboard shows the tag names. The node status bits stay `rtd.status` and `dio.status`; the dashboard labels them `rtd_ok` and `dio_ok`. Channels 3 and 4 and the analogue values keep their default names. The networks are otherwise identical to `examples/modbus-bridge`.

### Plant logic in one function node
A function node keeps `limit` (default 25.0), `alarm`, `run`, the light step and `LIGHT_OK` in node context. It reads `rtd.temp1` (0.1 °C, so it divides by 10), `rtd.temp2`, `dio.in0`, `dio.in1`, the status values, `limit`, `ack`, `run` and the I/O page's switch clicks, and it ticks on a 500 ms inject. It writes `dio.out0` and `dio.out1` through **canworks out**, sends one state message to the page templates (so a reloaded page shows everything at once), trend points and a notification when the alarm comes on. It does the same as `PLANT_LOGIC`:
- the alarm comes on when `temp1 > limit`, and Ack clears it only when `temp1 <= limit`;
- `dio_out0` bit 0 follows the alarm, and the other bits come from the I/O page switches;
- while `run` is on, `dio_out1` is a single bit that moves one place per step and `LIGHT_OK` is set at each step to whether `dio_in1` equals the `dio_out1` that was written; while it is off, `LIGHT_OK` is false and `dio_out1` comes from the switches.

Behaviour is defined by the CODESYS and truST examples' `PLANT_LOGIC`. When those change, this node follows.

### Widgets
- **Plant**: one `ui-template` for the two temperatures, the alarm line and the status dots (`rtd.status`, `dio.status`, `LIGHT_OK`, `bridge.state`), one `ui-chart` (series from the topic) for the trend, `ui-number-input` for the limit, `ui-button` Ack, `ui-switch` Running light and `ui-notification` when the alarm comes on.
- **I/O**: one `ui-template` with a row of 8 bit buttons per byte: outputs as switches (bit 0 of `dio_out0` is owned by the alarm and shown, not switched; `dio_out1` only while the light is off) and inputs as lamps. Sixteen `ui-switch` nodes plus packing would be four times the nodes for the same thing.
- **Service**: `ui-button` for NMT start, stop and reset of node 5 or 6 through **nmt**, a "Read device name" button through **sdo** (0x1008, string) into `ui-text`, and a `ui-table` of the last 20 EMCY messages from **emcy**.

### CI check
`tools/deploy/tests/test_nodered_example.py` runs in the tools shard. It:
- compares the plant files byte for byte with `examples/modbus-bridge`;
- runs the deploy tool's `--check` on the config and compares its networks with the plant's (entry names aside);
- exports the flow with `nodered.flow(cfg, "plant")`;
- asserts that every canworks node in `dashboard.json` uses the export's bridge id, every topic it filters or sends exists among the export's names and status topics, and every **canworks out** topic is an output;
- asserts that `docker-compose.yml` names `canworks.json`, `dashboard.json` and `start.sh`, and `start.sh` names the pinned dashboard version.

It needs no node and no Docker, and takes milliseconds.

## Risks / Trade-offs

- **First start needs the internet** (npm for Dashboard 2.0, and the image pulls) → this is said in the README, and later starts use the volume.
- **`latest` image and an old volume** → `start.sh` reinstalls the package when the version in `/share` differs from the one in `/data`. The flow is not replaced, because the map check shows "map mismatch" if the layout moved, and the README says how to reset.
- **Dashboard 2.0 changes its node format** → the version is pinned, and the hand check covers it.
- **Docker Desktop on Windows with `service:` network mode** → this is supported, and hand check 5.2 runs it on Windows.
