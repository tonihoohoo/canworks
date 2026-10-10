## MODIFIED Requirements

### Requirement: Bridge process
`canworks-bridge --config FILE` SHALL run the networks of a bridge config (a version 2 config with a `bridge` object) on Linux without an OpenPLC runtime. It SHALL run every network kind the build includes (CANopen master, slave and gateway, J1939, plain CAN, raw messages, simulated networks), the diagnostics channel, trace and the CiA 309-3 gateway (canopen-cia309-gateway) exactly as the plugin does. The only difference is that the process image is served to Modbus TCP clients instead of a PLC program. It SHALL log one line naming its config, its protocols, its listen address and the number of input and output bytes, and SHALL exit with a non-zero status and the check's messages when the config is not valid.

#### Scenario: CANopen network behind Modbus
- **WHEN** the bridge runs a config with a CANopen master network on `can0` with node 5 and a `bridge` object
- **THEN** node 5 is booted and exchanges PDOs as under the plugin, and a Modbus client reads its TPDO values from input registers

#### Scenario: Config without bridge object
- **WHEN** `canworks-bridge` is started with a config that has no `bridge` object
- **THEN** it exits with an error saying the config is not a bridge config

#### Scenario: CiA 309-3 next to Modbus
- **WHEN** a bridge config has `bridge` and `cia309` objects
- **THEN** a Modbus client reads registers on the Modbus port while a CiA 309-3 client on `127.0.0.1:7533` reads objects of the same nodes

## ADDED Requirements

### Requirement: CiA 309-3 gateway and the output watchdog
Requests through the CiA 309-3 gateway SHALL NOT feed the bridge's output watchdog and SHALL NOT end outputs off. NMT commands from the gateway SHALL follow the gateway's guards and SHALL be carried out like those of the control block. The bridge's status part SHALL list the gateway sessions.

#### Scenario: Gateway client only
- **WHEN** only a CiA 309-3 client is connected and it reads objects every 100 ms
- **THEN** the watchdog runs out as with no client, outputs go off, and the gateway client keeps being served
