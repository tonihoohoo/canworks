## ADDED Requirements

### Requirement: Messages name the adapter machine
Errors that an adapter server reports about its own adapter or interface SHALL reach the PC worded for the adapter machine and naming its host, never as if the PC were missing something. `canworks-diag trace` through an adapter server SHALL report the server's kernel drops as dropped by the adapter machine's kernel.

#### Scenario: Interface missing on the server
- **WHEN** the server was started with `--adapter socketcan:slcan0`, `slcan0` does not exist on its machine, and a PC connects with `--adapter remote:linuxbox`
- **THEN** the PC's error says there is no CAN interface slcan0 on the adapter machine linuxbox, and does not say "on this PC"

#### Scenario: Trace summary through a server
- **WHEN** the user runs `canworks-diag --adapter remote:linuxbox trace` and the server's kernel dropped frames
- **THEN** the summary line says the frames were dropped by the adapter machine's kernel, and does not mention a PLC

### Requirement: Server stop in the log
`canworks-diag adapter-serve` SHALL log one line when it stops, saying whether SIGTERM or Ctrl-C stopped it and how many PCs were connected, before it exits.

#### Scenario: Service stopped
- **WHEN** the adapter server runs as a service and the service is stopped
- **THEN** the service's log ends with a line saying the server stopped on SIGTERM and how many PCs were connected
