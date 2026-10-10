## ADDED Requirements

### Requirement: Connections handed to the CiA 309-3 gateway
The diagnostics channel SHALL offer the `cia309` op to logged-in connections (canopen-cia309-gateway). Once it is answered successfully, the connection SHALL carry no further JSON requests, SHALL keep its TLS session, SHALL be served by the CiA 309-3 gateway and SHALL no longer count towards the 4 diagnostics connections. Its SDO, NMT and LSS requests SHALL take the same bus-thread path, ordering, guards and log lines as the diagnostics channel's own requests, with the gateway's `allow_changes` and `allow_force` in place of the diagnostics `allow_changes` and the request's `force`. The login answer SHALL say whether the gateway is configured (`cia309: true`).

#### Scenario: Diagnostics slot freed
- **WHEN** four diagnostics clients are connected and one of them switches to the CiA 309-3 gateway
- **THEN** a new diagnostics client can connect and log in

#### Scenario: Diagnostics changes off, gateway changes on
- **WHEN** `diagnostics.allow_changes` is false, `cia309.allow_changes` is true, and a switched connection writes an object of a PRE-OPERATIONAL node
- **THEN** the write is carried out and logged as coming from the CiA 309-3 gateway with the client's address

### Requirement: Gateway command in the command-line client
`canworks-diag` SHALL offer `gateway` as the canopen-cia309-gateway capability describes, and `status` SHALL print the gateway's listen address and its open sessions (address, plain or tunnelled, commands served) when the runtime has one.

#### Scenario: Status shows sessions
- **WHEN** one tool is connected through `canworks-diag gateway` and `canworks-diag status` runs
- **THEN** the output has a CiA 309-3 gateway line with one tunnelled session and its address
