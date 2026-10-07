(*
 * CO402_CyclicTorque: cyclic synchronous torque (CiA 402 mode 10) on an axis
 * of the editor's PLCopen motion library (spec canopen-cia402-axis).
 *
 * Call it every scan while it is in use, after the axis's drive bridge and
 * with MC_Power enabled. On a rising Enable it sets the target torque 0x6071
 * to 0, selects mode 10 (operation stays enabled) and follows Torque, in per
 * mille of the drive's rated torque (0x6076), once 0x6061 shows 10.
 * MaxTorqueRate (per mille/s, 0 = off) limits the step between two
 * set-points to MaxTorqueRate * Axis.fCycleTime; a larger step sets Error
 * (ErrorID 3) and holds the last set-point. In the scan Enable goes FALSE the
 * block sends torque 0, then stops writing.
 *
 * ErrorID: 1 drive not enabled, 2 mode not reached within ModeTimeout (or
 * left), 3 step limit exceeded, 4 axis in error stop (fault or drive lost).
 *)
FUNCTION_BLOCK CO402_CyclicTorque
VAR_IN_OUT
  Axis : AXIS_REF_SM3;
END_VAR
VAR_INPUT
  Enable : BOOL;
  Torque : LREAL;                (* set-point [per mille of rated torque] *)
  MaxTorqueRate : LREAL := 0.0;  (* step limit [per mille/s], 0 = off *)
  ModeTimeout : TIME := T#500ms;
END_VAR
VAR_OUTPUT
  InSync : BOOL;
  Busy : BOOL;
  Error : BOOL;
  ErrorID : UINT;
END_VAR
VAR
  iState : INT;  (* 0 idle, 10 selecting the mode, 20 following, 99 error *)
  fLast : LREAL;
  fSet : LREAL;
  tMode : TON;
END_VAR
  IF NOT Enable THEN
    IF iState = 10 OR iState = 20 THEN
      Axis.Drive.Target_torque := INT#0;
    END_IF
    iState := 0;
  ELSIF iState = 0 THEN
    ErrorID := 0;
    IF Axis.bError OR NOT Axis.bCommunication THEN
      ErrorID := 4;
    ELSIF (Axis.Drive.StatusWord AND UINT#16#006F) <> UINT#16#0027 THEN
      ErrorID := 1;
    ELSE
      Axis.Drive.Target_torque := INT#0;
      fLast := 0.0;
      Axis.Drive.Modes_of_operation := SINT#10;
      iState := 10;
    END_IF
    IF ErrorID <> 0 THEN iState := 99; END_IF
  END_IF

  IF iState = 10 OR iState = 20 THEN
    IF Axis.bError OR NOT Axis.bCommunication THEN
      ErrorID := 4; iState := 99;
    ELSIF (Axis.Drive.StatusWord AND UINT#16#006F) <> UINT#16#0027 THEN
      ErrorID := 1; iState := 99;
    END_IF
  END_IF
  tMode(IN := iState = 10, PT := ModeTimeout);
  IF iState = 10 THEN
    Axis.Drive.Modes_of_operation := SINT#10;
    Axis.Drive.Target_torque := INT#0;
    IF Axis.Drive.Modes_of_operation_display = SINT#10 THEN
      iState := 20;
    ELSIF tMode.Q THEN
      ErrorID := 2; iState := 99;
    END_IF
  END_IF
  IF iState = 20 THEN
    IF Axis.Drive.Modes_of_operation_display <> SINT#10 THEN
      ErrorID := 2; iState := 99;
    ELSIF MaxTorqueRate > 0.0 AND ABS(Torque - fLast) > MaxTorqueRate * Axis.fCycleTime * 1.000001 THEN
      ErrorID := 3; iState := 99;
    ELSE
      fSet := LIMIT(-32768.0, Torque, 32767.0);
      Axis.Drive.Target_torque := LREAL_TO_INT(fSet);
      fLast := Torque;
    END_IF
  END_IF

  InSync := iState = 20;
  Busy := iState = 10 OR iState = 20;
  Error := iState = 99;
  IF iState = 0 THEN ErrorID := 0; END_IF
END_FUNCTION_BLOCK
