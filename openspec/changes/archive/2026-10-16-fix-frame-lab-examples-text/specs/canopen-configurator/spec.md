## MODIFIED Requirements

### Requirement: Frame lab layout
The Frame lab SHALL put the frame box (frame, Explain, bit rate) at the top, with tabs **Examples**, **Build** and **Arbitration** under it. Only the chosen tab's panel SHALL show, and the choice SHALL be kept for the page session. At 1280 px and wider, the result SHALL show in a column beside the input and SHALL stay in view while the page scrolls. In narrower windows the result SHALL show under the frame box, before the tabs. The Examples tab SHALL group the frames by network and node, and SHALL show the example frames every time it is shown, including after switching from another tab and after coming back to the Frame lab.

#### Scenario: Wide result beside the input
- **WHEN** the window is 1440 by 900 px and the user picks node 5's EMCY example
- **THEN** the result's meaning, identifier and data bits show beside the examples without scrolling the page

#### Scenario: Narrow result under the frame box
- **WHEN** the window is 1000 by 800 px and the user builds an SDO read
- **THEN** the result's meaning is inside the window without scrolling

#### Scenario: Arbitration result in the result column
- **WHEN** the user runs the arbitration demo at 1440 px
- **THEN** the demo's diagram and text show in the result column

#### Scenario: Examples after switching tabs
- **WHEN** the examples have loaded and the user picks Build, then Examples again
- **THEN** the Examples tab shows the example frames grouped by network and node, and no text such as `[object HTMLDivElement]`

#### Scenario: Examples in Commission a device after coming back
- **WHEN** in Commission a device the user opens the Frame lab, goes to the Nodes tab and back to the Frame lab
- **THEN** the Examples tab shows the example frames
