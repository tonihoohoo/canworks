(* The HMI's variables: FUXA reads and writes them by name over the
   project's OPC UA server (devices/servers/opcua.json). The CAN values
   come from the canworks variable list, which canworks_in fills before
   and canworks_out sends after this program in every scan. *)
PROGRAM main
  VAR
    temp1 : REAL;              (* temperature 1, degrees C *)
    temp2 : REAL;              (* temperature 2, degrees C *)
    limit : REAL := 25.0;      (* written by the HMI *)
    ack : BOOL;                (* written by the HMI; cleared after use *)
    run : BOOL := TRUE;        (* running light on, written by the HMI *)
    alarm : BOOL;
    light_ok : BOOL;
    canworks_ok : BOOL;        (* the bridge answers with this program's map *)
    bus_ok : BOOL;             (* and the CAN bus is up *)
    rtd_ok : BOOL;             (* node 5 operational *)
    dio_ok : BOOL;             (* node 6 operational *)
    dio_in0 : USINT;
    dio_in1 : USINT;
    dio_out0 : USINT;
    dio_out1 : USINT;
    manual_out0 : USINT;       (* bits 1-7 of dio_out0, written by the HMI *)
    manual_out1 : USINT;       (* dio_out1 while run is off, written by the HMI *)
    logic : PLANT_LOGIC;
  END_VAR

  canworks_ok := canworks.ok;
  bus_ok := canworks.bus_ok;
  rtd_ok := canworks.rtd_ok;
  dio_ok := canworks.dio_ok;
  temp1 := INT_TO_REAL(canworks.rtd_temp1) / 10.0;
  temp2 := INT_TO_REAL(canworks.rtd_temp2) / 10.0;
  dio_in0 := canworks.dio_in0;
  dio_in1 := canworks.dio_in1;

  logic(VALID := canworks_ok AND rtd_ok, TEMP := temp1, LIMIT := limit, ACK := ack, RUN := run,
        DIO_IN1 := dio_in1, MANUAL_OUT0 := manual_out0, MANUAL_OUT1 := manual_out1);
  alarm := logic.ALARM;
  light_ok := logic.LIGHT_OK;
  dio_out0 := logic.DIO_OUT0;
  dio_out1 := logic.DIO_OUT1;
  ack := FALSE;

  canworks.dio_out0 := dio_out0;
  canworks.dio_out1 := dio_out1;
END_PROGRAM
