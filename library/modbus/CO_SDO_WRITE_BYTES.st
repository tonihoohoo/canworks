(*
 * CO_SDO_WRITE_BYTES: writes the first SIZE bytes of BUFFER (up to 1024) to
 * object INDEX:SUBINDEX of node NODE (1..127) of CANopen master network
 * NETWORK, in one SDO download.
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
FUNCTION_BLOCK CO_SDO_WRITE_BYTES
VAR_INPUT
  EXECUTE : BOOL;
  NETWORK : USINT;
  NODE : USINT;
  INDEX : UINT;
  SUBINDEX : USINT;
  TIMEOUT : TIME;
  SIZE : UINT;
END_VAR
VAR_OUTPUT
  BUSY : BOOL;
  DONE : BOOL;
  ERROR : BOOL;
  ERROR_ID : UINT;
  ABORT_CODE : UDINT;
END_VAR
VAR_IN_OUT
  BUFFER : ARRAY[0..1023] OF BYTE;
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR
  x : CW_SDO_XFER;
END_VAR
  x(EXECUTE := EXECUTE, WRITE := TRUE, NETWORK := NETWORK, NODE := NODE, INDEX := INDEX, SUBINDEX := SUBINDEX,
    TIMEOUT := TIMEOUT, KIND := 3, LENGTH := SIZE, LINK := LINK, DATA := BUFFER);
  BUSY := x.BUSY;
  DONE := x.DONE;
  ERROR := x.ERROR;
  ERROR_ID := x.ERROR_ID;
  ABORT_CODE := x.ABORT_CODE;
END_FUNCTION_BLOCK
