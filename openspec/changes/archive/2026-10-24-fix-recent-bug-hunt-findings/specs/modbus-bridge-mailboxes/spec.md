## ADDED Requirements

### Requirement: Request baseline from the client's words
A request mailbox SHALL take its baseline (the counter that is not run) from the first request words a client writes after the bridge starts, not from the image before any write. Until the client has written them the mailbox SHALL answer nothing.

#### Scenario: Stale request after a restart
- **WHEN** the bridge restarts while a client keeps writing a request block with counter 7 for an SDO read, together with the PLC link header
- **THEN** the response shows counter 7 ended with ERROR_ID 8 and no SDO request is sent, and the client's next counter 8 runs

### Requirement: Idle ends the program's resources
When the control block sets idle, the bridge SHALL end the program's receivers, cyclic jobs and running mailbox operations with ERROR_ID 8 as it does on PLC stop, and SHALL log the reason as idle. It SHALL NOT report a missing keepalive for a client that kept writing them.

#### Scenario: Idle with a cyclic job
- **WHEN** a client with an open receiver and a running cyclic job sends idle and keeps writing keepalives
- **THEN** the job and the receiver end with ERROR_ID 8, the log says they ended because of idle, and no "stopped calling" warning is logged

### Requirement: Cancel drops queued work
An SDO or CAN send operation that ends with ERROR_ID 8 while it still waits in its queue SHALL be dropped and never sent. One already sent SHALL finish with its result discarded.

#### Scenario: Watchdog while an SDO write waits
- **WHEN** the watchdog fires while a mailbox SDO write waits behind another SDO transfer to the same node
- **THEN** the write ends with ERROR_ID 8 and never goes out on the bus

### Requirement: Receive and cyclic jobs need a request mailbox
A config with `receive` true or `cyclic_jobs` above 0 and `requests` 0 SHALL be refused by the PC tools and the bridge with a message that opening a receiver or a job needs a request mailbox.

#### Scenario: No request mailbox
- **WHEN** a config has `"mailboxes": {"requests": 0, "receive": true}`
- **THEN** both checks refuse it naming `requests`

### Requirement: Info reads count as mailbox use
Reads of the network info block or the cyclic job table SHALL count as mailbox use in the status and in diag, so diag SHALL NOT advise turning off the mailboxes for a client that reads them.

#### Scenario: Only CAN_BUS_INFO
- **WHEN** a program reads only the network info block for a minute and `canworks-diag status` runs
- **THEN** the mailbox line does not say that nothing used the mailboxes

### Requirement: Network restart ends its resources
When a CANopen network's session restarts, the bridge SHALL end that network's mailbox operations, receivers and cyclic jobs with ERROR_ID 8 and leave other networks' resources running.

#### Scenario: Interface bounce
- **WHEN** network io's interface goes down and up while a receiver on io and one on motion are open
- **THEN** the io receiver ends with ERROR_ID 8 and the motion receiver keeps delivering
