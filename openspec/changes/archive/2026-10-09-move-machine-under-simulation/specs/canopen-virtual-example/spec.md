## MODIFIED Requirements

### Requirement: Guide
The repository SHALL contain `docs/tour.md`, a step-by-step guide to the example for Windows, macOS and Linux, needing only a container engine, the PC tools and the editor. Each chapter SHALL say what to do, what the user sees, and which doc describes the feature. It SHALL cover installing, the configurator and its checks (with a deliberate mistake), the exports (DCF, DBC, HTML network document, slave EDS), the editor upload and debugger, online diagnostics, device parameters, simulation control and fault injection, LSS, the drive, slave and gateway, trace with triggers, frame inspector and export, sending raw frames, and running the scenario tests. It SHALL have a Simulated machine chapter on the gantry example (`examples/gantry-cell/`): deploy it to the local simulator runtime, open the Machine tab of the Simulation view, watch a pallet fill, jam the Z axis, stop the PLC, make the pick sensor stick, and see how the program reacts and recovers. It SHALL end with a section naming the features that need hardware and why: bit rate detection, slcan adapters and hot-plug, bus error states, commissioning straight from the PC through a USB adapter, program download, real-time timing, and the install on a runtime host. The README SHALL link the guide.

#### Scenario: Commands in the guide work
- **WHEN** the CI job runs the command-line steps of the guide against the example
- **THEN** each step succeeds as the guide says

#### Scenario: Machine chapter
- **WHEN** a user follows the Simulated machine chapter on a PC with the local simulator runtime
- **THEN** the Machine tab of Simulation shows the gantry filling the pallet, and each fault the chapter injects shows the reaction it describes
