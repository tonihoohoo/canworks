## ADDED Requirements

### Requirement: Install stamp
`install-stock.sh` SHALL write `<prefix>/lib/install-stamp` as the last step of each successful install, holding the canworks version, the protocols built and the runtime it was built for (native: the runtime's git commit; Docker: the runtime image id). It SHALL remove the stamp when a full install starts, and `--uninstall` SHALL remove it.

#### Scenario: Interrupted install
- **WHEN** an install is interrupted during the plugin build and then run again with the same release
- **THEN** the second run installs fully

### Requirement: Same-version re-run changes nothing
When a run computes the same stamp and the plugin library and canworks' runtime entries (native: its `plugins.conf` line; Docker: its runtime spec entries) are present, `install-stock.sh` SHALL skip everything that builds or installs canworks, `plugins.conf` and any runtime restart or container recreate, and SHALL say in one line that this version is already installed, the PLC keeps running, and `--force` installs it again. Versions `unknown` and `*-dirty` SHALL never be skipped.

#### Scenario: Same release again on a Docker-mode device
- **WHEN** `install-runtime.sh --version 0.112.0` runs on a device where 0.112.0 is installed for the same runtime image and the PLC runs a program
- **THEN** no plugin build runs, the runtime container is not recreated, the PLC still runs the same program afterwards, and the output says 0.112.0 is already installed and names `--force`

#### Scenario: Link added on a same-version run
- **WHEN** the same release is run again with `--with-link` on a device without the link
- **THEN** the remote link is installed, and the plugin and the PLC are left as they were

#### Scenario: Newer release
- **WHEN** a newer release is installed over 0.112.0
- **THEN** the full install runs as before and the stamp holds the new version

#### Scenario: Runtime changed
- **WHEN** the runtime image or commit changed since the last install
- **THEN** the full install runs and builds for the new runtime

#### Scenario: Checkout with local edits
- **WHEN** `install-stock.sh` runs twice from a checkout whose `git describe` ends in `-dirty`
- **THEN** both runs install fully

### Requirement: Host steps on a skipped install
A skipped install SHALL still load the J1939 kernel module and set up discovery and the remote link as asked, with step lines for those steps only.

#### Scenario: Nothing extra asked
- **WHEN** the same release runs again with no link or discovery options
- **THEN** the output has the one skip line and no build, restart or recreate

### Requirement: Force a full install
`install-stock.sh --force` SHALL install fully whatever the stamp says. `install-runtime.sh` and `install-runtime.ps1` SHALL pass `--force` through, also over SSH, and list it in their help.

#### Scenario: Force
- **WHEN** the same release runs again with `--force`
- **THEN** the full install runs, including the build and, in Docker mode, the container recreate
