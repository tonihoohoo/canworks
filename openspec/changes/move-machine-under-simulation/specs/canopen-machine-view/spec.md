## MODIFIED Requirements

### Requirement: Machine view
The configurator SHALL show the machine as a **Machine** tab of the **Simulation** view, after **Live values**, **Simulation file** and **Scenarios**, for a network whose simulation file section names a machine file; for other networks the tab SHALL not show. The configurator SHALL have no separate Machine item in the sidebar. While the Machine tab is open, the scene and its panel SHALL use the whole content area. Offline, it SHALL show the machine built from the machine file at its home positions. Online, against a runtime that runs the machine, it SHALL show the live machine from `sim_machine`. The view SHALL need no network access: its 3D library ships with the PC tools.

#### Scenario: Tab of Simulation
- **WHEN** a user opens **Simulation** for the `motion` network of the gantry example
- **THEN** the tabs read Live values, Simulation file, Scenarios and Machine, and the sidebar has no Machine item

#### Scenario: No machine file
- **WHEN** a user opens **Simulation** for a network whose section names no machine file
- **THEN** there is no Machine tab

#### Scenario: Offline preview
- **WHEN** a user opens the Machine tab for the gantry example with no runtime connected
- **THEN** the gantry, conveyor and pallet show at their home positions and the panel says the machine is offline

#### Scenario: No internet
- **WHEN** the PC has no internet connection and the configurator opens the Machine tab
- **THEN** the view loads completely
