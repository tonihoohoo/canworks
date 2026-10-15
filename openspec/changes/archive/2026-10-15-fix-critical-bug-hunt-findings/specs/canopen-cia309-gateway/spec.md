## MODIFIED Requirements

### Requirement: Session limits
The gateway SHALL serve at most `max_clients` sessions (plain and tunnelled together) and SHALL answer a further plain connection with one `ERROR: 102` line and close it. A session SHALL have at most 8 commands outstanding, answered in the order sent; a further command SHALL be answered `ERROR: 102`. A line longer than 16 KiB SHALL close the session. A session whose first line (blank lines and comments aside) is not a CiA 309-3 command, for example an HTTP request line, SHALL be answered with one `ERROR: 101` line and closed before any later line is read; a later line that does not parse SHALL keep today's `ERROR: 101` answer and the session. The same SHALL apply to sessions accepted by the PC forwarder of `canworks-diag gateway --listen`, before anything is forwarded. A plain session that sends no line for `cia309.idle_timeout_s` seconds (default 300, 0 for no limit) SHALL be closed. A command the bus thread has not answered within the session's command timeout (default 5 s, `set command_timeout`) SHALL be answered `ERROR: 103`. Every SDO download, NMT and LSS command carried out SHALL be logged with the client's address, marked as coming from the CiA 309-3 gateway.

#### Scenario: Pipelined commands
- **WHEN** a client sends 10 read commands without waiting
- **THEN** it receives answers to the first 8 in order and `ERROR: 102` for the 9th and 10th

#### Scenario: Browser request to the gateway port
- **WHEN** a local web page posts to the gateway port, so the first line is `POST / HTTP/1.1` and a valid write command follows in the body
- **THEN** the session gets one `ERROR: 101` and is closed, and no SDO download is sent

#### Scenario: Idle session
- **WHEN** a plain session sends nothing for 300 s
- **THEN** the gateway closes it and its slot is free
