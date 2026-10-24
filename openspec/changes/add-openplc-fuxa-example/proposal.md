## Why

There is no example of OpenPLC with an HMI on top of canworks. The Node-RED dashboard example (#298) shows a dashboard straight on the bridge, but the usual OpenPLC machine has a PLC program with the logic and an HMI that talks to the PLC. FUXA is an open-source web HMI/SCADA that runs in Docker and speaks Modbus and OPC UA, so it is the natural open HMI for OpenPLC.

Toni (2026-10-24): "Explore openplc + fuxa example". Then "Would it be better for fuxa and plc communicate with something else? Opc ua", and after the answer: "Propose".

The explore (report `research/openplc-fuxa-example-2026-10-24.md` in the project files) found:
- **FUXA should talk to the PLC, not to the bridge.** The limit, alarm, Ack and running light are PLC variables. With the PLC link only OpenPLC writes outputs and mailboxes. And the bridge's registers move when the map is repacked, with nothing guarding an HMI.
- **OPC UA rather than Modbus between FUXA and OpenPLC.** OpenPLC Runtime v4.3.1 has an `opcua` plugin that publishes **named, typed** program and global variables (`pouName` + `variablePath`), read live with `debug_read`, with read/write rights per role and anonymous sessions mapped to a configured role. It turns on when the uploaded project has an enabled OPC UA server entry (`devices/servers/<name>.json`, which the editor turns into `conf/opcua.json`). With Modbus the example would need a fixed `%MW`/`%MX` table, scaling, `mx_bits` and coil numbers.
- **FUXA 1.3.5** (`frangoteam/fuxa:1.3.5`) loads a whole project with `POST /api/project`. Its OPC UA client read a REAL and wrote a REAL and a BOOL against a stand-in server with the runtime's namespace and endpoint path (`ns=2;s=...`). Its OPC UA driver (`node-opcua` 2.149.0) is not in the image: it is installed from npm on first start (`POST /api/plugins`, 22 s here).
- The bridge link stays as it is: OpenPLC's own Modbus master to canworks-bridge on 127.0.0.1:1502 with the PLC link.
- `openplc-cli upload <project> --host <address>` uploads headless, and the editor asks to create the first runtime user on connect.

S7comm (native builds, numeric addressing), EtherNet/IP and MQTT (not in OpenPLC v4) were rejected.

## What Changes

- **A new example `examples/openplc-fuxa/`: a complete OpenPLC Editor project** on the shared plant:
  - `canworks/`: `canworks.json` with the networks and PDO entry names of `examples/node-red-dashboard` (`temp1`, `temp2`, `in0`, `in1`, `out0`, `out1`) and an OpenPLC connection (PLC link, `127.0.0.1:1502`, low word first, no mailboxes), plus byte-identical copies of `rtd8.eds`, `dio16.eds` and `simulation.json`.
  - The editor's own project files (`project.json`, `devices/configuration.json`, `devices/pin-mapping.json`), target OpenPLC Runtime v4, task `T#20ms`.
  - The canworks-owned editor files that Save writes (`devices/remote/canworks.json`, `canworks_in`, `canworks_out`, the `canworks` variable list), committed as generated.
  - **`PLANT_LOGIC`** as a function block (the shared logic of the Node-RED and CODESYS examples, here first in ST) and **`main`**, which calls it and holds the HMI variables as typed values: `temp1`, `temp2` (REAL °C), `limit` (REAL, 25.0 at start), `ack`, `run`, `alarm`, `light_ok`, `rtd_ok`, `dio_ok`, `canworks_ok`, `dio_in0`/`dio_in1`, `dio_out0`/`dio_out1` and `manual_out1`.
  - **An OPC UA server entry** `devices/servers/opcua.json`: endpoint `opc.tcp://0.0.0.0:4840/openplc/opcua`, only the `insecure` profile (None/None, Anonymous) with anonymous role `operator`, cycle 100 ms. It publishes `main`'s HMI variables, read-only for every role except `limit`, `ack`, `run` and `manual_out1` (`operator` and `engineer` read/write), and the `canworks` variable list as a read-only structure, so every CAN value can be browsed by name.
  - **`fuxa/project.json`**: a FUXA project with one OPC UA device (`opc.tcp://127.0.0.1:4840/openplc/opcua`), tags by node id and two views. **Plant** has both temperatures with a trend, the limit, the alarm lamp with Ack, the running light switch with its check, and node and bridge status. **I/O** has the 16 inputs as lamps and the 16 outputs, with `dio_out1` switchable while the running light is off.
  - **`fuxa/start.sh`**: starts FUXA, installs the OPC UA driver when it is missing, and loads `fuxa/project.json` once (a marker in the data volume), so later edits in FUXA's editor are kept.
  - **`docker-compose.yml`** with four services:
    - `setup` (bridge image): copies the plant files into a volume;
    - `bridge`: the simulated plant. It owns the network and publishes only on `127.0.0.1`: 8443 (runtime), 1881 (FUXA), 4840 (OPC UA) and 7531 (diagnostics);
    - `runtime`: upstream `ghcr.io/autonomy-logic/openplc-runtime` at the version canworks-local-runtime pins (v4.3.1), sharing the bridge's network;
    - `fuxa`: `frangoteam/fuxa:1.3.5`, sharing the bridge's network.
  - **`README.md`**:
    1. Run `docker compose up`.
    2. Open the folder in the OpenPLC Editor, connect to `localhost:8443` (create a user when asked), then **Build and Upload** (or `openplc-cli upload`).
    3. Open FUXA at `http://localhost:1881`.

    It also gives a route without Docker (bridge and runtime on a Linux device, FUXA anywhere), a note to stop `canworks-local-runtime` first (same ports), and a note on OPC UA security for a real machine.
- **A static check in the tools shard.** It confirms that:
  - the plant files match;
  - the config passes the check;
  - the committed canworks-owned editor files equal what `--into-project` writes;
  - every FUXA tag's node id is published by the OPC UA entry, and every tag FUXA writes is writable for `operator`;
  - the compose runtime tag equals the local runtime's pin;
  - compose and start script name files that exist.

  It needs no editor, runtime, FUXA or Docker, and adds no job.
- README.md (OpenPLC line and examples) and `docs/modbus-bridge.md` (OpenPLC section) link to the example. `docs/local-runtime.md` notes the shared ports.

## Non-goals

- A Service page (NMT, SDO, EMCY) in FUXA. These need the mailbox blocks; the Node-RED example already shows them.
- FUXA straight on the bridge, or a FUXA export from the register map (`hmi` connection format `fuxa`). That would be possible later, separately.
- canworks writing OPC UA server entries into editor projects from the configurator. The example's entry is a committed example file, not a canworks feature.
- OPC UA security beyond the example (users, certificates). The README points to the editor's OPC UA server screen.
- Running the editor, runtime, FUXA or Docker in CI.

## Capabilities

### New Capabilities

- `openplc-fuxa-example`: the example editor project, its OPC UA server entry, FUXA project, compose setup and logic.

### Modified Capabilities

- `canopen-ci`: the example's static check in the tools shard.
