## ADDED Requirements

### Requirement: Dashboard example on the shared plant
The repository SHALL have `examples/node-red-dashboard/` with `canworks.json`, `rtd8.eds`, `dio16.eds`, `simulation.json`, `dashboard.json`, `docker-compose.yml`, `start.sh` and `README.md`. `rtd8.eds`, `dio16.eds` and `simulation.json` SHALL be byte-identical to those of `examples/modbus-bridge`. The config SHALL have the same networks and nodes as `examples/modbus-bridge`, with PDO entry names `temp1`, `temp2` (0x7130:1/2 of node 5), `in0`, `in1` (0x6000:1/2 of node 6) and `out0`, `out1` (0x6200:1/2 of node 6), so the values are `rtd.temp1` ... `dio.out1` in Node-RED and `rtd_temp1` ... `dio_out1` in the PLC examples. Its bridge SHALL listen on `127.0.0.1:1502`, list `127.0.0.1` as its only writer, and have the status and control blocks, the SDO registers and the mailboxes, so the **nmt**, **sdo** and **emcy** nodes work. The example SHALL need no CAN hardware and contain no real device or vendor names.

#### Scenario: Plant files drift
- **WHEN** a change edits `examples/modbus-bridge/simulation.json` but not the example's copy
- **THEN** the example check fails naming both files

### Requirement: Run with Docker Compose
`docker compose up` in the example folder SHALL start the simulated plant in the canworks-bridge image and Node-RED 4 (`nodered/node-red:4.1`) with the canworks package and Node-RED Dashboard 2.0 (`@flowfuse/node-red-dashboard`, pinned version) installed and the example's flow loaded, on Linux and on Docker Desktop for macOS and Windows, with no CAN interface, no host network mode and no added capabilities. The Node-RED package and the canworks flow SHALL be exported at every start by the deploy tool in the bridge image of the same `CANWORKS_VERSION` (default `latest`), so the package, the flow and the bridge have one version and no file is exported by hand; the bridge SHALL run on a copy of the plant's files in a volume, since it writes generated files next to its config. Node-RED SHALL reach the bridge at `127.0.0.1:1502` by sharing the bridge service's network, and the editor and dashboard SHALL be at `http://localhost:1880` and `http://localhost:1880/dashboard`. Later starts SHALL keep the user's flow changes and reinstall the canworks package only when its version changed.

#### Scenario: First start
- **WHEN** a user with Docker runs `docker compose up` in the example folder on a Mac
- **THEN** within a few minutes `http://localhost:1880/dashboard` shows the Plant page, the two temperatures change, and every canworks node shows connected

#### Scenario: New tools version
- **WHEN** the user runs with `CANWORKS_VERSION` set to a newer release on an existing volume
- **THEN** Node-RED starts with that version's canworks package installed and the user's flow kept

### Requirement: Dashboard pages
`dashboard.json` SHALL hold the dashboard tab and its Dashboard 2.0 config nodes only. Its canworks nodes SHALL use the bridge config node of the flow exported from the example config under the name `plant`. Every topic it reads or writes SHALL exist in that export, and every topic it writes SHALL be an output. The dashboard SHALL have these pages:
- **Plant**: both temperatures in °C as values with one trend, a status dot for each node, the limit, the alarm lamp, an Ack button and the bridge state.
- **I/O**: switches for the 16 bits of `dio_out0` and `dio_out1`, with bit 0 of `dio_out0` shown as the alarm output and `dio_out1` switchable while the running light is off, and lamps for the 16 bits of `dio_in0` and `dio_in1`.
- **Service**: NMT start, stop and reset for each node, a read of the device name (0x1008) over SDO, and a table of received EMCY messages.

#### Scenario: Switch loops back
- **WHEN** the user turns the running light off on the Plant page and the switch for bit 3 of `dio_out1` on on the I/O page
- **THEN** the lamp for bit 3 of `dio_in1` comes on within a second

#### Scenario: Device name
- **WHEN** the user presses "Read device name" for node 5 on the Service page
- **THEN** the page shows the simulated module's device name from its EDS

### Requirement: Shared plant logic
The example's flow SHALL do the shared plant logic of the CODESYS and truST examples (`PLANT_LOGIC`) in one function node. The alarm SHALL come on when `rtd.temp1`/10 is above the limit (default 25.0 °C, set on the Plant page) and stay on until Ack is pressed while the temperature is at or below the limit. Bit 0 of `dio_out0` SHALL follow the alarm. While the Plant page's **Running light** (`RUN`, on at start) is on, one bit SHALL move along `dio_out1` every 500 ms and `LIGHT_OK` SHALL be shown true when, at a step, `dio_in1` equals the value written to `dio_out1`; while it is off, `LIGHT_OK` is false.

#### Scenario: Alarm and Ack
- **WHEN** the limit is 25.0 °C and the simulated temperature 1 rises past 25.0 °C and later falls back below it
- **THEN** the alarm lamp and bit 0 of `dio_out0` come on, stay on after the temperature falls, and go off when Ack is pressed

#### Scenario: Ack while too hot
- **WHEN** Ack is pressed while temperature 1 is above the limit
- **THEN** the alarm stays on

### Requirement: Example documentation
The example's README SHALL describe the Docker route first (`docker compose up`, the URLs, `CANWORKS_VERSION`, resetting with `docker compose down -v` after changing the config, the internet needed on first start) and then the route with a bridge installed on Linux and a local Node-RED (`--export-nodered-package`, `--export-nodered`, importing `dashboard.json`). README.md and `docs/node-red.md` SHALL link to the example.

#### Scenario: Without Docker
- **WHEN** a user follows the README's second route with a bridge installed on a Linux machine and Node-RED on the same machine
- **THEN** the same dashboard runs against that bridge
