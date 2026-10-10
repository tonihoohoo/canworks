## MODIFIED Requirements

### Requirement: Signals
Each signal SHALL have `name`, `start_bit`, `length` 1..64 and `iec_location`, and MAY have `byte_order` (`little` default, or `big`), `signed`, `scale`, `offset`, `unit`, `valid_location`, `multiplexer` and `mux` (`can-multiplexed-signals`). A switch of a `tx` entry with `pages` `all` or `rotate` SHALL have no `iec_location`. The IEC location size SHALL hold the length (X for 1 bit, B up to 8, W up to 16, D up to 32, L up to 64). Signals of one message that can be active in the same frame SHALL NOT overlap. RX signals SHALL use `%I` and TX signals `%Q`.

#### Scenario: Location too small
- **WHEN** a 16-bit signal maps `%IB10`
- **THEN** the file is rejected naming the signal, its length and the location

#### Scenario: Overlap on different pages
- **WHEN** two signals of PGN 65280 use bits 8-23, one with `mux.values` [1] and one with [2] on the same switch
- **THEN** the file loads
