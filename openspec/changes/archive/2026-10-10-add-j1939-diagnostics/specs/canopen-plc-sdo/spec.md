## MODIFIED Requirements

### Requirement: Library delivery
The library SHALL be built from its editor library project in this repository into `canworks.stlib`. It SHALL hold the SDO blocks, the CiA 402 blocks, the CAN frame blocks and helper functions of `can-plc-frames`, and the J1939 trouble code blocks and functions of `j1939-plc-diagnostics`. Each `deploy-v` release SHALL carry that file, `canworks-deploy library --out DIR` SHALL write the copy that matches the installed tools into `DIR`, `canworks-deploy library --install` SHALL install that copy into OpenPLC Editor on the same computer as the editor's Library Manager does, and `canworks-deploy library --project DIR` SHALL enable it in an editor project. The library's version SHALL equal the deploy package version. Installing it once with the editor's Library Manager ("install from file") SHALL make the blocks appear in the editor's library tree for every project that enables it.

#### Scenario: Install in the editor
- **WHEN** the user runs `canworks-deploy library --out .` and installs the written file in OpenPLC Editor 4.3.2
- **THEN** the library tree lists `canworks` with the `CO_SDO_*`, `CO402_*`, `CAN_*` and `J1939_*` blocks, and a project that enables it and calls `CO_SDO_READ`, `CAN_RECEIVE` and `J1939_DM_READ` builds for OpenPLC Runtime v4

#### Scenario: Install from the command line
- **WHEN** the user runs `canworks-deploy library --install` on a PC where OpenPLC Editor has run, then restarts the editor
- **THEN** the editor's library list shows `canworks` with the tools' version, and libraries installed before are still listed
