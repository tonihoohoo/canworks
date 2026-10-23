(*
 * CO_SDO_READ_REAL: reads object INDEX:SUBINDEX (REAL32 or REAL64) of node
 * NODE (1..127) of CANopen master network NETWORK into VALUE.
 * A rising edge of EXECUTE starts it; BUSY until the bridge has an answer,
 * then DONE or ERROR with ERROR_ID (docs/plc-library.md#sdo-blocks): 1 the
 * node aborted (ABORT_CODE), 2 no answer within TIMEOUT (T#0s: 5 s), 4 the
 * network is not running, 5 too many SDO requests wait, 6 invalid input,
 * 7 too large (a reply that is not 4 or 8 bytes), 8 cancelled, 20 the bridge is not reachable, 22 the config
 * has no request mailbox.
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD); the block
 * uses a request mailbox of the bridge (`mailboxes` in the config, see
 * CW_LINK_SERVICE for the words). Instances share the request mailboxes in
 * the order they started.
 *)
FUNCTION_BLOCK CO_SDO_READ_REAL
VAR_INPUT
  EXECUTE : BOOL;
  NETWORK : USINT;
  NODE : USINT;
  INDEX : UINT;
  SUBINDEX : USINT;
  TIMEOUT : TIME;
END_VAR
VAR_OUTPUT
  BUSY : BOOL;
  DONE : BOOL;
  ERROR : BOOL;
  ERROR_ID : UINT;
  ABORT_CODE : UDINT;
  VALUE : LREAL;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR
  x : CW_SDO_XFER;
  buf : ARRAY[0..1023] OF BYTE;
  was : BOOL;
  bad : BOOL;
  bits : LWORD;
  i : INT;
END_VAR
  x(EXECUTE := EXECUTE, WRITE := FALSE, NETWORK := NETWORK, NODE := NODE, INDEX := INDEX, SUBINDEX := SUBINDEX,
    TIMEOUT := TIMEOUT, KIND := 1, MAX_SIZE := 8, FETCH_MAX := 8, LINK := LINK, DATA := buf);
  BUSY := x.BUSY;
  DONE := x.DONE;
  ERROR := x.ERROR;
  ERROR_ID := x.ERROR_ID;
  ABORT_CODE := x.ABORT_CODE;
  IF x.DONE AND NOT was THEN
    bad := x.RSIZE <> 4 AND x.RSIZE <> 8;
    IF NOT bad THEN
      bits := 0;
      FOR i := UDINT_TO_INT(x.RSIZE) - 1 TO 0 BY -1 DO
        bits := SHL(bits, 8) OR BYTE_TO_LWORD(buf[i]);
      END_FOR;
      IF x.RSIZE = 4 THEN
        VALUE := REAL_TO_LREAL(CW_DWORD_TO_REAL(LWORD_TO_DWORD(bits)));
      ELSE
        VALUE := CW_LWORD_TO_LREAL(bits);
      END_IF;
    END_IF;
  END_IF;
  was := x.DONE;
  IF x.DONE AND bad THEN
    DONE := FALSE;
    ERROR := TRUE;
    ERROR_ID := 7;
  END_IF;
END_FUNCTION_BLOCK
