## ADDED Requirements

### Requirement: Editor project on the shared plant
The repository SHALL have `examples/openplc-fuxa/`: an OpenPLC Editor project with target OpenPLC Runtime v4 and the canworks config in its `canworks/` folder. `canworks/rtd8.eds`, `canworks/dio16.eds` and `canworks/simulation.json` SHALL be byte-identical to those of `examples/modbus-bridge`.

`canworks/canworks.json` SHALL have the same networks, nodes and PDO entry names as `examples/node-red-dashboard`. Its bridge SHALL have one OpenPLC connection with the PLC link, listen on `127.0.0.1:1502`, and use low word first and no mailboxes.

The project SHALL contain the canworks-owned editor files exactly as `canworks-deploy --into-project` writes them for that config, and the hand-written POUs `main` and `PLANT_LOGIC`. The example SHALL need no CAN hardware and contain no real device or vendor names.

#### Scenario: Plant files drift
- **WHEN** a change edits `examples/modbus-bridge/simulation.json` but not the example's copy
- **THEN** the example check fails naming both files

#### Scenario: Generated files out of date
- **WHEN** a tools change alters what `--into-project` writes for the example config
- **THEN** the example check fails naming the canworks-owned file that differs

### Requirement: Shared plant logic in ST
The project SHALL have a function block `PLANT_LOGIC` with the shared plant logic of the Node-RED and CODESYS examples:
- The alarm SHALL come on when temperature 1 in °C is above the limit and stay on until Ack is given while the temperature is at or below the limit. Bit 0 of `dio_out0` SHALL follow the alarm.
- While the running light is on, one bit SHALL move along `dio_out1` every 500 ms, and `LIGHT_OK` SHALL be true when, at a step, `dio_in1` equals the value written to `dio_out1`.
- While the running light is off, `dio_out1` SHALL be the HMI's `manual_out1`, and `LIGHT_OK` SHALL be false.

`main` SHALL hold the HMI variables `temp1`, `temp2` (REAL °C), `limit` (REAL, 25.0 at start), `ack`, `run` (TRUE at start), `alarm`, `light_ok`, `rtd_ok`, `dio_ok`, `canworks_ok`, `dio_in0`, `dio_in1`, `dio_out0`, `dio_out1` and `manual_out1`. It SHALL clear `ack` after the scan that used it.

#### Scenario: Alarm and Ack
- **WHEN** the limit is 25.0 °C and simulated temperature 1 rises past 25.0 °C and later falls back below it
- **THEN** `alarm` and bit 0 of `dio_out0` come on, stay on after the temperature falls, and go off when the HMI writes `ack` TRUE

#### Scenario: Ack while too hot
- **WHEN** the HMI writes `ack` TRUE while temperature 1 is above the limit
- **THEN** `alarm` stays on and `ack` reads FALSE again after the next scan

### Requirement: OPC UA server entry
The project SHALL have an enabled OPC UA server entry in `devices/servers/` in the editor's format:
- endpoint `opc.tcp://0.0.0.0:4840/openplc/opcua`, cycle 100 ms;
- one security profile with no security, Anonymous only, and anonymous role `operator`;
- no users and no certificates.

It SHALL publish `main`'s HMI variables as nodes `PLC.main.<name>`. `limit`, `ack`, `run` and `manual_out1` SHALL be read/write for `operator` and `engineer` and read-only for `viewer`; every other node SHALL be read-only for every role. It SHALL publish the `canworks` variable list read-only when the editor can address it.

#### Scenario: Read-only plant value
- **WHEN** an anonymous OPC UA client writes `PLC.main.temp1`
- **THEN** the write is refused and the value stays what the program computed

#### Scenario: Limit from the HMI
- **WHEN** an anonymous OPC UA client writes 22.0 to `PLC.main.limit`
- **THEN** the program uses 22.0 as the limit from the next scan

### Requirement: FUXA project
`examples/openplc-fuxa/fuxa/project.json` SHALL be a FUXA project with one OPC UA device at `opc.tcp://127.0.0.1:4840/openplc/opcua`. Every tag SHALL address a node the OPC UA entry publishes, and every tag a view writes SHALL be writable for `operator`. It SHALL have two views:
- **Plant**: both temperatures in °C with a trend, the limit as an input, the alarm lamp with an Ack button, the running light switch with its check, a status lamp for each node, and the bridge state.
- **I/O**: lamps for the 16 bits of `dio_in0` and `dio_in1`, and the 16 bits of `dio_out0`/`dio_out1`, with `dio_out1` switchable (through `manual_out1`) while the running light is off.

#### Scenario: Switch loops back
- **WHEN** the user turns the running light off on Plant and switches bit 3 of the outputs of `dio_out1` on, on the I/O view
- **THEN** the lamp for bit 3 of `dio_in1` comes on within a second

### Requirement: Run with Docker Compose
`docker compose up` in the example folder SHALL start:
- the simulated plant in the canworks-bridge image at `CANWORKS_VERSION` (default `latest`), on a copy of the plant files in a volume;
- the upstream OpenPLC Runtime image at the version `canworks-local-runtime` pins;
- FUXA 1.3.5.

The runtime and FUXA SHALL share the bridge service's network, on Linux and on Docker Desktop or Colima for macOS and Windows, with no CAN interface and no host network mode. Ports SHALL be published on `127.0.0.1` only: 8443 (runtime), 1881 (FUXA), 4840 (OPC UA) and 7531 (diagnostics).

On first start FUXA SHALL install its OPC UA driver and load `fuxa/project.json`. Later starts SHALL keep the user's FUXA changes.

#### Scenario: First run
- **WHEN** a user with Docker runs `docker compose up`, opens the folder in the OpenPLC Editor, uploads it to `localhost:8443` and opens `http://localhost:1881`
- **THEN** FUXA's Plant view shows the two temperatures changing and both nodes OK

#### Scenario: Restart keeps edits
- **WHEN** the user changes a view in FUXA's editor, then runs `docker compose down` and `docker compose up`
- **THEN** FUXA shows the changed view

### Requirement: Example documentation
The example's README SHALL describe:
- the Docker route: `docker compose up`, opening and uploading the project from the editor or with `openplc-cli upload`, the FUXA URL, `CANWORKS_VERSION`, starting over with `docker compose down -v`, and the internet needed on first start;
- that `canworks-local-runtime` uses the same ports and must be stopped first;
- the route without Docker: bridge and runtime on a Linux device, FUXA anywhere on the network, pointed at the device's port 4840;
- that the example's anonymous OPC UA access is for the local example only, and a real machine needs a secured profile with users;
- the editor version the project was made with.

README.md and `docs/modbus-bridge.md` SHALL link to the example.

#### Scenario: Without Docker
- **WHEN** a user follows the second route with the bridge and runtime on a Linux device and FUXA on a PC
- **THEN** FUXA's views show the plant after its device address is changed to the Linux device
