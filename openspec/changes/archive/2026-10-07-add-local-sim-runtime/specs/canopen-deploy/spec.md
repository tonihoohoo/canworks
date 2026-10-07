## ADDED Requirements

### Requirement: Uploading to the local simulator runtime
With `--runtime local`, the deploy tool SHALL take the target and credentials from the local runtime's saved settings (canopen-local-runtime), SHALL NOT ask the simulated-config confirmation, and SHALL print once before uploading that the local simulator runtime runs every network simulated. All other checks SHALL run as for any runtime.

#### Scenario: Real config to the local runtime
- **WHEN** a user deploys a config on `can0` with no simulated parts to `--runtime local` non-interactively
- **THEN** the upload goes ahead without `--yes` or `--simulated`, and the output says that every network runs simulated there

#### Scenario: Simulated config to the local runtime
- **WHEN** a user deploys a config with `adapter.simulate: true` to `--runtime local` non-interactively
- **THEN** the upload goes ahead without asking
