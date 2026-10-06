(*
 * A CiA 402 drive for the ST tests (test/cia402/run.sh): the power state
 * machine (CiA 402 figure "state machine"), profile position (mode 1),
 * profile velocity (mode 3) and homing (mode 6, method 35: the current
 * position is home), with halt (controlword bit 8) and a fault input.
 * One call is one cycle of Dt. test/drive/drive_slave.cpp plays the same
 * drive on a CAN bus.
 *
 * Statusword bits: 0 ready to switch on, 1 switched on, 2 operation enabled,
 * 3 fault, 4 voltage enabled, 5 quick stop (1 = not active), 6 switch on
 * disabled, 9 remote, 10 target reached, 12 set-point acknowledge / speed
 * zero / homing attained (by mode), 14 standstill (the bit the editor's
 * motion library reads as standstill).
 *)
FUNCTION_BLOCK CiA402_Drive
VAR_INPUT
	ControlWord : UINT;
	Modes : SINT;
	TargetPosition : DINT;
	ProfileVelocity : UDINT;
	TargetVelocity : DINT;
	Fault : BOOL;                (* raise a drive fault *)
	Dt : LREAL := 0.01;          (* cycle [s] *)
END_VAR
VAR_OUTPUT
	StatusWord : UINT;
	ModesDisplay : SINT;
	Position : DINT;
	Velocity : DINT;
	State : INT;                 (* 1 switch on disabled, 2 ready, 3 switched on, 4 enabled, 5 quick stop, 6 fault *)
END_VAR
VAR
	pos : LREAL;
	vel : LREAL;
	target : LREAL;
	cw : WORD;
	lastCw : WORD;
	ack : BOOL;
	homed : BOOL;
	step : LREAL;
END_VAR
	cw := UINT_TO_WORD(ControlWord);
	IF State = 0 THEN
		State := 1;
	END_IF

	(* Power state machine *)
	IF Fault AND State <> 6 THEN
		State := 6;
	ELSIF State = 6 THEN
		IF cw.7 AND NOT lastCw.7 AND NOT Fault THEN
			State := 1;
		END_IF
	ELSIF (cw AND WORD#16#0082) = WORD#16#0000 THEN
		State := 1;                                        (* disable voltage *)
	ELSIF (cw AND WORD#16#0086) = WORD#16#0002 THEN
		IF State = 4 THEN State := 5; ELSE State := 1; END_IF  (* quick stop *)
	ELSIF (cw AND WORD#16#0087) = WORD#16#0006 THEN
		State := 2;                                        (* shutdown *)
	ELSIF (cw AND WORD#16#008F) = WORD#16#0007 THEN
		IF State = 2 OR State = 4 THEN State := 3; END_IF  (* switch on / disable operation *)
	ELSIF (cw AND WORD#16#008F) = WORD#16#000F THEN
		IF State = 3 OR State = 5 THEN State := 4; END_IF  (* enable operation *)
	END_IF

	ModesDisplay := Modes;
	IF State <> 4 THEN
		vel := 0.0;
		ack := FALSE;
		target := pos;
	ELSIF cw.8 THEN
		vel := 0.0;                                        (* halt *)
	ELSIF ModesDisplay = 1 THEN
		IF cw.4 AND NOT lastCw.4 THEN
			IF cw.6 THEN target := target + DINT_TO_LREAL(TargetPosition);
			ELSE target := DINT_TO_LREAL(TargetPosition); END_IF
			ack := TRUE;
		ELSIF NOT cw.4 THEN
			ack := FALSE;
		END_IF
		step := UDINT_TO_LREAL(ProfileVelocity) * Dt;
		IF ABS(target - pos) <= step THEN
			vel := (target - pos) / Dt;
		ELSIF target > pos THEN
			vel := UDINT_TO_LREAL(ProfileVelocity);
		ELSE
			vel := -UDINT_TO_LREAL(ProfileVelocity);
		END_IF
	ELSIF ModesDisplay = 3 THEN
		vel := DINT_TO_LREAL(TargetVelocity);
	ELSIF ModesDisplay = 6 THEN
		vel := 0.0;
		IF cw.4 AND NOT lastCw.4 THEN
			pos := 0.0;                                    (* method 35: here is home *)
			target := 0.0;
			homed := TRUE;
		ELSIF NOT cw.4 THEN
			homed := FALSE;
		END_IF
	ELSE
		vel := 0.0;
	END_IF
	pos := pos + vel * Dt;
	Position := LREAL_TO_DINT(pos);
	Velocity := LREAL_TO_DINT(vel);

	(* Statusword *)
	CASE State OF
		1: StatusWord := 16#0250;   (* switch on disabled, quick stop off, remote *)
		2: StatusWord := 16#0231;
		3: StatusWord := 16#0233;
		4: StatusWord := 16#0237;
		5: StatusWord := 16#0217;
		6: StatusWord := 16#0218;
	END_CASE
	IF vel = 0.0 THEN
		StatusWord := StatusWord OR 16#4000;                (* standstill *)
	END_IF
	IF State = 4 THEN
		IF ModesDisplay = 1 THEN
			IF ack THEN StatusWord := StatusWord OR 16#1000; END_IF
			IF pos = target THEN StatusWord := StatusWord OR 16#0400; END_IF
		ELSIF ModesDisplay = 3 THEN
			IF vel = 0.0 THEN StatusWord := StatusWord OR 16#1000; END_IF
			IF vel = DINT_TO_LREAL(TargetVelocity) THEN StatusWord := StatusWord OR 16#0400; END_IF
		ELSIF ModesDisplay = 6 THEN
			IF homed THEN StatusWord := StatusWord OR 16#1400; END_IF
		END_IF
	END_IF
	lastCw := cw;
END_FUNCTION_BLOCK

(*
 * One bus cycle between a program and a CiA402_Drive: call it with the
 * outputs the program wrote, then copy its outputs into the program's
 * inputs (the test runner does not write VAR_IN_OUT back into a program's
 * located variables, so the test files copy them).
 *)
FUNCTION_BLOCK DriveLink
VAR_INPUT
	ControlWord : UINT;
	Modes : SINT;
	TargetPosition : DINT;
	ProfileVelocity : UDINT;
	TargetVelocity : DINT;
	Fault : BOOL;
	Lost : BOOL;                 (* the node stops answering: inputs hold, status bit FALSE *)
END_VAR
VAR_OUTPUT
	StatusWord : UINT;
	ModesDisplay : SINT;
	Position : DINT;
	Velocity : DINT;
	Online : BOOL;
END_VAR
VAR
	Drive : CiA402_Drive;
END_VAR
	Online := NOT Lost;
	IF NOT Lost THEN
		Drive(ControlWord := ControlWord, Modes := Modes, TargetPosition := TargetPosition,
		      ProfileVelocity := ProfileVelocity, TargetVelocity := TargetVelocity, Fault := Fault);
		StatusWord := Drive.StatusWord;
		ModesDisplay := Drive.ModesDisplay;
		Position := Drive.Position;
		Velocity := Drive.Velocity;
	END_IF
END_FUNCTION_BLOCK
