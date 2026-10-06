## ADDED Requirements

### Requirement: Simulation file in the bundle
When a `simulation.json` lies next to the config, the deploy tool SHALL check it and add it to the bundle as `conf/canopen/simulation.json`, together with the EDS or DCF files its extra devices and CSV files its value sources name, rewriting their paths as it does for node EDS files. `--into-project` and `--new-project` SHALL copy it into the project's `canopen/` folder the same way.

#### Scenario: Simulation file uploaded
- **WHEN** a user deploys a project whose `canopen/` folder has `simulation.json` naming `data/temp.csv`
- **THEN** the bundle has `conf/canopen/simulation.json` and the CSV, and the simulated devices use the CSV on the runtime

### Requirement: Warning before uploading a simulated config
When the config has `adapter.simulate: true`, the deploy tool SHALL say before uploading that the PLC will run on simulated devices and that no CAN interface will be used, and SHALL ask for confirmation unless `--yes` or `--simulated` is given. `--check-only` SHALL report it as a warning.

#### Scenario: Upload refused without confirmation
- **WHEN** a user deploys a simulated config non-interactively without `--yes` or `--simulated`
- **THEN** the deploy tool stops before uploading and says which option uploads it anyway
