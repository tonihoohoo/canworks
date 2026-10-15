(*
 * J1939_SET_BITS: writes a signal's raw value into a J1939 message of any
 * length, little-endian with the bit numbering of J1939_GET_BITS; the other
 * bits stay as they are. Returns TRUE, or FALSE (and writes nothing) when a
 * bit would fall outside the 1785 bytes or BIT_LENGTH is not 1..64.
 *)
FUNCTION J1939_SET_BITS : BOOL
VAR_IN_OUT
  DATA : ARRAY[0..1784] OF BYTE;
END_VAR
VAR_INPUT
  START_BIT : UINT;
  BIT_LENGTH : USINT;
  VALUE : LINT;
END_VAR
VAR
  i : DINT;
  pos : DINT;
  v : LWORD;
  b : BYTE;
END_VAR
  IF BIT_LENGTH = 0 OR BIT_LENGTH > 64 OR UINT_TO_DINT(START_BIT) + USINT_TO_DINT(BIT_LENGTH) > 14280 THEN
    J1939_SET_BITS := FALSE;
    RETURN;
  END_IF;
  v := LINT_TO_LWORD(VALUE);
  pos := UINT_TO_DINT(START_BIT);
  FOR i := 0 TO USINT_TO_DINT(BIT_LENGTH) - 1 DO
    b := SHL(BYTE#1, DINT_TO_UINT(pos MOD 8));
    IF (SHR(v, DINT_TO_UINT(i)) AND 16#01) = 1 THEN
      DATA[pos / 8] := DATA[pos / 8] OR b;
    ELSE
      DATA[pos / 8] := DATA[pos / 8] AND NOT b;
    END_IF;
    pos := pos + 1;
  END_FOR;
  J1939_SET_BITS := TRUE;
END_FUNCTION
