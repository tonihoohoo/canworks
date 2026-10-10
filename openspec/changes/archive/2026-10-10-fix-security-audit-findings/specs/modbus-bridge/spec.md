## MODIFIED Requirements

### Requirement: Clients and access
The bridge SHALL listen on `listen` and accept at most `max_clients` connections (default 16) and at most `max_clients_per_address` connections from one address (default 4), closing further ones at accept with a log line; when all slots are taken and a client whose address is in `writers` connects, the bridge SHALL close the oldest connection from an address not in `writers` to make room. A client whose address is not in `readers` (when set) SHALL be disconnected at accept. `writers` SHALL be required: a bridge config without it SHALL be refused, and `["0.0.0.0/0", "::/0"]` SHALL be the way to let every address write. A write from a client not in `writers` SHALL get exception 0x01 and change nothing. An entry of `readers` or `writers` that cannot be parsed SHALL stop the bridge from starting. The bridge SHALL answer requests for `unit_id` (default 1), 0 and 255, and SHALL answer other unit IDs with exception 0x0B. It SHALL support functions 1, 2, 3, 4, 5, 6, 15, 16, 23 and 8 (loopback), answer other functions with exception 0x01, and answer addresses outside the image or counts over 125 registers read, 123 registers written or 2000 bits with exception 0x02 or 0x03. A connection that has sent no complete request for 60 s SHALL be closed, and a connection holding an incomplete request for 5 s SHALL be closed. The bridge SHALL hold at most 8 KB of unsent replies per connection, SHALL NOT read further requests from a connection while it is over that, and SHALL close a connection that stays over it for 10 s.

#### Scenario: Write from a reader
- **WHEN** `writers` is `["10.0.0.20"]` and a client at 10.0.0.30 writes a holding register
- **THEN** it gets exception 0x01 and the output image is unchanged

#### Scenario: Config without writers
- **WHEN** a bridge config has no `writers`
- **THEN** the bridge refuses to start, naming `writers` and how to allow every address

#### Scenario: Read past the image
- **WHEN** the input image is 40 bytes and a client reads input registers 18 to 21
- **THEN** it gets exception 0x02

#### Scenario: Client that never reads its replies
- **WHEN** a client sends read requests without pause and never reads its socket
- **THEN** the bridge's memory stays bounded, other clients keep being served, and the client is disconnected after 10 s

#### Scenario: Slots full when the controller reconnects
- **WHEN** 16 connections from readers fill every slot and the writer at 10.0.0.20 connects
- **THEN** the oldest reader connection is closed and the writer is served

## ADDED Requirements

### Requirement: Stop clears the output image
With `on_client_loss: "stop"`, entering outputs off SHALL set every output location of the image to 0 without sending it, so the write that ends outputs off starts from zeros and not from the values written before the loss.

#### Scenario: One coil after a loss
- **WHEN** outputs were off after a loss with `"stop"`, and a writer then writes one coil
- **THEN** that coil's output is sent with its new value and every other output is sent as 0

### Requirement: Bridge service limits
The systemd unit that `install-bridge.sh` writes SHALL limit the bridge's memory and number of tasks, so a fault in the bridge cannot use up the device's memory.

#### Scenario: Installed unit
- **WHEN** `install-bridge.sh` installs instance `line1`
- **THEN** `systemctl show canworks-bridge@line1` reports a memory limit and a task limit
