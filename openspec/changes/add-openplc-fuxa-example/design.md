## Context

- OpenPLC reaches canworks through canworks-bridge and its own Modbus master (`modbus-connections`). In an editor project, Save writes the remote device `devices/remote/canworks.json`, the programs `canworks_in`/`canworks_out` and the `canworks` global variable list (typed members such as `canworks.rtd_temp1`, plus `ok` and `link`).
- `examples/node-red-dashboard` already names the plant's PDO entries (`temp1` ... `out1`) and holds the shared plant logic as a Node-RED function node.
- `canworks-local-runtime` runs the upstream runtime image pinned at `TESTED_RUNTIME` (v4.3.1) with the bridge in its network.
- In OpenPLC Runtime v4.3.1 (the tag is main as of 2026-10-13), the uploaded project's `conf/*.json` decides which plugins run (`update_plugin_configurations`). The editor makes `conf/opcua.json` from an enabled OPC UA entry in `devices/servers/`.
- The `opcua` plugin (asyncua) publishes configured nodes by `pouName` and `variablePath` (`GVL` for globals; variables, structures and arrays) and reads them with `debug_read`. It pushes subscriptions every `cycle_time_ms` and checks reads and writes against per-role permissions (`viewer`, `operator`, `engineer`). An anonymous session gets the profile's `anonymous_role`.

## Goals / Non-Goals

**Goals:**
- An OpenPLC project with a real HMI on the shared plant.
- Runs on Mac, Windows and Linux with one compose file and one upload.
- The HMI talks to the PLC by variable name.
- The same plant, tags and logic as the other examples.
- Committed files that CI keeps honest.

**Non-Goals:** a Service page, FUXA on the bridge, canworks writing OPC UA entries, OPC UA security setup, editor/runtime/FUXA in CI.

## Decisions

### OPC UA between FUXA and OpenPLC; Modbus stays between OpenPLC and the bridge
```
FUXA ──OPC UA, 127.0.0.1:4840──> OpenPLC Runtime v4 (main + PLANT_LOGIC)
                                     │ own Modbus master, 127.0.0.1:1502, PLC link
                                     v
                                canworks-bridge ── simulated rtd (node 5) + dio (node 6)
```
OPC UA gives the HMI names and IEC types (REAL °C, BOOL) and per-variable write rights. There is no address table, scaling or coil numbering to keep in step, and FUXA can browse the server. The cost is a heavier stack on both sides (asyncua in the runtime, node-opcua in FUXA), which is fine at HMI rates (100 ms server cycle, 500 ms FUXA polling).

Alternatives:
- OpenPLC's Modbus server with a `%MW`/`%MX` table. Rejected: Toni preferred OPC UA, and it needs fixed addresses, a divisor, `mx_bits` and coils.
- FUXA on the bridge. Rejected: the logic is in the PLC, the PLC link has one writer, and the addresses move on repack.
- S7comm. Rejected: native builds and numeric addressing.

### The example is a complete editor project
The user opens the folder in the OpenPLC Editor and uploads it; nothing is created by hand. The editor's own files (`project.json`, `devices/configuration.json`, `devices/pin-mapping.json`) are made once with `openplc-cli create` and committed with the editor version noted in the README. The canworks-owned files are committed as Save writes them, and the CI check regenerates them with `--into-project` on a copy and compares them, so a tools change that alters them fails until the example is updated. The user's POUs (`main`, `PLANT_LOGIC`) are hand-written. `canworks/.openplc-files.json` (the stamp) is committed too, so the configurator does not ask about changed files on first open.

### HMI variables in `main`, logic in `PLANT_LOGIC`
`main` converts the canworks values into HMI variables: `temp1 := INT_TO_REAL(canworks.rtd_temp1) / 10.0`, `rtd_ok := canworks.rtd_status`, and so on. It calls `PLANT_LOGIC(TEMP := temp1, LIMIT := limit, ACK := ack, RUN := run, DIO_IN1 := dio_in1, MANUAL_OUT1 := manual_out1)` and writes `canworks.dio_out0` (bit 0 = alarm) and `canworks.dio_out1` (the running light, or `manual_out1` while `run` is off).

`PLANT_LOGIC` does the same as the Node-RED example's plant logic:
- The alarm sets when `TEMP > LIMIT` and resets on `ACK` while `TEMP <= LIMIT`.
- While `RUN` is on, one bit walks along `DIO_OUT1` every 500 ms (a TON), and `LIGHT_OK` is set at each step when `DIO_IN1` equals the last value written.

`limit` starts at 25.0 and `run` at TRUE (initial values; not retained, so a PLC restart resets them, which the README says). `ack` is a command: `main` clears it after the scan that used it, so FUXA's button can just write TRUE.

### The OPC UA server entry
`devices/servers/opcua.json` is written in the editor's format (`protocol: "opcua"`, `opcuaServerConfig`):
- The server is enabled on `opc.tcp://0.0.0.0:4840/openplc/opcua` with `cycle_time_ms` 100.
- It has one security profile: `insecure`, None/None, `Anonymous`, `anonymousRole: "operator"`. There are no users, so the project holds no passwords (the editor stores OPC UA user passwords in clear text) and no certificates.
- Nodes: `main`'s HMI variables with node ids `PLC.main.<name>`. `limit`, `ack`, `run` and `manual_out1` get `operator: rw`, `engineer: rw`, `viewer: r`; every other node is `r` for every role. The `canworks` list is published as a structure `PLC.canworks`, read-only (a spike checks how the editor addresses a named global list).

The endpoint is reachable only inside the compose network and on the host's `127.0.0.1:4840` (for UaExpert and similar). The README says a real machine needs the editor's Sign/SignAndEncrypt profiles with users, and anonymous access off.

### FUXA project and loader
`fuxa/project.json` is a whole FUXA project (the `POST /api/project` body). It has one device `OpenPLC` (`type: "OPCUA"`, `property.address: "opc.tcp://127.0.0.1:4840/openplc/opcua"`, polling 500 ms), tags whose `address` is `ns=2;s=PLC.main.<name>` with FUXA types Float/Boolean/Byte, and the views **Plant** and **I/O**. The views are drawn in FUXA's editor against the running example and exported, because the view SVG is not practical to hand-write; after that the file is edited only through FUXA.

`fuxa/start.sh` (mounted, run as the container's command):
1. It starts the server (`npm start` in the image's work directory) in the background and waits for `GET /api/settings`.
2. It installs the OPC UA driver with `POST /api/plugins` (`node-opcua` at the version FUXA 1.3.5 registers) when `GET /api/plugins` does not list it as installed. It goes into the data volume, so only the first start needs the internet.
3. When `_appdata/.canworks-project` is missing, it posts `fuxa/project.json` to `/api/project` and writes the marker.
4. It waits on the server process.

FUXA reconnects by itself, so it may start before the PLC program runs; its tags show no value until the upload.

### Compose
```
setup     canworks-bridge image: copies canworks/canworks.json, simulation.json and the EDS files to the plant volume; exits
bridge    canworks-bridge image on the plant volume; publishes 127.0.0.1:8443, 1881, 4840, 7531
runtime   ghcr.io/autonomy-logic/openplc-runtime:v4.3.1, network_mode service:bridge,
          cap_add SYS_NICE SYS_RESOURCE, ulimit memlock -1, volume for /var/run/runtime
fuxa      frangoteam/fuxa:1.3.5, network_mode service:bridge, command fuxa/start.sh, volume for _appdata
```
The bridge owns the namespace, as in the Node-RED example. The runtime's Modbus master reaches it at `127.0.0.1:1502`, and FUXA reaches the runtime at `127.0.0.1:4840`.

`CANWORKS_VERSION` (default `latest`) picks the bridge image. The runtime tag is pinned to the local runtime's `TESTED_RUNTIME`, and the CI check compares them, so the two stay in step.

canworks-local-runtime falls back to no capabilities when an engine refuses them. Compose cannot, so hand checks 5.1/5.2 confirm that Colima and Docker Desktop accept the caps; if one refuses, the caps are dropped (the runtime runs without real-time priority, which is fine for a simulated plant).

The compose file and `canworks-local-runtime` use the same host ports (8443, 7531), so the README says to stop one before starting the other.

### Upload
The README gives the editor route (Open Project, device `localhost:8443`, create the runtime user when the editor asks, **Build and Upload**) and the command line route: `openplc-cli upload . --host localhost:8443 --user <user> --password <password>` after the user exists.

## Risks / Trade-offs

- **The editor project format changes with editor releases.** CI can only check the canworks-owned files. Mitigation: the README names the editor version it was made with, and the hand check covers opening it in the current editor.
- **The editor may rewrite or drop a hand-written OPC UA entry**, or address the `canworks` list differently than assumed. Mitigation: spike 1.1 opens, saves and builds the project in the editor before the files are final; if the list cannot be published as a structure, only `main`'s variables are published.
- **Namespace index** `ns=2` in FUXA's tags assumes the runtime registers its namespace first. Spike 1.2 reads the real index; FUXA tags use whatever the runtime gives.
- **The first start needs the internet** for the images and FUXA's OPC UA driver, the same as the Node-RED example.
- **The OPC UA plugin is new upstream** (v4). If it misbehaves at the 20 ms task, the cycle stays at 100 ms and the hand checks report it.
