"""Bus traces (canopen-bus-trace spec): frames recorded from the plugin's
diagnostics channel, CANopen decoding, file formats, statistics, triggers
and the recorder the configurator and canworks-diag share.

    model    Frame, Trace (packed 24-byte records, markers, gaps)
    formats  pcapng (native), candump log, ASC, BLF, TRC 2.1, CSV
    decode   CANopen decoding from a config and its EDS files
    stats    frame rate, bus load, per-identifier cycle times
    triggers trigger conditions and their evaluation
    recorder the recording loop over a diagnostics connection
"""
