## ADDED Requirements

### Requirement: Multi-network stop and upload test
CI SHALL start the bridge on a config with at least two CANopen networks under forced simulation, stop it with SIGTERM and require exit code 0, every network's stop NMT and no run marker, and SHALL upload a config to it and require the new config applied.

#### Scenario: Regression
- **WHEN** a change makes the bridge die on stop with two networks
- **THEN** the test fails naming the exit status

### Requirement: Doc references in every page
The doc reference test SHALL check links, anchors, paths, subcommands and options, per subcommand, in README.md, docs/*.md, SECURITY.md, tools/deploy/README.md, the release notes template and every example and config README.

#### Scenario: Removed option in a doc page
- **WHEN** docs/diagnostics.md names a `canworks-diag sim fault` kind the tool does not have
- **THEN** the test fails naming the file, line and option
