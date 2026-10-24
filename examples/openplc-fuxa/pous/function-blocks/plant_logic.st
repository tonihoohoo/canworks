(* The example plant's logic, the same as the plant logic of the Node-RED
   dashboard example: an alarm when temperature 1 is over the limit, held
   until Ack while it is back at or under it; the alarm sets output byte 0
   bit 0. While RUN is on, a light runs along output byte 1 (one bit every
   500 ms) and the loop back is checked on input byte 1; while it is off,
   output byte 1 is MANUAL_OUT1. *)
FUNCTION_BLOCK PLANT_LOGIC
  VAR_INPUT
    VALID : BOOL;          (* TEMP is a value from the bridge *)
    TEMP : REAL;           (* temperature 1 in degrees C *)
    LIMIT : REAL;
    ACK : BOOL;
    RUN : BOOL;
    DIO_IN1 : USINT;
    MANUAL_OUT0 : USINT;   (* bits 1-7 of output byte 0 *)
    MANUAL_OUT1 : USINT;   (* output byte 1 while RUN is off *)
  END_VAR
  VAR_OUTPUT
    ALARM : BOOL;
    LIGHT_OK : BOOL;
    DIO_OUT0 : USINT;
    DIO_OUT1 : USINT;
  END_VAR
  VAR
    tick : TON;
    light : USINT := 1;
  END_VAR

  IF VALID AND TEMP > LIMIT THEN
    ALARM := TRUE;
  ELSIF ACK THEN
    ALARM := FALSE;
  END_IF;
  DIO_OUT0 := (MANUAL_OUT0 AND USINT#16#FE) OR BOOL_TO_USINT(ALARM);

  IF RUN THEN
    tick(IN := TRUE, PT := T#500ms);
    IF tick.Q THEN
      tick(IN := FALSE);
      LIGHT_OK := DIO_IN1 = light;
      IF light >= USINT#128 THEN
        light := USINT#1;
      ELSE
        light := light * USINT#2;
      END_IF;
    END_IF;
    DIO_OUT1 := light;
  ELSE
    tick(IN := FALSE);
    LIGHT_OK := FALSE;
    DIO_OUT1 := MANUAL_OUT1;
  END_IF;
END_FUNCTION_BLOCK
