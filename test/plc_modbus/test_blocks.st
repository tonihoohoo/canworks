(*
 * The canworks blocks over the bridge (library/modbus) against the bridge
 * model. LINK word 21 holds the flags: 16#0001 the bridge answers, 16#0002
 * a control block, 16#0004 SDO registers, 16#0100 << n a live list for
 * network n. Run by test/plc_modbus/run.sh.
 *)
TEST 'SDO read through the bridge registers'
  VAR
    link : ARRAY[0..88] OF WORD;
    bridge : BridgeModel;
    rd : CO_SDO_READ;
  END_VAR
  link[21] := 16#0005;
  rd(EXECUTE := TRUE, NODE := 5, INDEX := 16#1018, SUBINDEX := 1, LINK := link);
  ASSERT_TRUE(rd.BUSY);
  ASSERT_EQ(link[8], 16#0100);
  ASSERT_EQ(link[9], 16#0501);
  ASSERT_EQ(link[10], 16#1018);
  bridge(LINK := link);
  link := bridge.LINK;
  rd(EXECUTE := TRUE, NODE := 5, INDEX := 16#1018, SUBINDEX := 1, LINK := link);
  ASSERT_TRUE(rd.DONE);
  ASSERT_FALSE(rd.BUSY);
  ASSERT_EQ(rd.DATA, 16#12345605);
  ASSERT_EQ(link[23], 0);
  rd(EXECUTE := TRUE, NODE := 5, INDEX := 16#1018, SUBINDEX := 1, LINK := link);
  ASSERT_TRUE(rd.DONE);
  rd(EXECUTE := FALSE, NODE := 5, INDEX := 16#1018, SUBINDEX := 1, LINK := link);
  ASSERT_FALSE(rd.DONE);
END_TEST

TEST 'two instances in one scan share the SDO registers'
  VAR
    link : ARRAY[0..88] OF WORD;
    bridge : BridgeModel;
    r1 : CO_SDO_READ;
    r2 : CO_SDO_READ;
    i : INT;
  END_VAR
  link[21] := 16#0005;
  r1(EXECUTE := TRUE, NODE := 5, INDEX := 16#1000, LINK := link);
  r2(EXECUTE := TRUE, NODE := 6, INDEX := 16#1000, LINK := link);
  ASSERT_TRUE(r2.BUSY);
  ASSERT_EQ(link[23], r1.me);
  bridge(LINK := link);
  link := bridge.LINK;
  FOR i := 1 TO 5 DO
    r1(EXECUTE := TRUE, NODE := 5, INDEX := 16#1000, LINK := link);
    r2(EXECUTE := TRUE, NODE := 6, INDEX := 16#1000, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(r1.DONE);
  ASSERT_TRUE(r2.DONE);
  ASSERT_EQ(r1.DATA, 16#12345605);
  ASSERT_EQ(r2.DATA, 16#12345606);
  ASSERT_EQ(bridge.REQUESTS, 2);
END_TEST

TEST 'SDO write sends the value and size'
  VAR
    link : ARRAY[0..88] OF WORD;
    bridge : BridgeModel;
    wr : CO_SDO_WRITE;
  END_VAR
  link[21] := 16#0005;
  wr(EXECUTE := TRUE, NODE := 7, INDEX := 16#2000, SUBINDEX := 3, DATA := 16#AABBCCDD, SIZE := 4, LINK := link);
  bridge(LINK := link);
  link := bridge.LINK;
  wr(EXECUTE := TRUE, NODE := 7, INDEX := 16#2000, SUBINDEX := 3, DATA := 16#AABBCCDD, SIZE := 4, LINK := link);
  ASSERT_TRUE(wr.DONE);
  ASSERT_EQ(bridge.WRITTEN, 16#AABBCCDD);
  ASSERT_EQ(bridge.WRITTEN_SIZE, 4);
END_TEST

TEST 'bridge not reachable ends at once with 20'
  VAR
    link : ARRAY[0..88] OF WORD;
    rd : CO_SDO_READ;
    nmt : CO_NMT;
  END_VAR
  link[21] := 16#0006;
  rd(EXECUTE := TRUE, NODE := 5, LINK := link);
  ASSERT_TRUE(rd.ERROR);
  ASSERT_FALSE(rd.BUSY);
  ASSERT_EQ(rd.ERROR_ID, 20);
  nmt(EXECUTE := TRUE, NODE := 5, COMMAND := 1, LINK := link);
  ASSERT_EQ(nmt.ERROR_ID, 20);
END_TEST

TEST 'link lost while busy ends with 20 and frees the registers'
  VAR
    link : ARRAY[0..88] OF WORD;
    bridge : BridgeModel;
    rd : CO_SDO_READ;
  END_VAR
  link[21] := 16#0005;
  bridge.SILENT_NODE := 9;
  rd(EXECUTE := TRUE, NODE := 9, LINK := link);
  bridge(LINK := link);
  link := bridge.LINK;
  link[21] := 16#0004;
  rd(EXECUTE := TRUE, NODE := 9, LINK := link);
  ASSERT_EQ(rd.ERROR_ID, 20);
  ASSERT_EQ(link[23], 0);
END_TEST

TEST 'writes not allowed by the config end with 21'
  VAR
    link : ARRAY[0..88] OF WORD;
    bridge : BridgeModel;
    wr : CO_SDO_WRITE;
  END_VAR
  link[21] := 16#0005;
  bridge.ALLOW_WRITE := FALSE;
  wr(EXECUTE := TRUE, NODE := 7, INDEX := 16#2000, DATA := 1, SIZE := 1, LINK := link);
  bridge(LINK := link);
  link := bridge.LINK;
  wr(EXECUTE := TRUE, NODE := 7, INDEX := 16#2000, DATA := 1, SIZE := 1, LINK := link);
  ASSERT_TRUE(wr.ERROR);
  ASSERT_EQ(wr.ERROR_ID, 21);
  ASSERT_EQ(wr.ABORT_CODE, 16#08000020);
END_TEST

TEST 'node abort ends with 1 and the abort code'
  VAR
    link : ARRAY[0..88] OF WORD;
    bridge : BridgeModel;
    rd : CO_SDO_READ;
  END_VAR
  link[21] := 16#0005;
  rd(EXECUTE := TRUE, NODE := 98, INDEX := 16#6000, LINK := link);
  bridge(LINK := link);
  link := bridge.LINK;
  rd(EXECUTE := TRUE, NODE := 98, INDEX := 16#6000, LINK := link);
  ASSERT_EQ(rd.ERROR_ID, 1);
  ASSERT_EQ(rd.ABORT_CODE, 16#06020000);
END_TEST

TEST 'no answer within TIMEOUT ends with 2'
  VAR
    link : ARRAY[0..88] OF WORD;
    bridge : BridgeModel;
    rd : CO_SDO_READ;
  END_VAR
  link[21] := 16#0005;
  bridge.SILENT_NODE := 9;
  rd(EXECUTE := TRUE, NODE := 9, TIMEOUT := T#100ms, LINK := link);
  bridge(LINK := link);
  link := bridge.LINK;
  ADVANCE_TIME(T#40ms);
  rd(EXECUTE := TRUE, NODE := 9, TIMEOUT := T#100ms, LINK := link);
  bridge(LINK := link);
  link := bridge.LINK;
  ADVANCE_TIME(T#40ms);
  rd(EXECUTE := TRUE, NODE := 9, TIMEOUT := T#100ms, LINK := link);
  ASSERT_TRUE(rd.BUSY);
  ADVANCE_TIME(T#40ms);
  rd(EXECUTE := TRUE, NODE := 9, TIMEOUT := T#100ms, LINK := link);
  ASSERT_TRUE(rd.ERROR);
  ASSERT_EQ(rd.ERROR_ID, 2);
  ASSERT_EQ(link[23], 0);
END_TEST

TEST 'invalid input and missing registers'
  VAR
    link : ARRAY[0..88] OF WORD;
    rd : CO_SDO_READ;
    wr : CO_SDO_WRITE;
    nmt : CO_NMT;
  END_VAR
  link[21] := 16#0001;
  rd(EXECUTE := TRUE, NODE := 5, LINK := link);
  ASSERT_EQ(rd.ERROR_ID, 22);
  nmt(EXECUTE := TRUE, NODE := 5, COMMAND := 1, LINK := link);
  ASSERT_EQ(nmt.ERROR_ID, 22);
  link[21] := 16#0007;
  wr(EXECUTE := TRUE, NODE := 5, SIZE := 5, LINK := link);
  ASSERT_EQ(wr.ERROR_ID, 6);
  nmt(EXECUTE := FALSE, LINK := link);
  nmt(EXECUTE := TRUE, NODE := 5, COMMAND := 3, LINK := link);
  ASSERT_EQ(nmt.ERROR_ID, 6);
END_TEST

TEST 'NMT through the control block'
  VAR
    link : ARRAY[0..88] OF WORD;
    bridge : BridgeModel;
    nmt : CO_NMT;
  END_VAR
  link[21] := 16#0003;
  nmt(EXECUTE := TRUE, NODE := 5, COMMAND := 2, LINK := link);
  ASSERT_TRUE(nmt.BUSY);
  bridge(LINK := link);
  link := bridge.LINK;
  nmt(EXECUTE := TRUE, NODE := 5, COMMAND := 2, LINK := link);
  ASSERT_TRUE(nmt.DONE);
  ASSERT_EQ(bridge.LAST_CMD, 4);
  ASSERT_EQ(bridge.LAST_NODE, 5);
  ASSERT_EQ(link[22], 0);
  nmt(EXECUTE := FALSE, LINK := link);
  bridge.REFUSE := TRUE;
  nmt(EXECUTE := TRUE, NODE := 0, COMMAND := 128, LINK := link);
  bridge(LINK := link);
  link := bridge.LINK;
  nmt(EXECUTE := TRUE, NODE := 0, COMMAND := 128, LINK := link);
  ASSERT_EQ(nmt.ERROR_ID, 5);
  ASSERT_EQ(bridge.LAST_CMD, 5);
  ASSERT_EQ(bridge.CONTROLS, 2);
END_TEST

TEST 'node live from the live list'
  VAR
    link : ARRAY[0..88] OF WORD;
    live : CO_NODE_LIVE;
  END_VAR
  link[21] := 16#0201;
  link[33] := 16#2002;
  live(NETWORK := 1, NODE := 5, LINK := link);
  ASSERT_TRUE(live.LIVE);
  live(NETWORK := 1, NODE := 9, LINK := link);
  ASSERT_TRUE(live.LIVE);
  live(NETWORK := 1, NODE := 6, LINK := link);
  ASSERT_FALSE(live.LIVE);
  live(NETWORK := 0, NODE := 5, LINK := link);
  ASSERT_FALSE(live.LIVE);
  link[21] := 16#0200;
  live(NETWORK := 1, NODE := 5, LINK := link);
  ASSERT_FALSE(live.LIVE);
END_TEST

TEST 'REAL and LREAL bit patterns'
  ASSERT_EQ(CW_REAL_TO_DWORD(1.0), DWORD#16#3F800000);
  ASSERT_EQ(CW_REAL_TO_DWORD(-2.5), DWORD#16#C0200000);
  ASSERT_EQ(CW_REAL_TO_DWORD(0.1), DWORD#16#3DCCCCCD);
  ASSERT_EQ(CW_REAL_TO_DWORD(0.0), DWORD#0);
  ASSERT_NEAR(CW_DWORD_TO_REAL(DWORD#16#40490FDB), 3.14159265, 0.000001);
  ASSERT_EQ(CW_REAL_TO_DWORD(CW_DWORD_TO_REAL(DWORD#16#00000001)), DWORD#16#00000001);
  ASSERT_EQ(CW_REAL_TO_DWORD(CW_DWORD_TO_REAL(DWORD#16#7F7FFFFF)), DWORD#16#7F7FFFFF);
  ASSERT_EQ(CW_REAL_TO_DWORD(CW_DWORD_TO_REAL(DWORD#16#C2F6E979)), DWORD#16#C2F6E979);
  ASSERT_EQ(CW_LREAL_TO_LWORD(-2.5), LWORD#16#C004000000000000);
  ASSERT_EQ(CW_LREAL_TO_LWORD(0.1), LWORD#16#3FB999999999999A);
  ASSERT_EQ(CW_LREAL_TO_LWORD(CW_LWORD_TO_LREAL(LWORD#16#0000000000000001)), LWORD#16#0000000000000001);
  ASSERT_EQ(CW_LREAL_TO_LWORD(CW_LWORD_TO_LREAL(LWORD#16#7FEFFFFFFFFFFFFF)), LWORD#16#7FEFFFFFFFFFFFFF);
  ASSERT_NEAR(CW_LWORD_TO_LREAL(LWORD#16#400921FB54442D18), 3.141592653589793, 0.000000000001);
END_TEST
