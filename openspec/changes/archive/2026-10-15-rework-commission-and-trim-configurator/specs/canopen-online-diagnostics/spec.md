## ADDED Requirements

### Requirement: Raw frame commands in the command-line client
`canworks-diag send ID [DATA]` SHALL send one frame. It SHALL take `--ext`, `--rtr` with `--dlc N`, and `--force`. With `--period-ms` it SHALL start a cyclic job, keep running until `--count` frames, `--duration` seconds or Ctrl-C, and stop the job on exit. `canworks-diag send-stop [JOB]` SHALL stop jobs of its own connection only; it is meant for scripts that keep a connection. Each command SHALL take `--network` as the other commands do. A plugin that answers `unknown op` SHALL be reported as too old for the command. `canworks-diag` SHALL have no `detect-bitrate` command.

#### Scenario: Send from the terminal
- **WHEN** `canworks-diag --runtime plc.local send 0x60A "40 18 10 01 00 00 00 00"` runs with `allow_changes` true and nothing OPERATIONAL
- **THEN** it prints that the frame was sent and exits 0

#### Scenario: Older plugin
- **WHEN** the runtime's plugin predates these ops
- **THEN** the command exits 1 saying the runtime's plugin is too old for it

#### Scenario: No detect command
- **WHEN** a user runs `canworks-diag --runtime plc.local detect-bitrate`
- **THEN** argument parsing fails with exit status 2 because the command does not exist

## REMOVED Requirements

### Requirement: Bit rate detection
**Reason**: There is no bit rate detection in the toolkit any more. No page uses the runtime sweep after the configurator's Scan page is removed, and the project is not in real use.
**Migration**: The bit rate comes from the config's `adapter.bitrate`. The Online view's bus state and error counters show a wrong one. The plugin answers `detect_bitrate`, `detect_bitrate_status` and `detect_bitrate_stop` with `unknown op`.

### Requirement: Guards on bit rate detection
**Reason**: There is no bit rate detection.
**Migration**: None.

### Requirement: Raw frame and bit rate commands in the command-line client
**Reason**: Replaced by "Raw frame commands in the command-line client", without `detect-bitrate`.
**Migration**: None.

### Requirement: Bit rate detection ends in bounded time
**Reason**: There is no bit rate detection.
**Migration**: None.
