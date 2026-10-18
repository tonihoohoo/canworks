## MODIFIED Requirements

### Requirement: Shipped examples swept in the browser
The page tests SHALL open each shipped example (`examples/virtual-plant`, `examples/j1939`, `examples/pdo-link`) and visit every view of every network, failing on a console error, an uncaught page error, an HTTP error answer, a clipped control or sideways scrolling, or a decoding note. The existing all-views layout test SHALL run at two widths instead of three, so the configurator page jobs' summed time does not grow.

#### Scenario: Overflow in an example
- **WHEN** a change makes the gateway routes table clip a route name at 1280 px
- **THEN** the sweep fails naming the example, network, view and the clipped field
