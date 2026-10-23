(*
 * J1939_DTC_SPLIT: the parts of a trouble code as the J1939 blocks and the
 * diagnostics.rx locations give it (spec j1939-plc-diagnostics):
 * DTC = SPN + FMI * 2^19 + OC * 2^24 + CM * 2^31.
 *)
FUNCTION_BLOCK J1939_DTC_SPLIT
VAR_INPUT
  DTC : UDINT;
END_VAR
VAR_OUTPUT
  SPN : UDINT;
  FMI : USINT;
  OC : USINT;
  CM : BOOL;
END_VAR
VAR
  d : DWORD;
END_VAR
  d := UDINT_TO_DWORD(DTC);
  SPN := DWORD_TO_UDINT(d AND DWORD#16#7FFFF);
  FMI := DWORD_TO_USINT(SHR(d, 19) AND DWORD#16#1F);
  OC := DWORD_TO_USINT(SHR(d, 24) AND DWORD#16#7F);
  CM := (d AND DWORD#16#80000000) <> DWORD#0;
END_FUNCTION_BLOCK
