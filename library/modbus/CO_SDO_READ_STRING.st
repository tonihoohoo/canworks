(*
 * CO_SDO_READ_STRING: reads object INDEX:SUBINDEX (a VISIBLE_STRING, up to
 * 254 characters before its first NUL) of node NODE (1..127) of CANopen
 * master network NETWORK into VALUE.
 * A rising edge of EXECUTE starts it; BUSY until the bridge has an answer,
 * then DONE or ERROR with ERROR_ID (docs/plc-library.md#sdo-blocks): 1 the
 * node aborted (ABORT_CODE), 2 no answer within TIMEOUT (T#0s: 5 s), 4 the
 * network is not running, 5 too many SDO requests wait, 6 invalid input,
 * 7 too large (more than 254 characters), 8 cancelled, 20 the bridge is not reachable, 22 the config
 * has no request mailbox.
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD); the block
 * uses a request mailbox of the bridge (`mailboxes` in the config, see
 * CW_LINK_SERVICE for the words). Instances share the request mailboxes in
 * the order they started.
 *)
FUNCTION_BLOCK CO_SDO_READ_STRING
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
  VALUE : STRING;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR
  x : CW_SDO_XFER;
  buf : ARRAY[0..1023] OF BYTE;
  was : BOOL;
  bad : BOOL;
  nchars : INT;
  i : INT;
END_VAR
  x(EXECUTE := EXECUTE, WRITE := FALSE, NETWORK := NETWORK, NODE := NODE, INDEX := INDEX, SUBINDEX := SUBINDEX,
    TIMEOUT := TIMEOUT, KIND := 2, MAX_SIZE := 16#FFFFFFFF, FETCH_MAX := 255, LINK := LINK, DATA := buf);
  BUSY := x.BUSY;
  DONE := x.DONE;
  ERROR := x.ERROR;
  ERROR_ID := x.ERROR_ID;
  ABORT_CODE := x.ABORT_CODE;
  IF x.DONE AND NOT was THEN
    nchars := UINT_TO_INT(x.GOT);
    FOR i := UINT_TO_INT(x.GOT) - 1 TO 0 BY -1 DO
      IF buf[i] = BYTE#0 THEN
        nchars := i;
      END_IF;
    END_FOR;
    bad := nchars > 254;
    IF NOT bad THEN
      VALUE := '';
      FOR i := 0 TO nchars - 1 DO
        VALUE := CONCAT(VALUE, CW_CHAR(buf[i]));
      END_FOR;
    END_IF;
  END_IF;
  was := x.DONE;
  IF x.DONE AND bad THEN
    DONE := FALSE;
    ERROR := TRUE;
    ERROR_ID := 7;
  END_IF;
END_FUNCTION_BLOCK
