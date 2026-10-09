## ADDED Requirements

### Requirement: Shipped examples swept in the browser
The page tests SHALL open each shipped example (`examples/virtual-plant`, `examples/gantry-cell`, `examples/j1939`) and visit every view of every network, failing on a console error, an uncaught page error, an HTTP error answer, a clipped control or sideways scrolling, or a decoding note. The existing all-views layout test SHALL run at two widths instead of three, so the configurator page jobs' summed time does not grow.

#### Scenario: Overflow in an example
- **WHEN** a change makes the gateway routes table clip a route name at 1280 px
- **THEN** the sweep fails naming the example, network, view and the clipped field

### Requirement: Configurator and plugin agree on bad configs
A test in the tools job SHALL run a corpus of invalid configs through both the configurator's check and the plugin's config loader (the `canopen_check` build) and SHALL fail when one refuses a config the other accepts. The corpus SHALL cover at least: a missing interface, out-of-range values in hex and decimal, duplicate COB-IDs, and a simulation source on an RPDO entry.

#### Scenario: New plugin check without a configurator check
- **WHEN** the plugin starts refusing a value that the configurator still accepts
- **THEN** the parity test fails naming the corpus entry

### Requirement: Browser run against the real plugin
A workflow of its own, separate from the CI workflow and like the integration workflow not awaited by `ci-ok`, SHALL run the configurator in Chromium against the real plugin running the virtual-plant example on its simulated bus (no CAN interface): connect, the node table, an object dictionary read and write, a simulation fault and its effect online, a device power cycle, a stopped TPDO raising its timeout bit, and a trace started, stopped and saved. It SHALL run weekly, on a manual run, and on pull requests that change the configurator's online or trace code or the plugin's diagnostics or simulated bus.

#### Scenario: Plugin-only pull request
- **WHEN** a pull request changes only `plugin/src/canopen/bus.cpp`
- **THEN** the browser run runs on it, and the CI workflow's wall time is unchanged

### Requirement: Page tests selected by path
The change classification SHALL report whether the configurator's front end or what it uses changed (its static files and server, the PC tools' modules it imports, the schemas, the shipped examples, the page tests and their data). The configurator page jobs SHALL run only then, or when shared CI files changed, or on every push to `main`; otherwise they SHALL report as skipped.

#### Scenario: Plugin-only change
- **WHEN** a pull request changes only `plugin/src/canopen/network.cpp`
- **THEN** the configurator page jobs report as skipped and `ci-ok` passes
