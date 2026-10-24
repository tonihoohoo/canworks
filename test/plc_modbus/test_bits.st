(*
 * Bit channels of PDO entries on the bridge (canopen-pdo-io "Bit channels in
 * the generated programs on the bridge"): the generated canworks_in and
 * canworks_out for examples/openplc-modbus with bits on rtd TPDO1 0x7130:1
 * (bit 9), dio TPDO1 0x6000:1 (bits 0 and 3) and dio RPDO1 0x6200:1 (bit 2),
 * as function blocks (make_programs.py, bits.st). Run by test/plc_modbus/run.sh.
 *)
TEST 'canworks_in reads each bit from its entry'
  VAR
    cin : canworks_in_fb;
  END_VAR
  cin.i6 := 16#0200;
  cin.i10 := 16#0900;
  cin();
  ASSERT_TRUE(cin.canworks.rtd_hi);
  ASSERT_EQ(cin.canworks.rtd_AI0_Input_PV, 512);
  ASSERT_TRUE(cin.canworks.dio_first_bit);
  ASSERT_TRUE(cin.canworks.dio_Read_input_8_bit_1_bit3);
  ASSERT_EQ(cin.canworks.dio_Read_input_8_bit_1, 9);
  cin.i6 := 16#01FF;
  cin.i10 := 16#F6FF;
  cin();
  ASSERT_FALSE(cin.canworks.rtd_hi);
  ASSERT_FALSE(cin.canworks.dio_first_bit);
  ASSERT_FALSE(cin.canworks.dio_Read_input_8_bit_1_bit3);
END_TEST

TEST 'canworks_out ORs each bit into its entry word'
  VAR
    cout : canworks_out_fb;
  END_VAR
  cout.canworks.dio_Write_output_8_bit_1 := 16#01;
  cout.canworks.dio_Write_output_8_bit_2 := 16#22;
  cout();
  ASSERT_EQ(cout.q3, 16#0122);
  cout.canworks.dio_lamp := TRUE;
  cout();
  ASSERT_EQ(cout.q3, 16#0522);
  cout.canworks.dio_Write_output_8_bit_1 := 0;
  cout();
  ASSERT_EQ(cout.q3, 16#0422);
END_TEST
