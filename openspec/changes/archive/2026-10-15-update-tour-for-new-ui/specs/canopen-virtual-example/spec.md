## MODIFIED Requirements

### Requirement: Guide
The repository SHALL contain `docs/tour.md`, a step-by-step guide to the example for Windows, macOS and Linux, needing only a container engine, the PC tools and the editor. Each chapter SHALL say what to do, what the user sees, and which doc describes the feature. Each step in the configurator SHALL name where it happens in the order the user finds it (the workspace, the tree entry or tool tab, the node tab, then the control) with the labels the page shows, and SHALL describe the page as it is in the same commit. It SHALL cover installing, the configurator and its checks (with a deliberate mistake), the exports (DCF, DBC, HTML network document, slave EDS), the editor upload and debugger, connecting through the connection bar to the local simulator runtime, online diagnostics, device parameters, simulation control and fault injection, LSS, the drive, slave and gateway, trace with triggers, frame inspector and export, sending raw frames, and running the scenario tests. A step that needs an earlier step's effect (for example a boot in a trace) SHALL make that effect happen where it is needed. It SHALL have a Simulated machine chapter on the gantry example (`examples/gantry-cell/`): deploy it to the local simulator runtime, open the Machine tab of the Simulation view, watch a pallet fill, jam the Z axis, stop the PLC, make the pick sensor stick, and see how the program reacts and recovers. It SHALL end with a section naming the features that need hardware and why: bit rate detection, slcan adapters and hot-plug, bus error states, commissioning straight from the PC through a USB adapter, program download, real-time timing, and the install on a runtime host. Its screenshots SHALL show the current page. The README SHALL link the guide.

#### Scenario: Commands in the guide work
- **WHEN** the CI job runs the command-line steps of the guide against the example
- **THEN** each step succeeds as the guide says

#### Scenario: Machine chapter
- **WHEN** a user follows the Simulated machine chapter on a PC with the local simulator runtime
- **THEN** the Machine tab of Simulation shows the gantry filling the pallet, and each fault the chapter injects shows the reaction it describes

#### Scenario: Labels in the guide exist on the page
- **WHEN** the docs tests run
- **THEN** every bold label in `docs/tour.md` that is not on the test's allow-list is found in the configurator's page code, and a missing one fails the test naming the label and its chapter

#### Scenario: First connection
- **WHEN** a user with a fresh configurator follows the connect step with the example open and the local simulator runtime running
- **THEN** switching to Commission opens the connect panel, **Local simulator runtime** and **Connect** ask for the token, and after `virtual-plant-demo` the connection bar shows the runtime and the Nodes table shows nodes 5, 6 and 7

#### Scenario: Boot story in the trace
- **WHEN** a user follows the frame inspector chapter
- **THEN** node 6 is reset while the trace records, and the Sequences tab shows its boot story
