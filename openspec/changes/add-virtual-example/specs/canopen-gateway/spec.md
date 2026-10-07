## ADDED Requirements

### Requirement: Upper master stand-in on a simulated bus
A master network of the gateway's config whose simulated interface is that of the upper slave network SHALL be treated as a stand-in for the upper master, not as a field network: it SHALL have no place in the field node status, no route SHALL name it as its field network, and EMCYs from its nodes SHALL NOT be forwarded to the upper network. The plugin and the deploy tool's check SHALL apply the same rule, and a route to the stand-in SHALL be rejected with an error saying it stands in for the upper master. The stand-in SHALL configure, start and supervise the gateway's slave node as any master does.

#### Scenario: Stand-in drives the gateway
- **WHEN** a config has field network `io` on `sim0`, upper slave network `cell` on `sim2` (node 20) and master network `host` on `sim2` with node 20 not simulated
- **THEN** `host` brings node 20 OPERATIONAL, the routes between `cell` and `io` run, the field node status lists only `io`'s nodes, and no warning names `host` as a status network

#### Scenario: Gateway EMCY not echoed
- **WHEN** the program sends an EMCY on the slave network and the stand-in receives it
- **THEN** the stand-in logs it once, and the gateway does not forward it up again

#### Scenario: Route to the stand-in
- **WHEN** a route's field end names network `host`
- **THEN** the config is rejected with an error saying `host` shares the upper network's simulated bus and stands in for the upper master
