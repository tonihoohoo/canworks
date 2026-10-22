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
  cin.i0 := 16#FC3C;
  cin.i1 := 16#D880;
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
  cin.i0 := 16#FC3C;
  cin.i1 := 16#D881;
  cin.i3 := 1;
  cin();
  ASSERT_FALSE(cin.canworks.ok);
  cin.i1 := 16#D880;
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
  ASSERT_EQ(cout.q1, 16#FC3C);
  ASSERT_EQ(cout.q2, 16#D880);
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
