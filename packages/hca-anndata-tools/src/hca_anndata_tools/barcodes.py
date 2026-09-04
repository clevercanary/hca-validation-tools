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
   works on a loaded ``obs``; the body here reads one dataset from the file
   and touches no matrix. (The gate's own anndata open still materialises
   obs and obsm first, as for every tool — see :func:`check_barcodes`.)
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import h5py

from ._io import gate_h5ad_paths, obs_index_name, read_index
from .qc import SAMPLE_ID_LIMIT, finding, run_read_check

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

    Read-only. The body reads the obs index and nothing else — no obs
    column, no matrix, no ``obsm`` — so its own cost is a regex pass over the
    IDs, a few seconds on a two-million-cell object. The gate's anndata open
    (#667) materialises the file's obs, obsm, and uns once before that, as it
    does for every tool, and on a wide obs that open is the larger share of
    the wall time. Needs no reference data; whether a barcode is on a 10x
    whitelist, and which chemistry it implies, is #696.

    Args:
        path: Path to an .h5ad file.
        shapes: How many ID shapes to list, most common first. Must be >= 1.

    Returns:
        Dict with ``filename``, ``n_obs``, ``structure``, and ``findings``.
        ``structure`` has ``with_barcode``, ``fraction`` (of cells whose ID
        holds a barcode), ``by_length`` (cells per barcode length,
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
    return run_read_check(path, shapes, _check_barcodes_at_path, knob="shapes")


def barcode_shape(value: str) -> tuple[int, str]:
    """Lattice's extraction on one ID: ``(barcode length, shape)``.

    The length is the first ``ACTG`` run of twelve or more, cut to sixteen,
    or :data:`NO_BARCODE`. The shape is the value with every digit run
    collapsed to ``#`` and that run replaced by ``<Nnt>``; with no run, just
    the digit collapse, so ``Krzak2023_119779`` reads ``Krzak#_#``.
    """
    # Digits collapse first: a barcode run holds no digit and ``#`` is not a
    # base, so the search finds the same run in the collapsed string.
    shape = _DIGIT_RUN.sub("#", value)
    m = BARCODE_RUN.search(shape)
    if m is None:
        return NO_BARCODE, shape
    length = min(len(m[0]), BARCODE_MAX_LENGTH)
    return length, f"{shape[: m.start()]}<{length}nt>{shape[m.end() :]}"


def _check_barcodes_at_path(path: str, shapes: int) -> dict:
    with h5py.File(path, "r") as f:
        obs = f["obs"]
        index_name = obs_index_name(obs)
        ids = read_index(obs, index_name, "obs")

    # One pass; every reported number is a projection of these tallies. The
    # barcode-less IDs are kept only up to the finding's cap — the count
    # comes from ``by_length`` — so nothing here is sized by the index.
    all_shapes: Counter[str] = Counter()
    missing_shapes: Counter[str] = Counter()
    missing_ids: list[str] = []
    by_length: Counter[int] = Counter()
    for value in ids:
        length, shape = barcode_shape(str(value))
        all_shapes[shape] += 1
        by_length[length] += 1
        if length == NO_BARCODE:
            missing_shapes[shape] += 1
            if len(missing_ids) < SAMPLE_ID_LIMIT:
                missing_ids.append(str(value))

    n_obs = len(ids)
    n_missing = by_length[NO_BARCODE]
    with_barcode = n_obs - n_missing
    findings: list[dict] = []
    if n_missing:
        findings.append(
            finding(
                "no_barcode_in_index",
                n_missing,
                missing_ids,
                f"obs/{index_name}",
                shapes=_top(missing_shapes, shapes),
            )
        )
    return {
        "filename": Path(path).name,
        "n_obs": n_obs,
        "structure": {
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
