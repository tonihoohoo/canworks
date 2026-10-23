## MODIFIED Requirements

### Requirement: Adapter server
`canworks-diag adapter-serve --adapter TYPE:CHANNEL --bitrate KBIT [--port P] [--bind ADDR] [--allow-changes]` SHALL serve the CAN adapter with the diagnostics protocol on port P (default 7536) of ADDR (default all addresses): TLS with a certificate made at start, and the SCRAM-SHA-256 login bound to it, as the bridge's diagnostics channel. After login it SHALL answer the operations of a local adapter (status, SDO, NMT, scan, LSS, trace, raw frames, PDO test, SYNC) with the same results and refusals. The bit rate SHALL be the one given; the server SHALL never guess it.

#### Scenario: Commission from the PC
- **WHEN** the server runs on a Linux machine with `--adapter socketcan:can0 --bitrate 500 --allow-changes` and a PC connects with the right token and allows changes
- **THEN** the PC can scan, read and write SDOs, and change a node ID with LSS on the machine's bus, with the same results as with a USB adapter on the PC

#### Scenario: Plain connection refused
- **WHEN** a client connects without TLS
- **THEN** the server closes the connection and nothing reaches the bus
