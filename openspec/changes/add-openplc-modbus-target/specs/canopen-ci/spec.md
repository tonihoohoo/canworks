## ADDED Requirements

### Requirement: OpenPLC through Modbus integration test
CI SHALL run the pinned stock runtime image with its Modbus master, `canworks-bridge` and a simulated CANopen node on vcan0, with a PLC program generated for an `openplc` example config and uploaded with its `conf/modbus_master.json`. It SHALL check values in both directions, that a 32-bit counter of one PDO is never read torn, that a PLC stop with `on_client_loss: "hold"` keeps the last values from before the stop, and that a program with another map hash leaves outputs off. It SHALL run when the bridge, the OpenPLC Modbus generator, the library or the runtime pin change, in the existing integration workflow.

#### Scenario: Stop holds the real values
- **WHEN** the program drives an RPDO value to 7 and the PLC is stopped through the runtime's REST API
- **THEN** the simulated node keeps receiving 7, never 0
