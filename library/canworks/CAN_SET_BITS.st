(*
 * CAN_SET_BITS: writes a signal's raw value into a frame's data, with the bit
 * numbering of CAN_GET_BITS; the other bits stay as they are. Returns TRUE,
 * or FALSE (and writes nothing) when a bit would fall outside the 8 bytes.
 *)
FUNCTION CAN_SET_BITS : BOOL
VAR_IN_OUT
  DATA : ARRAY[0..7] OF BYTE;
END_VAR
VAR_INPUT
  START_BIT : USINT;
  BIT_LENGTH : USINT;
  MOTOROLA : BOOL;
  VALUE : LINT;
END_VAR
VAR
  i : INT;
  pos : INT;
  shift : INT;
  v : LWORD;
  b : BYTE;
END_VAR
  (* First pass: every bit inside the frame? *)
  pos := USINT_TO_INT(START_BIT);
  FOR i := 0 TO USINT_TO_INT(BIT_LENGTH) - 1 DO
    IF pos < 0 OR pos > 63 THEN
      CAN_SET_BITS := FALSE;
      RETURN;
    END_IF;
    IF MOTOROLA THEN
      IF pos MOD 8 = 0 THEN
        pos := pos + 15;
      ELSE
        pos := pos - 1;
      END_IF;
    ELSE
      pos := pos + 1;
    END_IF;
  END_FOR;
  v := LINT_TO_LWORD(VALUE);
  pos := USINT_TO_INT(START_BIT);
  FOR i := 0 TO USINT_TO_INT(BIT_LENGTH) - 1 DO
    IF MOTOROLA THEN
      shift := USINT_TO_INT(BIT_LENGTH) - 1 - i;
    ELSE
      shift := i;
    END_IF;
    b := SHL(BYTE#1, INT_TO_UINT(pos MOD 8));
    IF (SHR(v, INT_TO_UINT(shift)) AND 16#01) = 1 THEN
      DATA[pos / 8] := DATA[pos / 8] OR b;
    ELSE
      DATA[pos / 8] := DATA[pos / 8] AND NOT b;
    END_IF;
    IF MOTOROLA THEN
      IF pos MOD 8 = 0 THEN
        pos := pos + 15;
      ELSE
        pos := pos - 1;
      END_IF;
    ELSE
      pos := pos + 1;
    END_IF;
  END_FOR;
  CAN_SET_BITS := TRUE;
END_FUNCTION
