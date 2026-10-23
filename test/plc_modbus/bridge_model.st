(*
 * The bridge's control block and SDO registers for the block tests
 * (test/plc_modbus/run.sh), working on the blocks' LINK words directly
 * (library/modbus: 0-3 status, 4-6 control, 7-13 SDO request, 14-20 SDO
 * response): one call is one Modbus poll round. Mirrors ControlBlock and
 * SdoBridgeRegisters in plugin/src/bridge/bridge_blocks.cpp: a request runs
 * when its counter changes, the response echoes the counter. A read answers
 * 16#123456nn (nn the node); SILENT_NODE stays busy, ABORT_NODE aborts with
 * 16#06020000, writes without ALLOW_WRITE abort with 16#08000020;
 * RESTARTED answers as a bridge that just started with the request in place
 * (control result 6, SDO abort 16#08000021).
 * STruC++'s test runner does not copy a source block's in-out back, so a
 * test writes `link := bridge.LINK;` after each call.
 *)
FUNCTION_BLOCK BridgeModel
VAR_INPUT
  ALLOW_WRITE : BOOL := TRUE;
  SILENT_NODE : USINT := 99;
  ABORT_NODE : USINT := 98;
  REFUSE : BOOL;
  RESTARTED : BOOL;
END_VAR
VAR_OUTPUT
  LAST_CMD : WORD;
  LAST_NET : WORD;
  LAST_NODE : WORD;
  WRITTEN : UDINT;
  WRITTEN_SIZE : WORD;
  REQUESTS : INT;
  CONTROLS : INT;
END_VAR
VAR_IN_OUT
  LINK : ARRAY[0..1279] OF WORD;
END_VAR
VAR
  cmd : WORD;
  node : WORD;
END_VAR
  IF LINK[4] <> LINK[2] THEN
    LINK[2] := LINK[4];
    CONTROLS := CONTROLS + 1;
    LAST_CMD := SHR(LINK[5], 8);
    LAST_NET := LINK[5] AND 16#00FF;
    LAST_NODE := SHR(LINK[6], 8);
    IF RESTARTED THEN
      LINK[3] := 16#0600;
    ELSIF REFUSE THEN
      LINK[3] := 16#0500;
    ELSIF LAST_NET > 0 THEN
      LINK[3] := 16#0200;
    ELSE
      LINK[3] := 0;
    END_IF;
  END_IF;
  IF LINK[7] <> LINK[14] THEN
    LINK[14] := LINK[7];
    REQUESTS := REQUESTS + 1;
    cmd := SHR(LINK[8], 8);
    node := SHR(LINK[9], 8);
    LINK[16] := 0;
    LINK[17] := 0;
    LINK[18] := 0;
    LINK[19] := 0;
    IF RESTARTED THEN
      LINK[15] := 16#0300;
      LINK[16] := 16#0800;
      LINK[17] := 16#0021;
    ELSIF cmd = 2 AND NOT ALLOW_WRITE THEN
      LINK[15] := 16#0300;
      LINK[16] := 16#0800;
      LINK[17] := 16#0020;
    ELSIF node = USINT_TO_WORD(SILENT_NODE) THEN
      LINK[15] := 16#0100;
    ELSIF node = USINT_TO_WORD(ABORT_NODE) THEN
      LINK[15] := 16#0300;
      LINK[16] := 16#0602;
    ELSE
      LINK[15] := 16#0200;
      IF cmd = 1 THEN
        LINK[18] := 16#1234;
        LINK[19] := 16#5600 OR node;
      ELSE
        WRITTEN := DWORD_TO_UDINT(SHL(WORD_TO_DWORD(LINK[12]), 16) OR WORD_TO_DWORD(LINK[13]));
        WRITTEN_SIZE := SHR(LINK[11], 8);
      END_IF;
    END_IF;
  END_IF;
END_FUNCTION_BLOCK
