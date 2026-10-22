## MODIFIED Requirements

### Requirement: Example project that runs without hardware
The repository SHALL contain an example project in `examples/virtual-plant/` that opens in OpenPLC Editor 4.3.2 and carries its CANopen configuration in a `canworks/` folder (config, EDS files, slave EDS description, simulation file). Every network of the example SHALL have `adapter.simulate: true`, and every device in it SHALL be made up (no real product names or identities). Uploaded to the local simulator runtime, or to any runtime with the plugin and no CAN hardware, the example SHALL start every configured node and run its PLC program without a CAN adapter or device.

#### Scenario: Upload to the local simulator runtime
- **WHEN** a user starts `canworks-local-runtime`, opens the example in the editor and uses Build and Upload to `localhost:8443`
- **THEN** the PLC runs, every configured node reaches OPERATIONAL, and the debugger shows moving temperatures

#### Scenario: Deploy tool route
- **WHEN** a user deploys the example with `canworks-deploy --runtime local` from a PC with no CAN adapter
- **THEN** the result is the same as with the editor upload
