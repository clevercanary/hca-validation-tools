#!/usr/bin/env python
"""Scan a tree of .h5ad files for masked (null) string elements.

The evidence behind the accepted gap recorded in
``docs/anndata-tools-contract.md``: masked string *values* and masked
*categories* are both reported by ``_io.masked_string_error``, which walks
every nullable-string element anndata can hold — obs/var/raw.var columns and
indexes, obsm/varm/uns frames, and the ``categories`` child of any
categorical.

Committed so the number in the contract is reproducible rather than asserted.

Run it through the package venv, which has anndata and h5py:

    cd packages/hca-anndata-tools
    uv run python ../../scripts/scan_masked_elements.py ~/hca-tracker-upload

Last run 2026-08-29: 223 real HDF5 files, 0 hits (1 unreadable — a
truncated download, not a masked-element finding).
"""

from __future__ import annotations

import sys
from pathlib import Path

import h5py

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages/hca-anndata-tools/src"))

from hca_anndata_tools._io import masked_string_error


def main(root: str) -> int:
    paths = [p for p in sorted(Path(root).rglob("*.h5ad")) if h5py.is_hdf5(p)]
    hits, unreadable = [], []
    for path in paths:
        try:
            with h5py.File(path, "r") as f:
                if reason := masked_string_error(f):
                    hits.append((path, reason))
        except Exception as e:  # a scan must not stop on one bad file
            unreadable.append((path, f"{type(e).__name__}: {e}"))

    print(f"real HDF5 .h5ad files scanned: {len(paths)}")
    print(f"  with masked string values or categories: {len(hits)}")
    for path, reason in hits:
        print(f"    {path.name}: {reason}")
    if unreadable:
        print(f"  could not be opened: {len(unreadable)}")
        for path, err in unreadable[:5]:
            print(f"    {path.name}: {err}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
