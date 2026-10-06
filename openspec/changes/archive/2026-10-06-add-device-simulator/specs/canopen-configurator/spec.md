## ADDED Requirements

### Requirement: Choose what is simulated
The **Bus and master** page SHALL have a **Network** choice, **Real** or **Simulated** (`adapter.simulate`), and each node SHALL have a **Simulated** switch (the node's `simulate`), shown on the node and as a badge in the node list, with **Simulate all** and **Simulate none** buttons. On a simulated network a node switched off SHALL be shown as absent. Choosing a simulated network SHALL keep the adapter settings. Simulating anything SHALL turn on online access with **Allow changes** when it is off (saying so), and every page SHALL show a banner naming what is simulated (the network, or the simulated node IDs on the real network) and that the configuration must not be uploaded to a machine as it is.

#### Scenario: Simulated network
- **WHEN** a user chooses **Simulated** network in a project with online access off
- **THEN** the saved config has `adapter.simulate: true`, its adapter settings unchanged, online access on with **Allow changes**, every node shows the **Simulated** badge, and every page shows the banner

#### Scenario: One device on the real network
- **WHEN** a user keeps the **Real** network and switches on **Simulated** for node 5 only
- **THEN** the saved config has `"simulate": true` on node 5 only and the banner says node 5 is simulated on the real network

### Requirement: Simulation view
The configurator SHALL have a **Simulation** view that connects to the runtime's simulated devices (or to a standalone simulator by address) and shows, per simulated device, whether it runs on a simulated or a real network, its NMT and power state, injected faults and the objects it carries in PDOs with live values, refreshed at least twice a second. A user SHALL be able to set and override values (switches for BOOLEAN and bits, sliders between the EDS limits for numbers), give and edit value sources and expressions with checking as they type, inject and clear every fault the simulator offers from buttons, and add extra devices. Changes made here SHALL be saveable to `simulation.json`. Without **Allow changes** the view SHALL be read-only and say why.

#### Scenario: Move a sensor value by hand
- **WHEN** a user drags the slider of node 5's 0x7130:1 to 900 in the Simulation view
- **THEN** the simulated device holds 900, the PLC sees it in the mapped input, and the slider shows an override that **Release** removes

#### Scenario: Save behaviour
- **WHEN** a user gives 0x6401:1 a sine in the view and presses **Save to simulation file**
- **THEN** `canopen/simulation.json` has that source and the next simulated start uses it

### Requirement: Scenarios in the configurator
The Simulation view SHALL list the scenarios of the simulation file, let a user create and edit them as a list of steps with checking, start and stop them, and show the running step, the time and the result of each expect, with failed expects showing the condition and the value seen.

#### Scenario: Run a scenario
- **WHEN** a user starts the scenario `sensor-break` from the view
- **THEN** the view shows each step as it runs and the scenario's result when it ends
