## MODIFIED Requirements

### Requirement: Checks before upload
Before uploading to a bridge, and for `--check`, the exports and `--into-project`, the deploy tool SHALL validate the config against the published JSON Schema for its `schema_version`, and SHALL run the same EDS checks the bridge runs at load (PDO-mappable, data type, access type, startup SDO value range, and the EDS lint with the bridge's rule and `eds_lint` setting, on the same prepared copy). Any failure SHALL stop with a non-zero exit, naming the file and the JSON path of the problem, and nothing SHALL be uploaded or written. Lint findings that do not stop the bridge SHALL be printed as warnings. A config with neither `bridge` nor `codesys` SHALL be refused as canopen-config-contract's "Config target" says.

#### Scenario: Schema violation
- **WHEN** the config has a node ID of 200
- **THEN** the tool exits non-zero naming `nodes[0].node_id` and the allowed range, and uploads nothing

#### Scenario: EDS check fails
- **WHEN** an `rx_pdos` entry targets a read-only object in the EDS and the user runs `canworks-deploy --config c.json --bridge plc.local`
- **THEN** the tool exits non-zero with the same message the bridge would log, and uploads nothing

#### Scenario: Blocking lint finding
- **WHEN** a node's EDS gives 0x1A00 sub 0 the data type UNSIGNED16, and `eds_lint` is unset
- **THEN** the tool exits non-zero with the same lint error the bridge would log, and uploads nothing

#### Scenario: Old plugin config
- **WHEN** the user runs `canworks-deploy --config old.json --check` on a config with neither `bridge` nor `codesys`
- **THEN** the tool exits non-zero with the message naming the configurator's **Switch to OpenPLC through Modbus**

### Requirement: Warning before uploading a config with simulated parts
When the config has a simulated network or any simulated node, `--bridge` SHALL say before uploading what is simulated (the network and no CAN interface used, or the simulated node IDs on the real network), and SHALL ask for confirmation unless `--yes` or `--simulated` is given, or the target is the local bridge (`--bridge local`), which runs every network simulated. `--check-only` SHALL report it as a warning.

#### Scenario: Upload refused without confirmation
- **WHEN** a user deploys a config with a simulated network to `--bridge plc.local` non-interactively without `--yes` or `--simulated`
- **THEN** the deploy tool stops before uploading and says which option uploads it anyway

#### Scenario: One simulated node
- **WHEN** a user deploys interactively a config on `can0` with node 5 simulated
- **THEN** the deploy tool says that node 5 will be a simulated device on the real network `can0` and asks before uploading

#### Scenario: Local bridge
- **WHEN** a user deploys a config on `can0` to `--bridge local` non-interactively
- **THEN** the upload goes ahead without asking, and the output says once that every network runs simulated there

### Requirement: Simulation file in the bundle
When a `simulation.json` lies next to the config, the deploy tool SHALL check it and upload it with the config to the bridge, together with the EDS or DCF files its extra devices and CSV files its value sources name. `--into-project` and `--new-project` SHALL copy it into the project's `canworks/` folder the same way.

#### Scenario: Simulation file uploaded
- **WHEN** a user deploys a config whose folder has `simulation.json` naming `data/temp.csv` with `--bridge plc.local`
- **THEN** the bridge receives the simulation file and the CSV, and its simulated devices use the CSV

### Requirement: Slave networks in the bundle and checks
The deploy tool SHALL upload each slave network's EDS with the config, and `--check` and every upload SHALL run the same EDS lint, object and binding checks the bridge runs, including the direction and location checks.

#### Scenario: Binding error found on the PC
- **WHEN** a slave binds an `rww` object to a `%QB` location and the user runs `canworks-deploy --check`
- **THEN** the check fails with the same message the bridge would log, before anything is uploaded

### Requirement: Deploy to a bridge
`canworks-deploy --config FILE --bridge TARGET` SHALL run the checks before upload, assemble the config and every file it names, and upload them with `put_config` over the diagnostics channel, with the same TLS options and token as `canworks-diag`. `TARGET` SHALL be `HOST[:PORT]`, a remembered runtime name reached by the automatic path choice (`link:NAME` forces the remote link), or `local` for the local bridge of canopen-local-runtime (`127.0.0.1` at its saved diagnostics port). It SHALL print the bridge's answer and exit non-zero when the bridge rejected the config or restored the previous one. `--check-only` SHALL stop before uploading. The deploy tool SHALL NOT upload anything to an OpenPLC runtime: the editor's own Build and upload sends the program and its Modbus master config.

#### Scenario: Successful bridge deploy
- **WHEN** a valid bridge config with two EDS files is deployed with `--bridge plc.local`
- **THEN** the bridge restarts with it and the tool prints the networks the bridge started

#### Scenario: Remembered device over the link
- **WHEN** the PC has paired with device `line1` and the user runs `canworks-deploy --config c.json --bridge line1`
- **THEN** the upload goes over the LAN when the device answers there, else over the remote link, with the same token

#### Scenario: Old runtime option
- **WHEN** the user runs `canworks-deploy --config c.json --runtime plc.local`
- **THEN** the command fails as for any unknown option

## REMOVED Requirements

### Requirement: Bundle assembly
**Reason**: Bundles carried the plugin's `conf/canworks.json` and EDS into an OpenPLC upload; the plugin is removed.
**Migration**: The editor's Build and upload for the program; `--bridge` for the config.

### Requirement: Address clash check across plugins
**Reason**: canworks no longer writes into the runtime's image; the editor allocates the Modbus master's locations itself.
**Migration**: None.

### Requirement: Upload through the runtime API
**Reason**: The deploy tool no longer uploads to an OpenPLC runtime.
**Migration**: The editor's Build and upload.

### Requirement: Warning about the editor's upload button
**Reason**: The editor's upload button is now the way to upload the program; nothing of canworks is lost by it.
**Migration**: None.

### Requirement: Uploading to the local simulator runtime
**Reason**: The local runtime's canworks part is a bridge container now.
**Migration**: `--bridge local` (Requirement: Deploy to a bridge).

### Requirement: Deploy to a remembered runtime
**Reason**: Runtime uploads are removed.
**Migration**: `--bridge NAME` takes a remembered runtime name (Requirement: Deploy to a bridge).
