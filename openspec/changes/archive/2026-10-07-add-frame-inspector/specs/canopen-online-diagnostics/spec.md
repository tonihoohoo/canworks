## MODIFIED Requirements

### Requirement: Trace in the command-line client
`openplc-canopen-diag trace` SHALL record a trace from the runtime into a file, with options for the output file and format, duration, capture filters, error frames and a trigger with pre- and post-trigger time. It SHALL print the frame count, the frame rate and any lost or dropped frames when it ends, and SHALL stop on Ctrl-C and still write the file. `openplc-canopen-diag convert IN OUT` SHALL convert a trace file between the supported formats. `openplc-canopen-diag explain --trace FILE --index N` SHALL explain one frame of a trace file as the `canopen-frame-explain` capability describes.

#### Scenario: Record to ASC for ten seconds
- **WHEN** a user runs `openplc-canopen-diag --runtime plc.local trace --duration 10 -o run.asc`
- **THEN** the command writes a Vector ASC file of ten seconds of bus traffic and prints the count, rate and losses

#### Scenario: Interrupted
- **WHEN** the user presses Ctrl-C during `openplc-canopen-diag trace -o run.pcapng`
- **THEN** the frames recorded so far are written to run.pcapng and the command exits with status 0

#### Scenario: Convert
- **WHEN** a user runs `openplc-canopen-diag convert run.log run.blf`
- **THEN** a BLF file with the same frames, times and directions is written

#### Scenario: Explain a frame of a trace file
- **WHEN** a user runs `openplc-canopen-diag explain --trace run.pcapng --index 120 --config canopen.json`
- **THEN** frame 120 of the file is explained with the SDO context of the trace and the bit rate from the file
