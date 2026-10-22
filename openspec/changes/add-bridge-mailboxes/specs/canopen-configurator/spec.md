## ADDED Requirements

### Requirement: Function blocks section
The Project page of a bridge config and of an OpenPLC config SHALL have a **Function blocks** section with a switch and, while on, the number of request mailboxes (1-4), the receive mailbox on or off, the number of cyclic jobs (0-16) and network info on or off, writing `bridge.mailboxes`. The section SHALL show the registers the blocks take and the requests per poll of the whole map against the budget of 40, and SHALL say which blocks need which part (for example "CAN_RECEIVE, J1939_RECEIVE and CO_RECV_EMCY need the receive mailbox"). A change in the section SHALL show that the editor project needs **Update declarations** and a new Build. **New config…** for OpenPLC SHALL start with the section on, one request mailbox, the receive mailbox, 4 cyclic jobs and network info.

#### Scenario: Turn on the receive mailbox
- **WHEN** the user turns on the receive mailbox of an OpenPLC config
- **THEN** the register and request counts grow, and the page says to run Update declarations and build again

#### Scenario: New OpenPLC config
- **WHEN** the user creates a new OpenPLC config
- **THEN** its Function blocks section is on with one request mailbox, the receive mailbox, 4 cyclic jobs and network info
