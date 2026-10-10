## ADDED Requirements

### Requirement: CiA 309-3 gateway settings
The Online access settings SHALL have a "CiA 309-3 gateway" part that turns `cia309` on and off and edits its plain port (or none), `max_clients`, "allow changes" and "allow force on running nodes" (both off by default; force with a warning that a standard tool can then stop nodes the program drives), and shows the network numbering, with optional explicit numbers per network. It SHALL say that the plain port listens on the PLC's loopback address only and that other machines connect through `canworks-diag gateway` with the project's token. The deploy tool's config check and the configurator's Check SHALL apply the plugin's `cia309` rules.

#### Scenario: Turn the gateway on
- **WHEN** the user turns on the CiA 309-3 gateway in a project with networks `io` and `drives` and saves
- **THEN** `canworks.json` has a top-level `cia309` object with `allow_changes` false, and the page shows `1 = io, 2 = drives`

#### Scenario: Network bind refused in Check
- **WHEN** a hand-edited project has `cia309.bind` set to `0.0.0.0`
- **THEN** Check reports `cia309.bind` with the plugin's message
