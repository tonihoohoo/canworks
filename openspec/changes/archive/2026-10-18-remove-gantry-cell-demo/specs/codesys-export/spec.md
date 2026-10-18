## MODIFIED Requirements

### Requirement: Script runs on IronPython 2.7 and CPython 3
`import_canworks.py` SHALL use only the CODESYS scripting API and the Python standard library, in syntax both IronPython 2.7 and CPython 3 accept, so CI runs it under CPython against a stand-in for the CODESYS API.

#### Scenario: CI
- **WHEN** CI runs the script under CPython 3 with the stand-in API and the virtual-plant plan
- **THEN** it creates the recorded tree and settings and reports no error
