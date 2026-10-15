(*
 * J1939_GET_BITS: a signal's raw value from a J1939 message of any length
 * (spec j1939-plc-blocks, "J1939 ST functions"). J1939 sends signals
 * little-endian: START_BIT is the least significant bit, bit 0 being the
 * least significant bit of byte 0. BIT_LENGTH 1..64; SIGNED sign-extends.
 * Bits outside the 1785 bytes read as 0.
 *)
FUNCTION J1939_GET_BITS : LINT
VAR_IN_OUT
  DATA : ARRAY[0..1784] OF BYTE;
END_VAR
VAR_INPUT
  START_BIT : UINT;
  BIT_LENGTH : USINT;
  SIGNED : BOOL;
END_VAR
VAR
  i : DINT;
  pos : DINT;
  bitv : LWORD;
  v : LWORD;
END_VAR
  v := 0;
  pos := UINT_TO_DINT(START_BIT);
  FOR i := 0 TO USINT_TO_DINT(BIT_LENGTH) - 1 DO
    IF i < 64 AND pos < 14280 THEN
      bitv := BYTE_TO_LWORD(SHR(DATA[pos / 8], DINT_TO_UINT(pos MOD 8)) AND 16#01);
      v := v OR SHL(bitv, DINT_TO_UINT(i));
    END_IF;
    pos := pos + 1;
  END_FOR;
  IF SIGNED AND BIT_LENGTH > 0 AND BIT_LENGTH < 64 THEN
    IF (SHR(v, USINT_TO_UINT(BIT_LENGTH) - 1) AND 16#01) = 1 THEN
      v := v OR SHL(LWORD#16#FFFFFFFFFFFFFFFF, USINT_TO_UINT(BIT_LENGTH));
    END_IF;
  END_IF;
  J1939_GET_BITS := LWORD_TO_LINT(v);
END_FUNCTION
