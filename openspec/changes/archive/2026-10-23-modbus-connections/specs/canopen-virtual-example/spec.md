## MODIFIED Requirements

### Requirement: Example project that runs without hardware
The repository SHALL contain an example project in `examples/virtual-plant/` that opens in OpenPLC Editor 4.3.2 and carries its CANopen configuration in a `canworks/` folder (config with an OpenPLC connection, EDS files, slave EDS description, simulation file), with the editor's remote device `devices/remote/canworks.json` and the generated `canworks` variable list and `canworks_in`/`canworks_out` programs. Every network of the example SHALL have `adapter.simulate: true`, and every device in it SHALL be made up (no real product names or identities). With its config on the local bridge, or on any bridge with no CAN hardware, and its program uploaded to the runtime next to that bridge, the example SHALL start every configured node and run its PLC program without a CAN adapter or device.

#### Scenario: Upload to the local simulator runtime
- **WHEN** a user starts `canworks-local-runtime`, runs `canworks-deploy --config examples/virtual-plant/canworks/canworks.json --bridge local`, opens the example in the editor and uses Build and Upload to `localhost:8443`
- **THEN** the PLC runs, `canworks_ok` is TRUE, every configured node reaches OPERATIONAL, and the debugger shows moving temperatures

#### Scenario: Deploy tool route
- **WHEN** a user puts the example's config on the local bridge from the configurator's Devices or connection bar instead of the command line
- **THEN** the result is the same as with `canworks-deploy --bridge local`
