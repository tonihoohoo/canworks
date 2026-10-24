# fuxa-nodered-example Specification

## Purpose
TBD - created by archiving change add-fuxa-nodered-example. Update Purpose after archive.

## Requirements

### Requirement: FUXA Node-RED example on the shared plant
The repository SHALL have `examples/fuxa-node-red/` with `canworks.json`, `rtd8.eds`, `dio16.eds`, `simulation.json`, `plant.json`, `fuxa/project.json`, `docker-compose.yml`, `start.sh` and `README.md`. The plant files SHALL be byte-identical to those of `examples/node-red-dashboard`. The example SHALL need no CAN hardware and contain no real device or vendor names.

#### Scenario: Plant files drift
- **WHEN** a change edits `examples/node-red-dashboard/canworks.json` but not this example's copy
- **THEN** the example check fails naming both files

### Requirement: Control in FUXA's Node-RED
The control SHALL run in FUXA's built-in Node-RED on the canworks Node-RED package, as the bridge's only Modbus client. FUXA SHALL have no device of its own. `plant.json` SHALL use the bridge node of the flow exported under the name `plant`.

#### Scenario: One client
- **WHEN** the example runs
- **THEN** the bridge's diagnostics list one Modbus client, Node-RED's

### Requirement: Shared plant logic unchanged
`plant.json` SHALL contain the dashboard example's **plant logic** function node with the same code, fed by **canworks in** and a 500 ms tick, and writing `dio.out0` and `dio.out1` through **canworks out**. It SHALL behave as `PLANT_LOGIC` of the other examples.

#### Scenario: Logic edited in one place
- **WHEN** a change edits the plant logic code in `examples/node-red-dashboard/dashboard.json` only
- **THEN** the example check fails naming both files

### Requirement: Values as FUXA Server tags
The flow SHALL write the plant state to tags of the FUXA Server device whose ids equal their names: `temp1`, `temp2`, `rtd_ok`, `dio_ok`, `canworks_ok`, `bus_ok`, `alarm`, `light_ok`, `dio_in0`, `dio_in1`, `dio_out0`, `dio_out1` and `bridge_state`. It SHALL write a tag only when it holds another value, so the tags are filled again after FUXA reloads its project.

#### Scenario: Temperature shown
- **WHEN** the simulated temperature 1 changes
- **THEN** the `temp1` tag in FUXA has the new value in °C within a second

### Requirement: Operator tags back to the logic
The tags `limit` (start 25), `run` (start true), `ack`, `manual_out0` and `manual_out1` SHALL reach the logic within half a second of a change in FUXA. Node-RED SHALL set `ack` back to false after using it. Bits 1-7 of `dio_out0` SHALL follow `manual_out0`, and while `run` is false, `dio_out1` SHALL follow `manual_out1`. At deploy the flow SHALL read the current operator values from FUXA.

#### Scenario: Limit from FUXA
- **WHEN** the operator sets `limit` below temperature 1 in FUXA
- **THEN** `alarm` turns true, bit 0 of `dio_out0` goes out, and bit 0 of `dio_in0` comes back on

#### Scenario: Ack
- **WHEN** the operator presses Ack while temperature 1 is at or below the limit
- **THEN** `alarm` turns false and `ack` reads false again

### Requirement: Operator values after a reload
When the FUXA project is saved or FUXA restarts, `limit`, `run`, `manual_out0` and `manual_out1` SHALL return to their start values and the logic SHALL follow them. The README SHALL say so.

#### Scenario: Project saved
- **WHEN** the limit is 30 and the user saves the project in FUXA's editor
- **THEN** the limit is 25 again and the alarm uses 25

### Requirement: Plant view
`fuxa/project.json` SHALL have a **Plant** view with:
- the two temperatures and their trend;
- the limit input, the alarm lamp and Ack;
- the running light switch and its check;
- the status of both nodes, `canworks_ok` and `bus_ok`.

#### Scenario: Alarm on the view
- **WHEN** the user sets the limit to 22.0 on the Plant view while temperature 1 is 23.0 °C
- **THEN** the alarm lamp comes on

### Requirement: I/O view
`fuxa/project.json` SHALL have an **I/O** view with lamps for the 16 input bits and the 16 output bits, and buttons for bits 1-7 of `manual_out0` and the 8 bits of `manual_out1` (these work while the running light is off).

#### Scenario: Manual output loops back
- **WHEN** the user turns the running light off and switches bit 3 of `manual_out1` on
- **THEN** the lamp for bit 3 of `dio_in1` comes on within a second

### Requirement: Run with Docker Compose
`docker compose up` in the folder SHALL start the simulated plant in the canworks-bridge image at `CANWORKS_VERSION` (default `latest`) and `frangoteam/fuxa:1.3.5` in the bridge's network. The package and flow SHALL be exported by that image. It SHALL run on Linux, macOS and Windows with no CAN interface, no host network mode and no added capabilities.

#### Scenario: First start
- **WHEN** a user with Docker runs `docker compose up`
- **THEN** within a few minutes `http://localhost:1881` shows the Plant view with both temperatures changing

### Requirement: Start script
The start script SHALL turn on FUXA's Node-RED and install the canworks package from the exported `.tgz` without the internet. It SHALL reinstall the package only when its version changed. It SHALL load the flow and the FUXA project once, so later starts keep the user's changes. Only `127.0.0.1:1881` SHALL be published.

#### Scenario: New tools version
- **WHEN** the user runs with a newer `CANWORKS_VERSION` on an existing volume
- **THEN** FUXA's Node-RED has that package version, and the user's flow and views are kept

### Requirement: Example documentation
The README SHALL describe the Docker route first. It SHALL give the URLs (`/` and `/nodered/`), the port shared with the OpenPLC + FUXA example, the restart behaviour and FUXA's security settings. It SHALL then describe the route with an installed bridge and a FUXA of the user's own. README.md and `docs/node-red.md` SHALL link to the example.

#### Scenario: Without Docker
- **WHEN** a user follows the second route with a bridge on a Linux device and FUXA on a PC
- **THEN** the views show the plant after the bridge node's host is changed to the device
