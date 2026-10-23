(*
 * J1939_DM_CLEAR: clears the trouble codes of ECU DESTINATION (255: every
 * ECU) on J1939 network NETWORK: the previously active ones (DM3,
 * PREVIOUS_ONLY) or the active and previously active ones (DM11). A rising edge of EXECUTE starts it; BUSY until the bridge has
 * an answer, then DONE or ERROR with ERROR_ID (docs/plc-library.md#j1939-blocks):
 * 1 the network is not running, 2 no such network, 3 invalid input,
 * 4 the network sends that PGN itself, 5 another DM2 read or clear for that
 * address is pending, 6 no answer within TIMEOUT, 7 the bus is off,
 * 8 cancelled, 9 no free job or receiver, 10 not a J1939 network, 11 the
 * network holds no address, 12 the destination answered NACK, 13 no DM1
 * from that source, 14 the transfer was aborted, 20 the bridge is not
 * reachable, 22 the config has no request mailbox.
 *)
(*
 * LINK is the generated `canworks.link` (ARRAY[0..1279] OF WORD); the block uses a request mailbox of the bridge (`mailboxes` in the config); instances share
 * them in the order they started (see
 * CW_LINK_SERVICE for the words).
 *)
FUNCTION_BLOCK J1939_DM_CLEAR
VAR_INPUT
  EXECUTE : BOOL;
  NETWORK : USINT;
  DESTINATION : USINT;
  PREVIOUS_ONLY : BOOL;
  TIMEOUT : TIME;
END_VAR
VAR_IN_OUT
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
  prev : BOOL;
  refused : UINT;
  ms : UDINT;
  buf : ARRAY[0..1784] OF BYTE;
END_VAR
  ms := TIME_TO_UDINT(TIMEOUT);
  IF ms > 65535 THEN
    ms := 65535;
  END_IF;
  IF EXECUTE AND NOT prev AND NOT x.BUSY THEN
    refused := 0;
    IF DESTINATION = 254 THEN
      refused := 3;
    END_IF;
  ELSIF NOT EXECUTE THEN
    refused := 0;
  END_IF;
  prev := EXECUTE;
  x(EXECUTE := EXECUTE AND refused = 0, OP := 14, NET := NETWORK, A0 := USINT_TO_WORD(DESTINATION),
    A1 := SEL(PREVIOUS_ONLY, WORD#0, WORD#1), A2 := UDINT_TO_WORD(ms), A3 := 0, A4 := 0, A5 := 0, LENGTH := 0,
    FETCH_MAX := 0, LINK := LINK, DATA := buf);
  BUSY := x.BUSY;
  DONE := x.DONE;
  ERROR := x.ERROR OR refused <> 0;
  ERROR_ID := SEL(refused <> 0, x.ERROR_ID, refused);
END_FUNCTION_BLOCK
