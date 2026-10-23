(*
 * CO_SDO_WRITE_STRING: writes VALUE (its characters, up to 254, without a
 * NUL) to object INDEX:SUBINDEX of node NODE (1..127) of CANopen master
 * network NETWORK.
 * A rising edge of EXECUTE starts it; BUSY until the bridge has an answer,
 * then DONE or ERROR with ERROR_ID (docs/plc-library.md#sdo-blocks): 1 the
 * node aborted (ABORT_CODE), 2 no answer within TIMEOUT (T#0s: 5 s), 4 the
 * network is not running, 5 too many SDO requests wait, 6 invalid input,
 * 7 too large, 8 cancelled, 20 the bridge is not reachable, 22 the config
 * has no request mailbox.
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD); the block
 * uses a request mailbox of the bridge (`mailboxes` in the config, see
 * CW_LINK_SERVICE for the words). Instances share the request mailboxes in
 * the order they started.
 *)
FUNCTION_BLOCK CO_SDO_WRITE_STRING
VAR_INPUT
  EXECUTE : BOOL;
  NETWORK : USINT;
  NODE : USINT;
  INDEX : UINT;
  SUBINDEX : USINT;
  TIMEOUT : TIME;
  VALUE : STRING;
END_VAR
VAR_OUTPUT
  BUSY : BOOL;
  DONE : BOOL;
  ERROR : BOOL;
  ERROR_ID : UINT;
  ABORT_CODE : UDINT;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR
  x : CW_SDO_XFER;
  buf : ARRAY[0..1023] OF BYTE;
  prev : BOOL;
  nchars : INT;
  i : INT;
END_VAR
  IF EXECUTE AND NOT prev AND NOT x.BUSY THEN
    nchars := LEN(VALUE);
    IF nchars > 254 THEN
      nchars := 254;
    END_IF;
    FOR i := 1 TO nchars DO
      buf[i - 1] := CW_CHAR_CODE(MID(VALUE, 1, i));
    END_FOR;
  END_IF;
  prev := EXECUTE;
  x(EXECUTE := EXECUTE, WRITE := TRUE, NETWORK := NETWORK, NODE := NODE, INDEX := INDEX, SUBINDEX := SUBINDEX,
    TIMEOUT := TIMEOUT, KIND := 2, LENGTH := INT_TO_UINT(nchars), LINK := LINK, DATA := buf);
  BUSY := x.BUSY;
  DONE := x.DONE;
  ERROR := x.ERROR;
  ERROR_ID := x.ERROR_ID;
  ABORT_CODE := x.ABORT_CODE;
END_FUNCTION_BLOCK
