(* canworks: truST's I/O image for canworks-bridge; copy into the project's src folder. *)
VAR_GLOBAL
    cw_in AT %IB0 : ARRAY[0..65] OF BYTE; (* input registers 0..32 *)
    cw_out AT %QB0 : ARRAY[0..31] OF BYTE; (* holding registers 0..15 *)
END_VAR
