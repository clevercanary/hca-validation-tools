"""HCA Validator - extends cellxgene Validator with HCA-specific rules."""

import functools
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from anndata.compat import DaskArray
from dask.array import map_blocks  # pyright: ignore[reportPrivateImportUsage]
from scipy import sparse

from hca_schema_validator._vendored.cellxgene_schema import gencode
from hca_schema_validator._vendored.cellxgene_schema.gencode import get_gene_checker
from hca_schema_validator._vendored.cellxgene_schema.ontology_parser import ONTOLOGY_PARSER
from hca_schema_validator._vendored.cellxgene_schema.utils import getattr_anndata
from hca_schema_validator._vendored.cellxgene_schema.validate import Validator

from . import __schema_version__ as HCA_SCHEMA_VERSION
from .labeler import HCA_DERIVED_OBS_LABELS

# GENCODE version info (loaded once at module level)
_GENE_INFO_PATH = Path(__file__).parent / "_vendored" / "cellxgene_schema" / "gencode_files" / "gene_info.yml"
with _GENE_INFO_PATH.open() as _f:
    _gene_info = yaml.safe_load(_f)

# Schema file constants
SCHEMA_DIR = "schema_definitions"
SCHEMA_FILENAME = "hca_schema_definition.yaml"


class HCAValidator(Validator):
    """
    HCA-specific validator extending cellxgene schema validation.

    Uses a custom schema definition that differs from CELLxGENE in key areas:
    - organism and organism_ontology_term_id are in obs (not uns)
    """

    def __init__(self, ignore_labels=True):
        """
        Initialize HCA validator.

        Args:
            ignore_labels: If True, skip label validation
        """
        super().__init__(ignore_labels=ignore_labels)
        # Initialize all validator state so the exception handler in
        # validate_adata() works even if reset() hasn't been called yet.
        self.reset()

    def _set_schema_def(self):
        """
        Sets schema dictionary using HCA-specific schema definition.

        Overrides the base method to load HCA's custom schema instead of
        the default CELLxGENE schema.
        """
        if not self.schema_version:
            # Use HCA schema version
            self.schema_version = HCA_SCHEMA_VERSION

        if not self.schema_def:
            # Load HCA-specific schema
            schema_path = Path(__file__).parent / SCHEMA_DIR / SCHEMA_FILENAME

            with schema_path.open() as fp:
                self.schema_def = yaml.safe_load(fp)

    def validate_adata(self, h5ad_path=None):
        """Override to reorder warnings — feature ID warnings come last."""
        result = super().validate_adata(h5ad_path)
        other, feature_id = [], []
        for w in self.warnings:
            (feature_id if "Feature ID '" in w else other).append(w)
        self.warnings = other + feature_id
        return result

    def _check_cosmetic_label_columns(self):
        warnings, errors = check_cosmetic_labels(self.adata, self.schema_def)
        self.warnings.extend(warnings)
        self.errors.extend(errors)

    def _check_x_normalization(self):
        warnings, errors = check_x_normalization(self.adata)
        self.warnings.extend(warnings)
        self.errors.extend(errors)

    def _deep_check(self):
        """
        The base class skips raw validation when *any* errors exist, but raw
        validation only depends on assay_ontology_term_id. We retry it here
        so raw-layer errors are reported in the same pass.
        """
        super()._deep_check()

        # Match by substring to avoid brittle coupling to exact upstream wording
        raw_skip_warnings = [w for w in self.warnings if "Validation of raw layer was not performed" in w]
        if raw_skip_warnings and "raw" in self.schema_def and "assay_ontology_term_id" in self.adata.obs.columns:
            for w in raw_skip_warnings:
                self.warnings.remove(w)
            self._validate_raw()

        self._check_cosmetic_label_columns()
        self._check_x_normalization()

    def _validate_list(self, list_name, current_list, element_type):
        """
        Extends base list validation with support for element_type: string.

        Validates that all elements are non-empty strings when element_type is "string".
        """
        super()._validate_list(list_name, current_list, element_type)
        if element_type == "string":
            for i in current_list:
                if not isinstance(i, str):
                    self.errors.append(f"Value '{i}' in list '{list_name}' is not valid, it must be a string.")
                elif len(i.strip()) == 0:
                    self.errors.append(f"Value in list '{list_name}' must not be empty or whitespace-only.")

    def _validate_dataframe(self, df_name):
        """
        Extends base dataframe validation with requirement_level support and
        scopes per-column sanity checks to schema-defined columns.

        Columns with requirement_level: strongly_recommended are removed from
        the schema before the base class runs (so it won't error on missing),
        then validated separately with warnings instead of errors.

        Columns with requirement_level: optional are also removed before the
        base class runs, then validated with full validation only if present.
        Missing optional columns produce no warning or error.

        Columns with requirement_level: forbidden are removed before the base
        class runs (so it never tries to validate values on them), then
        error if the column is present in the dataframe. The error text is
        taken from ``forbidden_error`` on the schema entry.

        For obs, the base class's per-column sanity loop is restricted to
        schema-defined columns. Curator-added extras (e.g. ``barcode``,
        ``original_cell_type``) and HCA fields defined only in the LinkML
        entity schemas are skipped, preventing zero-observation warnings
        and other type checks from amplifying on columns the h5ad validator
        has no rules for. Forbidden columns are intentionally excluded from
        ``schema_columns`` so they are also dropped from the per-column loop.
        """
        df_definition = self.schema_def["components"].get(df_name, {})
        if "columns" not in df_definition:
            super()._validate_dataframe(df_name)
            return

        # Capture the full schema column set before requirement_level
        # extraction below strips optional / strongly_recommended / forbidden
        # entries. Forbidden columns are excluded so the per-column sanity
        # loop ignores them even when they slip into obs. ``requirement_level``
        # comparisons are case-insensitive throughout so the validator stays
        # symmetric with HCALabeler's preflight (which already lowercases).
        schema_columns = {
            c for c, d in df_definition["columns"].items() if str(d.get("requirement_level", "")).lower() != "forbidden"
        }

        # Extract optional, strongly_recommended, and forbidden columns
        # before base class sees them.
        optional_columns = {}
        sr_columns = {}
        forbidden_columns = {}
        for col_name in list(df_definition["columns"]):
            col_def = df_definition["columns"][col_name]
            level = str(col_def.get("requirement_level", "")).lower()
            if level == "optional":
                optional_columns[col_name] = col_def
                del df_definition["columns"][col_name]
            elif level == "strongly_recommended":
                sr_columns[col_name] = col_def
                del df_definition["columns"][col_name]
            elif level == "forbidden":
                forbidden_columns[col_name] = col_def
                del df_definition["columns"][col_name]

        # For obs, filter to schema columns so the vendored per-column
        # sanity loop ignores curator extras. ``original_obs`` is both the
        # restore value and the "did we mutate?" sentinel; only set when
        # the obs actually has non-schema columns to drop.
        original_obs = None
        if df_name == "obs":
            current_obs = getattr_anndata(self.adata, "obs")
            if current_obs is not None and set(current_obs.columns) - schema_columns:
                original_obs = current_obs

        # Base class validates only required columns
        try:
            if original_obs is not None:
                kept = [c for c in original_obs.columns if c in schema_columns]
                self.adata.obs = original_obs[kept]
            super()._validate_dataframe(df_name)
        finally:
            # Restore schema def even if super() raises
            df_definition["columns"].update(sr_columns)
            df_definition["columns"].update(optional_columns)
            df_definition["columns"].update(forbidden_columns)
            # Restore the full obs so downstream checks see all columns
            if original_obs is not None:
                self.adata.obs = original_obs

        df = getattr_anndata(self.adata, df_name)
        if df is not None:
            # Forbidden columns: error if present.
            for col_name, col_def in forbidden_columns.items():
                if col_name in df.columns:
                    self.errors.append(
                        col_def.get(
                            "forbidden_error",
                            f"Column '{col_name}' must not be present in {df_name}.",
                        )
                    )
            # Validate strongly_recommended columns (warn if missing)
            for col_name, col_def in sr_columns.items():
                self._validate_strongly_recommended(df, df_name, col_name, col_def)
            # Validate optional columns (silent if missing, full validation if present)
            for col_name, col_def in optional_columns.items():
                if col_name in df.columns:
                    column = df[col_name]
                    if "dependencies" in col_def:
                        column = self._validate_column_dependencies(df, df_name, col_name, col_def["dependencies"])
                    if len(column) > 0:
                        if "warning_message" in col_def:
                            self.warnings.append(col_def["warning_message"])
                        self._validate_column(column, col_name, df_name, col_def)  # pyright: ignore[reportArgumentType]

    def _validate_strongly_recommended(self, df, df_name, col_name, col_def):
        """Validate a strongly_recommended column: warn on missing/NaN, error on blocklist."""
        if col_name not in df.columns:
            self.warnings.append(f"Column '{col_name}' in dataframe '{df_name}' is strongly recommended but missing.")
            return

        column = df[col_name]

        # NaN check — warn with count
        null_mask = column.isnull()
        if null_mask.any():
            nan_count = int(null_mask.sum())
            total = len(column)
            pct = (nan_count * 100 // total) if total > 0 else 0
            self.warnings.append(
                f"Column '{col_name}' is strongly recommended. {nan_count}/{total} ({pct}%) values are NaN."
            )

        # Separator check — reject values containing list separators
        separators = {",", ";", "|"}
        bad_sep_values = [str(v) for v in column.dropna().unique() if any(sep in str(v) for sep in separators)]
        if bad_sep_values:
            shown = bad_sep_values[:3]
            self.errors.append(
                f"Column '{col_name}' in dataframe '{df_name}' contains "
                f"values with list separators (e.g., {shown}). Each value "
                f"must be a single identifier, not a delimited list."
            )

        # Blocklist check — error on invalid values (case-insensitive)
        if "blocklist" in col_def:
            blocklist = {v.lower() for v in col_def["blocklist"]}
            bad_values = [str(v) for v in column.dropna().unique() if str(v).strip().lower() in blocklist]
            if bad_values:
                self.errors.append(
                    f"Column '{col_name}' in dataframe '{df_name}' contains "
                    f"invalid values {bad_values}. Placeholder values are not "
                    f"allowed. Leave the value missing (NaN/None) if not known."
                )

    def _get_organism_from_obs(self) -> str | None:
        """Get organism_ontology_term_id from obs (HCA schema stores it in obs)."""
        if (
            hasattr(self, "adata")
            and self.adata is not None
            and "organism_ontology_term_id" in self.adata.obs.columns
            and len(self.adata.obs) > 0
        ):
            return str(self.adata.obs["organism_ontology_term_id"].iloc[0])
        return None

    def _get_gencode_version_label(self) -> str:
        """Get a human-readable GENCODE version string for the dataset's organism."""
        organism = self._get_organism_from_obs()

        if organism == "NCBITaxon:9606":
            v = _gene_info["human"]["version"]
            return f"GENCODE v{v} (Ensembl 114)"
        if organism == "NCBITaxon:10090":
            v = _gene_info["mouse"]["version"]
            return f"GENCODE {v} (Ensembl 114)"
        return "GENCODE reference (Ensembl 114)"

    def _validate_feature_ids(self, column: pd.Series, df_name: str):
        """
        Override to improve warning messages with GENCODE version info.
        """
        version_label = self._get_gencode_version_label()
        dataset_organism = self._get_organism_from_obs()
        invalid_gene_organisms = []

        for feature_id in column:
            organism = gencode.get_organism_from_feature_id(feature_id)
            organism_ontology_id = None

            if not organism:
                self.warnings.append(f"Feature ID '{feature_id}' in '{df_name}' not found in {version_label}.")
                continue
            organism_ontology_id = organism.value

            valid_gene_id = get_gene_checker(organism).is_valid_id(feature_id)

            if not valid_gene_id:
                self.warnings.append(f"Feature ID '{feature_id}' in '{df_name}' not found in {version_label}.")

            if dataset_organism is not None and organism_ontology_id is not None and valid_gene_id:
                is_descendant = organism_ontology_id in ONTOLOGY_PARSER.get_term_ancestors(dataset_organism, True)
                if not is_descendant and organism_ontology_id not in gencode.EXEMPT_ORGANISMS:
                    invalid_gene_organisms.append(organism)

        invalid_gene_organisms = list(set(invalid_gene_organisms))
        if len(invalid_gene_organisms) > 0:
            self.warnings.append(
                f"obs['organism_ontology_term_id'] is '{dataset_organism}' "
                f"but feature_ids are from {invalid_gene_organisms}."
            )

    def _validate_column(self, column, column_name, df_name, column_def, default_error_message_suffix=None):
        """
        Extends base column validation with support for regex pattern matching.

        When a column_def contains a "pattern" key, validates that all non-NaN values
        match the specified regex pattern.
        """
        super()._validate_column(column, column_name, df_name, column_def, default_error_message_suffix)
        if "pattern" in column_def:
            compiled_pattern = re.compile(column_def["pattern"])
            description = column_def.get("pattern_description")
            for value in column.drop_duplicates():
                if pd.isna(value):
                    continue
                if not compiled_pattern.fullmatch(str(value)):
                    if description:
                        self.errors.append(
                            f"Column '{column_name}' in dataframe '{df_name}' contains a value "
                            f"'{value}' which is not valid. Expected {description}."
                        )
                    else:
                        self.errors.append(
                            f"Column '{column_name}' in dataframe '{df_name}' contains a value "
                            f"'{value}' that does not match the required pattern '{column_def['pattern']}'."
                        )


# Above this, a value in X cannot plausibly be log1p-normalized: exp(20) is
# ~4.8e8 counts for a single gene in a single cell. Used to catch raw counts in
# X before expm1 is applied — expm1 overflows float64 on real count values, so
# without this guard the profile check below returns inf and reports a
# mismatch, which is true but names the wrong cause.
_MAX_PLAUSIBLE_LOG1P_VALUE = 20.0

# Relative tolerance for the profile identity. The worst error measured on a
# correctly-normalized 2.1M-cell object was 3.0e-07 (float32 eps is 1.19e-07),
# and the seven breast-v1 files that fail the check land around 4e+01. Anything
# from 1e-6 to 1e-2 separates those cleanly; 1e-5 leaves ~33x headroom over
# observed noise while staying six orders below a real failure.
_PROFILE_RTOL = 1e-5

# Rows sampled for the profile check. The identity is per-cell and independent
# across cells, so this does not need to scale with n_obs; a few hundred rows
# makes a systematic normalization error overwhelmingly likely to surface.
_PROFILE_SAMPLE_ROWS = 200

# Relative spread allowed between the per-cell totals recovered from X. On the
# curated breast integrated object these land within 1.4e-07 of each other
# (9999.9993 to 10000.0007), so this leaves four orders of headroom while still
# separating a log1p-only file, whose recovered totals are the raw per-cell
# depths and so vary by whole multiples.
_TARGET_SUM_RTOL = 1e-3


def _max_finite(values, floor=0.0):
    """Largest finite entry in ``values``, or ``floor`` when there is none.

    ``floor`` defaults to 0.0 so a sparse matrix's implicit zeros are accounted
    for: reducing over the stored values alone would report a negative maximum
    for an all-negative matrix that also has implicit zeros.

    Reduced with ``where=`` rather than by boolean-indexing the finite entries.
    On the dense path ``values[np.isfinite(values)]`` would allocate a full-size
    mask plus a full-size copy — on a 5000-row chunk of a 36,788-gene matrix
    that is ~184 MB and up to ~736 MB, which is the cost this module goes out of
    its way to avoid elsewhere.
    """
    if values.size == 0:
        return floor
    largest = np.max(values, initial=floor, where=np.isfinite(values))
    return float(largest)


def _chunk_stats(x_chunk, raw_chunk):
    """Per-chunk reduction for the identical-matrix and magnitude checks.

    Returns ``[[identical, max_value]]`` for the chunk. Shaped as a 1-element
    object array because that is what ``map_blocks`` expects back from a
    blockwise reduction here — matching ``_validate_raw_data`` in the vendored
    validator, which is the established idiom in this file's base class.

    Sparse chunks are reduced through their CSR arrays rather than densified.
    That is not a micro-optimization: a 5000-row chunk of a 36,788-gene matrix
    densifies to 736 MB, and holding both chunks plus the finite mask peaks at
    ~2.4 GB *per dask task*. The Batch job runs 8 concurrent tasks on a 60 GB
    box, so the dense form transiently needs ~19 GB, scaling linearly with
    n_vars. The sparse form measures at 49 MB.

    Comparing the CSR arrays makes "identical" mean *identically stored*, which
    is narrower than *numerically equal* — two matrices can encode the same
    values with different explicit zeros. That is the safe direction: such a
    pair falls through to the profile check, which still errors, just with the
    more general message.
    """
    if sparse.issparse(x_chunk) and sparse.issparse(raw_chunk):
        identical = (
            x_chunk.shape == raw_chunk.shape
            and np.array_equal(x_chunk.indptr, raw_chunk.indptr)
            and np.array_equal(x_chunk.indices, raw_chunk.indices)
            and np.array_equal(x_chunk.data, raw_chunk.data)
        )
        return np.array([np.array([identical, _max_finite(x_chunk.data)], dtype=object)])

    x_dense = _densify(x_chunk)
    raw_dense = _densify(raw_chunk)
    identical = x_dense.shape == raw_dense.shape and np.array_equal(x_dense, raw_dense)
    # No implicit-zero floor here: a dense array stores every entry, so its own
    # maximum is the true one.
    max_value = _max_finite(x_dense, floor=float("-inf"))
    return np.array([np.array([identical, max_value if np.isfinite(max_value) else 0.0], dtype=object)])


def _densify(block):
    """Return ``block`` as a dense ndarray, whether it is sparse or already dense."""
    return block.toarray() if sparse.issparse(block) else np.asarray(block)


def _materialize(block):
    """Realize a matrix block, whether it is dask-backed or already concrete.

    ``read_h5ad`` in the vendored utils opens files with ``read_backed``, so
    ``adata.X`` is a chunked DaskArray on real files — but the test fixtures
    build AnnData directly and hold plain numpy or scipy matrices. Both reach
    this module, so neither can be assumed.
    """
    return block.compute() if isinstance(block, DaskArray) else block


def _identical_and_max(x, raw_x):
    """Return ``(x_is_identical_to_raw_x, max_finite_value_in_x)``.

    Returns ``None`` when the two cannot be compared without materializing a
    whole backed matrix, which the caller treats as "no verdict".

    One pass over both matrices via ``map_blocks`` when they are dask-backed
    with aligned chunks — the same idiom as ``_validate_raw_data`` in the
    vendored validator. When neither is dask-backed they are already resident,
    so a direct comparison costs nothing; that is the test-fixture case.

    The mixed case — one dask, one not, or two dask arrays chunked differently
    — is refused rather than materialized. It is reachable on a real file:
    ``read_backed`` chunks a CSC matrix as ``(n_obs, 5000)`` against CSR's
    ``(5000, n_vars)``, so an X stored CSC beside a CSR raw.X lands here. The
    vendored ``_validate_sparsity`` records an error for that file and
    continues, so materializing both 4.25-billion-nonzero matrices to add a
    second opinion would risk an OOM on a file already known to be invalid.
    """
    if isinstance(x, DaskArray) and isinstance(raw_x, DaskArray):
        if x.chunks != raw_x.chunks:
            return None
        results = map_blocks(_chunk_stats, x, raw_x, dtype=object).compute()
        # Reshaped, not iterated as rows. Dask reassembles the per-block (1, 2)
        # results along the *grid* axes: a row-chunked grid (k, 1) concatenates
        # to (k, 2), but a column-chunked grid (1, m) concatenates to (1, 2m).
        # Iterating rows there would read block 0 and silently discard the rest
        # — reporting "identical" off one block and a maximum blind to every
        # column past the first chunk. Column-chunked grids are reachable:
        # `read_backed` chunks a CSC matrix as (n_obs, chunk_size).
        pairs = np.asarray(results, dtype=object).reshape(-1, 2)
        identical = all(bool(flag) for flag in pairs[:, 0])
        max_value = max((float(value) for value in pairs[:, 1]), default=0.0)
        return identical, max_value

    if isinstance(x, DaskArray) or isinstance(raw_x, DaskArray):
        return None

    stats = _chunk_stats(x, raw_x)[0]
    return bool(stats[0]), float(stats[1])


def _profile_mismatch(x_rows, raw_rows):
    """Largest relative deviation from the normalization identity, or None.

    ``normalize_total`` scales each cell by a constant and ``log1p`` is applied
    elementwise, so for every cell::

        expm1(X[i]) / sum(expm1(X[i]))  ==  raw.X[i] / sum(raw.X[i])

    The target sum cancels, which is what makes this checkable without knowing
    it. That matters because ``scanpy.pp.normalize_total`` defaults to
    ``target_sum=None`` — normalizing to the *median* of per-cell totals, not
    to 1e4 — so a check written against an assumed constant would fire on every
    file that took the default.

    Rows whose raw counts sum to zero are skipped rather than guarded against
    division by zero; the vendored ``_has_valid_raw`` already errors on
    all-zero rows, so reporting them here would duplicate that.

    Returns ``(worst_deviation, target_sums)``. ``worst_deviation`` is None when
    no row could be compared; ``target_sums`` holds the recovered per-cell total
    for each comparable row, which the caller uses to check the
    ``normalize_total`` half of the transform.
    """
    # Densified once for the whole sample rather than per row: these are at most
    # _PROFILE_SAMPLE_ROWS rows, already materialized by the caller.
    x_dense = _densify(x_rows).astype(np.float64)
    raw_dense = _densify(raw_rows).astype(np.float64)

    worst = None
    target_sums: list[float] = []
    for i in range(x_dense.shape[0]):
        x_row = x_dense[i]
        raw_row = raw_dense[i]

        raw_total = raw_row.sum()
        if raw_total <= 0:
            continue

        expanded = np.expm1(x_row)
        expanded_total = expanded.sum()
        if not np.isfinite(expanded_total) or expanded_total <= 0:
            continue
        target_sums.append(float(expanded_total))

        raw_profile = raw_row / raw_total
        deviation = np.abs(expanded / expanded_total - raw_profile)
        # Relative to the raw profile, so a large absolute deviation on a
        # near-zero entry doesn't dominate. Compared against the raw profile
        # rather than the X profile because raw is the reference here.
        scale = np.maximum(raw_profile, np.finfo(np.float64).tiny)
        row_worst = float((deviation / scale).max())
        worst = row_worst if worst is None else max(worst, row_worst)
    return worst, target_sums


def check_x_normalization(adata):
    """Check that X holds a normalization of raw.X, and return (warnings, errors).

    HCA requires raw counts in ``raw.X`` and normalized values in ``X``. The
    vendored validator checks that ``raw.X`` *is* raw, and that the two
    matrices agree on shape and indices — but never that ``X`` differs from
    ``raw.X``, nor that it is derived from it. All seven breast-v1 source
    datasets ship ``X`` byte-identical to ``raw.X`` and validate clean today
    (see #524).

    Three checks, cheapest first, each short-circuiting: once one fires the
    later ones would only restate the same defect in vaguer terms.

    1. ``X`` identical to ``raw.X`` → normalization never ran.
    2. ``X`` holds values too large to be ``log1p`` output → raw counts in X.
    3. ``X`` is not a total-normalization of ``raw.X`` → the two are unrelated,
       or a non-standard transform was used.

    Silent when ``raw.X`` is absent: the vendored ``_validate_raw`` already owns
    that case and reports it, and a second message would not add anything.
    """
    if adata.raw is None:
        return [], []

    x = adata.X
    raw_x = adata.raw.X

    # Shape disagreement is already an error from _validate_x_raw_x_dimensions
    # (which also checks var.index and obs_names). Bail rather than report it
    # again — and because the comparisons below assume aligned shapes.
    if x.shape != raw_x.shape:
        return [], []

    verdict = _identical_and_max(x, raw_x)
    if verdict is None:
        # Not comparable without materializing a backed matrix; see
        # _identical_and_max. The file has other errors by construction.
        return [], []
    identical, max_value = verdict

    errors: list[str] = []

    if identical:
        errors.append(
            "X is identical to raw.X, so normalization has not been applied. "
            "X must hold normalized values and raw.X the raw counts."
        )
        return [], errors

    if max_value > _MAX_PLAUSIBLE_LOG1P_VALUE:
        errors.append(
            f"X contains values up to {max_value:.4g}, which is too large to be log1p output "
            f"(log1p of 10,000 counts is about 9.2). X may hold raw counts, or a normalization "
            f"that was never log-transformed."
        )
        return [], errors

    if max_value <= 0:
        # Every stored value is zero (or negative). raw.X is non-empty, since a
        # matching all-zero raw.X would have been caught as identical above and
        # the vendored _has_valid_raw errors on all-zero rows regardless. The
        # profile check cannot see this — every row divides out as unusable and
        # returns no verdict — so without this an emptied X validates clean,
        # which is the class of defect this whole check exists to catch.
        errors.append(
            "X contains no positive values, so it cannot hold normalized expression. "
            "Confirm X was not emptied or dropped during processing."
        )
        return [], errors

    n_rows = min(_PROFILE_SAMPLE_ROWS, x.shape[0])
    worst, target_sums = _profile_mismatch(_materialize(x[:n_rows]), _materialize(raw_x[:n_rows]))

    if worst is not None and worst > _PROFILE_RTOL:
        errors.append(
            f"X is not a normalization of raw.X: the per-cell expression profile of X "
            f"disagrees with raw.X by a relative error of {worst:.3g} (tolerance {_PROFILE_RTOL:g}), "
            f"sampled over {n_rows} cells. X should be log1p(normalize_total(raw.X))."
        )
        return [], errors

    # The profile identity alone does not prove `normalize_total` ran: it holds
    # exactly for a plain `log1p(raw.X)` too, because expm1 inverts log1p and
    # the profile is scale-free. What separates them is the recovered per-cell
    # total — constant across cells after normalize_total (whatever target it
    # used), but equal to each cell's own sequencing depth without it.
    if len(target_sums) > 1:
        low, high = min(target_sums), max(target_sums)
        spread = (high - low) / high if high > 0 else 0.0
        if spread > _TARGET_SUM_RTOL:
            errors.append(
                f"X was log-transformed but not total-normalized: the per-cell sums recovered "
                f"from X vary by a relative {spread:.3g} across {len(target_sums)} sampled cells "
                f"(from {low:.6g} to {high:.6g}, tolerance {_TARGET_SUM_RTOL:g}). "
                f"normalize_total makes these equal; without it they track each cell's "
                f"sequencing depth. X should be log1p(normalize_total(raw.X))."
            )

    return [], errors


def check_cosmetic_labels(adata, schema_def=None):
    """Run the producer-cosmetic-column check and return (warnings, errors).

    The controlled obs label columns are derived from their
    `*_ontology_term_id` counterparts. Carrying them is fine as long as they
    can be checked and they agree with canonical: `populate_labels` writes
    them deliberately, and CellxGENE exports arrive with them. What matters is
    that every populated row has a term ID and that the label matches the
    canonical ontology label for it.

    Per-column rules (each fires independently and aggregates):

    * column present with at least one label, source absent → warning (nothing
      to check the labels against). An all-NaN column has no labels to check,
      so it stays silent. The remediation depends on the source column's
      `requirement_level`: deleting the cosmetic column is only offered when the
      source is not required (`optional` or `strongly_recommended`), since a
      required source must be added regardless.
    * column present + source present → row-level checks:
        - cosmetic value, source NaN → error ("add term ID, delete the label,
          or delete the column")
        - both populated, file label != canonical → error ("delete the column
          or fix the term ID")
        - unresolvable term ID → silently skipped (the curie validator flags
          bad IDs through its own pathway)

    Args:
        adata: An AnnData object.
        schema_def: Loaded HCA schema definition dict. If omitted, the bundled
            HCA schema is loaded — pass an explicit value when reusing this
            check from a context that already has the schema in hand.

    Returns:
        ``(warnings, errors)`` — two lists of strings, ready for the caller to
        append to its own report. Issues #377, #443.
    """
    if schema_def is None:
        schema_def = _load_default_schema_def()

    warnings: list[str] = []
    errors: list[str] = []

    obs = getattr_anndata(adata, "obs")
    if obs is None:
        return warnings, errors

    obs_components = schema_def.get("components", {}).get("obs", {}).get("columns", {})
    for cosmetic_col in HCA_DERIVED_OBS_LABELS:
        if cosmetic_col not in obs.columns:
            continue
        source_col = f"{cosmetic_col}_ontology_term_id"
        if source_col not in obs.columns:
            if obs[cosmetic_col].notna().any():
                warnings.append(
                    f"obs['{cosmetic_col}'] is populated but obs['{source_col}'] is absent, "
                    f"so its labels can't be checked against the ontology. "
                    f"{_remediation_for_missing_source(obs_components, cosmetic_col, source_col)}"
                )
            continue
        exceptions = _collect_curie_exceptions(obs_components.get(source_col, {}))
        errors.extend(_compare_cosmetic_to_term_ids(obs, cosmetic_col, source_col, exceptions))

    return warnings, errors


def _remediation_for_missing_source(obs_components, cosmetic_col, source_col):
    # Deleting the cosmetic column only silences this warning. When the source
    # column is required by the schema, its absence is an error in its own
    # right, so deleting is not a remediation — adding the source column is the
    # only one. Columns carry no `requirement_level` when they are required.
    level = str(obs_components.get(source_col, {}).get("requirement_level", "")).lower()
    if level in ("optional", "strongly_recommended"):
        return f"Either add obs['{source_col}'], or delete obs['{cosmetic_col}']."
    return f"Add obs['{source_col}'] — the schema requires it."


def _collect_curie_exceptions(source_def):
    # `exceptions` (e.g. 'unknown', 'na') can live at the top-level
    # `curie_constraints` and/or inside per-rule `dependencies` blocks.
    # Union both so sentinel-vs-mismatch errors fire for any column that
    # only declares its sentinels conditionally.
    exceptions = set(source_def.get("curie_constraints", {}).get("exceptions", []))
    for dep in source_def.get("dependencies", []):
        exceptions.update(dep.get("curie_constraints", {}).get("exceptions", []))
    return exceptions


@functools.lru_cache(maxsize=1)
def _load_default_schema_def():
    schema_path = Path(__file__).parent / SCHEMA_DIR / SCHEMA_FILENAME
    with schema_path.open() as fp:
        return yaml.safe_load(fp)


def _compare_cosmetic_to_term_ids(obs, cosmetic_col, source_col, exceptions):
    pair_counts = (
        obs[[source_col, cosmetic_col]].astype(object).groupby([source_col, cosmetic_col], dropna=False).size()
    )
    canonical_cache: dict[str, str | None] = {}
    errors: list[str] = []
    for (term_id, file_label), n in pair_counts.items():
        file_label_str = None if pd.isna(file_label) else str(file_label)
        if pd.isna(term_id):
            if file_label_str is not None:
                errors.append(
                    f"obs['{cosmetic_col}']: {n} rows labeled '{file_label_str}' "
                    f"have NaN in {source_col}. Either add the term ID, "
                    f"delete the label, or delete the cosmetic column."
                )
            continue
        if file_label_str is None:
            continue
        term_id_str = str(term_id)
        if term_id_str not in canonical_cache:
            canonical_cache[term_id_str] = _lookup_canonical_label(term_id_str, exceptions)
        canonical = canonical_cache[term_id_str]
        if canonical is None or canonical == file_label_str:
            continue
        errors.append(
            f"obs['{cosmetic_col}']: {n} rows labeled '{file_label_str}' but "
            f"{source_col} is '{term_id_str}' (canonical label: '{canonical}'). "
            f"Either delete the cosmetic column, or fix {source_col} so it "
            f"matches the label."
        )
    return errors


def _lookup_canonical_label(term_id, exceptions):
    # Sentinels (e.g. 'unknown', 'na') are their own canonical label
    # — matches cellxgene labeler behavior.
    if term_id in exceptions:
        return term_id
    try:
        return ONTOLOGY_PARSER.get_term_label(term_id)
    except (KeyError, ValueError):
        return None
