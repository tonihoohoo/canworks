## ADDED Requirements

### Requirement: Editor project folder
The repository SHALL have `examples/openplc-fuxa/`: an OpenPLC Editor project with target OpenPLC Runtime v4, the canworks config in its `canworks/` folder, and the hand-written POUs `main` and `PLANT_LOGIC`. The example SHALL need no CAN hardware and contain no real device or vendor names.

#### Scenario: Open in the editor
- **WHEN** a user opens `examples/openplc-fuxa` in the OpenPLC Editor
- **THEN** the project opens with target OpenPLC Runtime v4 and builds without changes

### Requirement: Shared plant config
`canworks/rtd8.eds`, `canworks/dio16.eds` and `canworks/simulation.json` SHALL be byte-identical to those of `examples/modbus-bridge`. `canworks/canworks.json` SHALL have the same networks, nodes and PDO entry names as `examples/node-red-dashboard`. Its bridge SHALL have one OpenPLC connection with the PLC link, listen on `127.0.0.1:1502`, and use low word first and no mailboxes.

#### Scenario: Plant files drift
- **WHEN** a change edits `examples/modbus-bridge/simulation.json` but not the example's copy
- **THEN** the example check fails naming both files

### Requirement: Generated editor files committed
The project SHALL contain the canworks-owned editor files (remote device, `canworks_in`, `canworks_out`, the `canworks` variable list, the stamp) exactly as `canworks-deploy --into-project` writes them for its config.

#### Scenario: Generated files out of date
- **WHEN** a tools change alters what `--into-project` writes for the example config
- **THEN** the example check fails naming the canworks-owned file that differs

### Requirement: Alarm logic
The function block `PLANT_LOGIC` SHALL set the alarm when temperature 1 in °C is valid (bridge and node 5 OK) and above the limit, and reset it only on Ack while that no longer holds. Bit 0 of `dio_out0` SHALL follow the alarm, as in the Node-RED and CODESYS examples.

#### Scenario: Alarm and Ack
- **WHEN** the limit is 25.0 °C and simulated temperature 1 rises past 25.0 °C and later falls back below it
- **THEN** `alarm` and bit 0 of `dio_out0` come on, stay on after the temperature falls, and go off when the HMI writes `ack` TRUE

#### Scenario: Ack while too hot
- **WHEN** the HMI writes `ack` TRUE while temperature 1 is above the limit
- **THEN** `alarm` stays on

### Requirement: Running light logic
While the running light is on, `PLANT_LOGIC` SHALL move one bit along `dio_out1` every 500 ms and set `LIGHT_OK` when, at a step, `dio_in1` equals the value written. While it is off, `dio_out1` SHALL be the HMI's `manual_out1` and `LIGHT_OK` SHALL be false.

#### Scenario: Light checked
- **WHEN** the running light is on and the simulated module loops its outputs back
- **THEN** `light_ok` reads TRUE within a second

### Requirement: HMI variables in main
`main` SHALL hold the HMI variables `temp1`, `temp2` (REAL °C), `limit` (REAL, 25.0 at start), `ack`, `run` (TRUE at start), `alarm`, `light_ok`, `rtd_ok`, `dio_ok`, `canworks_ok`, `bus_ok`, `dio_in0`, `dio_in1`, `dio_out0`, `dio_out1`, `manual_out0` and `manual_out1`. It SHALL clear `ack` after the scan that used it.

#### Scenario: Ack is a command
- **WHEN** the HMI writes `ack` TRUE
- **THEN** `ack` reads FALSE again after the next scan

### Requirement: OPC UA server entry
The project SHALL have an enabled OPC UA server entry in `devices/servers/`, in the editor's format, on `opc.tcp://0.0.0.0:4840/openplc/opcua` with a 100 ms cycle. It SHALL have one profile with no security, Anonymous only and anonymous role `operator`, and no users or certificates.

#### Scenario: Anonymous connect
- **WHEN** an OPC UA client on the host connects anonymously to `opc.tcp://127.0.0.1:4840/openplc/opcua` while the program runs
- **THEN** the session opens and it can browse the published nodes

### Requirement: Published nodes and rights
The OPC UA entry SHALL publish `main`'s HMI variables as nodes `PLC.main.<name>`. `limit`, `ack`, `run`, `manual_out0` and `manual_out1` SHALL be read/write for `operator` and `engineer` and read-only for `viewer`. Every other node SHALL be read-only for every role. It SHALL publish each member of the `canworks` variable list except `link` read-only as `PLC.canworks.<member>`.

#### Scenario: Read-only plant value
- **WHEN** an anonymous OPC UA client writes `PLC.main.temp1`
- **THEN** the write is refused and the value stays what the program computed

#### Scenario: Limit from the HMI
- **WHEN** an anonymous OPC UA client writes 22.0 to `PLC.main.limit`
- **THEN** the program uses 22.0 as the limit from the next scan

### Requirement: FUXA project
`fuxa/project.json` SHALL be a FUXA project with one OPC UA device at `opc.tcp://bridge:4840/openplc/opcua`, because the runtime binds its server to the network's address and not to 127.0.0.1. Tag ids SHALL be the tag names. Every tag SHALL address a node the OPC UA entry publishes, and every tag a view writes SHALL be writable for `operator`.

#### Scenario: Tags resolve
- **WHEN** FUXA loads the project while the program runs
- **THEN** every tag of the project has a value

### Requirement: Plant view
The FUXA project SHALL have a **Plant** view with:
- both temperatures in °C with a trend;
- the limit as an input;
- the alarm lamp with an Ack button;
- the running light switch with its check;
- a status lamp for each node;
- the bridge state.

#### Scenario: Limit input
- **WHEN** the user sets the limit to 22.0 on the Plant view while temperature 1 is 23.0 °C
- **THEN** the alarm lamp comes on

### Requirement: I/O view
The FUXA project SHALL have an **I/O** view with lamps for the 16 bits of `dio_in0` and `dio_in1`, and the 16 output bits. Bits 1-7 of `dio_out0` SHALL be switchable through `manual_out0`, and the bits of `dio_out1` through `manual_out1` while the running light is off.

#### Scenario: Switch loops back
- **WHEN** the user turns the running light off on Plant and switches bit 3 of `dio_out1` on, on the I/O view
- **THEN** the lamp for bit 3 of `dio_in1` comes on within a second

### Requirement: Compose services
`docker compose up` in the example folder SHALL start:
- the simulated plant in the canworks-bridge image at `CANWORKS_VERSION` (default `latest`), on a copy of the plant files in a volume;
- the upstream OpenPLC Runtime image at the version `canworks-local-runtime` pins;
- FUXA 1.3.5.

The runtime and FUXA SHALL share the bridge's network, with no CAN interface, no host network mode and no added capabilities, on Linux, macOS and Windows.

#### Scenario: First run
- **WHEN** a user with Docker runs `docker compose up`, uploads the project to `localhost:8443` from the editor and opens `http://localhost:1881`
- **THEN** FUXA's Plant view shows the two temperatures changing and both nodes OK

### Requirement: Compose ports
The compose setup SHALL publish ports on `127.0.0.1` only: 8443 (runtime), 1881 (FUXA) and 4840 (OPC UA).

#### Scenario: Not on the network
- **WHEN** another machine on the LAN connects to the host's port 4840
- **THEN** the connection is refused

### Requirement: FUXA first start
On first start the FUXA service SHALL install its OPC UA driver and load `fuxa/project.json`. Later starts SHALL keep the user's FUXA changes and not need the internet.

#### Scenario: Restart keeps edits
- **WHEN** the user changes a view in FUXA's editor, then runs `docker compose down` and `docker compose up`
- **THEN** FUXA shows the changed view

### Requirement: Example README
The example's README SHALL describe:
- the Docker route: compose, upload from the editor or with `openplc-cli upload`, the FUXA URL, `CANWORKS_VERSION`, `docker compose down -v`, and the internet needed on first start;
- that `canworks-local-runtime` uses the same ports;
- a route without Docker;
- that anonymous OPC UA access is for the local example only;
- the editor version used.

#### Scenario: Without Docker
- **WHEN** a user follows the route without Docker, with the bridge and runtime on a Linux device and FUXA on a PC
- **THEN** FUXA's views show the plant after its device address is changed to the Linux device

### Requirement: Links to the example
README.md and `docs/modbus-bridge.md` SHALL link to the example, and `docs/local-runtime.md` SHALL say that it uses the same ports.

#### Scenario: Finding the example
- **WHEN** a user reads the OpenPLC section of `docs/modbus-bridge.md`
- **THEN** it links to `examples/openplc-fuxa`
