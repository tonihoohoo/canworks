## ADDED Requirements

### Requirement: Raw message status
The status answer SHALL hold, for each network with raw messages or program frame blocks: per receive message its name, identifier, counter, milliseconds since the last match, timed-out state, short-frame count and last data; per send message its name, identifier, sent count, last error and whether it overrides a protocol identifier; the numbers of open program receivers and cyclic jobs, frames dropped by receivers, program frames sent, and whether sends are confirmed by echo or by write. A plain network's status SHALL hold its bus state and counters like any network.

#### Scenario: Status of a plain network
- **WHEN** a client asks for the status of a plain network with one receive message that arrived 20 ms ago
- **THEN** the answer has that message with its counter, age about 20 ms and timed-out false

### Requirement: Raw send messages in the frame guard
The identifiers of a network's raw send messages SHALL be part of the map the `send_frame` guard checks, named as "raw message <name>", so sending one by hand needs `force`.

#### Scenario: Hand-sent frame on a raw message identifier
- **WHEN** raw send message `Lamps` uses 0x501 and a client sends 0x501 without `force`
- **THEN** the request is refused with "0x501 is raw message Lamps; force needed"

### Requirement: Replay a trace
The channel SHALL offer `replay`, which takes frames with times relative to the first, in batches of up to 500 frames, and sends them onto the request's network with their spacing, once or in a loop, and `replay_stop` and `replay_status`. A replay SHALL have the guards of `send_frame` (`allow_changes`, and `force` when a frame's identifier is in the guard map or a node is OPERATIONAL), SHALL be refused on a listen-only network, SHALL be limited to one per network and 1000 frames per second, and SHALL end on `replay_stop`, at the end of the frames, when its client disconnects or after 10 minutes, with its start and end logged with the client's address. `canworks-diag replay FILE` SHALL replay a candump log, `.asc`, `.trc`, pcapng or canworks trace file through the channel, or onto a USB adapter on the PC with `--adapter`, with `--rate N` (evenly spaced at N frames per second instead of the recorded spacing, at most 1000), `--loop`, `--network` and `--force`.

#### Scenario: Replay a recorded machine bus
- **WHEN** an engineer with `allow_changes` replays a 30 s trace of a plain network
- **THEN** the frames go out with their recorded spacing, the raw receive messages update as when it was recorded, and the log names the client and the number of frames sent

#### Scenario: Replay too fast
- **WHEN** a replay's frames hold more than 1000 frames within one second, or `--rate` asks for more than 1000 frames per second
- **THEN** the request is refused naming the 1000 frames per second limit, and nothing is sent
