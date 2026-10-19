"""Whether an integrated object's CAP annotations are the ones CAP now publishes (#781).

The object keeps a copy of its export's ``uns['cap_metadata']`` from when
``copy_cap_annotations`` ran; gut v1 carried v4 for two months after v5 moved
to a new CAP project. The tracker's ``cap_url`` names the current dataset, not
the local export, which can be stale too.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal, get_args

import h5py
from anndata.io import read_elem

from ._errors import Refusal
from ._io import gate_h5ad_paths, open_h5ad, read_group, read_uns
from .cap import CAP_METADATA_KEY, LEGACY_LAYOUT_DESCRIPTION
from .guards import legacy_layout_problems
from .qc import run_read
from .sources import INTEGRATED_DIR

CAP_SOURCE_DIR = "cap-source"

# Reported for both copies; only the timestamp decides which is newer.
CAP_FIELDS = ("publication_version", "publication_timestamp", "cap_dataset_url", "cellannotation_schema_version")

# behind: another dataset or an older publication than the export. export_stale:
# no local export carries cap_url, or it is older than the object's copy.
Status = Literal["current", "behind", "export_stale", "absent"]
STATUSES: tuple[Status, ...] = get_args(Status)


def _read_cap(path: Path) -> tuple[bool, dict | None]:
    """Whether the file uses the deprecated top-level CAP layout, and its CAP block's fields (None if no block).

    Raw h5py, after the anndata open: the layout check takes the stored uns group.
    """
    with h5py.File(path, "r") as f:
        uns = read_uns(f)
        block = read_group(uns, CAP_METADATA_KEY) if uns is not None else None
        fields = None if block is None else {k: str(read_elem(block[k])) if k in block else None for k in CAP_FIELDS}
        return bool(legacy_layout_problems(uns)), fields


def _when(fields: dict, which: str) -> datetime:
    if fields["publication_timestamp"] is None:
        raise Refusal(f"the {which}'s CAP block has no publication_timestamp, so the two cannot be ordered")
    # CAP writes ISO 8601 with a trailing Z, which Python 3.10 does not parse.
    return datetime.fromisoformat(fields["publication_timestamp"].replace("Z", "+00:00"))


def _status(current: dict | None, export: dict | None, cap_url: str) -> Status:
    if current is None:
        return "absent"
    if export is None:
        return "export_stale"
    if current["cap_dataset_url"] != cap_url:
        return "behind"
    ours, theirs = _when(current, "object"), _when(export, "export")
    if theirs > ours:
        return "behind"
    return "export_stale" if theirs < ours else "current"


def _check_at_path(path: str, cap_url: str) -> dict:
    target = Path(path)
    root = next((p for p in target.parents if p.name == INTEGRATED_DIR), None)
    if root is None:
        raise Refusal(
            f"{target} is not under an '{INTEGRATED_DIR}' directory, so its CAP exports cannot be located; "
            f"the tracker layout keeps them in <project>/{INTEGRATED_DIR}/{CAP_SOURCE_DIR}/"
        )
    cap_dir = root / CAP_SOURCE_DIR
    if target.parent == cap_dir:
        raise Refusal(f"{target.name} is in {CAP_SOURCE_DIR}/, so it is a CAP export, not an integrated object")

    legacy, current = _read_cap(target)  # the gate has opened the target through anndata already
    if legacy:
        raise Refusal(f"Cannot check CAP currency: {target.name} uses {LEGACY_LAYOUT_DESCRIPTION}")

    # Every export is opened through anndata first, as the contract's Scope rule
    # requires. One anndata cannot open (a download still in progress, say) is
    # listed with anndata's error and never matched, so it does not block the rest.
    checked, matches = [], []
    for p in sorted(cap_dir.glob("*.h5ad")):
        try:
            with open_h5ad(str(p), backed="r"):
                pass
        except Exception as e:
            checked.append({"filename": p.name, "cap_dataset_url": None, "error": str(e)})
            continue
        p_legacy, fields = _read_cap(p)
        checked.append({"filename": p.name, "cap_dataset_url": fields and fields["cap_dataset_url"]})
        if fields and fields["cap_dataset_url"] == cap_url:
            matches.append((p, p_legacy, fields))
    if len(matches) > 1:
        names = ", ".join(p.name for p, _, _ in matches)
        raise Refusal(f"{len(matches)} exports in {cap_dir} carry {cap_url} ({names}); keep one")

    export = None
    if matches:
        p, p_legacy, fields = matches[0]
        if p_legacy:
            raise Refusal(
                f"{p.name} carries {cap_url} but uses {LEGACY_LAYOUT_DESCRIPTION}, which copy_cap_annotations "
                f"refuses; it has to be re-exported from CAP"
            )
        export = {"path": str(p), **fields}

    return {
        "filename": target.name,
        "status": _status(current, export, cap_url),
        "object": current,
        "export": export,
        "cap_source_dir": str(cap_dir),
        "exports_checked": checked,
    }


@gate_h5ad_paths
def check_cap_currency(path: str, cap_url: str) -> dict:
    """Report whether an integrated object's CAP annotations are current with CAP.

    Read-only; reads uns, no matrix. ``cap_url`` is the tracker's ``cap_url``
    for the object. The export carrying it is found by ``cap_dataset_url`` among
    the ``.h5ad`` files in ``cap-source/`` under the nearest ``integrated-objects``
    ancestor. ``behind`` means re-import with ``copy_cap_annotations``;
    ``export_stale`` means download the current export first.

    Refuses a path outside the tracker layout or inside ``cap-source/``, an
    object or matched export in the deprecated top-level CAP layout, and two
    exports carrying ``cap_url``. An export anndata cannot open is listed with
    anndata's ``error`` and never matched.

    Args:
        path: Integrated-object .h5ad; auto-resolves to the latest edit snapshot.
        cap_url: The tracker's ``cap_url`` for the object.

    Returns:
        Dict with ``filename``, ``status`` (one of :data:`STATUSES`),
        ``object`` and ``export`` (:data:`CAP_FIELDS`; the export with its
        ``path``; None when absent), ``cap_source_dir`` and
        ``exports_checked``, or ``{"error": ...}``.
    """
    return run_read(path, lambda resolved: _check_at_path(resolved, cap_url))
