(*
 * CAN_J1939_PGN: the PGN of a 29-bit J1939 identifier; for a PDU1 PGN (PF
 * below 240) the destination byte is cleared.
 *)
FUNCTION CAN_J1939_PGN : UDINT
VAR_INPUT
  ID : UDINT;
END_VAR
VAR
  p : UDINT;
END_VAR
  p := SHR(ID, 8) AND 16#3FFFF;
  IF (SHR(p, 8) AND 16#FF) < 240 THEN
    p := p AND 16#3FF00;
  END_IF;
  CAN_J1939_PGN := p;
END_FUNCTION
