"""Shared serialization utilities for converting numpy types to JSON-serializable Python types."""

import numpy as np


def make_serializable(obj):
    """Recursively convert numpy types to JSON-serializable Python types.

    Handles dtype kinds ``biuU`` by ``tolist()`` and sends every other kind
    back through here. Known gaps, all passed through unchanged for
    ``json.dumps`` to refuse: ``datetime64``, ``timedelta64``, complex, and a
    bare ``np.void``. No caller produces any of them, and none has a
    representation worth picking blind.
    """
    # np.timedelta64 subclasses np.signedinteger, so it reaches this branch —
    # but int() on it raises rather than converting. Excluded so it falls
    # through to the passthrough, which is what the gap note above describes.
    if isinstance(obj, np.integer) and not isinstance(obj, np.timedelta64):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    # np.bytes_ is deliberately absent here: it subclasses bytes, so it falls
    # through to the decode below. Caught here it would go through str(), which
    # renders the repr — three bytes become the six characters b'dev'.
    if isinstance(obj, np.str_):
        return str(obj)
    if isinstance(obj, np.ndarray):
        # An allowlist, not a denylist: tolist() finishes the job only for
        # these kinds. It leaves bytes as bytes and — in an object or
        # structured array — numpy scalars as it found them. Anything
        # unfamiliar takes the careful path, since assuming tolist() finished
        # is what produced the bug this guard exists for.
        #
        # Floats are absent on purpose. longdouble is kind 'f' like float64
        # but tolist() hands it back as numpy, so one letter cannot cover
        # both, and it is not separable by itemsize (both are 8 bytes here).
        # The careful path costs microseconds at the sizes this sees — it
        # serializes metadata, not matrices — so accuracy wins. Every member
        # of biuU was checked: they all come back as clean Python types.
        if obj.dtype.kind in "biuU":
            return obj.tolist()
        return make_serializable(obj.tolist())
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [make_serializable(v) for v in obj]
    return obj
