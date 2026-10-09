(*
 * CAN_GET_BITS: a signal's raw value from a frame's data (spec
 * can-plc-frames, "ST helper functions"). Bit numbering as DBC files use it:
 * little-endian (Intel, MOTOROLA FALSE) signals start at their least
 * significant bit, big-endian (Motorola) signals at their most significant
 * bit, bit 0 being the least significant bit of byte 0. BIT_LENGTH 1..64; SIGNED sign-extends.
 * Bits outside the 8 bytes read as 0.
 *)
FUNCTION CAN_GET_BITS : LINT
VAR_IN_OUT
  DATA : ARRAY[0..7] OF BYTE;
END_VAR
VAR_INPUT
  START_BIT : USINT;
  BIT_LENGTH : USINT;
  MOTOROLA : BOOL;
  SIGNED : BOOL;
END_VAR
VAR
  i : INT;
  pos : INT;
  bitv : LWORD;
  v : LWORD;
END_VAR
  v := 0;
  pos := USINT_TO_INT(START_BIT);
  FOR i := 0 TO USINT_TO_INT(BIT_LENGTH) - 1 DO
    IF pos >= 0 AND pos < 64 THEN
      bitv := BYTE_TO_LWORD(SHR(DATA[pos / 8], INT_TO_UINT(pos MOD 8)) AND 16#01);
    ELSE
      bitv := 0;
    END_IF;
    IF MOTOROLA THEN
      v := SHL(v, 1) OR bitv;
      IF pos MOD 8 = 0 THEN
        pos := pos + 15;
      ELSE
        pos := pos - 1;
      END_IF;
    ELSE
      v := v OR SHL(bitv, INT_TO_UINT(i));
      pos := pos + 1;
    END_IF;
  END_FOR;
  IF SIGNED AND BIT_LENGTH > 0 AND BIT_LENGTH < 64 THEN
    IF (SHR(v, USINT_TO_UINT(BIT_LENGTH) - 1) AND 16#01) = 1 THEN
      v := v OR SHL(LWORD#16#FFFFFFFFFFFFFFFF, USINT_TO_UINT(BIT_LENGTH));
    END_IF;
  END_IF;
  CAN_GET_BITS := LWORD_TO_LINT(v);
END_FUNCTION
