"""Barcode structure of the obs index: which cells carry a 10x barcode, and what the IDs look like (#679).

A port of ``extract_barcodes`` from Lattice Data Coordination's
lattice-tools, ``cellxgene_resources/cellxgene_mods.py`` at commit
``8778a14f2a5a7039acf3ce74b3da220c24521905``:
https://github.com/Lattice-Data/lattice-tools/blob/8778a14f2a5a7039acf3ce74b3da220c24521905/cellxgene_resources/cellxgene_mods.py

    MIT License

    Copyright (c) 2020 Lattice Data Coordination

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

The original: for each obs index value, search for a run of twelve or more
``ACTG`` characters and keep the first sixteen of it as the cell's barcode;
warn ``No barcodes found`` when no value has one. That extraction is carried
verbatim (:data:`BARCODE_RUN`, :data:`BARCODE_MAX_LENGTH`). A 10x barcode is
sixteen bases (fourteen on the 2014 Chromium v1 chemistry), and every 10x
pipeline writes it into the cell ID, so an index with none is one whose IDs
were regenerated — positional integers, ``cell_<N>``, ``blood_qc-<N>`` — and
can no longer be joined to anything upstream. Lattice goes on to look each
barcode up in the union of the 10x whitelists; that half is #696, because the
whitelists are 10x's and cannot ship with this package.

Deviations from the original, each with its reason:

1. **A report, not a warning line.** The original warns only when *no*
   value has a barcode. Here every cell is counted: how many carry a
   barcode, how many of each length, and the ID *shapes* — each value with
   its barcode replaced by ``<Nnt>`` and every digit run collapsed to ``#``
   (``MH0023_mix_ACGT…-1`` → ``MH#_mix_<16nt>-#``), tallied most common
   first. An integrated object mixes IDs from many studies, and the shapes
   are how a reader sees which families are present and which lack barcodes.
2. **A finding on any barcode-less cell, not only when none is found.**
   Gut all-lineages has 111,869 barcode-less cells out of 944,502, all one
   source dataset; the original's all-or-nothing warning is silent on it.
   The finding carries the shapes of the barcode-less IDs so it names the
   family (``Krzak#_#``), not a bare count.
3. **Read-only through the shared gate**, obs index only. The original
   works on a loaded ``obs``; this reads one dataset from the file, so it
   costs seconds on a two-million-cell object and touches no matrix.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import h5py
import numpy as np

from ._io import gate_h5ad_paths, obs_index_name, read_index
from .qc import finding, run_read

# ``extract_barcodes`` in the original: the run to search for, and how much
# of it is the barcode. Twelve is Lattice's floor, not a 10x length; a
# twelve- or thirteen-base run is reported at its own length and joins
# nothing in #696.
BARCODE_RUN = re.compile(r"[ACTG]{12,}")
BARCODE_MAX_LENGTH = 16
# Run length recorded for a value with no barcode.
NO_BARCODE = 0
# Shapes listed per report; enough to see every study in an integrated
# object, not enough to fill a caller's context.
DEFAULT_SHAPES = 20

_DIGIT_RUN = re.compile(r"\d+")


@gate_h5ad_paths
def check_barcodes(path: str, shapes: int = DEFAULT_SHAPES) -> dict:
    """Report which cells carry a 10x barcode in their ID, and what the IDs look like.

    Read-only: reads the obs index and nothing else — no obs column, no
    matrix, no ``obsm`` — so it finishes in seconds on a two-million-cell
    object. Needs no reference data; whether a barcode is on a 10x whitelist,
    and which chemistry it implies, is #696.

    Args:
        path: Path to an .h5ad file.
        shapes: How many ID shapes to list, most common first. Must be >= 1.

    Returns:
        Dict with ``filename``, ``n_obs``, ``structure``, and ``findings``.
        ``structure`` has ``cells``, ``with_barcode``, ``fraction`` (of cells
        whose ID holds a barcode), ``by_length`` (cells per barcode length,
        ``"0"`` for none; ``"16"`` is every 10x chemistry since 2016,
        ``"14"`` the 2014 Chromium v1), and ``shapes`` — the distinct ID
        patterns with the barcode shown as ``<Nnt>`` and digit runs as
        ``#``, each with its cell count. ``findings`` is empty when every
        cell has a barcode; otherwise it holds one ``no_barcode_in_index``
        in the shared finding shape — ``count`` = barcode-less cells,
        ``sample_ids`` = up to 20 of their IDs — plus ``shapes``, the
        patterns of those IDs with counts, so the finding names the ID family
        rather than a number. No pass/fail verdict on the file. On failure,
        ``error`` is returned instead.
    """
    if not isinstance(shapes, int) or shapes < 1:
        return {"error": f"shapes must be a positive int, got {shapes!r}"}
    return run_read(path, lambda resolved: _check_barcodes_at_path(resolved, shapes))


def barcode_shape(value: str) -> tuple[int, str]:
    """Lattice's extraction on one ID: ``(barcode length, shape)``.

    The length is the first ``ACTG`` run of twelve or more, cut to sixteen,
    or :data:`NO_BARCODE`. The shape is the value with that run replaced by
    ``<Nnt>`` and every digit run collapsed to ``#``; with no run, just the
    digit collapse, so ``Krzak2023_119779`` reads ``Krzak#_#``.
    """
    m = BARCODE_RUN.search(value)
    if m is None:
        return NO_BARCODE, _DIGIT_RUN.sub("#", value)
    length = min(m.end() - m.start(), BARCODE_MAX_LENGTH)
    before = _DIGIT_RUN.sub("#", value[: m.start()])
    after = _DIGIT_RUN.sub("#", value[m.end() :])
    return length, f"{before}<{length}nt>{after}"


def _check_barcodes_at_path(path: str, shapes: int) -> dict:
    with h5py.File(path, "r") as f:
        obs = f["obs"]
        index_name = obs_index_name(obs)
        ids = read_index(obs, index_name, "obs")

    described = [barcode_shape(str(v)) for v in ids]
    lengths = np.fromiter((length for length, _ in described), dtype=np.int64, count=len(described))
    all_shapes = Counter(shape for _, shape in described)
    missing = lengths == NO_BARCODE
    n_obs = len(ids)
    with_barcode = n_obs - int(missing.sum())

    findings: list[dict] = []
    if missing.any():
        missing_shapes = Counter(shape for (length, shape) in described if length == NO_BARCODE)
        findings.append(
            finding(
                "no_barcode_in_index",
                int(missing.sum()),
                ids[missing],
                f"obs/{index_name}",
                shapes=_top(missing_shapes, shapes),
            )
        )

    by_length = Counter(int(length) for length in lengths)
    return {
        "filename": Path(path).name,
        "n_obs": n_obs,
        "structure": {
            "cells": n_obs,
            "with_barcode": with_barcode,
            "fraction": with_barcode / n_obs if n_obs else 0.0,
            "by_length": {str(length): count for length, count in sorted(by_length.items(), reverse=True)},
            "shapes": _top(all_shapes, shapes),
        },
        "findings": findings,
    }


def _top(counter: Counter, limit: int) -> list[dict]:
    """The ``limit`` most common shapes, as ``{"shape", "cells"}`` rows."""
    return [{"shape": shape, "cells": count} for shape, count in counter.most_common(limit)]
