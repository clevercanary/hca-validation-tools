"""Which cells carry a 10x barcode in their obs index ID (#679).

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
warn ``No barcodes found`` when no value has one. The search is carried
verbatim (:data:`BARCODE_RUN`). A 10x barcode is sixteen bases (fourteen on
the 2014 Chromium v1 chemistry), and every 10x pipeline writes it into the
cell ID, so an index with none is one whose IDs were regenerated —
positional integers, ``cell_<N>``, ``blood_qc-<N>`` — and can no longer be
joined to anything upstream. Lattice goes on to look each barcode up in the
union of the 10x whitelists; that half is #696, because the whitelists are
10x's and cannot ship with this package.

Deviations from the original, each with its reason:

1. **A count, not a warning line.** The original warns only when *no*
   value has a barcode. Here every cell is counted — how many carry a
   barcode, and how many of each length — and the finding fires on any
   barcode-less cell. Gut all-lineages has 111,869 barcode-less cells out of
   944,502, all one source dataset; the original's all-or-nothing warning
   is silent on it. The finding's sample IDs (``Krzak2023_119779``, ...)
   show which family they are.
2. **The run's true length, not the first sixteen.** The original cuts to
   sixteen because that is what the whitelist lookup joins on. A histogram
   that did the same would file a 24-base Parse or a 32-base concatenated
   multiome run under ``16`` beside genuine 10x barcodes, which is the one
   thing a length count is for. The cut moves to #696 with the lookup.
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
from .qc import SAMPLE_ID_LIMIT, finding, run_read

# ``extract_barcodes`` in the original: the run to search for. Twelve is
# Lattice's floor, not a 10x length; every run is reported at its own length
# here, and the cut to sixteen the original makes belongs to the whitelist
# lookup (#696).
BARCODE_RUN = re.compile(r"[ACTG]{12,}")
# Run length recorded for a value with no barcode.
NO_BARCODE = 0


@gate_h5ad_paths
def check_barcodes(path: str) -> dict:
    """Report which cells carry a 10x barcode in their ID.

    Read-only. The body reads the obs index and nothing else — no obs
    column, no matrix, no ``obsm`` — so its own cost is a regex pass over the
    IDs, a few seconds on a two-million-cell object. The gate's anndata open
    (#667) materialises the file's obs, obsm, and uns once before that, as it
    does for every tool, and on a wide obs that open is the larger share of
    the wall time. Needs no reference data; whether a barcode is on a 10x
    whitelist, and which chemistry it implies, is #696.

    Args:
        path: Path to an .h5ad file.

    Returns:
        Dict with ``filename``, ``n_obs``, ``structure``, and ``findings``.
        ``structure`` has ``with_barcode``, ``fraction`` (of cells whose ID
        holds a barcode), and ``by_length`` (cells per barcode run length,
        ``"0"`` for none; ``"16"`` is every 10x chemistry since 2016,
        ``"14"`` the 2014 Chromium v1, anything longer is a run that is not
        a 10x barcode on its own). ``findings`` is empty when every cell has
        a barcode; otherwise it holds one ``no_barcode_in_index`` in the
        shared finding shape — ``count`` = barcode-less cells, ``sample_ids``
        = up to 20 of their IDs, which show the ID family by example. No
        pass/fail verdict on the file. On failure, ``error`` is returned
        instead.
    """
    return run_read(path, _check_barcodes_at_path)


def barcode_length(value: str) -> int:
    """Lattice's search on one ID: the length of the first ``ACTG`` run of twelve or more, or :data:`NO_BARCODE`."""
    m = BARCODE_RUN.search(value)
    return len(m[0]) if m else NO_BARCODE


def _check_barcodes_at_path(path: str) -> dict:
    with h5py.File(path, "r") as f:
        obs = f["obs"]
        index_name = obs_index_name(obs)
        ids = read_index(obs, index_name, "obs")

    # One pass; every reported number is a projection of ``by_length``. The
    # barcode-less IDs are kept only up to the finding's cap, so nothing here
    # is sized by the index.
    by_length: Counter[int] = Counter()
    missing_ids: list[str] = []
    for value in ids:
        length = barcode_length(str(value))
        by_length[length] += 1
        if length == NO_BARCODE and len(missing_ids) < SAMPLE_ID_LIMIT:
            missing_ids.append(str(value))

    n_obs = len(ids)
    n_missing = by_length[NO_BARCODE]
    with_barcode = n_obs - n_missing
    findings: list[dict] = []
    if n_missing:
        findings.append(finding("no_barcode_in_index", n_missing, missing_ids, f"obs/{index_name}"))
    return {
        "filename": Path(path).name,
        "n_obs": n_obs,
        "structure": {
            "with_barcode": with_barcode,
            "fraction": with_barcode / n_obs if n_obs else 0.0,
            "by_length": {str(length): count for length, count in sorted(by_length.items(), reverse=True)},
        },
        "findings": findings,
    }
