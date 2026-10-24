## ADDED Requirements

### Requirement: Mailbox reads only while in use
The config node SHALL read the request mailboxes' response blocks only while a job holds a request mailbox and for one poll after it ends, the receive mailbox only while a receiver is open or closing, and the cyclic job table only while a cyclic job runs. It SHALL read network info and every other input range on every poll. When a part turns busy, the config node SHALL read it once before the job's first write to it, so the job's counter follows what the bridge holds.

#### Scenario: Idle flow
- **WHEN** a flow with **canworks in**, a **canworks sdo** node and a **canworks can receive** node runs on the example bridge config with the default mailboxes and no job or receiver is active
- **THEN** the config node's polls read no request response block, no receive mailbox and no cyclic job table

#### Scenario: First job after idle
- **WHEN** the **canworks sdo** node then reads 0x1008:0 of node 5 as `string`
- **THEN** it ends with `done` and the device name, at most one poll later than with every range read on every poll
