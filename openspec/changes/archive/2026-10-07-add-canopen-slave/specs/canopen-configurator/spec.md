## ADDED Requirements

### Requirement: Network role switch
Each network tab SHALL have a role, master or slave. Switching a network with nodes to slave SHALL ask before dropping the master settings and nodes; switching back SHALL start with an empty master network.

#### Scenario: Switch to slave
- **WHEN** the user sets a new network's role to slave
- **THEN** the tab shows the adapter settings and the slave device page instead of the master settings and node list

### Requirement: Slave device page
The slave device page SHALL edit node ID (or LSS), the EDS (pick a file, or build one), the bound objects with their PLC locations, `inputs_on_loss` and the status and EMCY locations. Object rows SHALL come from the EDS, show the direction from its access type, and offer only matching PLC areas.

#### Scenario: Bind an object
- **WHEN** the user adds 0x2100:1 (access `ro`, UNSIGNED16) from the EDS
- **THEN** the row suggests a free `%QW` location and refuses an `%I` one

### Requirement: Build the slave EDS in the configurator
The page SHALL have an object list editor (name, type, direction, default, limits), identity fields and a layout choice, and SHALL generate the EDS with the same generator as `slave-eds` into the project's `canopen/` folder, then offer to bind every generated object to suggested locations.

#### Scenario: Build and bind
- **WHEN** the user enters four objects, generates and accepts the suggested bindings
- **THEN** `canopen/` has the EDS and the config binds all four objects

### Requirement: Export the slave EDS
The page SHALL have an **Export EDS** button that saves the slave's EDS for import into the other master's tool, with a file name from the device name.

#### Scenario: Export
- **WHEN** the user clicks **Export EDS**
- **THEN** a save dialog offers the EDS the plugin runs
