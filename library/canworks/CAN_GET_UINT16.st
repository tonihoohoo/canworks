(*
 * CAN_GET_UINT16: the 16-bit unsigned value in DATA[OFFSET..OFFSET+1],
 * least significant byte first, or most significant first with MOTOROLA.
 * 0 when the bytes do not fit in the frame.
 *)
FUNCTION CAN_GET_UINT16 : UINT
VAR_IN_OUT
  DATA : ARRAY[0..7] OF BYTE;
END_VAR
VAR_INPUT
  OFFSET : USINT;
  MOTOROLA : BOOL;
END_VAR
VAR
  i : INT;
  v : WORD;
END_VAR
  v := 0;
  IF USINT_TO_INT(OFFSET) + 2 <= 8 THEN
    FOR i := 0 TO 1 DO
      IF MOTOROLA THEN
        v := SHL(v, 8) OR BYTE_TO_WORD(DATA[USINT_TO_INT(OFFSET) + i]);
      ELSE
        v := v OR SHL(BYTE_TO_WORD(DATA[USINT_TO_INT(OFFSET) + i]), INT_TO_UINT(8 * i));
      END_IF;
    END_FOR;
  END_IF;
  CAN_GET_UINT16 := WORD_TO_UINT(v);
END_FUNCTION
