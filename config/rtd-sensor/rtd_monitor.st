(* Starter program for config/rtd-sensor: the RTD-8 temperature
   module as node 5. The module sends each temperature as an INT in 0.1 degC
   (0x6132 "decimal digits" = 1), so 215 means 21.5 degC.

   Paste into a Structured Text POU in the OpenPLC editor (target OpenPLC
   Runtime v4), Build only, then deploy with canworks-deploy and
   config/rtd-sensor/canopen_config.json. *)
PROGRAM rtd_monitor
  VAR
    ai0_raw AT %IW100 : INT;
    ai1_raw AT %IW101 : INT;
    ai2_raw AT %IW102 : INT;
    ai3_raw AT %IW103 : INT;
    ai0_status AT %IB100 : BYTE;     (* 0x6150: 0 = OK, non-zero = sensor fault *)
    node_ok AT %IX10.0 : BOOL;       (* node 5 is OPERATIONAL *)
    high_alarm AT %QX100.0 : BOOL;   (* AI0 above the limit *)
  END_VAR
  VAR
    temp0 : REAL;
    temp1 : REAL;
    temp2 : REAL;
    temp3 : REAL;
    limit : REAL := 25.0;
  END_VAR

  temp0 := INT_TO_REAL(ai0_raw) / 10.0;
  temp1 := INT_TO_REAL(ai1_raw) / 10.0;
  temp2 := INT_TO_REAL(ai2_raw) / 10.0;
  temp3 := INT_TO_REAL(ai3_raw) / 10.0;
  high_alarm := node_ok AND (ai0_status = 0) AND (temp0 > limit);
END_PROGRAM

CONFIGURATION Config0
  RESOURCE Res0 ON PLC
    TASK task0(INTERVAL := T#20ms, PRIORITY := 0);
    PROGRAM instance0 WITH task0 : rtd_monitor;
  END_RESOURCE
END_CONFIGURATION
