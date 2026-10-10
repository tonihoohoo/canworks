## ADDED Requirements

### Requirement: Expression size limits
An expression SHALL be refused when it is longer than 4096 characters or nests deeper than 128 levels, with its position, wherever it comes from (simulation file, control protocol, `sim_check_expr`). Checking or evaluating an expression SHALL never crash the process that runs the simulator.

#### Scenario: Deep nesting
- **WHEN** a client checks an expression made of 10,000 `(` followed by `1` and 10,000 `)`
- **THEN** the check answers with an error naming the nesting limit and its position, and the plugin keeps running

### Requirement: Taken node IDs stay off
A simulated device whose node ID was found in use on a real bus SHALL stay off for the rest of that session: `power on`, `clear`, scenario steps and live control SHALL NOT bring it back, and SHALL answer that the node ID is taken by a real device. Extra devices from the simulation file SHALL be checked like configured nodes: against node IDs heard on the bus at start and against the configuration's node IDs that are not simulated.

#### Scenario: Clear on a taken node
- **WHEN** node 5 has `simulate: true` on `can0`, a real node 5 answers at start, and a scenario step clears all faults of node 5
- **THEN** no frame with node 5's identifiers is sent by the simulator, and the step reports that node 5 is taken

#### Scenario: Extra device on a real node ID
- **WHEN** the simulation file adds an extra device with node ID 23 and the configuration has a real node 23
- **THEN** the extra device is not started and the log says node 23 is taken

### Requirement: CSV files the simulator may read
A CSV time series SHALL name a regular file inside the config's folder or the simulation file's folder after links are resolved, of at most 16 MB with lines of at most 4096 bytes; other files SHALL be refused with the reason. The file SHALL be read when the source is set, not during a simulation tick.

#### Scenario: Path outside the project
- **WHEN** a CSV source names `/etc/passwd` or `../../secret.csv`
- **THEN** the source is refused saying the file must be inside the project

### Requirement: Simulation work per tick is bounded
`delay()` SHALL treat a delay that is not a finite number as 0 and SHALL keep a bounded history, also when time goes backwards after a power cycle. A `repeat` whose body ran a whole pass without waiting SHALL continue on the next tick.

#### Scenario: Repeat without a wait
- **WHEN** a scenario has `{"repeat":{"steps":[{"log":"x"}]}}`
- **THEN** at most one log line per tick is written

### Requirement: Standalone control socket needs a hello
The standalone simulator's control socket SHALL require a `hello` as the first line of every connection, with or without a token, and SHALL close a connection whose first line is not JSON or starts with an HTTP method, without running anything.

#### Scenario: Request from a web page
- **WHEN** a browser sends an HTTP POST to the control port whose body holds a `sim_clear` line
- **THEN** the connection is closed and nothing is run

### Requirement: Forced simulation switch values
When `CANWORKS_FORCE_SIMULATE` is set to a value other than `1` or empty, the plugin SHALL log a warning that the value is ignored and the configured interfaces are used.

#### Scenario: Wrong value
- **WHEN** `CANWORKS_FORCE_SIMULATE=true`
- **THEN** the log warns that only `1` forces simulation
