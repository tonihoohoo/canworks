## MODIFIED Requirements

### Requirement: Function blocks section
The Modbus bridge page of a bridge config and of an OpenPLC config SHALL have a **Function blocks** section with a switch and, while on, the number of request mailboxes (0-4), the receive mailbox on or off with its receive blocks (1 or 2), the number of cyclic jobs (0-16), network info on or off and the input and output areas with Suggest, writing `bridge.mailboxes`. Turning it on SHALL place both areas in free ranges. The section SHALL show the registers the blocks take and, for OpenPLC, the requests per poll of the whole map against the budget of 40, the expected receive rate with the receive mailbox on ("about N CAN frames/s at this poll": the CAN records per batch times the poll rate, halved), and SHALL say which blocks need which part (for example "CAN_RECEIVE, J1939_RECEIVE and CO_RECV_EMCY" for the receive mailbox). For OpenPLC a count change SHALL move both areas to free ranges at once, and the section SHALL say that the editor project needs **Update declarations** and a new Build. **New config…** for OpenPLC and a switch to OpenPLC SHALL start with the section on, one request mailbox, the receive mailbox, 4 cyclic jobs and network info.

#### Scenario: Turn on the receive mailbox
- **WHEN** the user turns on the receive mailbox of an OpenPLC config
- **THEN** the areas move to free ranges, the register and request counts grow, and the page says to run Update declarations and build again

#### Scenario: New OpenPLC config
- **WHEN** the user creates a new OpenPLC config
- **THEN** its Function blocks section is on with one request mailbox, the receive mailbox, 4 cyclic jobs and network info

#### Scenario: Second receive block
- **WHEN** the user sets receive blocks to 2 in an OpenPLC config with a 10 ms poll
- **THEN** the areas move to free ranges, the register and request counts grow by 120 registers and one request, and the expected rate reads about 1050 CAN frames/s
