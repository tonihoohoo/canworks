(*
 * The program the project generator writes for config/cia402-drive (its
 * axis `drive` and the bridge call), with the editor's PLCopen motion blocks
 * called on that axis, against the drive model. Run by test/cia402/run.sh.
 * Each cycle: the program's scan, the test's motion block calls (after the
 * bridge, as in a user program), one bus cycle. Time stands still (the test
 * runner advances it only between test statements, not inside a loop), so
 * the library's timeouts never fire; the drive model moves by its own Dt.
 *)
TEST 'MC_Power enables the drive through the CiA 402 state machine'
	VAR
		m : main;
		bus : DriveLink;
		power : MC_Power;
		status : MC_ReadStatus;
		i : INT;
		seenShutdown, seenSwitchOn : BOOL;
	END_VAR
	FOR i := 1 TO 40 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, ProfileVelocity := m.drive_Profile_velocity,
		    TargetVelocity := m.drive_Target_velocity);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_ok := bus.Online;
		IF (m.drive_Controlword AND 16#8F) = 16#06 THEN seenShutdown := TRUE; END_IF
		IF (m.drive_Controlword AND 16#8F) = 16#07 THEN seenSwitchOn := TRUE; END_IF
	END_FOR
	ASSERT_TRUE(seenShutdown, 'drive got Shutdown');
	ASSERT_TRUE(seenSwitchOn, 'drive got Switch on');
	ASSERT_EQ(m.drive_Controlword AND 16#8F, 16#0F, 'drive got Enable operation');
	ASSERT_EQ(bus.Drive.State, 4);
	ASSERT_TRUE(power.Status);
	ASSERT_TRUE(m.drive.bRegulatorRealState);
	status(Axis := m.drive, Enable := TRUE);
	ASSERT_TRUE(status.StandStill);
END_TEST

TEST 'MC_MoveVelocity sets mode 3 and the target velocity'
	VAR
		m : main;
		bus : DriveLink;
		power : MC_Power;
		status : MC_ReadStatus;
		i : INT;
		move : MC_MoveVelocity;
	END_VAR
	FOR i := 1 TO 80 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		move(Axis := m.drive, Execute := power.Status, Velocity := 1000.0);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, ProfileVelocity := m.drive_Profile_velocity,
		    TargetVelocity := m.drive_Target_velocity);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_EQ(m.drive_Modes_of_operation, 3);
	ASSERT_EQ(m.drive_Target_velocity, 1000);
	ASSERT_EQ(m.drive_Velocity_actual_value, 1000);
	ASSERT_TRUE(move.InVelocity);
	status(Axis := m.drive, Enable := TRUE);
	ASSERT_TRUE(status.ContinuousMotion);
	ASSERT_GT(m.drive.fActPosition, 100.0);
END_TEST

TEST 'MC_MoveAbsolute reaches the target in profile position'
	VAR
		m : main;
		bus : DriveLink;
		power : MC_Power;
		status : MC_ReadStatus;
		i : INT;
		move : MC_MoveAbsolute;
		busy : BOOL;
	END_VAR
	FOR i := 1 TO 200 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		move(Axis := m.drive, Execute := power.Status, Position := 500.0, Velocity := 2000.0);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, ProfileVelocity := m.drive_Profile_velocity,
		    TargetVelocity := m.drive_Target_velocity);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_ok := bus.Online;
		IF move.Busy THEN busy := TRUE; END_IF
		(* Done can be TRUE before the drive takes the new set-point (the
		   library checks target reached, not the set-point acknowledge), so
		   trust it only after Busy. *)
		IF busy AND move.Done THEN EXIT; END_IF
	END_FOR
	ASSERT_TRUE(busy AND move.Done);
	ASSERT_EQ(m.drive_Modes_of_operation, 1);
	ASSERT_EQ(m.drive_Target_position, 500);
	ASSERT_EQ(m.drive_Profile_velocity, 2000);
	ASSERT_EQ(bus.Drive.Position, 500);
	ASSERT_NEAR(m.drive.fActPosition, 500.0, 0.5);
END_TEST

TEST 'a drive fault is error stop and MC_Reset clears it'
	VAR
		m : main;
		bus : DriveLink;
		power : MC_Power;
		status : MC_ReadStatus;
		i : INT;
		reset : MC_Reset;
		fault : BOOL;
	END_VAR
	FOR i := 1 TO 150 DO
		fault := i >= 40 AND i < 60;
		m();
		power(Axis := m.drive, Enable := i < 60 OR i >= 100);
		reset(Axis := m.drive, Execute := i >= 70 AND i < 90);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, ProfileVelocity := m.drive_Profile_velocity,
		    TargetVelocity := m.drive_Target_velocity, Fault := fault);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_ok := bus.Online;
		IF i = 55 THEN
			status(Axis := m.drive, Enable := TRUE);
	ASSERT_TRUE(status.Errorstop);
			ASSERT_TRUE(m.drive.bError);
			ASSERT_TRUE(power.Error);
		END_IF
		IF i = 89 THEN
			ASSERT_TRUE(reset.Done);
			ASSERT_FALSE(m.drive.bError);
		END_IF
	END_FOR
	ASSERT_EQ(bus.Drive.State, 4);
	ASSERT_TRUE(power.Status);
END_TEST

TEST 'a lost drive (status bit FALSE) is error stop'
	VAR
		m : main;
		bus : DriveLink;
		power : MC_Power;
		status : MC_ReadStatus;
		i : INT;
	END_VAR
	FOR i := 1 TO 60 DO
		m();
		power(Axis := m.drive, Enable := TRUE);
		bus(ControlWord := m.drive_Controlword, Modes := m.drive_Modes_of_operation,
		    TargetPosition := m.drive_Target_position, ProfileVelocity := m.drive_Profile_velocity,
		    TargetVelocity := m.drive_Target_velocity, Lost := i > 40);
		m.drive_Statusword := bus.StatusWord;
		m.drive_Modes_of_operation_display := bus.ModesDisplay;
		m.drive_Position_actual_value := bus.Position;
		m.drive_Velocity_actual_value := bus.Velocity;
		m.drive_ok := bus.Online;
	END_FOR
	ASSERT_FALSE(m.drive_ok);
	ASSERT_FALSE(m.drive.bCommunication);
	status(Axis := m.drive, Enable := TRUE);
	ASSERT_TRUE(status.Errorstop);
END_TEST
