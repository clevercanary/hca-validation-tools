"""Internal I/O utilities for AnnData file access."""

# pyright: reportArgumentType=none, reportReturnType=none
# h5py stubs return Group | Dataset | Datatype from __getitem__; runtime is always
# narrower (Group or Dataset). Asserting/casting at every site would add heavy
# churn without catching real bugs — this module is the narrowing boundary.

from __future__ import annotations

import functools
import gc
import inspect
import os
import warnings
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Literal, ParamSpec

import anndata as ad
import h5py
import pandas as pd
from anndata.io import read_elem, write_elem

from ._keys import EDIT_LOG_KEY, MASKED_STRING_REMEDY, PROVENANCE_KEY
from .write import resolve_latest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    import numpy as np
    from pandas.api.typing import NAType

# The HCA placeholder vocabulary (case-insensitive): obs values that mean
# "no data". replace_placeholder_values blanks exact (lowercased) matches of
# these; backfill_obs_from_source additionally treats empty/whitespace values
# as missing, via is_missing_value below.
DEFAULT_PLACEHOLDERS = [
    "unknown",
    "na",
    "n/a",
    "none",
    "not available",
    "not applicable",
    "tbd",
    "todo",
    "null",
    "undefined",
]


def is_missing_value(value: str | NAType, placeholders: set[str]) -> bool:
    """True if a value means "no data": pd.NA/NaN (readers hand masked
    entries through as pd.NA), empty/whitespace, or a placeholder (compare
    against a pre-lowercased set). NA is judged here, not at call sites —
    a caller-side guard is the per-site drift that reintroduces
    "'NAType' object has no attribute 'strip'" one consumer at a time."""
    if pd.isna(value):
        return True
    s = value.strip()
    return not s or s.lower() in placeholders


def iter_dataframe_groups(f: h5py.File) -> Iterator[tuple[str, h5py.Group]]:
    """Every dataframe group anndata serializes, as ``(label, group)``.

    The one roster: obs, var, raw/var, each obsm/varm/raw-varm frame, and
    dataframes nested anywhere in uns. Both the masked-categories open scan
    and the file normalization pass walk this, so a frame added to one
    cannot silently fall out of the other.
    """
    for path in ("obs", "var", "raw/var"):
        group = f.get(path)
        if isinstance(group, h5py.Group):
            yield path, group
    for holder_name in ("obsm", "varm", "raw/varm"):
        holder = f.get(holder_name)
        if not isinstance(holder, h5py.Group):
            continue
        label_prefix = "raw.varm" if holder_name == "raw/varm" else holder_name
        for key in holder:
            member = holder[key]
            if isinstance(member, h5py.Group) and encoding_of(member) == "dataframe":
                yield f"{label_prefix}['{key}']", member

    def walk_uns(prefix: str, group: h5py.Group) -> Iterator[tuple[str, h5py.Group]]:
        for key in group:
            member = group[key]
            if not isinstance(member, h5py.Group):
                continue
            label = f"{prefix}['{key}']"
            enc = encoding_of(member)
            if enc == "dataframe":
                yield label, member
            elif enc in (None, "dict"):
                yield from walk_uns(label, member)

    uns = f.get("uns")
    if isinstance(uns, h5py.Group):
        yield from walk_uns("uns", uns)


def _masked_categories_open_error(path: str) -> str | None:
    """Name the masked-categories column pandas' reader refused.

    anndata cannot *read* a categorical whose categories are masked — pandas
    raises "Categorical categories cannot be null" naming no column — so the
    column is found again via h5py. Best-effort by design: the file is
    already known bad, and a scan failure must not replace the original
    error with a second traceback.

    The index is named as an index rather than as a column. Since #661 this
    message is what a caller sees for the whole file rather than only what a
    tool that reached this shape saw, and telling someone to repair a column
    that is really the obs index sends them looking for the wrong thing.
    """
    with suppress(Exception), h5py.File(path, "r") as f:
        for label, group in iter_dataframe_groups(f):
            index_name = obs_index_name(group)
            for col in group:
                item = group[col]
                role = "index" if col == index_name else "column"
                if (
                    isinstance(item, h5py.Group)
                    and "categories" in item
                    and (reason := masked_categories_reason(read_categories(item), f"{label} {role} '{col}'"))
                ):
                    return reason
    return None


@contextmanager
def open_h5ad(path: str, backed: Literal["r", "r+"] | None = "r"):
    """Open an h5ad file with automatic cleanup.

    Args:
        path: Absolute path to an .h5ad file.
        backed: Backing mode. Use "r" for read-only (default), None for full in-memory read.

    Yields:
        An AnnData object.

    Raises:
        ValueError: With the column named, when the file holds a categorical
            whose categories are masked — a shape anndata itself cannot read
            (see :func:`masked_categories_reason`). anndata's own exception
            is chained (``from e``), so the naming is added on top rather
            than in place of it — but the chain survives only as far as a
            caller that preserves it, and the tool handlers currently return
            ``str(e)`` and drop it (#657). Since #661 every tool reaches
            this refusal, through :func:`gate_h5ad_paths`.
    """
    try:
        adata = ad.read_h5ad(path, backed=backed)
    except ValueError as e:
        if "Categorical categories cannot be null" in str(e) and (named := _masked_categories_open_error(path)):
            raise ValueError(named) from e
        raise
    try:
        yield adata
    finally:
        if hasattr(adata, "file") and adata.file is not None:
            adata.file.close()
        del adata
        gc.collect()


# The parameter names that carry a caller-supplied h5ad path. Gating is per
# path, not per tool: copy_cap_annotations opened its source through anndata
# and read its *target* with raw h5py, so a per-tool audit passed it while an
# unopenable target was still snapshotted and written (#661).
GATED_PATH_PARAMS = ("path", "source_path", "target_path")

_P = ParamSpec("_P")


def gate_h5ad_paths(fn: Callable[_P, dict]) -> Callable[_P, dict]:
    """Refuse a file anndata cannot open, before the tool reads it.

    The contract's Scope rule — we operate on files anndata can read — held
    only for tools that happened to go through :func:`open_h5ad`. Fifteen
    tools reached the file with raw h5py instead, and so ran to completion on
    a file nobody can open: the writers among them left a snapshot behind and
    reported success. This decorator is that rule's enforcement (#661).

    Every parameter named in :data:`GATED_PATH_PARAMS` is opened through
    anndata first, in declaration order. ``ad.read_h5ad`` is the whole
    predicate, so there is no list of failure modes here — a truncated
    download and a masked-categories column arrive as the same refusal.

    **We are not in the diagnosis business.** The gate is unconditional: a
    tool of ours reporting confidently on a file anndata rejected is the
    failure being removed, so the storage-layer readers are gated too even
    though they are how one might otherwise ask *why* a file will not open.

    Three behaviours the wrapper preserves deliberately:

    - **The refusal is anndata's own text.** ``str(e)`` and nothing else, per
      principle 11 and #661's AC3 — no summary, no explanation of ours.
    - **It returns rather than raises**, matching the ``{"error": ...}`` shape
      every tool already returns, so the gate cannot break a caller that
      expects a dict. This is also the single site #657 needs for these
      refusals instead of one per tool.
    - **A missing file falls through untouched**, so each tool keeps its own
      "File not found" message rather than getting h5py's.

    Paths are resolved with :func:`~hca_anndata_tools.write.resolve_latest`
    first, so the gate opens the file the tool will actually operate on.
    Resolving is idempotent, so the tool's own call is left in place.

    Raises:
        TypeError: At decoration time, if the function has no gated path
            parameter — a tool that cannot be gated is a mistake here, not a
            silent no-op.
    """
    sig = inspect.signature(fn)
    gated = [name for name in sig.parameters if name in GATED_PATH_PARAMS]
    if not gated:
        raise TypeError(
            f"{fn.__name__} has no parameter in {GATED_PATH_PARAMS} to gate. "
            f"A tool that opens an h5ad names its path parameter one of these; "
            f"one that opens no file should not carry this decorator."
        )

    @functools.wraps(fn)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> dict:
        try:
            bound = sig.bind_partial(*args, **kwargs)
            for name in gated:
                raw = bound.arguments.get(name)
                if raw is None:
                    continue
                # os.fspath so a pathlib.Path is gated like a str. Skipping
                # what is not a str fails *open*: the tool then reads the file
                # anyway, which is the hole this decorator exists to close.
                resolved = resolve_latest(os.fspath(raw))
                if not Path(resolved).is_file():
                    continue
                with open_h5ad(resolved, backed="r"):
                    pass
        except Exception as e:
            # Inside the try with the open, not beside it: resolve_latest globs
            # and Path.is_file stats, and both can raise (a name too long, a
            # permission error). Before #661 those ran inside each tool's own
            # handler and came back as {"error": ...}; letting one escape here
            # would turn a clean error into a tool-call failure.
            return {"error": str(e)}
        return fn(*args, **kwargs)

    # The roster AC2 enumerates against. Set here rather than inferred from
    # __wrapped__, which any functools.wraps decorator would also set, and
    # carrying the *names* so the check can catch a tool that gates one side
    # of a two-file operation and not the other.
    wrapper.__gated_paths__ = tuple(gated)  # pyright: ignore[reportFunctionMemberAccess]
    return wrapper


def _decode_bytes(val):
    """Decode bytes to str, pass through anything else."""
    if isinstance(val, bytes):
        return val.decode("utf-8")
    return val


def encoding_of(item: h5py.Group | h5py.Dataset | h5py.Datatype) -> str | None:
    """The declared ``encoding-type`` of an HDF5 item, or None if unstamped.

    A reader, not a guard: callers decide what an unfamiliar encoding means.
    Older AnnData wrote string arrays with no ``encoding-type`` at all, so
    None is "unstamped", not "invalid". Accepts the ``Group | Dataset |
    Datatype`` union h5py member access is typed as, so call sites need
    neither an isinstance dance nor a pyright suppression.
    """
    return _decode_bytes(item.attrs.get("encoding-type"))


def holds_string_values(item: h5py.Group | h5py.Dataset | h5py.Datatype) -> bool:
    """True if this element's values are strings, whatever its container.

    The one place the string-encoding taxonomy lives: a Dataset answers by
    dtype, and a Group holds strings only as a ``nullable-string-array`` —
    the values+mask serialization of pandas ``StringDtype``. Callers that
    fork on "can these values be compared or backfilled as strings" ask
    here, so the next string-holding encoding anndata ships is taught in
    one place rather than at every call site — per-site taxonomy tracking
    is the drift that produced hca-validation-tools#637.
    """
    if isinstance(item, h5py.Group):
        # Encoding only — a stamped-but-truncated group is caught by
        # read_element's corruption check, with the element named.
        return encoding_of(item) == "nullable-string-array"
    return h5py.check_string_dtype(item.dtype) is not None


def is_writable_element(item: h5py.Group | h5py.Dataset | h5py.Datatype) -> bool:
    """True if this package can write ``item`` back in place.

    The operative test is the container, not the encoding name.
    ``replace_string_dataset`` calls ``storage_like``, which copies chunking and
    compression off an existing Dataset; a Group — ``nullable-string-array``, or
    whatever multi-part encoding AnnData adds next — has none of those
    properties to copy (hca-validation-tools#641).

    Note what this is *not* about: anndata can write nullable strings, behind
    the ``allow_write_nullable_strings`` setting it ships defaulting to False.
    The constraint here is our own hand-rolled writer needing a Dataset, which
    no setting changes.

    Judging by encoding name instead would refuse elements that write perfectly
    well: a fixed-width byte index and a numeric categorical's ``categories``
    are both stamped ``array``, and both are Datasets. It would equally *pass*
    an unstamped Group, which then fails at the write.

    Since hca-validation-tools#637 the readers cope with every encoding
    anndata knows, and since #641 this predicate is *informational*: it
    feeds ``get_storage_info``'s report, and no writer refuses on it —
    ``replace_string_dataset`` normalizes a group target to a plain Dataset
    as it rewrites it, which is why "writable in place" here means
    "byte-preserving replace" rather than "rewritable at all".
    """
    return isinstance(item, h5py.Dataset)


def require_nullable_children(item: h5py.Group) -> None:
    """Raise the named corruption error for a truncated values+mask group.

    A stamped nullable group missing a child is a corrupt file (a truncated
    write); reaching into it directly would leak a raw KeyError. One spelling
    for every consumer — the readers and the normalizing writers alike.
    """
    enc = encoding_of(item) or "nullable"
    for child in ("values", "mask"):
        if child not in item:
            raise ValueError(f"'{item.name}' is stamped '{enc}' but has no '{child}' dataset — the file is corrupt")


def read_element(item: h5py.Group | h5py.Dataset | h5py.Datatype) -> np.ndarray:
    """Read a string or categorical element, whatever encoding it uses.

    The read counterpart of the write rule stated above ``replace_string_dataset``:
    use anndata where there is no storage layout to preserve, hand-roll only
    where there is. A read has no layout to carry, so it goes through
    ``read_elem`` — which dispatches on ``encoding-type`` via anndata's own
    registry and therefore handles ``string-array``, ``nullable-string-array``
    and whatever AnnData adds next, without this package tracking the taxonomy.

    Hand-rolled ``[:]`` slices are what broke on nullable indexes: a
    ``nullable-string-array`` is a *group* of ``values`` + ``mask``, so ``[:]``
    raises and ``.asstr()`` has no such attribute
    (hca-validation-tools#637). Reaching into ``values`` ourselves would
    re-implement the registry badly and break again on the next encoding.

    Returns an object array of decoded ``str``, matching what the hand-rolled
    readers returned. Two details are load-bearing:

    * **``dtype=object``** — a fixed-width unicode dtype would silently clip
      longer values assigned in later (see ``rename_cell_ids``).
    * **Decoding.** ``read_elem`` dispatches on ``encoding-type``, and a
      fixed-width byte array is stamped ``array`` (which is what anndata's own
      ``write_elem`` does for a numpy ``S``-kind array), so it comes back as
      raw ``bytes`` — no exception, no warning. The readers this replaced all
      decoded, and skipping it makes cell IDs compare unequal to their
      ``str`` counterparts: a join silently matches nothing rather than
      failing. Only the bytes case pays for the decode.

    Masked entries surface as ``pd.NA``; callers that cannot tolerate a
    missing value must check before converting to str, because ``str(pd.NA)``
    is ``"<NA>"`` and would turn every masked row into the *same* value.
    """
    import numpy as np

    if isinstance(item, h5py.Group) and (enc := encoding_of(item)) and enc.startswith("nullable-"):
        require_nullable_children(item)

    with warnings.catch_warnings():
        # anndata warns on every read of a legacy unstamped element. encoding_of
        # calls those "old, not invalid", and the readers handle them, so the
        # warning is noise the MCP server would repeat on every tool call
        # against such a file. Matched on the message, not the class: anndata
        # raises an OldFormatWarning, which is private and a
        # PendingDeprecationWarning subclass, so naming a category would couple
        # us to an internal.
        warnings.filterwarnings("ignore", message=".*written without encoding metadata.*")
        raw = read_elem(item)
    # atleast_1d: anndata's unstamped-dataset fallback unwraps a length-1
    # byte-string array to a scalar, which would otherwise reach callers as a
    # 0-d array they cannot iterate.
    raw = np.atleast_1d(np.asanyarray(raw))
    if raw.dtype.kind == "S":
        # Decode off the fixed-width array directly. Boxing to object first
        # allocates a bytes object per row that the next line discards:
        # 0.33s and 427 MB peak becomes 0.20s and 278 MB on a 2M-row index.
        return np.array([v.decode("utf-8") for v in raw.flat], dtype=object).reshape(raw.shape)
    values = np.asarray(raw, dtype=object)
    if values.size and isinstance(values.flat[0], bytes):
        # Variable-length bytes have no fixed-width array to decode off.
        values = np.array([_decode_bytes(v) for v in values.flat], dtype=object).reshape(values.shape)
    return values


def index_length(item: h5py.Group | h5py.Dataset | h5py.Datatype) -> int:
    """The row count of an index element, from HDF5 metadata where it can be.

    The one place this package looks inside a nullable group's ``values``
    child, and it is deliberately bounded to a *shape*: no decoding, no mask,
    nothing that re-implements anndata's registry — which is the reason the
    reads go through :func:`read_element` instead.

    :func:`read_element` answers the same question by materialising every ID:
    1.15s and 174 MB on a 944k-cell object, for a number HDF5 already stores in
    a header. Callers run it after a multi-gigabyte copy, with a curator
    already waiting.

    Anything else — an encoding we have not met, a scalar — falls through to
    ``read_element``, so the unknown case is correct but slow rather than
    wrong.
    """
    if isinstance(item, h5py.Dataset) and item.ndim:
        return item.shape[0]
    if isinstance(item, h5py.Group) and isinstance(values := item.get("values"), h5py.Dataset) and values.ndim:
        return values.shape[0]
    return read_element(item).shape[0]


def _strip_ensembl_version(eid: str) -> str:
    """Strip version suffix from Ensembl ID: ENSG00000173947.7 -> ENSG00000173947."""
    if eid.startswith("ENSG") and "." in eid:
        return eid.rsplit(".", 1)[0]
    return eid


def obs_index_name(obs: h5py.Group | h5py.Dataset | h5py.Datatype) -> str:
    """The name of the index dataset, from the group's ``_index`` attribute.

    A reader, not a guard — the same lookup obsm DataFrames and ``var`` need
    for their own index.
    """
    return _decode_bytes(obs.attrs.get("_index", "_index"))


def read_index(group: h5py.Group | h5py.Dataset | h5py.Datatype, name: str, label: str) -> np.ndarray:
    """Read a dataframe index, enforcing what every index read needs.

    An index is a join key, and a missing value in one is never legitimate:
    ``str(pd.NA)`` is ``"<NA>"``, so masked rows collapse to a single
    identifier. Worse than a crash — pandas joins ``pd.NA`` to ``pd.NA``, so a
    masked cell matches the *other* file's masked cell and is counted as a
    legitimate match (hca-validation-tools#637). ``check_duplicate_ids``
    catches that only for two or more masked rows; a single one passes.

    The underlying values usually survive a mask, so a masked index is
    repairable — but not by guessing here.

    Duplicates are deliberately **not** checked here. They have
    context-dependent remedies that only the caller knows: ``rename_cell_ids``
    distinguishes duplicates that already exist ("repair the file") from ones
    the rename would create ("change the arguments"), and folding that into a
    shared reader would flatten two refusals into one unhelpful message.
    Callers keep their own ``check_duplicate_ids``.

    Raises:
        ValueError: The index contains missing values, or is a categorical
            whose categories are masked (named here, before the read —
            pandas' own message names no element).
    """
    import numpy as np

    item = group[name]
    # A categorical index whose *categories* are masked would otherwise
    # surface as pandas' unnamed "Categorical categories cannot be null"
    # out of read_element (principle 11). Named in the shared reader so
    # rename, backfill, and every other index read refuse identically —
    # and before paying for the codes (read_categories is
    # distinct-value-sized).
    if (
        isinstance(item, h5py.Group)
        and "categories" in item
        and (reason := masked_categories_reason(read_categories(item), f"{label} index '{name}'"))
    ):
        raise ValueError(reason)
    values = read_element(item)
    missing = np.flatnonzero(pd.isna(values))
    if missing.size:
        raise ValueError(
            f"{label} index '{name}' has {missing.size} missing value(s) "
            f"(first at row {missing[0]}) — an entry with no identifier cannot be joined on"
        )
    return values


def masked_categories_reason(cats: pd.Index, subject: str) -> str | None:
    """Why these categories block a rewrite, or None if none are masked.

    A masked (pd.NA) category has no value a rewrite could keep —
    ``str(pd.NA)`` is ``"<NA>"`` — and none to compare against anything.
    Shared so the wording cannot drift between the tools that rewrite
    categoricals; ``subject`` is what varies.
    """
    n_masked = int(pd.isna(cats).sum())
    if not n_masked:
        return None
    return (
        f"{subject} has {n_masked} masked (null) categories — a masked "
        "category has no value a rewrite could keep; repair the column upstream first"
    )


def read_obs_index(path: str) -> list[str]:
    """Read the obs index (cell IDs) from an h5ad file.

    Raises:
        ValueError: The index has missing values. Duplicates are *not* checked
            — see :func:`read_index` for why that is left to callers.
    """
    with h5py.File(path, "r") as f:
        idx_key = obs_index_name(f["obs"])
        return list(read_index(f["obs"], idx_key, "obs"))


def read_column_order(obs: h5py.Group | h5py.Dataset | h5py.Datatype) -> list[str]:
    """Decode a dataframe group's ``column-order`` attribute to str names.

    The group-level core for callers already holding an open handle;
    :func:`read_obs_column_names` is the path-based wrapper. Accepts the
    ``Group | Dataset | Datatype`` union ``f["obs"]`` is typed as, so call
    sites need neither an isinstance dance nor a pyright suppression.
    """
    return [_decode_bytes(c) for c in obs.attrs["column-order"]]


def read_obs_column_names(path: str) -> list[str]:
    """Read obs column names from an h5ad file via h5py (no AnnData load)."""
    with h5py.File(path, "r") as f:
        return read_column_order(f["obs"])


def read_obs_categorical_values(path: str, column: str) -> set[str | NAType]:
    """Read the unique category values for a categorical obs column.

    The set can contain ``pd.NA``: a nullable column's masked rows, or a
    masked category, come through as NA (the annotation says so, so pyright
    holds callers to an NA policy instead of letting ``sorted``/``lower``
    crash at runtime on the liver shape).

    For categorical columns, HDF5 stores a small 'categories' array
    separately from the per-cell 'codes' array. This reads only the
    categories, avoiding the expensive full-column materialization.

    Note: returns all declared categories, which may include unused values
    if the file was subsetted without removing unused categories. This is
    acceptable because callers operate on full integrated objects, not subsets.

    Falls back to reading the full dataset for non-categorical columns.
    """
    with h5py.File(path, "r") as f:
        item = f["obs"][column]
        if isinstance(item, h5py.Group) and "categories" in item:
            return set(read_element(item["categories"]))
        # Non-categorical: read the full element
        return set(read_element(item))


def read_var_gene_names(path: str) -> tuple[set[str], dict[str, str]]:
    """Read gene names and Ensembl ID mapping from var via h5py.

    Returns:
        gene_names: Set of all gene symbols in var
        eid_to_var_name: Dict mapping Ensembl ID (stripped of version) to gene symbol
    """
    with h5py.File(path, "r") as f:
        var = f["var"]
        # read_index, not read_element: these Ensembl IDs are lookup keys, and
        # _strip_ensembl_version would hit pd.NA with an AttributeError about
        # NAType — the opaque failure this module now refuses by name.
        index = list(read_index(var, obs_index_name(var), "var"))

        # Find gene name column
        name_col = None
        for col in ("feature_name", "gene_name"):
            if col in var:
                name_col = col
                break

        if name_col is None:
            # Fallback: index IS the gene names
            return set(index), {}

        item = var[name_col]
        if isinstance(item, h5py.Group) and "categories" in item:
            categories, codes = read_categorical_data(item)
            names = [categories[c] if c >= 0 else "" for c in codes]
        else:
            names = list(read_element(item))
        # A masked name is no name — same as an unset categorical code above.
        # pd.NA must not escape into results: str(pd.NA) is "<NA>", and the
        # MCP layer cannot serialize NAType at all.
        names = ["" if pd.isna(n) else n for n in names]

        gene_names = set(names)

        eid_to_var_name = {_strip_ensembl_version(eid): name for eid, name in zip(index, names, strict=True)}

        return gene_names, eid_to_var_name


def require_stamped_group(f: h5py.File, path: str) -> h5py.Group:
    """``require_group`` plus the dict encoding attrs anndata expects.

    ``require_group`` leaves a group it creates bare, and anndata reads a group
    with no encoding metadata under an OldFormatWarning — so every site that
    may create a group stamps it here, at the creation, rather than relying on
    some later call to do it as a side effect. ``setdefault`` leaves the attrs
    of an existing group untouched.
    """
    group = f.require_group(path)
    group.attrs.setdefault("encoding-type", "dict")
    group.attrs.setdefault("encoding-version", "0.1.0")
    return group


def ensure_provenance_group(f: h5py.File) -> h5py.Group:
    """Get or create the uns/provenance group with correct encoding attrs.

    Stamps ``uns`` itself as well as the provenance group: ``require_group``
    creates a missing parent implicitly, so ``uns`` may be born here too.
    """
    require_stamped_group(f, "uns")
    return require_stamped_group(f, f"uns/{PROVENANCE_KEY}")


def read_group(parent: h5py.File | h5py.Group, name: str) -> h5py.Group | None:
    """``parent[name]`` as a group, or None when absent or not a group.

    ``get`` can hand back a Dataset on a malformed file, and callers treat
    these nodes as mappings — where h5py's answers on a Dataset range from
    AttributeError to a silently wrong ``in`` (#617). Narrowing here, once,
    is what keeps the call sites honest; :func:`read_uns` and
    :func:`read_provenance` are its two named shorthands.
    """
    node = parent.get(name)
    return node if isinstance(node, h5py.Group) else None


def read_uns(f: h5py.File) -> h5py.Group | None:
    """The file's uns group, or None when it is absent or not a group."""
    return read_group(f, "uns")


def read_batch_condition(uns: h5py.Group | None) -> list[str]:
    """Read ``uns['batch_condition']`` as a list of obs column names.

    The HCA schema types it ``element_type: match_obs_columns``, so every entry
    must name an obs column. Returns an empty list when absent or unreadable —
    an unreadable value is the validator's problem to report, not a reason for
    a mutating tool to refuse.
    """
    if uns is None or "batch_condition" not in uns:
        return []
    try:
        raw = uns["batch_condition"][()]
    except (OSError, TypeError, ValueError):
        return []
    if isinstance(raw, bytes | str):
        return [_decode_bytes(raw)]
    try:
        return [_decode_bytes(v) for v in raw]
    except TypeError:
        return []


def read_provenance(uns: h5py.Group | None) -> h5py.Group | None:
    """The provenance group, or None when absent or not a group."""
    if uns is None:
        return None
    return read_group(uns, PROVENANCE_KEY)


def read_edit_log_h5py(f: h5py.File) -> str:
    """Read the edit log JSON string from an open h5py File.

    Returns "[]" if no edit log exists.
    """
    prov = read_provenance(read_uns(f))
    log = prov.get(EDIT_LOG_KEY) if prov is not None else None
    if isinstance(log, h5py.Dataset):
        raw = log[()]
        if isinstance(raw, bytes | str):
            return _decode_bytes(raw)
    return "[]"


def write_edit_log_h5py(f: h5py.File, log_json: str) -> None:
    """Write the edit log JSON string into an open h5py File.

    Through anndata's ``write_elem``, per the rule below: the edit log is a
    plain string element with no storage layout to preserve, so anndata owns
    its encoding. ``write_elem`` overwrites the key itself.
    """
    write_elem(ensure_provenance_group(f), EDIT_LOG_KEY, log_json)


def read_categories(item: h5py.Group) -> pd.Index:
    """Read only the categories of a categorical h5py group.

    Distinct-value-sized, so a caller that may refuse (a masked-categories
    check) reads this before paying for the n_obs-sized codes.
    """
    return pd.Index(read_element(item["categories"]))


def read_categorical_data(item: h5py.Group) -> tuple[pd.Index, np.ndarray]:
    """Read categories and codes from a categorical h5py group.

    Args:
        item: An h5py Group with 'categories' and 'codes' datasets.

    Returns:
        (categories, codes) — pandas Index of decoded category strings and numpy codes array.
    """
    return read_categories(item), item["codes"][:]


def update_column_order(
    f_out: h5py.File,
    new_columns: list[str],
    deleted: set[str] | None = None,
) -> None:
    """Update the obs column-order attribute: remove deleted, append new.

    Columns that are both deleted and re-added preserve their original
    position. Only columns deleted but not re-added are removed. Truly
    new columns are appended at the end.

    Args:
        f_out: Open h5py File in append mode.
        new_columns: Column names to append (or replace in-place).
        deleted: Column names that were removed (if any).
    """
    current = [_decode_bytes(c) for c in f_out["obs"].attrs["column-order"]]
    if deleted:
        new_set = set(new_columns)
        # Only remove columns that were deleted and NOT re-added
        current = [c for c in current if c not in (deleted - new_set)]
    to_add = [c for c in new_columns if c not in current]
    f_out["obs"].attrs["column-order"] = current + to_add


def transplant_obs_columns(
    f_temp: h5py.File,
    f_out: h5py.File,
    columns: list[str],
    overwrite: bool = False,
) -> set[str]:
    """Copy obs columns from temp file to output file via h5py.copy().

    Optionally deletes existing columns first (overwrite mode).
    Updates column-order attribute.

    Args:
        f_temp: Source h5py File (read mode) with columns in obs.
        f_out: Target h5py File (append mode).
        columns: Column names to transplant.
        overwrite: If True, delete existing columns before copying.

    Returns:
        Set of column names that were deleted (empty if not overwriting).
    """
    deleted = set()
    copied = []
    for col in columns:
        if col not in f_temp["obs"]:
            continue
        if col in f_out["obs"]:
            if overwrite:
                del f_out["obs"][col]
                deleted.add(col)
            else:
                continue
        f_temp.copy(f"obs/{col}", f_out["obs"])
        copied.append(col)

    update_column_order(f_out, copied, deleted)
    return deleted


def check_duplicate_ids(index, label: str) -> str | None:
    """Return an error message if index has duplicates, else None.

    Accepts anything pd.Index accepts (list, ndarray, or an existing Index,
    which passes through without a copy); the check runs in pandas' C
    hashtable rather than a per-element Python loop.
    """
    idx = pd.Index(index)
    if not idx.has_duplicates:
        return None
    dupes = idx[idx.duplicated()].unique()[:5].tolist()
    return f"{label} have duplicate IDs (first 5): {dupes}"


# The rule for the two encoders below, and for anything added beside them:
# use anndata's ``write_elem`` where there is no storage layout to preserve
# (see write_edit_log_h5py, and batch_condition in rename_column); hand-roll
# only where there is. These two carry the original dataset's compression,
# chunks and maxshape — and, for a categorical, the narrowed codes dtype —
# forward across a delete-and-recreate, which write_elem would discard.
def storage_like(ds: h5py.Dataset) -> dict:
    """The storage properties to carry across a delete-and-recreate."""
    return {
        "compression": ds.compression,
        "compression_opts": ds.compression_opts,
        "chunks": ds.chunks,
        "shuffle": ds.shuffle,
        "fletcher32": ds.fletcher32,
        # A contiguous dataset reports maxshape == shape; passing any
        # non-None maxshape to create_dataset forces chunked layout, so
        # only carry it when the dataset is actually resizable.
        "maxshape": ds.maxshape if ds.maxshape != ds.shape else None,
    }


def replace_string_dataset(parent: h5py.Group, name: str, data: np.ndarray) -> None:
    """Delete and recreate a string dataset, preserving its attrs and storage.

    A ``nullable-string-array`` *group* target is normalized as it is
    rewritten: the new data lands as a plain ``string-array`` Dataset with
    storage settings carried from the old ``values`` child — every write
    fixes the format in its own path (#641), so no caller has to refuse an
    encoding or send the curator to another tool. Callers guarantee ``data``
    holds no pd.NA (their masked checks run before the snapshot).
    """
    ds = parent[name]
    if isinstance(ds, h5py.Group):
        if "codes" in ds and "categories" in ds:
            # A categorical group target — anndata writes a CategoricalIndex
            # this way. Flatten it: ``data`` is already the full per-row
            # array, and the row-shaped ``codes`` child carries the storage
            # settings. ``ordered`` is categorical machinery with no meaning
            # on a plain dataset, so it does not survive.
            layout = ds["codes"]
            dropped = ("encoding-type", "encoding-version", "ordered")
        else:
            require_nullable_children(ds)
            layout = ds["values"]
            dropped = ("encoding-type", "encoding-version")
        storage = storage_like(layout)  # pyright: ignore[reportArgumentType]
        # Preserve whatever else a producer stamped on the group; only what
        # describes the old encoding changes, because that is what changed.
        attrs = {k: v for k, v in ds.attrs.items() if k not in dropped}
        attrs |= {"encoding-type": "string-array", "encoding-version": "0.2.0"}
    else:
        attrs = dict(ds.attrs)
        storage = storage_like(ds)
    del parent[name]
    new_ds = parent.create_dataset(name, data=data, dtype=h5py.string_dtype(encoding="utf-8"), **storage)
    for key, attr_value in attrs.items():
        new_ds.attrs[key] = attr_value


def compact_categories(categories: list[str], codes: np.ndarray) -> tuple[list[str], np.ndarray, list[int]]:
    """Drop categories no code references and remap the codes accordingly.

    Codes below 0 (NaN) stay -1. Returns the kept categories, the remapped
    codes as int64 (:func:`replace_categorical_column` sizes the on-disk dtype
    itself), and the *positions* the kept categories held before — which
    :func:`remap_palette` needs to keep a per-category palette aligned.
    """
    import numpy as np

    valid = codes >= 0
    # Range-check before bincount: one corrupt out-of-range code would
    # otherwise size the bincount allocation to max(code)+1 entries.
    if valid.any() and int(codes[valid].max()) >= len(categories):
        raise ValueError(
            f"categorical codes reference category {int(codes[valid].max())} "
            f"but only {len(categories)} categories exist — the column is corrupt"
        )
    used = np.flatnonzero(np.bincount(codes[valid], minlength=len(categories)))
    kept = [categories[i] for i in used]
    lookup = np.full(len(categories), -1, dtype=np.int64)
    lookup[used] = np.arange(len(used))
    new_codes = np.full(codes.shape, -1, dtype=np.int64)
    new_codes[valid] = lookup[codes[valid]]
    return kept, new_codes, used.tolist()


def direct_members(group: h5py.Group) -> set[str]:
    """A group's direct children, for membership tests.

    Membership against this set, not ``name in group`` — h5py's
    ``__contains__`` resolves link paths, so it accepts names that point
    outside the group entirely (the ``/`` trap ``guards.is_malformed_name``
    rejects). True of any group, which is why uns lookups use it too.
    """
    return set(group.keys())


def remap_palette(uns: h5py.Group | None, key: str | None, kept: Sequence[int], n_before: int) -> str | None:
    """Keep only the colours of the categories that survived, by position.

    ``uns['<column>_colors']`` is positionally aligned to the column's
    categories, so removing a category shifts every colour after it — and the
    HCA validator checks only the palette's *length*, so a file whose lengths
    happen to still agree is simply mis-coloured with nothing reported. Every
    tool that removes a category owes this remap (#624).

    Takes the surviving positions rather than calling
    :func:`compact_categories` itself, because not every caller may use that
    function: ``merge_obs_categories`` must not, since it drops every
    unreferenced category and would discard one left empty for its own reasons.

    Returns the key it rewrote, or None when there was nothing to do: no
    palette, or one this function cannot safely interpret — a length that
    already disagrees with ``n_before``, or a node that is not a string array.
    An already-broken palette is the validator's to report, not this
    function's to guess at.
    """
    import numpy as np

    if uns is None or key is None or key not in direct_members(uns):
        return None
    node = uns[key]
    # A palette that is not a one-dimensional string Dataset is not one we can
    # realign, and the write below could not recreate it in place. Rejected
    # here, before any read. Treated like a mismatched length: left alone.
    if not isinstance(node, h5py.Dataset) or node.ndim != 1 or not h5py.check_string_dtype(node.dtype):
        return None
    colors = list(read_element(node))
    if len(colors) != n_before:
        return None
    write_elem(uns, key, np.array([colors[i] for i in kept], dtype=object))
    return key


def _codes_dtype(n_categories: int, original: np.dtype) -> np.dtype:
    """Smallest signed dtype holding the category count, never narrower than
    the original codes dtype (extending categories can overflow int8)."""
    import numpy as np

    for dt in (np.int8, np.int16, np.int32, np.int64):
        if np.iinfo(dt).max >= n_categories - 1 and np.dtype(dt).itemsize >= original.itemsize:
            return np.dtype(dt)
    return np.dtype(np.int64)


def replace_categorical_column(parent: h5py.Group, col: str, categories: list[str], codes: np.ndarray) -> None:
    """Delete and recreate a categorical column group, preserving its encoding
    attrs and the codes dataset's storage settings (see storage_like).

    The codes are written at the smallest dtype that holds the new category
    count without narrowing the original — a caller that extended the
    categories does not have to know about int8 overflow.
    """
    import numpy as np

    item = parent[col]
    encoding_type = item.attrs["encoding-type"]
    encoding_version = item.attrs["encoding-version"]
    ordered = bool(item.attrs["ordered"])
    codes_storage = storage_like(item["codes"])
    codes = codes.astype(_codes_dtype(len(categories), item["codes"].dtype))

    del parent[col]
    grp = parent.create_group(col)
    grp.attrs["encoding-type"] = encoding_type
    grp.attrs["encoding-version"] = encoding_version
    grp.attrs["ordered"] = ordered
    cat_data = np.array(categories, dtype=object) if categories else np.array([], dtype=h5py.string_dtype())
    cat_ds = grp.create_dataset("categories", data=cat_data)
    cat_ds.attrs["encoding-type"] = "string-array"
    cat_ds.attrs["encoding-version"] = "0.2.0"
    codes_ds = grp.create_dataset("codes", data=codes, **codes_storage)
    codes_ds.attrs["encoding-type"] = "array"
    codes_ds.attrs["encoding-version"] = "0.2.0"


def _iter_string_element_targets(f: h5py.File) -> Iterator[tuple[h5py.Group, str]]:
    """``(parent, name)`` of every element that may hold string values.

    Dataframe members via :func:`iter_dataframe_groups` (a categorical
    member targets its ``categories`` child), plus the *group-shaped*
    string carriers nested in uns: nullable arrays (values+mask groups) and
    the ``categories`` child of a bare uns categorical. Plain h5py Datasets
    in uns are already plain and are deliberately not walked.
    One walker for the normalizer, so an element cannot fall between the
    dataframe and uns halves.
    """
    for _, df in iter_dataframe_groups(f):
        # Sorted: direct_members is a set, and both encodings_normalized and
        # the masked-element message should be stable between runs.
        for name in sorted(direct_members(df)):
            item = df[name]
            if isinstance(item, h5py.Group):
                if "categories" in item:
                    yield item, "categories"
                else:
                    yield df, name

    def walk_uns(group: h5py.Group) -> Iterator[tuple[h5py.Group, str]]:
        for key in group:
            member = group[key]
            if not isinstance(member, h5py.Group):
                continue
            enc = encoding_of(member)
            if enc in (None, "dict"):
                yield from walk_uns(member)
            elif enc == "dataframe":
                continue  # covered via iter_dataframe_groups
            elif "categories" in member:
                yield member, "categories"
            else:
                yield group, key

    uns = f.get("uns")
    if isinstance(uns, h5py.Group):
        yield from walk_uns(uns)


def _nullable_string_targets(f: h5py.File) -> Iterator[tuple[h5py.Group, str, str]]:
    """The ``(parent, name, loc)`` triples the file normalizer acts on."""
    for parent, name in _iter_string_element_targets(f):
        target = parent[name]
        if isinstance(target, h5py.Group) and encoding_of(target) == "nullable-string-array":
            yield parent, name, f"{parent.name}/{name}".removeprefix("/")


def masked_string_error(f: h5py.File, ignore_obs_columns: Sequence[str] = ()) -> str | None:
    """The named refusal for masked nullable-string elements, or None.

    Judged off the tiny on-disk ``mask`` datasets alone — cheap enough to
    run read-only against a multi-gigabyte *source* before any copy is made
    (convert), and against an output before anything is rewritten. Names
    every masked element with its count in one message.

    ``ignore_obs_columns``: obs columns the caller's pipeline deletes before
    writing (convert's SRE strip) — a masked value there never reaches the
    output, so refusing on it would make the preflight stricter than the
    chokepoint it fronts for.
    """
    import numpy as np

    masked: list[str] = []
    for parent, name, loc in _nullable_string_targets(f):
        if ignore_obs_columns:
            # Skip anything under an ignored obs column — the column itself
            # or its categories child (a categorical group's nullable
            # encoding lives one level down).
            parts = (parent.name or "").split("/")  # ('', 'obs') or ('', 'obs', col)
            if len(parts) >= 2 and parts[1] == "obs":
                owner = name if len(parts) == 2 else parts[2]
                if owner in ignore_obs_columns:
                    continue
        target = parent[name]
        require_nullable_children(target)  # pyright: ignore[reportArgumentType]
        if n_masked := int(np.count_nonzero(np.asarray(target["mask"][:]))):  # pyright: ignore[reportIndexIssue]
            masked.append(f"{loc} ({n_masked})")
    if masked:
        return f"{', '.join(masked)} hold(s) {MASKED_STRING_REMEDY}"
    return None


def normalize_file_string_encodings(f: h5py.File) -> tuple[list[str], str | None]:
    """Normalize every nullable-string element in an open file to the profile.

    Walks :func:`_iter_string_element_targets` — dataframe indexes, plain
    columns, and categorical ``categories``, plus bare arrays and
    categoricals nested in uns. Masked elements refuse via
    :func:`masked_string_error` before anything is rewritten; the rewrite
    itself is :func:`replace_string_dataset`'s normalizing branch, so this
    pass and the in-place tools produce the identical on-disk shape.
    """
    if err := masked_string_error(f):
        return [], err
    normalized: list[str] = []
    # Materialized before rewriting: replace_string_dataset deletes and
    # recreates elements inside groups the generator would still be
    # iterating, and mutating an HDF5 group mid-iteration is undefined.
    for parent, name, loc in list(_nullable_string_targets(f)):
        # The values child alone: the mask is known all-zero, and reading
        # the assembled nullable element would pay for it a second time.
        replace_string_dataset(parent, name, read_element(parent[name]["values"]))  # pyright: ignore[reportIndexIssue, reportArgumentType]
        normalized.append(loc)
    return normalized, None


def verify_categorical_integrity(
    f: h5py.File,
    columns: list[str],
    expected_valid_counts: dict[str, int] | None = None,
) -> str | None:
    """Check categorical obs columns for data corruption.

    Verifies: codes length matches obs count, all codes in range,
    no codes below -1. Optionally checks that the number of non-NaN
    values matches expected counts (catches NaN→valid corruption).

    Args:
        f: Open h5py File.
        columns: Column names to check.
        expected_valid_counts: If provided, {col: expected_non_nan_count}.

    Returns:
        None if all columns pass, or an error message string.
    """
    obs = f["obs"]
    # Not len(obs[idx_key]): on a nullable index that is the *member* count of
    # the values+mask group — 2 — so every column would be reported corrupt.
    n_obs = index_length(obs[obs_index_name(obs)])

    for col in columns:
        item = obs[col]
        if not (isinstance(item, h5py.Group) and "categories" in item):
            continue
        n_cats = index_length(item["categories"])
        codes = item["codes"][:]

        if len(codes) != n_obs:
            return f"Column '{col}': codes length {len(codes)} != n_obs {n_obs}"
        if (codes < -1).any():
            return f"Column '{col}': found codes below -1"
        valid = codes[codes >= 0]
        if len(valid) > 0 and n_cats > 0 and int(valid.max()) >= n_cats:
            return f"Column '{col}': max code {valid.max()} >= n_categories {n_cats}"
        if expected_valid_counts and col in expected_valid_counts:
            actual = int((codes >= 0).sum())
            expected = expected_valid_counts[col]
            if actual != expected:
                return f"Column '{col}': expected {expected} valid values, got {actual}"

    return None


def verify_obs_transplant(
    temp_path: str,
    output_path: str,
    columns: list[str],
) -> str | None:
    """Verify obs columns were transplanted correctly via full-column comparison.

    Compares raw HDF5 data (categories + codes for categoricals, or full
    dataset for non-categoricals) between temp and output for each column.

    Returns:
        None if all columns match, or an error message string on mismatch.
    """
    import numpy as np

    with h5py.File(temp_path, "r") as f_temp, h5py.File(output_path, "r") as f_out:
        for col in columns:
            temp_item = f_temp["obs"][col]
            out_item = f_out["obs"][col]

            if isinstance(temp_item, h5py.Group) and "categories" in temp_item:
                if not np.array_equal(read_element(temp_item["categories"]), read_element(out_item["categories"])):
                    return f"Verification failed: categories mismatch for column '{col}'"
                if not np.array_equal(temp_item["codes"][:], out_item["codes"][:]):
                    return f"Verification failed: codes mismatch for column '{col}'"
            else:
                # read_elem, not read_element: this branch compares whatever the
                # column holds, and object-boxing a float column costs ~14x here
                # for no gain. dtype=object exists for callers that assign
                # longer strings back in; a comparison does not.
                # Not np.array_equal: it raises on object arrays holding
                # pd.NA and calls NaN != NaN, so a byte-perfect float or
                # nullable column would fail verification. Series.equals
                # treats missing as equal to missing.
                if not pd.Series(read_elem(temp_item)).equals(pd.Series(read_elem(out_item))):
                    return f"Verification failed: data mismatch for column '{col}'"

    return None
