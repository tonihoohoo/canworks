(*
 * J1939_SEND: sends LENGTH bytes of DATA (0..1785; more than 8 by the
 * transport protocol, BAM to 255) as PGN to DESTINATION with PRIORITY (0: 6)
 * on J1939 network NETWORK. A rising edge of EXECUTE starts it; BUSY until the bridge has
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
FUNCTION_BLOCK J1939_SEND
VAR_INPUT
  EXECUTE : BOOL;
  NETWORK : USINT;
  PGN : UDINT;
  DESTINATION : USINT;
  PRIORITY : USINT;
  LENGTH : UINT;
  TIMEOUT : TIME;
END_VAR
VAR_IN_OUT
  DATA : ARRAY[0..1784] OF BYTE;
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
  prio : USINT;
END_VAR
  ms := DWORD_TO_UDINT(TIME_TO_DWORD(TIMEOUT));
  IF ms > 65535 THEN
    ms := 65535;
  END_IF;
  IF EXECUTE AND NOT prev AND NOT x.BUSY THEN
    refused := 0;
    IF LENGTH > 1785 OR PRIORITY > 7 THEN
      refused := 3;
    END_IF;
  ELSIF NOT EXECUTE THEN
    refused := 0;
  END_IF;
  prev := EXECUTE;
  prio := PRIORITY;
  IF prio = 0 THEN
    prio := 6;
  END_IF;
  x(EXECUTE := EXECUTE AND refused = 0, OP := 11, NET := NETWORK, A0 := DWORD_TO_WORD(SHR(UDINT_TO_DWORD(PGN), 16)),
    A1 := UDINT_TO_WORD(PGN), A2 := SHL(USINT_TO_WORD(DESTINATION), 8) OR USINT_TO_WORD(prio),
    A3 := UINT_TO_WORD(LENGTH), A4 := UDINT_TO_WORD(ms), A5 := WORD#0, LENGTH := LENGTH, FETCH_MAX := 0, LINK := LINK,
    DATA := DATA);
  BUSY := x.BUSY;
  DONE := x.DONE;
  ERROR := x.ERROR OR refused <> 0;
  ERROR_ID := SEL(refused <> 0, x.ERROR_ID, refused);
END_FUNCTION_BLOCK
