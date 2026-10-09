(*
 * CO402_CyclicPosition: cyclic synchronous position (CiA 402 mode 8) on an
 * axis of the editor's PLCopen motion library (spec canopen-cia402-axis).
 *
 * Call it every scan while it is in use, after the axis's drive bridge and
 * with MC_Power enabled. On a rising Enable it sets the target position
 * 0x607A to the actual position, selects mode 8 (operation stays enabled) and
 * follows Position once 0x6061 shows 8: one set-point per PLC cycle, applied
 * by the drive on SYNC. MaxVelocity (units/s, 0 = off) limits the step
 * between two set-points to MaxVelocity * Axis.fCycleTime; a larger step sets
 * Error (ErrorID 3) and holds the last set-point. Enable FALSE stops writing
 * the set-point (the drive holds the last one); hand the axis to another
 * block then.
 *
 * ErrorID: 1 drive not enabled, 2 mode not reached within ModeTimeout (or
 * left), 3 step limit exceeded, 4 axis in error stop (fault or drive lost).
 *)
FUNCTION_BLOCK CO402_CyclicPosition
VAR_IN_OUT
  Axis : AXIS_REF_SM3;
END_VAR
VAR_INPUT
  Enable : BOOL;
  Position : LREAL;            (* set-point [u] *)
  MaxVelocity : LREAL := 0.0;  (* step limit [u/s], 0 = off *)
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
  tMode : TON;
END_VAR
  IF NOT Enable THEN
    iState := 0;
  ELSIF iState = 0 THEN
    ErrorID := 0;
    IF Axis.bError OR NOT Axis.bCommunication THEN
      ErrorID := 4;
    ELSIF (Axis.Drive.StatusWord AND UINT#16#006F) <> UINT#16#0027 THEN
      ErrorID := 1;
    ELSE
      Axis.Drive.Target_Position := Axis.Drive.Position_Actual_Value;
      fLast := DINT_TO_LREAL(Axis.Drive.Position_Actual_Value) / Axis.fIncPerUnit;
      Axis.Drive.Modes_of_operation := SINT#8;
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
    Axis.Drive.Modes_of_operation := SINT#8;
    Axis.Drive.Target_Position := Axis.Drive.Position_Actual_Value;  (* hold until the drive is in mode 8 *)
    IF Axis.Drive.Modes_of_operation_display = SINT#8 THEN
      fLast := DINT_TO_LREAL(Axis.Drive.Position_Actual_Value) / Axis.fIncPerUnit;
      iState := 20;
    ELSIF tMode.Q THEN
      ErrorID := 2; iState := 99;
    END_IF
  END_IF
  IF iState = 20 THEN
    IF Axis.Drive.Modes_of_operation_display <> SINT#8 THEN
      ErrorID := 2; iState := 99;
    ELSIF MaxVelocity > 0.0 AND ABS(Position - fLast) > MaxVelocity * Axis.fCycleTime * 1.000001 THEN
      ErrorID := 3; iState := 99;
    ELSE
      Axis.Drive.Target_Position := LREAL_TO_DINT(Position * Axis.fIncPerUnit);
      fLast := Position;
    END_IF
  END_IF

  InSync := iState = 20;
  Busy := iState = 10 OR iState = 20;
  Error := iState = 99;
  IF iState = 0 THEN ErrorID := 0; END_IF
END_FUNCTION_BLOCK
