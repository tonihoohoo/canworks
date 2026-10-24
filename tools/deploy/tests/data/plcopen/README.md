# PLCopen test data

- `tc6_xml_v201.xsd`: the PLCopen TC6 XML schema 2.01, as shipped in the
  MIT-licensed `plcopen` Python package 1.0.1 (PyPI). `test_plcopen.py` checks
  every export against it. The generic files use the schema's
  namespace `tc6_0201`; the CODESYS library file uses `tc6_0200` (the one
  CODESYS reads), mapped to `tc6_0201` for the check: the two versions
  describe the same elements.
- `generic/`: golden files of `--export-plcopen` for the
  OpenPLC Modbus example turned into a PLC link config (`test_plcopen.py`,
  `UPDATE_GOLDEN=1` rewrites them), without the library.
