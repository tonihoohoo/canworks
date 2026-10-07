"""The verdict of a bit rate sweep (canopen-online-diagnostics, "Bit rate
detection"), for the sweeps the PC tools run themselves on a local adapter.

The plugin has the same rules in C++ (decide_sweep in
plugin/src/bitrate_sweep.cpp); test/fixtures/sweep_verdicts.json holds the
cases both are tested against.
"""

RATES = (1000, 800, 500, 250, 125, 50, 20, 10)  # kbit/s, the CiA 301 rates in sweep order


def matches(frames, error_frames):
    """A rate matches when it saw a valid frame and its error frames are at
    most 1 % of its valid frames."""
    return frames > 0 and error_frames * 100 <= frames


def decide(results):
    """results: [{bitrate_kbit, frames, error_frames}] in sweep order ->
    {verdict, bitrate_kbit, candidates}. Exactly one match: detected. More
    than one: ambiguous with them. None but frames somewhere: ambiguous with
    the rate that had the most. No frames at all: silent."""
    candidates = [r["bitrate_kbit"] for r in results if matches(r["frames"], r["error_frames"])]
    if len(candidates) == 1:
        return {"verdict": "detected", "bitrate_kbit": candidates[0], "candidates": []}
    if candidates:
        return {"verdict": "ambiguous", "bitrate_kbit": None, "candidates": candidates}
    most = None
    for r in results:
        if r["frames"] and (most is None or r["frames"] > most["frames"]):
            most = r
    if most is not None:
        return {"verdict": "ambiguous", "bitrate_kbit": None, "candidates": [most["bitrate_kbit"]]}
    return {"verdict": "silent", "bitrate_kbit": None, "candidates": []}
