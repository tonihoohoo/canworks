## ADDED Requirements

### Requirement: Limits on unpaired connections
The link service SHALL accept at most 8 connections from PCs that are not paired, and at most 2 from one address. A pairing attempt SHALL count against the pairing rate limit before the login exchange starts, so attempts made at the same time cannot get past it. The service SHALL run with a memory limit.

#### Scenario: Many unpaired connections
- **WHEN** a host opens 20 connections without pairing
- **THEN** the service keeps 2 of them, refuses the rest, and paired PCs still connect

### Requirement: Discovery answers from the asked host
When the PC tools ask a known host directly, they SHALL accept an answer only from that host's address. An answer that gives a paired runtime a different link ID SHALL NOT replace the remembered one; the tools SHALL report the change and need `--repair` to pair again.

#### Scenario: Forged answer
- **WHEN** another host answers a direct discovery query for a paired runtime with a different link ID
- **THEN** the answer is ignored and the remembered link ID stays

#### Scenario: Runtime reinstalled
- **WHEN** the paired runtime itself answers with a new link ID after a reinstall
- **THEN** the tools say the runtime's identity changed and that `--repair` pairs it again
