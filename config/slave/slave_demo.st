(* Starter program for config/slave: OpenPLC as CANopen node 10 on the
   network "line", under another master. The master writes the speed
   setpoint, the mode and the run bit (0x2000-0x2002); the program answers
   with the actual speed, a status word and a temperature (0x2100-0x2101),
   and raises an EMCY while the temperature is too high.

   Paste into a Structured Text POU in the OpenPLC editor (target OpenPLC
   Runtime v4), Build only, then deploy with canworks-deploy and
   config/slave/canopen_config.json. *)
PROGRAM slave_demo
  VAR
    line_speed_setpoint AT %IW300 : UINT;   (* 0x2000:1, from the master *)
    line_mode AT %IB300 : USINT;            (* 0x2001:1, from the master *)
    line_run AT %IX300.0 : BOOL;            (* 0x2002:1, from the master *)
    line_actual_speed AT %QW300 : UINT;     (* 0x2100:1, to the master *)
    line_status_word AT %QW301 : UINT;      (* 0x2100:2, to the master *)
    line_temperature AT %QW302 : INT;       (* 0x2101:1, to the master, 0.1 degC *)
    line_state AT %IB301 : USINT;           (* own NMT state: 5 operational *)
    line_comm_ok AT %IX300.1 : BOOL;        (* operational, master heartbeat seen *)
    line_sync_count AT %IW301 : UINT;       (* SYNCs received *)
    line_emcy AT %QW303 : WORD;             (* non-zero: send an EMCY *)
    line_errreg AT %QB300 : BYTE;           (* 0x1001 bits sent with it *)
  END_VAR
  VAR
    ramp : UINT := 0;
    status : UINT := 0;
    temp : INT := 215;
  END_VAR

  (* Ramp the actual speed towards the setpoint while the master runs us. *)
  IF line_comm_ok AND line_run THEN
    IF ramp < line_speed_setpoint THEN
      ramp := ramp + 1;
    ELSIF ramp > line_speed_setpoint THEN
      ramp := ramp - 1;
    END_IF;
  ELSE
    ramp := 0;
  END_IF;
  line_actual_speed := ramp;
  line_temperature := temp;

  (* Status word: bit 0 running, bit 1 at setpoint, bits 8-9 the mode. *)
  status := USINT_TO_UINT(line_mode MOD 4) * 256;
  IF ramp > 0 THEN status := status + 1; END_IF;
  IF ramp = line_speed_setpoint THEN status := status + 2; END_IF;
  line_status_word := status;

  (* EMCY 0x4210 (temperature too high) with the temperature bit of 0x1001. *)
  IF temp > 600 THEN
    line_emcy := 16#4210;
    line_errreg := 16#09;
  ELSE
    line_emcy := 0;
    line_errreg := 0;
  END_IF;
END_PROGRAM

CONFIGURATION Config0
  RESOURCE Res0 ON PLC
    TASK task0(INTERVAL := T#10ms, PRIORITY := 0);
    PROGRAM instance0 WITH task0 : slave_demo;
  END_RESOURCE
END_CONFIGURATION
