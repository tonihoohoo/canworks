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
FUXA ──OPC UA, bridge:4840──────> OpenPLC Runtime v4 (main + PLANT_LOGIC)
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
`main` converts the canworks values into HMI variables: `temp1 := INT_TO_REAL(canworks.rtd_temp1) / 10.0`, `rtd_ok := canworks.rtd_status`, and so on. It calls `PLANT_LOGIC(VALID := canworks_ok AND rtd_ok, TEMP := temp1, LIMIT := limit, ACK := ack, RUN := run, DIO_IN1 := dio_in1, MANUAL_OUT0 := manual_out0, MANUAL_OUT1 := manual_out1)` and writes `canworks.dio_out0` (bit 0 = alarm, bits 1-7 from `manual_out0`) and `canworks.dio_out1` (the running light, or `manual_out1` while `run` is off).

`PLANT_LOGIC` does the same as the Node-RED example's plant logic:
- The alarm sets when `VALID` and `TEMP > LIMIT`, and resets on `ACK` once that no longer holds, so a stale temperature raises no alarm.
- While `RUN` is on, one bit walks along `DIO_OUT1` every 500 ms (a TON), and `LIGHT_OK` is set at each step when `DIO_IN1` equals the last value written.

`limit` starts at 25.0 and `run` at TRUE (initial values; not retained, so a PLC restart resets them, which the README says). `ack` is a command: `main` clears it after the scan that used it, so FUXA's button can just write TRUE.

### The OPC UA server entry
`devices/servers/opcua.json` is written in the editor's format (`protocol: "opcua"`, `opcuaServerConfig`):
- The server is enabled on `opc.tcp://0.0.0.0:4840/openplc/opcua` with `cycle_time_ms` 100.
- It has one security profile: `insecure`, None/None, `Anonymous`, `anonymousRole: "operator"`. There are no users, so the project holds no passwords (the editor stores OPC UA user passwords in clear text) and no certificates.
- Nodes: `main`'s HMI variables with node ids `PLC.main.<name>`. `limit`, `ack`, `run`, `manual_out0` and `manual_out1` get `operator: rw`, `engineer: rw`, `viewer: r`; every other node is `r` for every role. Every member of the `canworks` list except `link` is published read-only as `pouName: "GVL"`, `variablePath: "canworks.<member>"`, node id `PLC.canworks.<member>`. The editor's headless compile (4.3.2) resolves all of them.

The runtime turns a `0.0.0.0` bind address into the container's own address, so the server is not on `127.0.0.1` inside the network. FUXA uses `bridge:4840` (the compose service name of the network's owner). The host reaches it at `127.0.0.1:4840` (for UaExpert and similar). The README says a real machine needs the editor's Sign/SignAndEncrypt profiles with users, and anonymous access off.

### FUXA project and loader
`fuxa/project.json` is a whole FUXA project (the `POST /api/project` body). It has one device `OpenPLC` (`type: "OPCUA"`, `property.address: "opc.tcp://bridge:4840/openplc/opcua"`, polling 500 ms), tags whose `address` is `ns=2;s=PLC.main.<name>` with FUXA types Float/Boolean/Byte, and the views **Plant** and **I/O**. Tag ids are the tag names, so views can be shared with other FUXA examples. The file was generated by a script (views laid out on a grid, FUXA's own widget types) and checked in a browser against the running example; later changes can be made in FUXA's editor and exported.

`fuxa/start.sh` (mounted, run as the container's command):
1. It starts the server (`node main.js` in the image's server directory) in the background and waits for `GET /api/settings`.
2. It installs the OPC UA driver with `POST /api/plugins` (`node-opcua` at the version FUXA 1.3.5 registers) when `GET /api/plugins` does not list it as installed. It goes into the data volume, so only the first start needs the internet.
3. When `_appdata/.canworks-project` is missing, it posts `fuxa/project.json` to `/api/project` and writes the marker.
4. It waits on the server process.

FUXA reconnects by itself, so it may start before the PLC program runs; its tags show no value until the upload.

### Compose
```
setup     canworks-bridge image: copies canworks/canworks.json, simulation.json and the EDS files to the plant volume; exits
bridge    canworks-bridge image on the plant volume; publishes 127.0.0.1:8443, 1881, 4840
runtime   ghcr.io/autonomy-logic/openplc-runtime:v4.3.1, network_mode service:bridge,
          no added capabilities, volume for /var/run/runtime
fuxa      frangoteam/fuxa:1.3.5, network_mode service:bridge, entrypoint fuxa/start.sh, volumes for _appdata and _pkg
```
The bridge owns the namespace, as in the Node-RED example. The runtime's Modbus master reaches it at `127.0.0.1:1502`, and FUXA reaches the runtime at `bridge:4840`.

`CANWORKS_VERSION` (default `latest`) picks the bridge image. The runtime tag is pinned to the local runtime's `TESTED_RUNTIME`, and the CI check compares them, so the two stay in step.

canworks-local-runtime falls back to no capabilities when an engine refuses them. Compose cannot, and a test engine refused `SYS_RESOURCE` and the memlock limit, so the compose file adds none: the runtime warns that real-time priority failed and runs, which is fine for a simulated plant.

The compose file and `canworks-local-runtime` use the same host port 8443, so the README says to stop one before starting the other.

### Upload
The README gives the editor route (Open Project, device `localhost:8443`, create the runtime user when the editor asks, **Build and Upload**) and the command line route of editor 4.3.2: `openplc-cli upload . --host localhost --yes` with `OPENPLC_USER`/`OPENPLC_PASSWORD` after the user exists.

## Risks / Trade-offs

- **The editor project format changes with editor releases.** CI can only check the canworks-owned files. Mitigation: the README names the editor version it was made with, and the hand check covers opening it in the current editor.
- **The editor may rewrite or drop a hand-written OPC UA entry.** The headless compile keeps and resolves it; the hand checks open and save it in the editor.
- **Namespace index** `ns=2` in FUXA's tags is what the runtime gives its namespace (checked against the running runtime).
- **The first start needs the internet** for the images and FUXA's OPC UA driver, the same as the Node-RED example.
- **The OPC UA plugin is new upstream** (v4). If it misbehaves at the 20 ms task, the cycle stays at 100 ms and the hand checks report it.
