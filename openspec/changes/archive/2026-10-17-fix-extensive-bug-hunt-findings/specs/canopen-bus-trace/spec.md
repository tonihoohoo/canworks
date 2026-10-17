## ADDED Requirements

### Requirement: Trace dialects and damaged files
The trace readers SHALL honour ASC `base` and `timestamps` headers, read TRC 1.0 and 1.1 layouts, refuse unknown layouts and lines whose byte count differs from the DLC, refuse pcapng files without a CAN interface, and report every damaged file as a format error with its offset.

#### Scenario: ASC in decimal
- **WHEN** an ASC file says `base dec` and has ID 385
- **THEN** the frame is read as 0x181

#### Scenario: Truncated pcap
- **WHEN** a pcap file is 10 bytes long
- **THEN** the tool reports a format error, not a traceback

### Requirement: Replay loops keep the rate
Replay with `--loop` SHALL wait at least one recorded period between loops and keep the frame rate limit across loops; `--loop` on a plan shorter than 1 s SHALL need `--rate`.

#### Scenario: One-frame loop
- **WHEN** a one-frame trace is replayed with `--loop` and no `--rate`
- **THEN** the replay is refused

### Requirement: Dropped frames are reported
A recording that drops its oldest frames SHALL say how many were dropped and the span that remains.

#### Scenario: Long recording
- **WHEN** `canworks-diag trace` records more than its frame limit
- **THEN** the summary reports the dropped count
