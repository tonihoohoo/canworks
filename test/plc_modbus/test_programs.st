(*
 * The generated canworks_in and canworks_out (tools/deploy/canworks/
 * openplcmodbus.py) for test/plc_modbus/canworks.json, as function blocks
 * (make_programs.py): raw Modbus words to typed values and back, low word
 * first, and the PLC link header. Run by test/plc_modbus/run.sh.
 *)
TEST 'canworks_in converts the input registers'
  VAR
    cin : canworks_in_fb;
  END_VAR
  cin.i0 := 16#EC2C;
  cin.i1 := 16#168F;
  cin.i3 := 5;
  cin.i6 := 16#0380;
  cin.i7 := 16#FF05;
  cin.i8 := 16#FFFE;
  cin.i9 := 16#7960;
  cin.i10 := 16#FFFE;
  cin.i11 := 16#0000;
  cin.i12 := 16#3FC0;
  cin.i13 := 16#CDEF;
  cin.i14 := 16#89AB;
  cin.i15 := 16#4567;
  cin.i16 := 16#0123;
  cin.i17 := 0;
  cin.i18 := 0;
  cin.i19 := 0;
  cin.i20 := 16#C004;
  cin.i21 := 7;
  cin();
  ASSERT_TRUE(cin.canworks.ok);
  ASSERT_EQ(cin.canworks.link[21], 16#0007);
  ASSERT_TRUE(cin.canworks.cab_In_status);
  ASSERT_TRUE(cin.canworks.cab_In_flag);
  ASSERT_TRUE(cin.canworks.cab_In_low);
  ASSERT_EQ(cin.canworks.cab_In_sbyte, -1);
  ASSERT_EQ(cin.canworks.cab_In_ubyte, 5);
  ASSERT_EQ(cin.canworks.cab_In_word, -2);
  ASSERT_EQ(cin.canworks.cab_In_dword, -100000);
  ASSERT_NEAR(cin.canworks.cab_In_real, 1.5, 0.0);
  ASSERT_EQ(cin.canworks.cab_Wide_lword, ULINT#16#0123456789ABCDEF);
  ASSERT_NEAR(cin.canworks.cab_Wide_lreal, -2.5, 0.0);
  ASSERT_EQ(cin.canworks.link[14], 7);
END_TEST

TEST 'canworks.ok needs the map hash and a moving counter'
  VAR
    cin : canworks_in_fb;
  END_VAR
  cin.i0 := 16#EC2C;
  cin.i1 := 16#1690;
  cin.i3 := 1;
  cin();
  ASSERT_FALSE(cin.canworks.ok);
  cin.i1 := 16#168F;
  cin.i3 := 2;
  cin();
  ASSERT_TRUE(cin.canworks.ok);
  cin();
  ADVANCE_TIME(T#200ms);
  cin();
  ASSERT_TRUE(cin.canworks.ok);
  ADVANCE_TIME(T#200ms);
  cin();
  ASSERT_FALSE(cin.canworks.ok);
  cin.i3 := 3;
  cin();
  ASSERT_TRUE(cin.canworks.ok);
  cin.i0 := 0;
  cin.i1 := 0;
  cin.i3 := 4;
  cin();
  ASSERT_FALSE(cin.canworks.ok);
END_TEST

TEST 'canworks_out writes the holding registers and the header last'
  VAR
    cout : canworks_out_fb;
  END_VAR
  cout.canworks.cab_Out_flag := TRUE;
  cout.canworks.cab_Out_low := TRUE;
  cout.canworks.cab_Out_sbyte := -2;
  cout.canworks.cab_Out_ubyte := 7;
  cout.canworks.cab_Out_word := -3;
  cout.canworks.cab_Out_dword := -100000;
  cout.canworks.cab_Out_real := 1.5;
  cout.canworks.cab_Wide_lreal_2 := -2.5;
  cout.canworks.link[5] := 16#0400;
  cout.canworks.link[13] := 16#BEEF;
  cout();
  ASSERT_EQ(cout.q0, 1);
  ASSERT_EQ(cout.q1, 16#EC2C);
  ASSERT_EQ(cout.q2, 16#168F);
  ASSERT_EQ(cout.q3, 16#0108);
  ASSERT_EQ(cout.q4, 16#FE07);
  ASSERT_EQ(cout.q5, 16#FFFD);
  ASSERT_EQ(cout.q6, 16#7960);
  ASSERT_EQ(cout.q7, 16#FFFE);
  ASSERT_EQ(cout.q8, 16#0000);
  ASSERT_EQ(cout.q9, 16#3FC0);
  ASSERT_EQ(cout.q10, 0);
  ASSERT_EQ(cout.q13, 16#C004);
  ASSERT_EQ(cout.q15, 16#0400);
  ASSERT_EQ(cout.q23, 16#BEEF);
END_TEST

TEST 'mailbox words go between the registers and LINK, the link service runs'
  VAR
    cin : canworks_in_fb;
    cout : canworks_out_fb;
  END_VAR
  (* responses from input register 28, the receive mailbox from 100, info
     from 220, the cyclic table from 238; requests from holding register 24,
     the acknowledgement from 96, keepalives from 99 *)
  cin.i0 := 16#EC2C;
  cin.i1 := 16#168F;
  cin.i3 := 1;
  cin.i28 := 16#0042;
  cin.i99 := 16#5A5A;
  cin.i100 := 16#7001;
  cin.i220 := 16#000C;
  cin.i254 := 16#0009;
  cin();
  ASSERT_EQ(cin.canworks.link[89], 16#0431);
  ASSERT_EQ(cin.canworks.link[216], 16#0042);
  ASSERT_EQ(cin.canworks.link[287], 16#5A5A);
  ASSERT_EQ(cin.canworks.link[720], 16#7001);
  ASSERT_EQ(cin.canworks.link[960], 16#000C);
  ASSERT_EQ(cin.canworks.link[1120], 16#0009);
  (* CW_LINK_SERVICE ran: one scan, the new batch acknowledged *)
  ASSERT_EQ(cin.canworks.link[90], 1);
  ASSERT_EQ(cin.canworks.link[102], 16#7001);
  cout.canworks.link[144] := 16#0101;
  cout.canworks.link[215] := 16#0202;
  cout.canworks.link[102] := 16#7001;
  cout.canworks.link[131] := 16#0303;
  cout();
  ASSERT_EQ(cout.q24, 16#0101);
  ASSERT_EQ(cout.q95, 16#0202);
  ASSERT_EQ(cout.q96, 16#7001);
  ASSERT_EQ(cout.q102, 16#0303);
END_TEST
