(*
 * CAN_SEND: sends one CAN frame (ID, EXTENDED, RTR, DLC 0..8 bytes of DATA)
 * on network NETWORK. A rising edge of EXECUTE starts it; BUSY until the
 * bridge has sent it, then DONE or ERROR with ERROR_ID
 * (docs/plc-library.md#frame-blocks): 1 the network is not running, 2 no
 * such network, 3 invalid input, 5 too many frames wait, 6 not sent within
 * TIMEOUT (T#0s: 1 s), 7 the bus is off, 8 cancelled, 20 the bridge is not
 * reachable, 22 the config has no request mailbox.
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD); the block uses a request mailbox of the bridge (`mailboxes` in the config); instances share
 * them in the order they started (see
 * CW_LINK_SERVICE for the words).
 *)
FUNCTION_BLOCK CAN_SEND
VAR_INPUT
  EXECUTE : BOOL;
  NETWORK : USINT;
  ID : UDINT;
  EXTENDED : BOOL;
  RTR : BOOL;
  DLC : USINT;
  TIMEOUT : TIME;
END_VAR
VAR_IN_OUT
  DATA : ARRAY[0..7] OF BYTE;
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR_OUTPUT
  BUSY : BOOL;
  DONE : BOOL;
  ERROR : BOOL;
  ERROR_ID : UINT;
END_VAR
VAR
  x : CW_REQUEST;
  buf : ARRAY[0..1784] OF BYTE;
  prev : BOOL;
  refused : UINT;
  flags : WORD;
  ms : UDINT;
  i : INT;
END_VAR
  IF EXECUTE AND NOT prev AND NOT x.BUSY THEN
    refused := 0;
    IF DLC > 8 THEN
      refused := 3;
    END_IF;
    FOR i := 0 TO 7 DO
      buf[i] := DATA[i];
    END_FOR;
  ELSIF NOT EXECUTE THEN
    refused := 0;
  END_IF;
  prev := EXECUTE;
  flags := SEL(EXTENDED, WORD#0, WORD#1) OR SEL(RTR, WORD#0, WORD#2);
  ms := DWORD_TO_UDINT(TIME_TO_DWORD(TIMEOUT));
  IF ms > 65535 THEN
    ms := 65535;
  END_IF;
  x(EXECUTE := EXECUTE AND refused = 0, OP := 5, NET := NETWORK, A0 := DWORD_TO_WORD(SHR(UDINT_TO_DWORD(ID), 16)),
    A1 := UDINT_TO_WORD(ID), A2 := SHL(flags, 8) OR USINT_TO_WORD(DLC), A3 := UDINT_TO_WORD(ms), A4 := WORD#0, A5 := WORD#0,
    LENGTH := 8, FETCH_MAX := 0, LINK := LINK, DATA := buf);
  BUSY := x.BUSY;
  DONE := x.DONE;
  ERROR := x.ERROR OR refused <> 0;
  ERROR_ID := SEL(refused <> 0, x.ERROR_ID, refused);
END_FUNCTION_BLOCK
