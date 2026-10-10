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
  SPN := DTC AND 16#7FFFF;
  FMI := UDINT_TO_USINT(SHR(DTC, 19) AND 16#1F);
  OC := UDINT_TO_USINT(SHR(DTC, 24) AND 16#7F);
  CM := (DTC AND 16#80000000) <> 0;
END_FUNCTION_BLOCK
