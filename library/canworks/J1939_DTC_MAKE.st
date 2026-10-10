(*
 * J1939_DTC_MAKE: a trouble code as the J1939 blocks give it (spec
 * j1939-plc-diagnostics): SPN + FMI * 2^19 + OC * 2^24, the conversion
 * method bit clear. Each part is cut to its width (SPN 19 bits, FMI 5, OC 7).
 *)
FUNCTION J1939_DTC_MAKE : UDINT
VAR_INPUT
  SPN : UDINT;
  FMI : USINT;
  OC : USINT;
END_VAR
  J1939_DTC_MAKE := (SPN AND 16#7FFFF) OR SHL(USINT_TO_UDINT(FMI) AND 16#1F, 19)
                    OR SHL(USINT_TO_UDINT(OC) AND 16#7F, 24);
END_FUNCTION
