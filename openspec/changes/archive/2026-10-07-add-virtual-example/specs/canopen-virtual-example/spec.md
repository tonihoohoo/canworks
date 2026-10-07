## ADDED Requirements

### Requirement: Example project that runs without hardware
The repository SHALL contain an example project in `examples/virtual-plant/` that opens in OpenPLC Editor 4.3.2 and carries its CANopen configuration in a `canopen/` folder (config, EDS files, slave EDS description, simulation file). Every network of the example SHALL have `adapter.simulate: true`, and every device in it SHALL be made up (no real product names or identities). Uploaded to the local simulator runtime, or to any runtime with the plugin and no CAN hardware, the example SHALL start every configured node and run its PLC program without a CAN adapter or device.

#### Scenario: Upload to the local simulator runtime
- **WHEN** a user starts `openplc-canopen-sim-runtime`, opens the example in the editor and uses Build and Upload to `localhost:8443`
- **THEN** the PLC runs, every configured node reaches OPERATIONAL, and the debugger shows moving temperatures

#### Scenario: Deploy tool route
- **WHEN** a user deploys the example with `openplc-canopen-deploy --runtime local` from a PC with no CAN adapter
- **THEN** the result is the same as with the editor upload

### Requirement: What the example shows
The example SHALL exercise at least: several networks; a master network with SYNC from a timer and the TIME producer; a master network with SYNC from the PLC cycle; PDO mapping written from the config onto a device with a blank default mapping; startup SDOs; identity check; a mandatory node; heartbeat supervision; configuration check (0x1020) and opt-in store (0x1010); an input PDO receive timeout; node status, state and EMCY locations; SDO variables, NMT commands and SDO function blocks in the program; LSS node ID assignment of a simulated device without a node ID; a CiA 402 axis in the cyclic synchronous modes; OpenPLC as a slave with an EDS generated from its description; a gateway with routes, field node status, EMCY forwarding, SDO bridge and behaviour on loss of the upper master; online diagnostics with a token; and a simulation file with value sources, an expression, start-up or timed faults and scenarios marked as tests.

#### Scenario: Gateway route
- **WHEN** the example runs and the simulated temperature of node 5 on network `io` changes
- **THEN** the routed value on the slave network `cell` follows it and the stand-in master on `host` receives it in its PDO

#### Scenario: Fault reaction
- **WHEN** the user stops the heartbeat of node 6 from the configurator's Simulation view
- **THEN** node 6's status bit goes FALSE, the program's fault output switches on, and the field node status on `cell` shows node 6 lost

### Requirement: Guide
The repository SHALL contain `docs/tour.md`, a step-by-step guide to the example for Windows, macOS and Linux, needing only a container engine, the PC tools and the editor. Each chapter SHALL say what to do, what the user sees, and which doc describes the feature. It SHALL cover installing, the configurator and its checks (with a deliberate mistake), the exports (DCF, DBC, HTML network document, slave EDS), the editor upload and debugger, online diagnostics, device parameters, simulation control and fault injection, LSS, the drive, slave and gateway, trace with triggers, frame inspector and export, sending raw frames, and running the scenario tests. It SHALL end with a section naming the features that need hardware and why: bit rate detection, slcan adapters and hot-plug, bus error states, commissioning straight from the PC through a USB adapter, program download, real-time timing, and the install on a runtime host. The README SHALL link the guide.

#### Scenario: Commands in the guide work
- **WHEN** the CI job runs the command-line steps of the guide against the example
- **THEN** each step succeeds as the guide says

### Requirement: Example checked in CI
CI SHALL check the example on pull requests that change it, the plugin, the PC tools or the local simulator runtime image, and on the image's weekly run: the deploy tool's check and exports pass without warnings the guide does not mention, the program compiles with the editor's ST compiler, the example deployed to the local simulator runtime image brings every configured node to OPERATIONAL (the slave seen from the stand-in master included), and every scenario marked as a test passes with a JUnit report.

#### Scenario: A change breaks the example
- **WHEN** a pull request renames a config field the example uses
- **THEN** the example job fails naming the field
