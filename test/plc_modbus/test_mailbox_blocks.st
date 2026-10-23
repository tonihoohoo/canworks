(*
 * The canworks blocks over the bridge's mailboxes (library/modbus) against
 * the mailbox model. A scan: CW_LINK_SERVICE, the blocks, then one model
 * round (one Modbus poll). LINK word 21 bit 0: the bridge answers; word 89:
 * the mailbox flags (16#0431: one request mailbox, the receive mailbox,
 * network info, 4 cyclic jobs). Run by test/plc_modbus/run.sh.
 *)
TEST 'link service counts scans, moves tickets and frees a forgotten mailbox'
  VAR
    link : ARRAY[0..1279] OF WORD;
    svc : CW_LINK_SERVICE;
    i : INT;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  link[92] := 7;
  link[94] := 5;
  link[98] := 0;
  svc(LINK := link);
  ASSERT_EQ(link[90], 1);
  ASSERT_EQ(link[93], 7);
  ASSERT_EQ(link[92], 0);
  FOR i := 1 TO 100 DO
    svc(LINK := link);
  END_FOR;
  ASSERT_EQ(link[94], 0);
  (* a new batch: acknowledged, its receivers pending *)
  link[720] := 16#4321;
  link[721] := 16#0001;
  link[722] := 16#0004;
  svc(LINK := link);
  ASSERT_EQ(link[102], 16#4321);
  ASSERT_EQ(link[103], 16#0001);
  ASSERT_EQ(link[104], 16#0004);
  (* bridge gone: requests and acknowledgement cleared *)
  link[21] := 0;
  link[145] := 16#0500;
  link[94] := 3;
  svc(LINK := link);
  ASSERT_EQ(link[145], 0);
  ASSERT_EQ(link[94], 0);
  ASSERT_EQ(link[102], 0);
END_TEST

TEST 'three senders share one mailbox in call order'
  VAR
    link : ARRAY[0..1279] OF WORD;
    svc : CW_LINK_SERVICE;
    bridge : MailboxModel;
    s1 : CAN_SEND;
    s2 : CAN_SEND;
    s3 : CAN_SEND;
    d : ARRAY[0..7] OF BYTE;
    i : INT;
    first2 : INT;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  d[0] := 16#11;
  FOR i := 1 TO 12 DO
    svc(LINK := link);
    s1(EXECUTE := TRUE, ID := 16#101, DLC := 1, DATA := d, LINK := link);
    s2(EXECUTE := TRUE, ID := 16#102, DLC := 1, DATA := d, LINK := link);
    s3(EXECUTE := TRUE, ID := 16#103, DLC := 1, DATA := d, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
    IF bridge.TX_COUNT = 2 AND first2 = 0 THEN
      first2 := i;
      ASSERT_EQ(bridge.TX_ID, 16#102);
    END_IF;
  END_FOR;
  ASSERT_TRUE(s1.DONE);
  ASSERT_TRUE(s2.DONE);
  ASSERT_TRUE(s3.DONE);
  ASSERT_EQ(bridge.TX_COUNT, 3);
  ASSERT_EQ(bridge.TX_ID, 16#103);
  ASSERT_EQ(bridge.TX_B0, 16#11);
  ASSERT_EQ(link[94], 0);
END_TEST

TEST 'without mailboxes or bridge the blocks end in the same call'
  VAR
    link : ARRAY[0..1279] OF WORD;
    s : CAN_SEND;
    rd : CO_SDO_READ_STRING;
    rx : CAN_RECEIVE;
    info : CAN_BUS_INFO;
    d : ARRAY[0..7] OF BYTE;
  END_VAR
  link[21] := 1;
  s(EXECUTE := TRUE, ID := 1, DLC := 0, DATA := d, LINK := link);
  ASSERT_TRUE(s.ERROR);
  ASSERT_EQ(s.ERROR_ID, 22);
  rd(EXECUTE := TRUE, NODE := 5, INDEX := 16#1008, LINK := link);
  ASSERT_EQ(rd.ERROR_ID, 22);
  rx(ENABLE := TRUE, ID := 1, RX_DATA := d, LINK := link);
  ASSERT_EQ(rx.ERROR_ID, 22);
  info(NETWORK := 0, LINK := link);
  ASSERT_EQ(info.ERROR_ID, 22);
  link[21] := 0;
  link[89] := 16#0431;
  s(EXECUTE := FALSE, DATA := d, LINK := link);
  s(EXECUTE := TRUE, ID := 1, DLC := 9, DATA := d, LINK := link);
  ASSERT_EQ(s.ERROR_ID, 3);
  s(EXECUTE := FALSE, DATA := d, LINK := link);
  s(EXECUTE := TRUE, ID := 1, DLC := 0, DATA := d, LINK := link);
  ASSERT_EQ(s.ERROR_ID, 20);
END_TEST

TEST 'SDO string, bytes and REAL reads'
  VAR
    link : ARRAY[0..1279] OF WORD;
    svc : CW_LINK_SERVICE;
    bridge : MailboxModel;
    rs : CO_SDO_READ_STRING;
    rb : CO_SDO_READ_BYTES;
    r4 : CO_SDO_READ_REAL;
    r8 : CO_SDO_READ_REAL;
    r5 : CO_SDO_READ_REAL;
    long : CO_SDO_READ_STRING;
    buf : ARRAY[0..1023] OF BYTE;
    i : INT;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  FOR i := 1 TO 40 DO
    svc(LINK := link);
    rs(EXECUTE := TRUE, NODE := 5, INDEX := 16#1008, LINK := link);
    rb(EXECUTE := TRUE, NODE := 5, INDEX := 16#2000, BUFFER := buf, LINK := link);
    r4(EXECUTE := TRUE, NODE := 5, INDEX := 16#6000, LINK := link);
    r8(EXECUTE := TRUE, NODE := 5, INDEX := 16#6001, LINK := link);
    r5(EXECUTE := TRUE, NODE := 5, INDEX := 16#6002, LINK := link);
    long(EXECUTE := TRUE, NODE := 5, INDEX := 16#2001, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(rs.DONE);
  ASSERT_EQ(rs.VALUE, 'Valve block 24 V');
  ASSERT_TRUE(rb.DONE);
  ASSERT_EQ(rb.SIZE, 600);
  ASSERT_EQ(buf[0], 0);
  ASSERT_EQ(buf[300], 49);
  ASSERT_EQ(buf[599], 97);
  ASSERT_TRUE(r4.DONE);
  ASSERT_EQ(r4.VALUE, 1.5);
  ASSERT_TRUE(r8.DONE);
  ASSERT_EQ(r8.VALUE, -2.25);
  ASSERT_TRUE(r5.ERROR);
  ASSERT_EQ(r5.ERROR_ID, 7);
  ASSERT_TRUE(long.ERROR);
  ASSERT_EQ(long.ERROR_ID, 7);
  ASSERT_EQ(bridge.FETCHES, 5);
END_TEST

TEST 'SDO writes: 600 bytes staged, a string, a REAL32'
  VAR
    link : ARRAY[0..1279] OF WORD;
    svc : CW_LINK_SERVICE;
    bridge : MailboxModel;
    wb : CO_SDO_WRITE_BYTES;
    ws : CO_SDO_WRITE_STRING;
    wr : CO_SDO_WRITE_REAL;
    buf : ARRAY[0..1023] OF BYTE;
    i : INT;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  FOR i := 0 TO 599 DO
    buf[i] := INT_TO_BYTE(i MOD 7);
  END_FOR;
  FOR i := 1 TO 20 DO
    svc(LINK := link);
    wb(EXECUTE := TRUE, NODE := 5, INDEX := 16#2000, SIZE := 600, BUFFER := buf, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(wb.DONE);
  ASSERT_EQ(bridge.W_LEN, 600);
  ASSERT_EQ(bridge.w_data[599], 4);
  ASSERT_EQ(bridge.w_data[128], 2);
  ASSERT_EQ(bridge.STAGES, 5);
  FOR i := 1 TO 6 DO
    svc(LINK := link);
    ws(EXECUTE := TRUE, NODE := 5, INDEX := 16#2002, VALUE := 'abc', LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(ws.DONE);
  ASSERT_EQ(bridge.W_LEN, 3);
  ASSERT_EQ(bridge.W_KIND, 2);
  ASSERT_EQ(bridge.w_data[2], 99);
  FOR i := 1 TO 6 DO
    svc(LINK := link);
    wr(EXECUTE := TRUE, NODE := 5, INDEX := 16#6000, VALUE := 1.5, SIZE := 4, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(wr.DONE);
  ASSERT_EQ(bridge.W_LEN, 8);
  ASSERT_EQ(bridge.W_KIND, 1);
  ASSERT_EQ(bridge.W_SIZE, 4);
  ASSERT_EQ(bridge.w_data[6], 16#F8);
  ASSERT_EQ(bridge.w_data[7], 16#3F);
END_TEST

TEST 'SDO abort and timeout keep the bridge answer'
  VAR
    link : ARRAY[0..1279] OF WORD;
    svc : CW_LINK_SERVICE;
    bridge : MailboxModel;
    ra : CO_SDO_READ_BYTES;
    rt : CO_SDO_READ_STRING;
    buf : ARRAY[0..1023] OF BYTE;
    i : INT;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  FOR i := 1 TO 12 DO
    svc(LINK := link);
    ra(EXECUTE := TRUE, NODE := 98, INDEX := 16#2000, BUFFER := buf, LINK := link);
    rt(EXECUTE := TRUE, NODE := 99, INDEX := 16#1008, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_EQ(ra.ERROR_ID, 1);
  ASSERT_EQ(ra.ABORT_CODE, 16#06020000);
  ASSERT_EQ(rt.ERROR_ID, 2);
  ASSERT_EQ(rt.ABORT_CODE, 16#05040000);
END_TEST

TEST 'bridge gone during a transfer ends with 20'
  VAR
    link : ARRAY[0..1279] OF WORD;
    svc : CW_LINK_SERVICE;
    bridge : MailboxModel;
    rb : CO_SDO_READ_BYTES;
    buf : ARRAY[0..1023] OF BYTE;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  svc(LINK := link);
  rb(EXECUTE := TRUE, NODE := 5, INDEX := 16#2000, BUFFER := buf, LINK := link);
  bridge(LINK := link);
  link := bridge.LINK;
  ASSERT_TRUE(rb.BUSY);
  link[21] := 0;
  svc(LINK := link);
  rb(EXECUTE := TRUE, NODE := 5, INDEX := 16#2000, BUFFER := buf, LINK := link);
  ASSERT_TRUE(rb.ERROR);
  ASSERT_EQ(rb.ERROR_ID, 20);
  ASSERT_EQ(link[94], 0);
END_TEST

TEST 'a waiting instance that is no longer called is skipped'
  VAR
    link : ARRAY[0..1279] OF WORD;
    svc : CW_LINK_SERVICE;
    bridge : MailboxModel;
    s1 : CAN_SEND;
    s2 : CAN_SEND;
    s3 : CAN_SEND;
    d : ARRAY[0..7] OF BYTE;
    i : INT;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  svc(LINK := link);
  s1(EXECUTE := TRUE, ID := 1, DATA := d, LINK := link);
  s2(EXECUTE := TRUE, ID := 2, DATA := d, LINK := link);
  s3(EXECUTE := TRUE, ID := 3, DATA := d, LINK := link);
  bridge(LINK := link);
  link := bridge.LINK;
  (* s2 is never called again *)
  FOR i := 1 TO 8 DO
    svc(LINK := link);
    s1(EXECUTE := TRUE, ID := 1, DATA := d, LINK := link);
    s3(EXECUTE := TRUE, ID := 3, DATA := d, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(s1.DONE);
  ASSERT_TRUE(s3.DONE);
  ASSERT_EQ(bridge.TX_COUNT, 2);
END_TEST

TEST 'CAN_RECEIVE drains a batch in one scan'
  VAR
    link : ARRAY[0..1279] OF WORD;
    svc : CW_LINK_SERVICE;
    bridge : MailboxModel;
    rx : CAN_RECEIVE;
    d : ARRAY[0..7] OF BYTE;
    i : INT;
    got : INT;
    ids : ARRAY[0..9] OF UDINT;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  FOR i := 1 TO 4 DO
    svc(LINK := link);
    rx(ENABLE := TRUE, ID := 16#180, MASK := 16#780, RX_DATA := d, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(rx.ACTIVE);
  FOR i := 0 TO 4 DO
    bridge(INJ_CAN := TRUE, INJ_ID := 16#181 + INT_TO_UDINT(i), INJ_DLC := 2, INJ_B0 := INT_TO_BYTE(10 * i), HOLD := TRUE,
           LINK := link);
    link := bridge.LINK;
  END_FOR;
  bridge(INJ_CAN := TRUE, INJ_ID := 16#281, HOLD := FALSE, LINK := link);
  link := bridge.LINK;
  svc(LINK := link);
  rx(ENABLE := TRUE, ID := 16#180, MASK := 16#780, RX_DATA := d, LINK := link);
  WHILE rx.NEW DO
    ids[got] := rx.RX_ID;
    got := got + 1;
    IF got = 5 THEN
      ASSERT_EQ(d[0], 40);
      ASSERT_EQ(d[1], 41);
      ASSERT_EQ(rx.RX_DLC, 2);
    END_IF;
    rx(ENABLE := TRUE, ID := 16#180, MASK := 16#780, RX_DATA := d, LINK := link);
  END_WHILE;
  ASSERT_EQ(got, 5);
  ASSERT_EQ(ids[0], 16#181);
  ASSERT_EQ(ids[4], 16#185);
  ASSERT_EQ(link[104], 0);
  (* acknowledged: the next batch can come *)
  bridge(INJ_CAN := TRUE, INJ_ID := 16#186, LINK := link);
  link := bridge.LINK;
  svc(LINK := link);
  rx(ENABLE := TRUE, ID := 16#180, MASK := 16#780, RX_DATA := d, LINK := link);
  ASSERT_TRUE(rx.NEW);
  ASSERT_EQ(rx.RX_ID, 16#186);
  (* disabled: the receiver closes *)
  FOR i := 1 TO 4 DO
    svc(LINK := link);
    rx(ENABLE := FALSE, RX_DATA := d, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_FALSE(rx.ACTIVE);
  ASSERT_EQ(bridge.OPEN_RX, 0);
END_TEST

TEST 'CAN_RECEIVE keeps receiving as the bridge clock wraps'
  VAR
    link : ARRAY[0..1279] OF WORD;
    svc : CW_LINK_SERVICE;
    bridge : MailboxModel;
    rx : CAN_RECEIVE;
    d : ARRAY[0..7] OF BYTE;
    i : INT;
    k : INT;
    got : INT;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  FOR i := 1 TO 4 DO
    svc(LINK := link);
    rx(ENABLE := TRUE, ID := 16#180, MASK := 16#780, RX_DATA := d, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(rx.ACTIVE);
  (* one frame every 10 s of bridge time, for more than one 65.5 s wrap *)
  FOR k := 1 TO 10 DO
    bridge(INJ_CAN := TRUE, INJ_ID := 16#181, SKIP_MS := 10000, LINK := link);
    link := bridge.LINK;
    svc(LINK := link);
    rx(ENABLE := TRUE, ID := 16#180, MASK := 16#780, RX_DATA := d, LINK := link);
    IF rx.NEW THEN
      got := got + 1;
      rx(ENABLE := TRUE, ID := 16#180, MASK := 16#780, RX_DATA := d, LINK := link);
    END_IF;
  END_FOR;
  ASSERT_EQ(got, 10);
  ASSERT_TRUE(rx.ACTIVE);
  ASSERT_FALSE(rx.ERROR);
END_TEST

TEST 'a receiver the bridge closed opens again'
  VAR
    link : ARRAY[0..1279] OF WORD;
    svc : CW_LINK_SERVICE;
    bridge : MailboxModel;
    rx : CAN_RECEIVE;
    d : ARRAY[0..7] OF BYTE;
    i : INT;
    saw8 : BOOL;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  FOR i := 1 TO 4 DO
    svc(LINK := link);
    rx(ENABLE := TRUE, ID := 16#180, RX_DATA := d, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(rx.ACTIVE);
  bridge(CLOSE_SLOT := 0, LINK := link);
  link := bridge.LINK;
  FOR i := 1 TO 6 DO
    svc(LINK := link);
    rx(ENABLE := TRUE, ID := 16#180, RX_DATA := d, LINK := link);
    IF rx.ERROR_ID = 8 THEN
      saw8 := TRUE;
    END_IF;
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(saw8);
  ASSERT_TRUE(rx.ACTIVE);
  ASSERT_FALSE(rx.ERROR);
END_TEST

TEST 'CAN_SEND_CYCLIC starts, updates only on change and stops'
  VAR
    link : ARRAY[0..1279] OF WORD;
    svc : CW_LINK_SERVICE;
    bridge : MailboxModel;
    cyc : CAN_SEND_CYCLIC;
    d : ARRAY[0..7] OF BYTE;
    i : INT;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  d[0] := 1;
  FOR i := 1 TO 10 DO
    svc(LINK := link);
    cyc(ENABLE := TRUE, ID := 16#200, DLC := 1, PERIOD := T#20ms, DATA := d, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(cyc.ACTIVE);
  ASSERT_EQ(bridge.CYC_SETS, 1);
  ASSERT_TRUE(cyc.COUNT > 3);
  d[0] := 2;
  FOR i := 1 TO 5 DO
    svc(LINK := link);
    cyc(ENABLE := TRUE, ID := 16#200, DLC := 1, PERIOD := T#20ms, DATA := d, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_EQ(bridge.CYC_SETS, 2);
  ASSERT_EQ(bridge.job_data[0], 16#0200);
  FOR i := 1 TO 5 DO
    svc(LINK := link);
    cyc(ENABLE := FALSE, DATA := d, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_FALSE(cyc.ACTIVE);
  ASSERT_EQ(bridge.CYC_STOPS, 1);
  ASSERT_FALSE(bridge.job_on[0]);
END_TEST

TEST 'bus info and ECU info from the info block'
  VAR
    link : ARRAY[0..1279] OF WORD;
    bridge : MailboxModel;
    bus : CAN_BUS_INFO;
    ecu : J1939_ECU_INFO;
    other : J1939_ECU_INFO;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  bridge(LINK := link);
  link := bridge.LINK;
  bus(NETWORK := 0, LINK := link);
  ASSERT_FALSE(bus.ERROR);
  ASSERT_EQ(bus.STATE, 0);
  ASSERT_EQ(bus.BUS_LOAD, 12);
  ASSERT_EQ(bus.BUS_OFF_COUNT, 3);
  ASSERT_EQ(bus.RX_COUNT, 1000);
  ASSERT_EQ(bus.TX_COUNT, 65536);
  ecu(ENABLE := TRUE, NETWORK := 0, LINK := link);
  ASSERT_TRUE(ecu.VALID);
  ASSERT_EQ(ecu.STATE, 1);
  ASSERT_EQ(ecu.ADDRESS, 16#80);
  ASSERT_EQ(ecu.NAME, 16#A00000000000ABCD);
  ASSERT_EQ(ecu.ECU_COUNT, 4);
  other(ENABLE := TRUE, NETWORK := 1, LINK := link);
  ASSERT_EQ(other.ERROR_ID, 10);
  bus(NETWORK := 2, LINK := link);
  ASSERT_EQ(bus.ERROR_ID, 2);
END_TEST

TEST 'J1939 send short and long, request long, DM read and clear, find ECU'
  VAR
    link : ARRAY[0..1279] OF WORD;
    svc : CW_LINK_SERVICE;
    bridge : MailboxModel;
    snd : J1939_SEND;
    req : J1939_REQUEST;
    nack : J1939_REQUEST;
    dm : J1939_DM_READ;
    clr : J1939_DM_CLEAR;
    find : J1939_FIND_ECU;
    data : ARRAY[0..1784] OF BYTE;
    rdata : ARRAY[0..1784] OF BYTE;
    ndata : ARRAY[0..1784] OF BYTE;
    dtcs : ARRAY[0..31] OF UDINT;
    i : INT;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  FOR i := 0 TO 299 DO
    data[i] := INT_TO_BYTE(i MOD 13);
  END_FOR;
  FOR i := 1 TO 40 DO
    svc(LINK := link);
    snd(EXECUTE := TRUE, PGN := 65281, DESTINATION := 255, LENGTH := 300, DATA := data, LINK := link);
    req(EXECUTE := TRUE, PGN := 65000, DESTINATION := 16#21, DATA := rdata, LINK := link);
    nack(EXECUTE := TRUE, PGN := 59999, DESTINATION := 16#21, DATA := ndata, LINK := link);
    dm(EXECUTE := TRUE, SOURCE := 0, DTCS := dtcs, LINK := link);
    clr(EXECUTE := TRUE, DESTINATION := 9, LINK := link);
    find(ENABLE := TRUE, NAME := 16#A000000000000000, MASK := 16#FF00000000000000, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(snd.DONE);
  ASSERT_EQ(bridge.J_LEN, 300);
  ASSERT_EQ(bridge.J_PRIO, 6);
  ASSERT_EQ(bridge.j_data[299], 0);
  ASSERT_EQ(bridge.j_data[140], 10);
  ASSERT_TRUE(req.DONE);
  ASSERT_EQ(req.LENGTH, 300);
  ASSERT_EQ(req.SOURCE, 16#21);
  ASSERT_EQ(rdata[299], 43);
  ASSERT_TRUE(nack.ERROR);
  ASSERT_EQ(nack.ERROR_ID, 12);
  ASSERT_EQ(nack.ACK_CODE, 1);
  ASSERT_TRUE(dm.DONE);
  ASSERT_EQ(dm.COUNT, 2);
  ASSERT_EQ(dm.LAMPS, 16#44);
  ASSERT_EQ(dm.FLASH, 16#04);
  ASSERT_EQ(dm.AGE, T#1500ms);
  ASSERT_EQ(dtcs[0], 16#00012304);
  ASSERT_EQ(dtcs[1], 16#0005A1FF);
  ASSERT_TRUE(clr.DONE);
  ASSERT_EQ(bridge.DM_CLEARED, 9);
  ASSERT_TRUE(find.VALID);
  ASSERT_TRUE(find.FOUND);
  ASSERT_EQ(find.ADDRESS, 16#33);
  ASSERT_EQ(find.FOUND_NAME, 16#A00000000000ABCD);
END_TEST

TEST 'J1939_RECEIVE reads a long message whole'
  VAR
    link : ARRAY[0..1279] OF WORD;
    svc : CW_LINK_SERVICE;
    bridge : MailboxModel;
    rx : J1939_RECEIVE;
    data : ARRAY[0..1784] OF BYTE;
    i : INT;
    got : BOOL;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  FOR i := 1 TO 4 DO
    svc(LINK := link);
    rx(ENABLE := TRUE, PGN := 65282, RX_DATA := data, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(rx.ACTIVE);
  bridge(INJ_J1939 := TRUE, INJ_ID := 65282, INJ_LEN := 200, INJ_SRC := 0, INJ_B0 := 1, LINK := link);
  link := bridge.LINK;
  FOR i := 1 TO 10 DO
    svc(LINK := link);
    rx(ENABLE := TRUE, PGN := 65282, RX_DATA := data, LINK := link);
    IF rx.NEW THEN
      got := TRUE;
      ASSERT_EQ(rx.RX_LENGTH, 200);
      ASSERT_EQ(rx.RX_PGN, 65282);
      ASSERT_EQ(data[0], 1);
      ASSERT_EQ(data[199], 200);
    END_IF;
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(got);
  ASSERT_FALSE(rx.ERROR);
END_TEST

TEST 'two EMCY receivers each get a message; a new session shows 8 once'
  VAR
    link : ARRAY[0..1279] OF WORD;
    svc : CW_LINK_SERVICE;
    bridge : MailboxModel;
    e1 : CO_RECV_EMCY;
    e2 : CO_RECV_EMCY;
    m1 : ARRAY[0..4] OF BYTE;
    m2 : ARRAY[0..4] OF BYTE;
    i : INT;
    n1 : INT;
    n2 : INT;
    eights : INT;
  END_VAR
  link[21] := 1;
  link[89] := 16#0431;
  FOR i := 1 TO 6 DO
    svc(LINK := link);
    e1(ENABLE := TRUE, MSEF := m1, LINK := link);
    e2(ENABLE := TRUE, NODE := 3, MSEF := m2, LINK := link);
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_TRUE(e1.ACTIVE);
  ASSERT_TRUE(e2.ACTIVE);
  bridge(INJ_EMCY := TRUE, INJ_NODE := 3, INJ_CODE := 16#8130, LINK := link);
  link := bridge.LINK;
  FOR i := 1 TO 4 DO
    svc(LINK := link);
    e1(ENABLE := TRUE, MSEF := m1, LINK := link);
    e2(ENABLE := TRUE, NODE := 3, MSEF := m2, LINK := link);
    IF e1.NEW THEN
      n1 := n1 + 1;
      ASSERT_EQ(e1.ERROR_CODE, 16#8130);
      ASSERT_EQ(e1.EMCY_NODE, 3);
      ASSERT_EQ(e1.ERROR_REGISTER, 16#81);
      ASSERT_EQ(m1[4], 5);
    END_IF;
    IF e2.NEW THEN
      n2 := n2 + 1;
    END_IF;
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_EQ(n1, 1);
  ASSERT_EQ(n2, 1);
  bridge(INJ_RESTART := TRUE, INJ_NODE := 3, LINK := link);
  link := bridge.LINK;
  FOR i := 1 TO 4 DO
    svc(LINK := link);
    e1(ENABLE := TRUE, MSEF := m1, LINK := link);
    IF e1.ERROR_ID = 8 THEN
      eights := eights + 1;
    END_IF;
    bridge(LINK := link);
    link := bridge.LINK;
  END_FOR;
  ASSERT_EQ(eights, 1);
  ASSERT_TRUE(e1.ACTIVE);
END_TEST
