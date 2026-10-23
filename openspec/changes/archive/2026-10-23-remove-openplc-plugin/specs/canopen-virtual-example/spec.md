## MODIFIED Requirements

### Requirement: Example project that runs without hardware
The repository SHALL contain an example project in `examples/virtual-plant/` that opens in OpenPLC Editor 4.3.2 and carries its CANopen configuration in a `canworks/` folder (config with `bridge.openplc`, EDS files, slave EDS description, simulation file), with the editor's remote device `devices/remote/canworks.json` and the generated `canworks` variable list and `canworks_in`/`canworks_out` programs. Every network of the example SHALL have `adapter.simulate: true`, and every device in it SHALL be made up (no real product names or identities). With its config on the local bridge, or on any bridge with no CAN hardware, and its program uploaded to the runtime next to that bridge, the example SHALL start every configured node and run its PLC program without a CAN adapter or device.

#### Scenario: Upload to the local simulator runtime
- **WHEN** a user starts `canworks-local-runtime`, runs `canworks-deploy --config examples/virtual-plant/canworks/canworks.json --bridge local`, opens the example in the editor and uses Build and Upload to `localhost:8443`
- **THEN** the PLC runs, `canworks_ok` is TRUE, every configured node reaches OPERATIONAL, and the debugger shows moving temperatures

#### Scenario: Deploy tool route
- **WHEN** a user puts the example's config on the local bridge from the configurator's Devices or connection bar instead of the command line
- **THEN** the result is the same as with `canworks-deploy --bridge local`

### Requirement: What the example shows
The example SHALL exercise at least: several networks; a master network with SYNC from a timer and the TIME producer; PDO mapping written from the config onto a device with a blank default mapping; startup SDOs; identity check; a mandatory node; heartbeat supervision; configuration check (0x1020) and opt-in store (0x1010); an input PDO receive timeout; node status, state and EMCY values in the program; typed values through `canworks_in`/`canworks_out`, NMT through `CO_NMT` and an SDO read and write through `CO_SDO_READ`/`CO_SDO_WRITE`; LSS node ID assignment of a simulated device without a node ID; a made-up conveyor device whose speed set-point and actual speed are plain PDO values, the actual speed following the set-point through a simulation expression; OpenPLC as a slave with an EDS generated from its description; a gateway with routes, field node status, EMCY forwarding, SDO bridge and behaviour on loss of the upper master; online diagnostics with a token; and a simulation file with value sources, an expression, start-up or timed faults and scenarios marked as tests. It SHALL have no CiA 402 axis and no SYNC from the PLC cycle.

#### Scenario: Gateway route
- **WHEN** the example runs and the simulated temperature of node 5 on network `io` changes
- **THEN** the routed value on the slave network `cell` follows it and the stand-in master on `host` receives it in its PDO

#### Scenario: Fault reaction
- **WHEN** the user stops the heartbeat of node 6 from the configurator's Simulation view
- **THEN** node 6's status bit goes FALSE, the program's fault output switches on, and the field node status on `cell` shows node 6 lost

#### Scenario: Conveyor speed
- **WHEN** the program sets the conveyor's speed set-point to 1200
- **THEN** the conveyor's actual speed in the program rises to 1200 within the time the simulation expression gives

### Requirement: Guide
The repository SHALL contain `docs/tour.md`, a step-by-step guide to the example for Windows, macOS and Linux, needing only a container engine, the PC tools and the editor. Each chapter SHALL say what to do, what the user sees, and which doc describes the feature. Each step in the configurator SHALL name where it happens in the order the user finds it (the workspace, the tree entry or tool tab, the node tab, then the control) with the labels the page shows, and SHALL describe the page as it is in the same commit. It SHALL cover installing, the configurator and its checks (with a deliberate mistake), the exports (DCF, DBC, HTML network document, slave EDS), putting the config on the local bridge, the editor upload and debugger with the `canworks` variables, connecting through the connection bar to the local simulator runtime, online diagnostics, device parameters, simulation control and fault injection, LSS, the conveyor, slave and gateway, trace with triggers, frame inspector and export, sending raw frames, and running the scenario tests. A step that needs an earlier step's effect (for example a boot in a trace) SHALL make that effect happen where it is needed. It SHALL end with a section naming the features that need hardware and why: bit rate detection, slcan adapters and hot-plug, bus error states, commissioning straight from the PC through a USB adapter, program download, real-time timing, and the install on a Linux device. Its screenshots SHALL show the current page. The README SHALL link the guide.

#### Scenario: Commands in the guide work
- **WHEN** the CI job runs the command-line steps of the guide against the example
- **THEN** each step succeeds as the guide says

#### Scenario: Machine chapter
- **WHEN** a user reads the guide's chapter list
- **THEN** it ends with Scenario tests and the hardware section, and no chapter names a gantry, the Machine tab, a drive axis or CiA 402

#### Scenario: Labels in the guide exist on the page
- **WHEN** the docs tests run
- **THEN** every bold label in `docs/tour.md` that is not on the test's allow-list is found in the configurator's page code, and a missing one fails the test naming the label and its chapter

#### Scenario: First connection
- **WHEN** a user with a fresh configurator follows the connect step with the example open and the local simulator runtime running
- **THEN** switching to Commission opens the connect panel, **Local simulator runtime** and **Connect** ask for the token, and after `virtual-plant-demo` the connection bar shows the runtime and the Nodes table shows nodes 5, 6 and 7

#### Scenario: Boot story in the trace
- **WHEN** a user follows the frame inspector chapter
- **THEN** node 6 is reset while the trace records, and the Sequences tab shows its boot story

### Requirement: Example checked in CI
CI SHALL check the example on pull requests that change it, the bridge, the PC tools, the library or the local runtime command, and weekly: the deploy tool's check and exports pass without warnings the guide does not mention, the generated remote device and programs equal the ones in the example, the program compiles with the editor's ST compiler, the example on the bridge with the pinned runtime's Modbus master brings every configured node to OPERATIONAL (the slave seen from the stand-in master included) with `canworks_ok` TRUE, and every scenario marked as a test passes with a JUnit report.

#### Scenario: A change breaks the example
- **WHEN** a pull request renames a config field the example uses
- **THEN** the example job fails naming the field
