"""HCA Validator - extends cellxgene Validator with HCA-specific rules."""

import contextlib
import csv
import functools
import gzip
import heapq
import re
from collections import Counter, namedtuple
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from anndata.compat import DaskArray

# dask re-exports map_blocks without listing it in __all__, so pyright treats
# it as private. The vendored validator imports it the same way (validate.py:14).
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

    def _check_donor_consistency(self):
        warnings, errors = check_donor_consistency(self.adata)
        self.warnings.extend(warnings)
        self.errors.extend(errors)

    def _check_gene_annotation_version(self):
        warnings, errors = check_gene_annotation_version(self.adata)
        self.warnings.extend(warnings)
        self.errors.extend(errors)

    def _check_retired_feature_ids(self):
        warnings, errors, verdicts = _retired_findings(self.adata)
        # The per-identifier warnings are already in self.warnings by now --
        # _validate_feature_ids writes them while the dataframes are validated --
        # so each is annotated in place with the verdict for the gene it names.
        # They are logged after _deep_check returns, so this reaches the Batch
        # payload as well as the in-memory list.
        self.warnings = annotate_feature_id_warnings(self.warnings, verdicts)
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
        self._check_donor_consistency()
        self._check_gene_annotation_version()
        # Last, so that validate_adata's reordering leaves this summary directly
        # above the per-identifier feature ID warnings it explains: those are
        # moved to the end and everything else keeps the order it was added in.
        self._check_retired_feature_ids()

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

# How far a cell's recovered rescale factor may sit from 1.0 and still count as
# "this cell was never rescaled". Measured across 69 real gut and breast files,
# the two populations are perfectly bimodal on this test — a log1p-only file
# scores 100% of sampled cells, a normalized one 0% — so the threshold has
# enormous margin and is not a tuned knob.
_DEPTH_MATCH_RTOL = 1e-3

# Fraction of sampled cells that must sit at factor 1.0 before X is called
# un-normalized. It has to be a fraction rather than `any`, because
# ``normalize_total`` defaults to ``target_sum=None`` — the *median* per-cell
# depth — so on a correctly normalized file every cell whose depth is near that
# median legitimately scores 1.0. `all` fails the other way: the sample is taken
# from the head of the file, so a concatenated object whose first component was
# log1p-only would slip through on one atypical cell.
_DEPTH_MATCH_FRACTION = 0.5

# Cells needed before the un-normalized verdict is trustworthy. With
# ``target_sum=None`` the target is the *median* per-cell depth, so on a
# one-cell object the target is that cell's own depth and its factor is exactly
# 1.0 — a correctly normalized file would be condemned by a sample of one.
_DEPTH_MATCH_MIN_CELLS = 2

# The layer holding the counts that remain after ambient RNA removal. When it is
# present it — not raw.X — is the matrix X must be a normalization of, because
# desouping is what stands between the two.
DESOUPED_COUNTS_LAYER = "desouped_counts"

# How far a recovered count may sit from a whole number, or from its raw
# counterpart, and still be treated as equal. The absolute term dominates for the
# small counts that make up almost every entry; the relative term keeps deep
# genes from drifting into a false verdict.
#
# The relative term is set three orders above what the round trip alone costs. X
# is stored float32, so recovering a count through log1p/expm1 carries a relative
# error of roughly 1e-6 — but the recovery also divides by a scale estimated as a
# median over the row, which carries the spread of whatever that row disagrees
# about, and that is the larger of the two errors on exactly the rows this has to
# judge.
#
# The margin is affordable because the populations it separates sit nowhere near
# it. Measured across the 140-file local prod corpus: genuinely desouped files
# score 0.0000% of entries above raw.X and 0.00% non-integral, while files whose
# X is not a normalization of any count matrix score 19.5-40.2% non-integral.
_IMPLIED_COUNT_ATOL = 0.05
_IMPLIED_COUNT_RTOL = 1e-3

# Recovered counts above this are not tested for integrality. The float32 round
# trip costs more than half a count somewhere above ~1e5, at which point the
# question stops being answerable rather than merely noisy; this sits an order of
# magnitude below that. Almost every entry in a count matrix is far smaller, so
# the test still sees the overwhelming majority of the sample.
#
# The integrality test uses _IMPLIED_COUNT_ATOL alone, not _counts_equal. A
# relative term makes the test vacuous long before this ceiling: the furthest a
# value can sit from the nearest whole number is 0.5, which 1e-3 * count passes
# at a count of 450. Every entry above that would score integral unconditionally
# while still counting toward the sample, diluting the non-integral fraction on
# deep data until the verdict could not fire at all.
_INTEGRAL_TEST_MAX_COUNT = 1e4

# Fraction of testable entries that must recover to whole numbers before X is
# accepted as a normalization of *some* count matrix.
_INTEGRAL_FRACTION = 0.95

# Non-integral entries needed before that fraction is acted on. The fraction
# alone is unsafe on a small sample — on a 13-entry object a single noisy value
# clears 5% on its own — while a genuinely non-count X puts most of its entries
# on the wrong side. Requiring both keeps the verdict honest at either size.
_MIN_NON_INTEGRAL_ENTRIES = 3

# Why X and its source disagree. NOT_COUNTS says X is not a normalization of any
# count matrix; EXCESS that it came from a different one; DESOUPED that it came
# from this one with counts removed; MIXED that both are true at once.
_VERDICT_NOT_COUNTS = "not_counts"
_VERDICT_EXCESS = "excess"
_VERDICT_DESOUPED = "desouped"
_VERDICT_MIXED = "mixed"


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
    """Per-chunk reduction over X and raw.X.

    Returns ``[[identical, max_value, has_non_finite]]`` for the chunk. Shaped
    as a 1-element object array because that is what ``map_blocks`` expects back
    from a blockwise reduction here — matching ``_validate_raw_data`` in the
    vendored validator, which is the established idiom in this file's base class.

    ``has_non_finite`` rides along on this pass rather than costing a traversal
    of the matrix elsewhere. It does evaluate ``isfinite`` a second time over
    the chunk's stored values, which is far cheaper than another full pass.

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
    # `format` rather than `issparse`: a COO matrix is sparse but has no
    # indptr/indices, so the comparison below would raise AttributeError, which
    # validate_adata's blanket handler turns into "Unexpected validation error"
    # and abandons the remaining deep checks. Falling through to the dense path
    # keeps the verdict correct on formats h5ad never stores but in-memory
    # callers can still hand us.
    if getattr(x_chunk, "format", None) in ("csr", "csc") and getattr(raw_chunk, "format", None) in ("csr", "csc"):
        identical = (
            x_chunk.shape == raw_chunk.shape
            and np.array_equal(x_chunk.indptr, raw_chunk.indptr)
            and np.array_equal(x_chunk.indices, raw_chunk.indices)
            and np.array_equal(x_chunk.data, raw_chunk.data)
        )
        has_non_finite = not bool(np.all(np.isfinite(x_chunk.data)))
        return np.array([np.array([identical, _max_finite(x_chunk.data), has_non_finite], dtype=object)])

    if sparse.issparse(x_chunk) != sparse.issparse(raw_chunk):
        # Mixed storage — anndata allows X and raw.X to use different encodings,
        # so a dense X beside a CSR raw.X is a legitimate file. Densifying the
        # sparse side to compare would allocate ~736 MB per block on a
        # 5000 x 36,788 chunk, which is exactly the cost the sparse path above
        # exists to avoid, and it would be paid on valid files.
        #
        # Reported as not identical, which is consistent rather than a
        # concession: "identical" here means identically *stored* (see above),
        # and two different encodings never are. A value-equal pair still falls
        # through to the profile check.
        values = x_chunk.data if sparse.issparse(x_chunk) else np.asarray(x_chunk)
        floor = 0.0 if sparse.issparse(x_chunk) else float("-inf")
        max_value = _max_finite(values, floor=floor)
        has_non_finite = not bool(np.all(np.isfinite(values)))
        return np.array([np.array([False, max_value if np.isfinite(max_value) else 0.0, has_non_finite], dtype=object)])

    x_dense = _densify(x_chunk)
    raw_dense = _densify(raw_chunk)
    identical = x_dense.shape == raw_dense.shape and np.array_equal(x_dense, raw_dense)
    # No implicit-zero floor here: a dense array stores every entry, so its own
    # maximum is the true one.
    max_value = _max_finite(x_dense, floor=float("-inf"))
    has_non_finite = not bool(np.all(np.isfinite(x_dense)))
    return np.array([np.array([identical, max_value if np.isfinite(max_value) else 0.0, has_non_finite], dtype=object)])


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


def _scan_x_against_raw(x, raw_x):
    """Return ``(identical, max_finite_value_in_x, x_has_non_finite)``.

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
        # Reshaped, not iterated as rows. Dask reassembles the per-block (1, 3)
        # results along the *grid* axes: a row-chunked grid (k, 1) concatenates
        # to (k, 3), but a column-chunked grid (1, m) concatenates to (1, 3m).
        # Iterating rows there would read block 0 and silently discard the rest
        # — reporting "identical" off one block and a maximum blind to every
        # column past the first chunk. Column-chunked grids are reachable:
        # `read_backed` chunks a CSC matrix as (n_obs, chunk_size).
        rows = np.asarray(results, dtype=object).reshape(-1, 3)
        identical = all(bool(flag) for flag in rows[:, 0])
        max_value = max((float(value) for value in rows[:, 1]), default=0.0)
        has_non_finite = any(bool(flag) for flag in rows[:, 2])
        return identical, max_value, has_non_finite

    if isinstance(x, DaskArray) or isinstance(raw_x, DaskArray):
        return None

    stats = _chunk_stats(x, raw_x)[0]
    return bool(stats[0]), float(stats[1]), bool(stats[2])


def _comparable_row(x_row, source_row):
    """``(expm1(X), source)`` over the genes X carries, or None if unusable.

    The one place the comparison's gene set is decided. Both ``_profile_mismatch``
    and ``_implied_counts`` need it, and they run back to back on the same rows —
    the second explains why the first failed — so a divergence between them would
    have the verdict reasoning over a different set of genes than the check that
    raised the alarm, with nothing to catch it.

    Restricted to the genes X actually carries. `feature_is_filtered` is a
    schema-supported var flag whose defined meaning is "zero in X, present in
    raw.X" — the vendored validator's own remediation message tells curators to
    set it — so those genes are legitimately absent from X and must not read as a
    mismatch. The arithmetic still works out exactly: normalize_total scaled the
    row by target/sum(source), so over any subset of genes both the target and
    the full total cancel from the profile, and dividing the recovered total by
    the same subset's source total gives back the same rescale factor an
    unfiltered row would report.

    The cost is that genes present in the source but zeroed in X are ignored
    rather than compared, which is what makes the check tolerant of an X that
    dropped genes it should have kept.

    Rows carrying a non-finite source value are refused outright. Such a value
    would make the row's total NaN, NaN passes a ``<= 0`` test, the deviation
    computed from it would be NaN, and ``max`` keeps NaN once it appears — after
    which ``worst > _PROFILE_RTOL`` is False forever. One NaN anywhere in the
    source matrix would otherwise silence the check for the entire file.
    """
    if not np.all(np.isfinite(source_row)):
        return None

    support = x_row != 0
    if not support.any():
        return None

    return np.expm1(x_row[support]), source_row[support]


def _profile_mismatch(x_rows, source_rows):
    """Largest relative deviation from the normalization identity, or None.

    ``source_rows`` is the matrix X should be derived from — ``raw.X``, or
    ``layers['desouped_counts']`` when ambient RNA removal was applied and the
    counts it left were retained.

    ``normalize_total`` scales each cell by a constant and ``log1p`` is applied
    elementwise, so for every cell::

        expm1(X[i]) / sum(expm1(X[i]))  ==  source[i] / sum(source[i])

    The target sum cancels, which is what makes this checkable without knowing
    it. That matters because ``scanpy.pp.normalize_total`` defaults to
    ``target_sum=None`` — normalizing to the *median* of per-cell totals, not
    to 1e4 — so a check written against an assumed constant would fire on every
    file that took the default.

    Rows whose source counts sum to zero are skipped rather than guarded against
    division by zero; the vendored ``_has_valid_raw`` already errors on
    all-zero rows, so reporting them here would duplicate that.

    Returns ``(worst_deviation, rescale_factors)``. ``worst_deviation`` is None
    when no row could be compared. ``rescale_factors`` holds, per comparable
    row, the factor ``normalize_total`` must have applied to it — the total
    recovered from X over the row's own count total. A factor of 1.0 means the
    row was never rescaled, which is how the caller checks the
    ``normalize_total`` half of the transform.
    """
    # Densified once for the whole sample rather than per row: these are at most
    # _PROFILE_SAMPLE_ROWS rows, already materialized by the caller.
    x_dense = _densify(x_rows).astype(np.float64)
    source_dense = _densify(source_rows).astype(np.float64)

    worst = None
    rescale_factors: list[float] = []
    for i in range(x_dense.shape[0]):
        comparable = _comparable_row(x_dense[i], source_dense[i])
        if comparable is None:
            continue
        expanded, source_support = comparable

        source_total = source_support.sum()
        if source_total <= 0:
            continue

        expanded_total = expanded.sum()
        if not np.isfinite(expanded_total) or expanded_total <= 0:
            continue
        rescale_factors.append(float(expanded_total / source_total))

        source_profile = source_support / source_total
        deviation = np.abs(expanded / expanded_total - source_profile)
        # Relative to the raw profile, so a large absolute deviation on a
        # near-zero entry doesn't dominate. Compared against the raw profile
        # rather than the X profile because raw is the reference here.
        scale = np.maximum(source_profile, np.finfo(np.float64).tiny)
        row_worst = float((deviation / scale).max())
        worst = row_worst if worst is None else max(worst, row_worst)
    return worst, rescale_factors


def _counts_equal(left, right):
    """Entrywise "these two recovered counts are the same", within tolerance."""
    return np.isclose(left, right, rtol=_IMPLIED_COUNT_RTOL, atol=_IMPLIED_COUNT_ATOL)


def _implied_counts(x_row, source_row):
    """Counts recovered from one row of X, and the source counts beside them.

    ``normalize_total`` multiplied the cell by one constant, so undoing ``log1p``
    leaves every gene scaled by that same constant. Recovering it does not need
    the target sum: the ratio ``expm1(X)/source`` is that constant at every gene
    the two matrices agree on, so its **median** recovers it even when a minority
    of genes disagree — which is exactly the case desouping produces, and is why
    the median is load-bearing here rather than a robustness flourish.

    Returns ``(implied, source)`` over the genes X carries, or ``None`` when the
    row cannot be used. Both are count-scale vectors, directly comparable.
    """
    comparable = _comparable_row(x_row, source_row)
    if comparable is None:
        return None
    expanded, source_support = comparable

    scaled = source_support > 0
    if not scaled.any():
        return None
    scale = float(np.median(expanded[scaled] / source_support[scaled]))
    if not np.isfinite(scale) or scale <= 0:
        return None

    return expanded / scale, source_support


def _implied_counts_verdict(x_rows, raw_rows):
    """Why X disagrees with the counts it should have come from, or None.

    Called only once the profile identity has already failed, so this decides
    *what to say*, not *whether* to say it. Every verdict rests on one physical
    invariant: a pipeline can remove counts but never invent them.

    - **NOT_COUNTS** — the recovered values are not whole numbers, so X is not a
      normalization of any count matrix.
    - **EXCESS** — they are whole numbers, but exceed the raw counts somewhere.
      Nothing adds counts, so X came from a different matrix.
    - **DESOUPED** — whole numbers, never above the raw counts, below them
      somewhere. Counts were removed between the two, which is what ambient RNA
      removal does.
    - **MIXED** — both directions at once, which is neither of the above and is
      reported as neither. Measured across the prod corpus, this is a real
      population rather than a tolerance artifact: all 31 genuinely-desouped
      files score *exactly* zero entries above raw.X, while four eye objects
      carry heavy removal (12-13% of entries) alongside a trace of genes that X
      has and raw.X does not. Float error would appear in all of them or none.

    Returns None when none of these fits — the sample recovers to whole numbers
    that match the raw counts, yet the profile still disagreed. That leaves the
    caller to report the disagreement without naming a cause, which is the
    honest outcome rather than a fallback.
    """
    x_dense = _densify(x_rows).astype(np.float64)
    raw_dense = _densify(raw_rows).astype(np.float64)

    testable = 0
    integral = 0
    excess = 0
    deficit = 0

    for i in range(x_dense.shape[0]):
        recovered = _implied_counts(x_dense[i], raw_dense[i])
        if recovered is None:
            continue
        implied, raw_support = recovered

        # Above the ceiling the float32 round trip is worth more than half a
        # count, so integrality stops being decidable. Excluded from the test
        # rather than allowed to answer it wrongly.
        decidable = implied <= _INTEGRAL_TEST_MAX_COUNT
        testable += int(decidable.sum())
        candidates = implied[decidable]
        integral += int((np.abs(candidates - np.rint(candidates)) <= _IMPLIED_COUNT_ATOL).sum())

        differs = ~_counts_equal(implied, raw_support)
        excess += int((differs & (implied > raw_support)).sum())
        deficit += int((differs & (implied < raw_support)).sum())

    # The entry-count test guards the division as well as the verdict: it can
    # only pass when `testable` is at least _MIN_NON_INTEGRAL_ENTRIES, since
    # `integral` is counted over the same entries `testable` is.
    non_integral = testable - integral
    if non_integral >= _MIN_NON_INTEGRAL_ENTRIES and non_integral / testable > 1 - _INTEGRAL_FRACTION:
        return _VERDICT_NOT_COUNTS
    if excess and deficit:
        return _VERDICT_MIXED
    if excess:
        return _VERDICT_EXCESS
    if deficit:
        return _VERDICT_DESOUPED
    return None


def _layer_chunks_align(layer, x):
    """True when the layer can be row-sliced without reading matrices whole.

    ``read_backed`` chunks a CSC matrix as ``(n_obs, chunk_size)`` against CSR's
    ``(5000, n_vars)``, so slicing the first 200 rows off a CSC layer beside a
    CSR X touches every chunk in the grid — the entire layer read to sample 200
    rows, at a per-chunk peak of ``n_obs x 5000``.

    Refused for the same reason ``_scan_x_against_raw`` refuses the mixed case:
    the vendored ``_validate_sparsity`` inspects layers too and records an error
    for any non-CSR encoding, so the file is already known invalid and a second
    opinion is not worth the OOM.
    """
    if isinstance(layer, DaskArray) != isinstance(x, DaskArray):
        return False
    if isinstance(layer, DaskArray):
        return layer.chunks == x.chunks
    return True


def _unusable_layer_error(declared_rows):
    """The error from the declared layer being unfit as the source, or None.

    Asked before the layer is trusted, because an unusable layer does not make
    the comparison below fail — it makes it silently not happen. ``_comparable_row``
    refuses any row carrying a non-finite source value, and a row with nothing
    positive in it divides out as unusable, so a layer that is entirely NaN or
    entirely zero across the sample drops every row: ``_profile_mismatch`` returns
    no verdict and no rescale factors, checks 8 and 9 are both skipped, and the
    file is reported clean. Attaching such a layer would otherwise switch the
    whole contract off, which is the one outcome this check must never produce.

    No vendored check reads layer *values* — ``_validate_sparsity`` only inspects
    the encoding — so unlike ``raw.X``, whose non-finite entries ``_validate_raw_data``
    already rejects as non-integer, nothing else would catch this.
    """
    values = _densify(declared_rows)

    if not np.all(np.isfinite(values)):
        return (
            f"layers['{DESOUPED_COUNTS_LAYER}'] contains NaN or infinite values, which cannot be "
            f"counts. That layer must hold the counts left behind by ambient RNA removal, so every "
            f"entry in it must be a finite count."
        )

    if bool((values < 0).any()):
        # Same failure shape as the two above, reached differently: a row whose
        # negatives cancel its positives has a non-positive total, which
        # `_profile_mismatch` skips. Enough such rows and the sample empties out.
        # raw.X is spared this only because the vendored `_validate_raw_data`
        # rejects its non-positive values as non-counts; nothing does that here.
        return (
            f"layers['{DESOUPED_COUNTS_LAYER}'] contains negative values, which cannot be counts. "
            f"That layer must hold the counts left behind by ambient RNA removal, so every entry "
            f"in it must be zero or a positive count."
        )

    if not bool((values > 0).any()):
        return (
            f"layers['{DESOUPED_COUNTS_LAYER}'] holds no counts. That layer must hold the counts "
            f"left behind by ambient RNA removal, and X must be a normalization of them. Populate "
            f"it with those counts, or remove it if ambient RNA removal was not applied."
        )

    return None


def _exceeds_counts(candidate_rows, ceiling_rows):
    """True when ``candidate_rows`` holds more counts than ``ceiling_rows`` anywhere.

    The same invariant ``_implied_counts_verdict`` applies to recovered counts,
    but asked of two matrices as stored — no log1p/expm1 round trip stands
    between them, so a single entry over the ceiling is decisive here in a way it
    is not there.

    The cheap comparison runs first and the tolerance only on the entries that
    survive it. That ordering is what keeps this the cheap check its position in
    ``check_x_normalization`` claims: applying ``_counts_equal`` to the whole
    sample builds four full-width float64 temporaries, ~260 MB at 200 x 36,788,
    to answer a question that is False everywhere on a valid file. Restricted to
    the exceeding entries — of which a valid file has none — it allocates
    nothing.
    """
    candidate = _densify(candidate_rows)
    ceiling = _densify(ceiling_rows)

    # False wherever either side is NaN, so those entries drop out here rather
    # than needing a mask of their own. An infinity does compare greater, and is
    # excluded below.
    over = candidate > ceiling
    if not over.any():
        return False

    above = candidate[over].astype(np.float64)
    limit = ceiling[over].astype(np.float64)
    return bool((np.isfinite(above) & np.isfinite(limit) & ~_counts_equal(above, limit)).any())


def _source_mismatch_error(verdict, worst, n_rows):
    """The message for an X that disagrees with raw.X, chosen by verdict.

    The generic form is the fallback rather than the norm: it says only that the
    two disagree, which is all that can be claimed when the sample was too small
    to classify.
    """
    if verdict == _VERDICT_NOT_COUNTS:
        return (
            "X is not a normalization of any count matrix: undoing log1p and the per-cell scaling "
            "recovers values that are not whole numbers. Either X was produced by a different "
            "transform — scran, SCTransform, TPM, log2(CPM+1) — or it was altered after "
            "normalization, which is what rounding or truncating to an integer dtype does."
        )

    if verdict == _VERDICT_EXCESS:
        return (
            "X was normalized from a different matrix than raw.X: undoing the normalization "
            "recovers more counts than raw.X holds. No processing step adds counts — filtering, QC "
            "and ambient RNA removal can only take them away — so X cannot have been derived from "
            "raw.X. raw.X must hold the counts that X was normalized from."
        )

    if verdict == _VERDICT_MIXED:
        return (
            f"X disagrees with raw.X in both directions: counts were removed across most of the "
            f"genes that differ, which is the signature of ambient RNA removal, but X also holds "
            f"counts that raw.X does not. Nothing adds counts, so raw.X cannot be the matrix X was "
            f"normalized from even though desouping evidently ran. Retain the counts X was derived "
            f"from as layers['{DESOUPED_COUNTS_LAYER}'], and confirm raw.X holds the counts those "
            f"were removed from."
        )

    if verdict == _VERDICT_DESOUPED:
        return (
            f"X appears to be normalized from desouped counts, but layers['{DESOUPED_COUNTS_LAYER}'] "
            f"is missing. Undoing the normalization recovers fewer counts than raw.X and never "
            f"more, which is the signature of ambient RNA removal. Desouped counts cannot be "
            f"recomputed from raw.X, so they must be retained as layers['{DESOUPED_COUNTS_LAYER}'] "
            f"— float32 counts, same shape as raw.X. Without them X can be neither verified nor "
            f"re-derived."
        )

    return (
        f"X is not a normalization of raw.X: the per-cell expression profile of X disagrees with "
        f"raw.X by a relative error of {worst:.3g} (tolerance {_PROFILE_RTOL:g}), sampled over "
        f"{n_rows} cells. X should be log1p(normalize_total(raw.X)), or "
        f"log1p(normalize_total(layers['{DESOUPED_COUNTS_LAYER}'])) when ambient RNA removal was "
        f"applied and those counts were retained."
    )


def _whole_matrix_error(identical, max_value, has_non_finite):
    """The error from the checks that read both matrices in full, or None.

    These four are answered by a single pass over X and raw.X, before any
    row is sampled, and each short-circuits the rest: once X is known to hold
    raw counts or a NaN, the sampled comparisons below would only restate
    that in vaguer terms.
    """
    if identical:
        # The spec used to say that an author-provided dataset with no
        # normalized matrix has `adata.X` = the raw matrix — which, since raw.X
        # is required regardless, made X == raw.X a documented state. CELLxGENE
        # has no such state: raw goes in raw.X when a normalized matrix exists,
        # otherwise in X with raw.X absent, so location alone says which is
        # which. That third state is precisely why `_has_valid_raw` walks past
        # these files — it validates raw.X, finds valid counts, and nothing ever
        # looks at X. The sentence is gone (#562), so this is an error.
        # Named no source, deliberately. This check runs in the whole-matrix
        # pass, before layers are read, so it cannot know whether the file
        # carries desouped counts — and naming raw.X would point a curator who
        # does carry them at the wrong matrix.
        return (
            "X is identical to raw.X, so normalization has not been applied. X must hold the "
            "normalized values and raw.X the raw counts. Normalize X from raw.X, or from "
            f"layers['{DESOUPED_COUNTS_LAYER}'] if ambient RNA removal was applied."
        )

    if has_non_finite:
        # Reported before the checks below because a NaN or inf makes them
        # unreliable rather than merely wrong: `_profile_mismatch` skips any row
        # whose expanded total is non-finite, so a partially-NaN X would be
        # judged on its remaining rows and reported clean — success claimed over
        # a matrix that was never fully evaluated. The maximum ignores
        # non-finite entries for the same reason.
        return (
            "X contains NaN or infinite values, which cannot be normalized expression. Every entry in X must be finite."
        )

    if max_value > _MAX_PLAUSIBLE_LOG1P_VALUE:
        return (
            f"X contains values up to {max_value:.4g}, which is too large to be log1p output "
            f"(log1p of 10,000 counts is about 9.2). X may hold raw counts, or a normalization "
            f"that was never log-transformed."
        )

    if max_value <= 0:
        # Every stored value is zero (or negative). raw.X is non-empty, since a
        # matching all-zero raw.X would have been caught as identical above and
        # the vendored _has_valid_raw errors on all-zero rows regardless. The
        # profile check cannot see this — every row divides out as unusable and
        # returns no verdict — so without this an emptied X validates clean,
        # which is the class of defect this whole check exists to catch.
        return (
            "X contains no positive values, so it cannot hold normalized expression. "
            "Confirm X was not emptied or dropped during processing."
        )

    return None


def check_x_normalization(adata):
    """Check that X holds a normalization of its source counts, and return (warnings, errors).

    HCA requires raw counts in ``raw.X`` and normalized values in ``X``. The
    vendored validator checks that ``raw.X`` *is* raw, and that the two matrices
    agree on shape and indices — but never that ``X`` differs from ``raw.X``,
    nor that it is derived from it. All seven breast-v1 source datasets ship
    ``X`` byte-identical to ``raw.X`` and validated clean before #524.

    The matrix X must be derived from is not always ``raw.X``. When ambient RNA
    removal was applied, the counts that survive it are what X was normalized
    from, and they cannot be recomputed from ``raw.X`` — the removal is
    parameterised and often stochastic. So the contract is three matrices
    (#562)::

        raw.X                      raw counts
        layers['desouped_counts']  counts after ambient RNA removal, when it ran
        X                          log1p(normalize_total( desouped_counts
                                                          if present else raw.X ))

    Checks run cheapest first and short-circuit: once one fires the later ones
    would only restate the same defect in vaguer terms.

    1. ``X`` identical to ``raw.X`` → normalization never ran.
    2. ``X`` holds NaN or infinite values → not expression data at all, and it
       makes every check below unreliable rather than merely wrong.
    3. ``X`` holds values too large to be ``log1p`` output → raw counts, or a
       normalization that was never log-transformed.
    4. ``X`` holds no positive values → the matrix was emptied or dropped.
    5. ``layers['desouped_counts']`` holds NaN, infinities, negatives, or no
       counts at all → it cannot serve as the source, and left unchecked it would
       switch the comparisons below off rather than fail them.
    6. ``layers['desouped_counts']`` holds more counts than ``raw.X`` → the
       layer is not what it claims to be, so it cannot be trusted as the source.
    7. No sampled cell could be compared at all → the checks below would not run,
       and passing on that is indistinguishable from passing on a clean file.
    8. ``X`` is not a total-normalization of its source. When the source is
       ``desouped_counts`` that is the whole finding; when it is ``raw.X``,
       ``_implied_counts_verdict`` names the cause — including the case where
       desouping evidently ran but its counts were not retained.
    9. ``X`` was log-transformed but never total-normalized.

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

    verdict = _scan_x_against_raw(x, raw_x)
    if verdict is None:
        # Not comparable without materializing a backed matrix; see
        # _scan_x_against_raw. The file has other errors by construction.
        return [], []

    scan_error = _whole_matrix_error(*verdict)
    if scan_error is not None:
        return [], [scan_error]

    n_rows = min(_PROFILE_SAMPLE_ROWS, x.shape[0])
    x_rows = _materialize(x[:n_rows])
    raw_rows = _materialize(raw_x[:n_rows])

    # When ambient RNA removal ran, the counts it left behind — not raw.X — are
    # what X was normalized from, so they are what X must be checked against.
    # Resolved once, into the matrix and the name it goes by, because every
    # decision below turns on it: which matrix to compare against, whether a
    # cause can be inferred, and what to call the source when reporting.
    #
    # anndata aligns layers to X's shape on construction, so no shape guard is
    # needed here; a layer of the wrong shape cannot be loaded in the first place.
    declared = adata.layers.get(DESOUPED_COUNTS_LAYER)

    if declared is not None and not _layer_chunks_align(declared, x):
        # Sampling the layer would cost the whole layer; see _layer_chunks_align.
        # The file has other errors by construction.
        return [], []

    declared_rows = None if declared is None else _materialize(declared[:n_rows])
    source_rows = raw_rows if declared_rows is None else declared_rows
    source_name = "raw.X" if declared_rows is None else f"layers['{DESOUPED_COUNTS_LAYER}']"

    if declared_rows is not None:
        unusable = _unusable_layer_error(declared_rows)
        if unusable is not None:
            return [], [unusable]

    if declared_rows is not None and _exceeds_counts(declared_rows, raw_rows):
        # Checked before the layer is trusted as the source. If it holds more
        # counts than raw.X it is not a desouped version of raw.X at all, and
        # comparing X against it would report on a relationship between two
        # matrices that are not the ones the contract describes.
        return [], [
            f"layers['{DESOUPED_COUNTS_LAYER}'] holds more counts than raw.X. Ambient RNA removal "
            f"only removes counts, so the desouped matrix must be everywhere less than or equal to "
            f"raw.X. Check that raw.X holds the pre-desouping counts, and that the layer was not "
            f"populated from a different matrix."
        ]

    worst, rescale_factors = _profile_mismatch(x_rows, source_rows)

    if worst is None:
        # Not one sampled cell could be compared. Reported rather than passed
        # over, because "the check found nothing wrong" and "the check never ran"
        # are the same return value otherwise — the failure the layer guard above
        # exists to prevent, reached by a different route. The whole-matrix checks
        # do not cover it: they ask about X and raw.X as a whole, so an X whose
        # first cells are empty or negative while later ones are not clears all
        # four and still leaves the sample with nothing to compare.
        return [], [
            f"X could not be checked against {source_name}: none of the first {n_rows} cells hold "
            f"values that can be compared. X must hold normalized expression for every cell. "
            f"Confirm X was not partly emptied or overwritten."
        ]

    if worst > _PROFILE_RTOL:
        if declared_rows is not None:
            # The layer is present and X does not match it. There is no further
            # cause to name: the file states which matrix X came from, and X did
            # not come from it.
            return [], [
                f"X is not a normalization of {source_name}. When that layer is present it is the "
                f"matrix X must be derived from, so X should be "
                f"log1p(normalize_total({source_name})). Re-derive X from the desouped counts, or "
                f"correct the layer if it does not hold the counts X was built from."
            ]

        return [], [_source_mismatch_error(_implied_counts_verdict(x_rows, raw_rows), worst, n_rows)]

    # The profile identity alone does not prove `normalize_total` ran: it holds
    # exactly for a plain `log1p(raw.X)` too, because expm1 inverts log1p and the
    # profile is scale-free. What separates them is whether each cell's recovered
    # total is its *own* raw depth — which is what a cell that was never rescaled
    # reports back.
    #
    # Asked per cell rather than as a spread across cells. An earlier version
    # flagged X whenever the recovered totals varied by more than a tolerance,
    # and that misread float32 error as evidence: on a correctly normalized file
    # a deep cell's log1p/expm1 round trip loses enough precision to move its
    # recovered total off the target by ~0.1%. Run across 69 real gut and breast
    # files, the spread test produced 6 false positives out of 15 candidates,
    # with correctly-normalized files spanning 1e-07 to 3.5e-01 — no threshold
    # separates them.
    unscaled = sum(1 for factor in rescale_factors if abs(factor - 1.0) < _DEPTH_MATCH_RTOL)
    if len(rescale_factors) >= _DEPTH_MATCH_MIN_CELLS and unscaled / len(rescale_factors) > _DEPTH_MATCH_FRACTION:
        return [], [
            f"X was log-transformed but never total-normalized: for {unscaled} of "
            f"{len(rescale_factors)} sampled cells the total recovered from X is that cell's own "
            f"count depth in {source_name}, so no rescaling was applied. normalize_total makes "
            f"every cell sum to a common target. X should be log1p(normalize_total({source_name}))."
        ]

    return [], []


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


# ---------------------------------------------------------------------------
# Donor-level consistency (#680)
#
# Port of the donor-metadata cell of Lattice's curation QA notebook (cell 37;
# there is no library function), pinned at commit
# ``8778a14f2a5a7039acf3ce74b3da220c24521905``:
# https://github.com/Lattice-Data/lattice-tools/blob/8778a14f2a5a7039acf3ce74b3da220c24521905/cellxgene_resources/curation_qa.ipynb
#
# Lattice runs value_counts over five fields (donor_id, sex, development_stage,
# self_reported_ethnicity, disease) and reports every donor_id that appears
# under more than one combination as ERROR. The cell's markdown tells the
# curator to drop disease when a donor contributed healthy and diseased tissue
# and to drop development_stage for longitudinal studies.
#
# Deviations from Lattice:
# * organism and manner_of_death are added: both are Donor slots in the HCA
#   LinkML schema. CELLxGENE has no manner_of_death, and Lattice's datasets
#   are single-organism.
# * ethnicity is dropped: HCA does not carry it (#409).
# * development_stage and disease are warnings, not errors. The HCA schema
#   puts both at Sample grain (age at sampling; "disease, if expected to
#   impact the sample"), so a longitudinal or tumor-plus-adjacent donor
#   legitimately carries two values. A mis-join looks identical, so the
#   signal is kept, but as a warning.
# * one real value plus a not-a-claim value is a fill-in warning, not a
#   conflict. That split is borrowed from Lattice's sex check (cell 41),
#   which its donor cell does not do.
# * rows whose donor_id is not an individual are skipped. The LinkML
#   donor_id slot recommends "pooled" for samples of several individuals
#   that demultiplexing could not separate and "unknown" when it is not
#   known which observations share an individual; the validator requires
#   "na" for cell lines. None of these is one person, so a pool carrying two
#   sexes is not a conflict.
# * null is not a claim and never counts. Lattice's value_counts silently
#   drops any row with a null in any of its five fields.
# * the report is capped per column; Lattice displays the whole DataFrame.
#
# tests/test_validator.py asserts the error-tier columns equal the Donor
# slots in shared/src/hca_validation/schema/donor.yaml, so this map cannot
# drift from the LinkML schema unnoticed.
DONOR_GRAIN_COLUMNS: dict[str, str] = {
    "organism_ontology_term_id": "error",
    "sex_ontology_term_id": "error",
    "manner_of_death": "error",
    "development_stage_ontology_term_id": "warning",
    "disease_ontology_term_id": "warning",
}
_DONOR_REPORT_MAX_DONORS = 10
_DONOR_REPORT_MAX_VALUES = 5
# Values that mean "not known" rather than a claim, applied to every column
# the way Lattice's sex check treats its literal "unknown". Where one of
# these is not admitted by a column (organism has no unknown), the curie or
# enum validator already errors on it, so this set only decides the tier of
# the donor message. "not applicable" is a claim (manner_of_death: alive).
_NOT_A_CLAIM = frozenset({"unknown", "na", ""})
# donor_id values that do not name one individual (see the deviation note);
# an empty string is a missing ID, which the column validator already rejects.
_DONOR_ID_NOT_AN_INDIVIDUAL = frozenset({"pooled", "unknown", "na", ""})


def check_donor_consistency(adata):
    """Report donors whose obs metadata varies where one individual's should not. #680.

    Error-tier columns are donor-level facts; warning-tier columns are sample
    facts that usually follow the donor but legitimately vary in some studies.

    Groups obs by ``donor_id`` alone — the same individual can legitimately
    appear under several ``dataset_id`` values in an integrated object —
    skipping the reserved IDs that do not name one individual, and classifies
    each donor's distinct non-null values per :data:`DONOR_GRAIN_COLUMNS`
    column as a conflict, a fill-in, or nothing (see :func:`_donor_value_sets`).

    Reads obs only. Emits one message per column and bucket, naming at most
    ``_DONOR_REPORT_MAX_DONORS`` donors with at most
    ``_DONOR_REPORT_MAX_VALUES`` values each, so one bad donor in a
    multi-million-cell file is one line. Silent when ``donor_id`` is absent
    (the column checks already report that).

    Args:
        adata: An AnnData object.

    Returns:
        ``(warnings, errors)`` — two lists of strings.
    """
    obs = getattr_anndata(adata, "obs")
    if obs is None or "donor_id" not in obs.columns:
        return [], []

    warnings: list[str] = []
    errors: list[str] = []
    for col, severity in DONOR_GRAIN_COLUMNS.items():
        if col not in obs.columns:
            continue
        conflicts, fillable = _donor_value_sets(obs, col)
        if conflicts:
            message = _donor_conflict_message(col, conflicts, severity)
            (errors if severity == "error" else warnings).append(message)
        if fillable:
            warnings.append(_donor_fill_in_message(col, fillable))

    return warnings, errors


def _donor_value_sets(obs, col):
    # Deduplicate the (donor, value) pairs first — one pass over n_obs. Null
    # rows are not claims and are dropped. Then stringify: donor IDs and values
    # that differ only in dtype (1 vs "1") collapse into what the wrangler will
    # see, and categoricals lose their unused categories. The obs index is
    # dropped so an index named "donor_id" cannot collide with the column.
    pairs = obs[["donor_id", col]].reset_index(drop=True).drop_duplicates().dropna().astype(str)
    pairs = pairs[~pairs["donor_id"].isin(_DONOR_ID_NOT_AN_INDIVIDUAL)]
    conflicts: dict[str, list[str]] = {}
    fillable: dict[str, list[str]] = {}
    for donor, values in pairs.groupby("donor_id")[col]:
        distinct = sorted(set(values))
        if len(distinct) < 2:
            continue
        real = [v for v in distinct if v not in _NOT_A_CLAIM]
        if len(real) >= 2:
            conflicts[donor] = distinct
        elif len(real) == 1:
            fillable[donor] = distinct
    return conflicts, fillable


def _plural(n, noun):
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def _format_donor_values(donors):
    parts = []
    for donor, values in list(donors.items())[:_DONOR_REPORT_MAX_DONORS]:
        shown = ", ".join(f"'{v}'" for v in values[:_DONOR_REPORT_MAX_VALUES])
        if len(values) > _DONOR_REPORT_MAX_VALUES:
            shown += f", and {len(values) - _DONOR_REPORT_MAX_VALUES} more"
        parts.append(f"'{donor}' has [{shown}]")
    text = "; ".join(parts)
    if len(donors) > _DONOR_REPORT_MAX_DONORS:
        text += f"; and {_plural(len(donors) - _DONOR_REPORT_MAX_DONORS, 'more donor')}"
    return text


def _donor_conflict_message(col, conflicts, severity):
    found = f"obs['{col}'] varies within {_plural(len(conflicts), 'donor')}"
    if severity == "error":
        return (
            f"{found} — donor-level metadata must be constant per donor_id: "
            f"{_format_donor_values(conflicts)}. Either the donor_id merges two "
            f"individuals, or the value is wrong in some rows."
        )
    return (
        f"{found}: {_format_donor_values(conflicts)}. This is sample-level metadata "
        f"that usually follows the donor; legitimate for longitudinal sampling or a "
        f"donor who contributed both healthy and diseased tissue, otherwise a mis-join."
    )


def _donor_fill_in_message(col, fillable):
    subject = "1 donor mixes" if len(fillable) == 1 else f"{len(fillable)} donors mix"
    return (
        f"obs['{col}']: {subject} an unknown value with a real value and can be "
        f"filled in: {_format_donor_values(fillable)}."
    )


# --- gene_annotation_version (#710) ------------------------------------------
# Release 76 is the first GRCh38 core database and r55 the first GRCh37 one.
# Verified against the archive itself, whose database names carry the assembly --
# though the suffix is not uniform, so a query for plain "_37" or "_38" sees only
# part of it. Grouped by assembly family the archive is r48-r54 NCBI36, r55-r75
# GRCh37, r76-r116 GRCh38, none of them with gaps. Early GRCh37 releases carry a
# patch letter (homo_sapiens_core_56_37a through _62_37g) and NCBI36 appears as
# _36j through _36p, so r54 and earlier are served, not absent. They predate
# GRCh37 and name an assembly this check does not speak for -- the same treatment
# accessions below .13 get.
_FIRST_GRCH38_RELEASE = 76
_FIRST_GRCH37_RELEASE = 55
# RefSeq accessions for the human assembly: GCF_000001405.26 is GRCh38, and
# .13-.25 are GRCh37 patches. Below .13 is older still (.12 is NCBI36), so those
# name an assembly this check has no business labelling.
_FIRST_GRCH38_ACCESSION = 26
_FIRST_GRCH37_ACCESSION = 13
# GENCODE numbers its human releases 66 behind Ensembl's across the modern range:
# GENCODE 32 is Ensembl 98, GENCODE 48 is Ensembl 114. Used only to place the
# ceiling of the Ensembl/GENCODE ambiguity, never to convert a declared value --
# see _highest_gencode_release.
_GENCODE_ENSEMBL_OFFSET = 66
# Deliberately wider than the schema pattern, which demands a lowercase "v" and
# the accession's full zero padding. "98", "V98" and "gcf_000001405.40" are
# format errors the pattern already reports, and the parser reads them anyway --
# so such a file gets the format error *and* whatever the genes say about the
# release. That doubles the report on one value, which is the cost; the gain is
# that the producer fixes the case and the wrong release in one round instead of
# discovering the second only after correcting the first. Narrowing these to the
# pattern would buy a single accepted surface at the price of that round trip.
_ACCESSION_RE = re.compile(r"^GCF_0*1405\.(\d+)$", re.IGNORECASE)
_RELEASE_RE = re.compile(r"^v?(\d{2,3})$", re.IGNORECASE)
# Human genes are ENSG + digits, optionally carrying Ensembl's numeric version
# suffix. Anchored, because other species share the prefix -- gorilla is
# ENSGGOG... -- and a prefix test would date them as human. The suffix is matched
# rather than split off: splitting every id at its first dot turned a custom
# feature such as ENSG00000141510.beta into TP53 and dated it as a known gene,
# and collapsed distinct ids like mycustom.1 and mycustom.2 into one.
_HUMAN_ENSG_RE = re.compile(r"^(ENSG\d+)(?:\.\d+)?$")
# Values that say "nothing recorded" rather than making a claim.
_VERSION_NOT_A_CLAIM = frozenset({"", "nan", "none", "na", "unknown", "not available", "not applicable"})
_INTERVALS_PATH = Path(__file__).parent / "gene_release_intervals.csv.gz"
_HUMAN_ORGANISM = "NCBITaxon:9606"
# A claim about organism is an NCBITaxon curie. Anything else -- a placeholder
# like "unknown", free text like "Homo sapiens", a typo -- states nothing, and
# is the same epistemic position as an absent column.
_ORGANISM_CURIE_RE = re.compile(r"^NCBITaxon:\d+$")
# Stated rather than detected, because nothing in the file reliably says whether
# it is merged. Three candidate signals were measured across the corpus and all
# fail: 7 of 111 source datasets carry a uns copy of the field, 90 of 103
# integrated objects declare only one version, and a dataset/study obs column is
# absent from 23 integrated objects while 6 source datasets have one holding
# several values (site, chemistry, cohort, subject -- the name does not pin the
# meaning). A merged gene list is a union of its sources: the breast atlas is
# exactly the union of its seven, 36,788 genes against an intersection of 11,711,
# so its apparent release is set by whichever source used the newest annotation
# and need not match any single one. So each finding names both readings rather
# than hedging one of them -- on a merged object the result is not a weaker
# verdict but a different and expected one. Remove these once #719's
# source_dataset_id makes merged-ness a fact the check can read, and gate on it.
# Appended to a finding where a release *was* found to fit, so it must not
# repeat _SCOPE_NO_RELEASE's union argument: saying "no single release fits it"
# beside a sentence naming the releases that do contradicts the finding, and an
# integrated-object reader takes the second clause as the operative one.
_SCOPE_TOO_EARLY = (
    " If this is a source dataset -- one study, one annotation -- the declared value cannot be "
    "correct. On an integrated object each declared value must instead match the source dataset its "
    "cells came from."
)
_SCOPE_NO_RELEASE = (
    " If this is a source dataset, its gene list spans releases -- a reference that mixes them, or "
    "one built outside Ensembl. On an integrated object this is expected: a union of sources "
    "annotated against different releases matches none of them, and each declared value must match "
    "the source dataset its cells came from."
)
# The assembly names obs['reference_genome'] may hold. Anything else -- a
# placeholder like "not applicable", or a malformed value the column's own enum
# already errors on -- names no assembly, so there is nothing to compare against.
_KNOWN_ASSEMBLIES = frozenset({"GRCh38", "GRCh37", "GRCm39", "GRCm38", "GRCm37"})

# Parsed forms of obs['gene_annotation_version'].
#   release     - an Ensembl release number, datable against the gene list
#   assembly    - an assembly accession; names a genome, not an annotation (#719)
#   ambiguous   - a number below 76, which Ensembl and GENCODE both write the
#                 same way: 'v32' is Ensembl r32 or GENCODE 32, and those are
#                 different annotations. Carries the number but claims no assembly.
#   missing     - nothing recorded
#   uninterpretable - none of the above
ParsedVersion = namedtuple("ParsedVersion", "kind release assembly raw")


def parse_annotation_version(value) -> ParsedVersion:
    """Read one ``gene_annotation_version`` value, or decline to.

    Strict about meaning, not about spelling. Every form it accepts is matched
    exactly and anything else is reported rather than guessed at, because a value
    interpreted wrongly is worse than one left alone in a check about wrong
    metadata -- but the shapes it matches are a little wider than the schema
    pattern's, deliberately, for the reason given where they are defined.

    The schema documents this field with assembly accessions (its example is
    ``GCF_000001405.40``, which is GRCh38.p14), so an accession is a conforming
    value that happens to name a genome rather than an annotation. It is parsed,
    and reported as not-an-annotation rather than as the producer's mistake.
    """
    raw = "" if value is None else str(value).strip()
    if raw.lower() in _VERSION_NOT_A_CLAIM:
        return ParsedVersion("missing", None, None, raw)

    if match := _ACCESSION_RE.match(raw):
        patch = int(match.group(1))
        if patch == 0:
            return ParsedVersion("uninterpretable", None, None, raw)
        if patch >= _FIRST_GRCH38_ACCESSION:
            assembly = "GRCh38"
        elif patch >= _FIRST_GRCH37_ACCESSION:
            assembly = "GRCh37"
        else:
            # Pre-GRCh37 (.12 is NCBI36). Naming it GRCh37 would make a wrong
            # assembly comparison look like a clean one.
            assembly = None
        return ParsedVersion("assembly", None, assembly, raw)

    if match := _RELEASE_RE.match(raw):
        release = int(match.group(1))
        if release == 0:
            # Neither scheme has a release 0, so there is nothing to be ambiguous
            # between; the schema pattern reports it as the format error it is.
            return ParsedVersion("uninterpretable", None, None, raw)
        if release < _FIRST_GRCH38_RELEASE:
            # Could be an Ensembl release or a GENCODE one, and they disagree
            # about the assembly. Which readings are open depends on how far
            # GENCODE has got, which only the shipped table knows, so the number
            # is carried up and the caller decides.
            return ParsedVersion("ambiguous", release, None, raw)
        return ParsedVersion("release", release, "GRCh38", raw)

    # The schema pattern rejects anything else as a format error, so there is
    # nothing useful to add here beyond declining to judge the content.
    return ParsedVersion("uninterpretable", None, None, raw)


@contextlib.contextmanager
def _shipped_table(path: Path):
    """Yield a shipped reference table's data lines, with its comment header dropped.

    Both committed artifacts share one container: gzip, UTF-8, one or more leading
    ``#`` lines naming what the table covers, then a CSV header. Said once here so
    the format is defined in one place rather than once per reader.

    The encoding is named rather than left to the locale: the generators write
    UTF-8, so reading must not depend on where the validator happens to run.
    """
    with gzip.open(path, "rt", newline="", encoding="utf-8") as fh:
        yield (line for line in fh if not line.startswith("#"))


@functools.lru_cache(maxsize=1)
def _gene_release_intervals() -> tuple[dict[str, list[tuple[int, int]]], int, int]:
    """Read the shipped table: gene -> runs of releases it exists in, and the covered range.

    Intervals rather than one (first, last) pair because genes are occasionally
    resurrected -- ENSG00000288593 is retired at r105 and returns at r109 -- and
    a flat pair would claim it existed in between.
    """
    table: dict[str, list[tuple[int, int]]] = {}
    with _shipped_table(_INTERVALS_PATH) as lines:
        rows = csv.reader(lines)
        next(rows, None)  # header
        for gene, first, last in rows:
            table.setdefault(gene, []).append((int(first), int(last)))
    covered = [r for runs in table.values() for pair in runs for r in pair]
    return table, min(covered), max(covered)


def _earliest_release_explaining(genes: set[str]) -> tuple[int | None, dict[int, int], set[str]]:
    """The earliest release containing every known gene, the per-release shortfall, and the unknown genes.

    A gene cannot be present before Ensembl defined it, so the earliest release
    that contains all of a file's genes is a hard lower bound on what produced
    it. Genes the table has never heard of cannot be explained by any release
    and are returned separately rather than making every release look wrong.

    Counts each gene's runs into a difference array rather than walking every
    release it spans: nearly every gene spans the whole table, which made the
    naive form O(genes x releases).
    """
    table, first_covered, last_covered = _gene_release_intervals()
    releases = range(first_covered, last_covered + 1)
    delta = [0] * (len(releases) + 1)
    unknown = set()
    for gene in genes:
        runs = table.get(gene)
        if runs is None:
            unknown.add(gene)
            continue
        for first, last in runs:
            delta[first - first_covered] += 1
            delta[last + 1 - first_covered] -= 1

    known = len(genes) - len(unknown)
    shortfall = {}
    running = 0
    for offset, release in enumerate(releases):
        running += delta[offset]
        shortfall[release] = known - running
    earliest = next((r for r in releases if shortfall[r] == 0), None) if known else None
    return earliest, shortfall, unknown


def check_gene_annotation_version(adata):
    """Report a declared gene annotation the file's own genes rule out. #710.

    Two independent comparisons, one needing no reference data:

    1. The declared value and ``reference_genome`` must name the same assembly.
       Ensembl r76 and later, and RefSeq accessions .26 and later, are GRCh38.
    2. The declared release must be one the genes allow. For each release, count
       the genes it cannot explain; the releases explaining all of them are the
       window that could have produced the file. Both directions are reported:
       genes are retired as well as born, so a declared release can fall after
       the window as well as before it -- nine prod declarations do.

    Dates on human ``ENSG`` identifiers only. Spike-ins, other species and
    custom features have no Ensembl release, and left in they would make every
    release fail to explain the file. The match is exact rather than a prefix
    test: gorilla identifiers are ``ENSGGOG...`` and would otherwise be dated
    as human.

    The declared organism gates comparison 1 and nothing else. The
    release-to-assembly mapping is human-only -- Ensembl numbers releases across
    all species, so r110 says GRCh38 only for a human file -- and that half is
    withheld unless every row states the human organism. Comparison 2 is not
    withheld: an ``ENSG`` identifier is a human gene whatever ``obs`` declares,
    so a file claiming another organism while carrying human genes is still
    dated against them.

    Returns:
        ``(warnings, errors)`` -- two lists of strings. Everything here is a
        warning: the field is the producer's to correct, and the schema itself
        documents it with assembly accessions (#719), so some non-datable
        values are conforming rather than mistaken.
    """
    obs = getattr_anndata(adata, "obs")
    if obs is None or "gene_annotation_version" not in obs.columns:
        return [], []

    # A duplicated column name makes obs[name] a DataFrame rather than a Series,
    # so .unique() raises and the run reports "Unexpected validation error"
    # instead of the real defect. The base validator already reports duplicate
    # column names; this check has nothing to add and should not mask it.
    if obs.columns.duplicated().any():
        duplicated = set(obs.columns[obs.columns.duplicated()])
        if duplicated & {"gene_annotation_version", "reference_genome", "organism_ontology_term_id"}:
            return [], []

    # The organism gates assembly claims and nothing else, because the two
    # comparisons rest on different evidence.
    #
    # Dating needs no organism statement: it runs on ENSG identifiers, which are
    # human by construction, against a human table, so what the column says
    # cannot make a human gene stop being one. A file whose required organism
    # column is missing still has a gene list, and "80 of these genes postdate
    # the release you declared" is true of it either way -- 20 prod files, 17 of
    # them eye, have no organism column and were losing real findings to a
    # blanket gate. Earlier revisions also returned early on a stated non-human
    # organism, which silenced findings rather than adding any: three mouse
    # cells in two million discarded the other two million, and a file whose
    # taxon and features disagree is already reported by the feature-id organism
    # check. Non-human features are excluded by the ENSG match and counted, and
    # whether a non-human organism belongs in an HCA file at all is the schema's
    # to say (#723).
    #
    # Assembly claims do need it, because the release-to-assembly mapping is
    # human-only: Ensembl numbers releases across all species, so r110 means
    # GRCh38 for a human file and GRCm39 for a mouse one. Requiring the positive
    # statement rather than rejecting an explicitly non-human one matters
    # because _deep_check runs after schema errors are collected -- a mouse file
    # with no organism column would otherwise be told its GRCm39 reference
    # contradicts r98. Only a well-formed curie is a claim -- a column of
    # "unknown" states no more than an absent one -- and every row must carry
    # the human one.
    organism = obs["organism_ontology_term_id"] if "organism_ontology_term_id" in obs.columns else None
    human = organism is not None and bool((organism.astype(str) == _HUMAN_ORGANISM).all())

    # Filtered by what the parser calls a missing value, not by one hardcoded
    # string. Discarding only "nan" left a column of "unknown" or "Not
    # available" looking like a declaration, so the file-level findings fired on
    # a file that had declared nothing -- while the same file saying "nan" was
    # silent. One rule for what counts as a declaration, and the parser owns it.
    # Stripped before de-duplication: parse_annotation_version strips, so "v98"
    # and " v98 " parse identically and produced two byte-identical warnings.
    declared = {str(v).strip() for v in obs["gene_annotation_version"].dropna().unique()}
    declared = {v for v in declared if parse_annotation_version(v).kind != "missing"}
    if not declared:
        return [], []

    # Which assemblies each declared version is paired with, and on how many
    # cells. Pairwise rather than column-wide: an integrated object legitimately
    # carries cells from several assemblies, so the question is not whether the
    # column is unanimous but whether any pair contradicts itself.
    pairs = _assembly_pairs(obs)
    n_cells = len(obs)
    # Counted over the column, not over the assemblies _assembly_pairs kept. A
    # column holding GRCh37 beside "not applicable" varies, even though only one
    # of those names an assembly -- counting the kept subset made it look uniform
    # and the message then said the whole file is GRCh37 when some cells are not.
    # dropna before astype(str): astype turns NaN into the string "nan", which
    # nunique then counts as an assembly. A column of GRCh38 beside NaN looked
    # like it varied, so the message framed every cell naming an assembly as a
    # minority -- the reading this count exists to prevent.
    # Stripped before counting, for the same reason the pairs are: "GRCh38" and
    # " GRCh38 " are one assembly, and counting them as two makes n_genomes > 1
    # on a file whose column does not vary -- the message then names a cell
    # split that is not there, which is the exact reading this count exists to
    # prevent.
    n_genomes = (
        obs["reference_genome"].dropna().astype(str).str.strip().nunique() if "reference_genome" in obs.columns else 0
    )

    var = getattr_anndata(adata, "var")
    # fullmatch, not match: Python's "$" also matches immediately before a final
    # newline, so "ENSG00000141510\n" would normalise to TP53 and be dated --
    # the exact misclassification the anchored pattern exists to prevent.
    #
    # The non-Ensembl features are counted as they are rejected, not derived as
    # len(features) - len(ensg). That subtraction compares a list against a set,
    # so anything collapsing under de-duplication was reported as a feature with
    # no Ensembl release: two copies of one gene, ENSG...18 beside ENSG...19, or
    # a pair of _PAR_Y ids, all of which are Ensembl genes.
    ensg: set[str] = set()
    n_non_ensembl = 0
    for feature in (str(i) for i in var.index) if var is not None else ():
        matched = _HUMAN_ENSG_RE.fullmatch(feature)
        if matched:
            ensg.add(matched.group(1))
        else:
            n_non_ensembl += 1

    # Dating depends only on the gene list, so it is done once rather than per
    # declared value; a file carrying several values is exactly the muddled case
    # this check reports on, and it should not pay for each one.
    dated = _earliest_release_explaining(ensg) if ensg else None

    warnings = []
    if dated and dated[0] is None and len(ensg) > len(dated[2]):
        warnings.append(_no_release_explains_message(dated, ensg, n_non_ensembl))

    if dated and dated[2]:
        # A gene no release contains means a newer annotation than this table
        # covers, or a reference built outside Ensembl. It is a fact about the
        # file's gene list, not about any one declared value, so it is said once
        # however many values the file carries.
        warnings.append(_unknown_identifiers_message(dated[2], ensg))

    for value in sorted(declared):
        warnings.extend(
            _annotation_version_messages(
                parse_annotation_version(value),
                pairs.get(value, {}),
                n_cells,
                n_genomes,
                human,
                ensg,
                n_non_ensembl,
                dated,
            )
        )
    return warnings, []


def _assembly_pairs(obs) -> dict[str, dict[str, int]]:
    """Map each declared version to the assemblies it appears with, and their cell counts.

    Only assemblies the column is allowed to name are kept; a placeholder or a
    malformed value names none, and its own enum already reports it.

    Both columns are stripped first, and only stripped: surrounding whitespace
    is not part of either name, and dropping a pair over it loses the one
    comparison that needs no reference data. Case is left alone -- "grch38" is
    still not an assembly this keeps -- because that is a different and larger
    question than padding, and the enum is the place to settle it.
    """
    if "reference_genome" not in obs.columns:
        return {}
    paired = obs[["gene_annotation_version", "reference_genome"]].dropna().astype(str)
    out: dict[str, dict[str, int]] = {}
    for (version, genome), count in paired.value_counts().items():
        assembly = genome.strip()
        if assembly in _KNOWN_ASSEMBLIES:
            # Keyed on the stripped version, because the caller looks these up by
            # the stripped value -- parse_annotation_version strips, so "v98" and
            # " v98 " are one declaration. Keying on the raw string meant a padded
            # value found nothing here and its assembly comparison was skipped in
            # silence, which is the one finding this check exists for. Counts are
            # summed rather than assigned, since two spellings now collapse onto
            # one key and the second would otherwise overwrite the first.
            bucket = out.setdefault(version.strip(), {})
            bucket[assembly] = bucket.get(assembly, 0) + int(count)
    return out


def _annotation_version_messages(
    parsed, genomes, n_cells, n_genomes, human, ensg: set[str], n_non_ensembl: int, dated
) -> list[str]:
    """Everything sayable about one declared value.

    ``genomes`` maps each assembly this value is paired with to its cell count.
    ``human`` is whether every row states the human organism; without it only
    the gene comparison runs, since that is the half ENSG identifiers support on
    their own.
    """
    said = []
    if parsed.kind == "missing":
        return []

    if parsed.kind == "uninterpretable":
        # The schema pattern already reports this as a format error; repeating it
        # here as a warning would say the same thing more quietly.
        return []

    if not human:
        # Everything that does not rest on the release-to-assembly mapping, which
        # is the only human-specific part. Dating runs on ENSG identifiers; the
        # ambiguity between Ensembl and GENCODE is about which scheme the number
        # belongs to, not which genome; and an accession names a genome rather
        # than an annotation whoever produced it. What stays gated is the GRCh37
        # and GRCh38 classification of a release, which holds only for human.
        if parsed.kind == "release" and parsed.release >= _FIRST_GRCH38_RELEASE:
            return _release_against_genes(parsed, ensg, n_non_ensembl, dated)
        if parsed.kind == "ambiguous" and parsed.release <= _highest_gencode_release():
            # Only while the number really is ambiguous -- above the ceiling it
            # can only be an Ensembl release, and saying which assembly that
            # implies is the human-specific part.
            return _ambiguous_release_number(parsed)
        if parsed.kind == "ambiguous":
            # Settled as an Ensembl release below r76. The assembly it implies is
            # human-specific and stays gated, but the gene list can still refute
            # it -- that rests on ENSG identifiers alone -- and where nothing
            # refutes it the coverage limit is still worth saying. Returning
            # nothing here made the value silent on a file with no organism
            # column while the same file with one got a finding.
            refuted = _refuted_by_later_genes(parsed, ensg, dated)
            if refuted:
                return [refuted]
            _, first_covered, _ = _gene_release_intervals()
            return [
                f"obs['gene_annotation_version'] is {parsed.raw!r}, which is older than this reference "
                f"data covers (from r{first_covered}), so the genes in this file were not checked "
                f"against it."
            ]
        if parsed.kind == "assembly":
            return [_accession_is_not_an_annotation(parsed)]
        return []

    if parsed.kind == "ambiguous" and parsed.release > _highest_gencode_release():
        # GENCODE has not issued this number, so it can only be an Ensembl
        # release -- and every release below r76 is GRCh37. Settling it here
        # rather than in its own branch is what lets it reach the assembly
        # comparison below: twigger2022 declares v75 against reference_genome
        # GRCh38, which is the contradiction this check exists to report. Only
        # r55 and later are GRCh37; older releases used NCBI36 and claim nothing.
        assembly = "GRCh37" if parsed.release >= _FIRST_GRCH37_RELEASE else None
        parsed = parsed._replace(kind="release", assembly=assembly)

    for genome, cells in sorted(genomes.items()):
        if not parsed.assembly or parsed.assembly == genome:
            continue
        # Name the cells only when reference_genome itself varies. The count is of
        # the (version, assembly) pair, so on a file whose genome column holds one
        # value it is really a count of the *version* partition -- saying "110,744
        # of 2,128,505 cells have GRCh38" where every cell does reads as a 5%
        # minority and attributes the split to the wrong column.
        where = (
            f"{cells:,} of this file's {n_cells:,} cells pair it with obs['reference_genome'] = {genome!r}"
            if n_genomes > 1
            else f"obs['reference_genome'] is {genome!r}"
        )
        said.append(
            f"obs['gene_annotation_version'] is {parsed.raw!r} ({parsed.assembly}), but {where}. "
            f"These name different assemblies."
        )

    if parsed.kind == "assembly":
        said.append(_accession_is_not_an_annotation(parsed))
        return said

    if parsed.kind == "ambiguous":
        said.extend(_ambiguous_release_number(parsed))
        return said

    said.extend(_release_against_genes(parsed, ensg, n_non_ensembl, dated))
    return said


def _highest_gencode_release() -> int:
    """The newest GENCODE human release that exists, as the ceiling of the ambiguity below.

    Derived from the shipped Ensembl table, not from the vendored
    ``gene_info.yml``. That file records the GENCODE version cellxgene-schema
    pinned, which lags the releases GENCODE has actually issued -- it says 48
    while our own table reaches Ensembl r116, and r115 and r116 are GENCODE 49
    and 50. Reading the ceiling from the pin classified those two as Ensembl-only
    and so as GRCh37, which put a false assembly mismatch on a valid GENCODE
    declaration.

    The offset is trusted here and nowhere else. GENCODE and Ensembl have run a
    fixed distance apart across the modern range -- GENCODE 32 is Ensembl 98,
    GENCODE 48 is Ensembl 114, the latter confirmed by gene_info.yml pinning
    every non-GENCODE species to release-114 -- and the ceiling sits at the top
    of that range. It is not trusted at the bottom, where GENCODE 19 is the
    GRCh37 freeze rather than anything near r85, which is why no message
    converts one scheme to the other.
    """
    _, _, last_covered = _gene_release_intervals()
    return last_covered - _GENCODE_ENSEMBL_OFFSET


def _accession_is_not_an_annotation(parsed) -> str:
    """Report an accession in a field that asks for an annotation.

    Says nothing about which genome the file is, only that the value names one
    rather than a gene set, so it holds without an organism statement.
    """
    return (
        f"obs['gene_annotation_version'] is {parsed.raw!r}, which names a genome assembly rather "
        f"than a gene annotation, so the genes in this file cannot be checked against it. Two "
        f"datasets on the same assembly can use annotations differing by thousands of genes."
    )


def _ambiguous_release_number(parsed) -> list[str]:
    """Report a number below r76, which Ensembl and GENCODE both write the same way.

    No Ensembl equivalent is quoted for the GENCODE reading. The two schemes run
    a fixed distance apart only recently -- GENCODE 32 is Ensembl 98 and GENCODE
    48 is Ensembl 114 -- and not across the older range, where GENCODE 19 is the
    GRCh37 freeze rather than anything near r85. Naming a release we would have
    to extrapolate is the one part of this message that could be wrong, and the
    producer is being asked which scheme they meant, not for a conversion.

    Only reached for numbers GENCODE has actually issued; above that the caller
    has already settled the value as an Ensembl release.
    """
    return [
        f"obs['gene_annotation_version'] is {parsed.raw!r}, which could be Ensembl r{parsed.release} or "
        f"GENCODE {parsed.release}. Those are different annotations, on possibly different assemblies, "
        f"so this file's genes cannot be checked against it until the value says which scheme is meant."
    ]


def _no_release_explains_message(dated, ensg: set[str], n_non_ensembl: int) -> str:
    """Report that no covered release contains every gene the table knows.

    A property of the gene list, so it is said once however many versions the
    file declares. Names the release that comes closest rather than referring to
    it: a curator cannot act on "the closest release" without knowing which.
    Ties resolve to the earliest, since shortfall is keyed in release order.
    """
    _, first_covered, last_covered = _gene_release_intervals()
    _, shortfall, unknown = dated
    closest = min(shortfall, key=lambda r: shortfall[r])
    skipped = n_non_ensembl
    context = f" ({_plural(skipped, 'feature')} excluded from dating -- not plain Ensembl gene ids)" if skipped else ""
    # Named, not just counted: #710 asks for the minimum *and* the unexplained
    # genes. On a file whose intervals are individually known but jointly
    # impossible, nothing else supplies an identifier to investigate -- the
    # unknown-identifier finding does not fire, and the per-declaration branch
    # reports only counts.
    table, _, _ = _gene_release_intervals()
    examples = heapq.nsmallest(
        3,
        (g for g in ensg if g not in unknown and not any(a <= closest <= b for a, b in table[g])),
    )
    return (
        f"No Ensembl release this reference data covers, r{first_covered} to r{last_covered}, contains "
        f"every one of this file's known genes -- "
        f"r{closest} comes closest, with {shortfall[closest]:,} of {len(ensg) - len(unknown):,} still "
        f"unexplained -- for example {', '.join(examples)}{context}.{_SCOPE_NO_RELEASE}"
    )


def _unknown_identifiers_message(unknown: set[str], ensg: set[str]) -> str:
    """Report identifiers no release in the shipped table contains.

    Names both ends of the covered range. Saying only "through r116" reads as
    *from the beginning* through r116, which points the reader at a newer
    annotation -- but the table starts at r76, and a gene retired before then is
    just as unknown to it. That is the likelier reading for a low-numbered
    identifier, and the message should not rule it out.
    """
    _, first_covered, last_covered = _gene_release_intervals()
    return (
        f"{len(unknown):,} of this file's {len(ensg):,} Ensembl identifiers are in none of the releases "
        f"this reference data covers, r{first_covered} to r{last_covered} -- for example "
        f"{', '.join(sorted(unknown)[:3])}. They may come from an annotation newer than r{last_covered}, "
        f"from one older than r{first_covered} (where genes retired before r{first_covered} would not appear "
        f"either), or from a reference built outside Ensembl."
    )


def _format_runs(releases) -> str:
    """Render release numbers as contiguous runs: "r98", "r105 to r110", "r100 to r104 and r109 to r116"."""
    runs: list[list[int]] = []
    for r in sorted(releases):
        if runs and r == runs[-1][1] + 1:
            runs[-1][1] = r
        else:
            runs.append([r, r])
    parts = [f"r{a}" if a == b else f"r{a} to r{b}" for a, b in runs]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f" and {parts[-1]}"


def _why_absent(ensg: set[str], unknown: set[str], table, release: int) -> tuple[int, int, int]:
    """Split the genes absent at ``release`` by why they are absent.

    Three reasons, and they mean different things about the declaration: defined
    after it (too early), retired before it (too late), or retired before it and
    defined again later -- a resurrection gap, which says only that this
    particular release is wrong. Every absent gene falls in exactly one, so the
    counts sum to the shortfall and no case renders as zeroes.
    """
    born_later = retired_earlier = in_gap = 0
    for gene in ensg:
        if gene in unknown:
            continue
        runs = table[gene]
        if any(first <= release <= last for first, last in runs):
            continue
        if all(first > release for first, _ in runs):
            born_later += 1
        elif all(last < release for _, last in runs):
            retired_earlier += 1
        else:
            in_gap += 1
    return born_later, retired_earlier, in_gap


def _refuted_by_later_genes(parsed, ensg: set[str], dated) -> str | None:
    """Rule out a release below the table's floor using genes born after it.

    A gene whose first appearance is later than the floor did not exist at any
    earlier release either, covered or not, so it refutes every release below
    the floor without the GRCh37 data being shipped (#724). Only a gene first
    seen *at* the floor is genuinely unknown before it.

    That inference is empirical, not structural: a gene present before the floor,
    retired, and later resurrected would break it. Measured against Ensembl's
    GRCh37 archive -- r65 to r75, 68,375 distinct ENSG ids -- none of the 30,786
    table genes first appearing above the floor occurs in any of them. If
    Ensembl ever resurrects a pre-r76 id into a later release this becomes wrong
    silently, which is one more reason to ship the GRCh37 range (#724).

    Rests on ENSG identifiers and the human table alone, so it is available
    whether or not obs states an organism -- the organism-neutral path calls it
    too, and without that the refutation vanished on a file with no organism
    column while firing on the same file with one.
    """
    if dated is None:
        return None
    table, first_covered, _ = _gene_release_intervals()
    _, _, unknown = dated
    born_later = sorted(g for g in ensg if g not in unknown and min(first for first, _ in table[g]) > first_covered)
    if not born_later:
        return None
    return (
        f"obs['gene_annotation_version'] is {parsed.raw!r}, but {len(born_later):,} of this file's "
        f"{len(ensg) - len(unknown):,} known genes did not exist until after Ensembl r{first_covered} -- "
        f"for example {', '.join(born_later[:3])}, so they cannot have been in r{parsed.release}."
        f"{_SCOPE_TOO_EARLY}"
    )


def _release_against_genes(parsed, ensg: set[str], n_non_ensembl: int, dated) -> list[str]:
    """Compare a declared Ensembl release with what the gene list can support.

    A release outside the shipped table is reported as such rather than as
    nonexistent, and the two directions mean different things: below the table
    is a permanent fact about Ensembl (r75 and earlier are GRCh37), while above
    it is a fact about this reference data and clears when it is regenerated.
    """
    table, first_covered, last_covered = _gene_release_intervals()
    # Against the constant, not the table's floor: which release first carried
    # GRCh38 is a fact about Ensembl, and reading it off the shipped data would
    # let a narrower table rewrite it.
    #
    # Deliberately ahead of the refutation below, so r54 and earlier is only
    # ever reported as undatable while r55-r75 can still be refuted by a gene
    # born after the table's floor. The same gene evidence therefore refutes
    # v55 and merely fails to date v54, which is an asymmetry on purpose: below
    # r55 no assembly is claimed at all and the declaration is two assembly
    # changes away from anything the table measures, so the one sentence that
    # can be said about it is that it cannot be checked. #724 would date the
    # whole band properly and this branch goes with it.
    if parsed.release < _FIRST_GRCH37_RELEASE:
        return [
            f"obs['gene_annotation_version'] is {parsed.raw!r}. Ensembl r{_FIRST_GRCH37_RELEASE} is the first "
            f"GRCh37 release and r{_FIRST_GRCH38_RELEASE} the first GRCh38 one, so r{parsed.release} predates "
            f"both and the genes in this file cannot be checked against it."
        ]
    if parsed.release < _FIRST_GRCH38_RELEASE:
        # Below the table, but not beyond refuting. A gene whose first appearance
        # is later than the table's floor did not exist at any earlier release
        # either, covered or not -- so it rules out every release below the
        # floor without the GRCh37 data being shipped (#724). Only a gene first
        # seen *at* the floor is genuinely unknown before it.
        refuted = _refuted_by_later_genes(parsed, ensg, dated)
        if refuted:
            return [refuted]
        # Nothing in the gene list rules it out, and the table cannot date it:
        # the limit here is our reference data, not the declaration.
        return [
            f"obs['gene_annotation_version'] is {parsed.raw!r}. Ensembl r{_FIRST_GRCH38_RELEASE} is the first "
            f"GRCh38 release, so r{parsed.release} is a GRCh37 annotation, which this reference data does "
            f"not cover -- the genes in this file were not checked against it."
        ]
    if parsed.release > last_covered:
        return [
            f"obs['gene_annotation_version'] is {parsed.raw!r}, which is newer than this reference data "
            f"covers (through r{last_covered}), so the genes in this file were not checked against it."
        ]
    if dated is None:
        return []
    earliest, shortfall, unknown = dated
    said = []

    skipped = n_non_ensembl
    context = f" ({_plural(skipped, 'feature')} excluded from dating -- not plain Ensembl gene ids)" if skipped else ""
    if earliest is None:
        # No release explains the whole gene list -- said once per file, from the
        # check itself. The declared value is still worth comparing against the
        # best available fit, which is a different fact: Cohen_26 declares v106,
        # leaving 615 genes unexplained where r110 leaves 99.
        missing_here = shortfall.get(parsed.release)
        best = min(shortfall.values())
        if missing_here and missing_here > best:
            # Same denominator rule as below: the shortfall counts genes the
            # table knows, so the total must too.
            return [
                f"obs['gene_annotation_version'] is {parsed.raw!r}, but {missing_here:,} of this file's "
                f"{len(ensg) - len(unknown):,} {'known genes' if unknown else 'genes'} are not in Ensembl "
                f"r{parsed.release} -- {missing_here - best:,} more than the closest release leaves "
                f"unexplained{context}.{_SCOPE_NO_RELEASE}"
            ]
        return []

    # The window is computed over the genes the table knows, so say so when some
    # are not -- otherwise this contradicts the unknown-identifiers warning above.
    scope = "This file's known genes are" if unknown else "This file's gene set is"
    # The shortfall counts only genes the table knows, so the denominator counts
    # those too -- dividing by every ENSG-shaped id mixed two populations and
    # read as "1 of 3" where one of the three was deliberately excluded from the
    # numerator. _no_release_explains_message already divided correctly.
    datable = len(ensg) - len(unknown)
    noun = ("known gene" if unknown else "gene") + ("" if datable == 1 else "s")
    missing_here = shortfall.get(parsed.release)
    if missing_here:
        # "Did not exist" is only true of genes defined after the declared release.
        # A retired gene did exist -- ENSG00000130723 spans r76-r102 -- so saying it
        # did not asserts the opposite of the table, and hides that the declaration
        # is too late rather than too early.
        reasons = [
            (n, text)
            for n, text in zip(
                _why_absent(ensg, unknown, table, parsed.release),
                ("defined after it", "retired before it", "retired before it and defined again later"),
                strict=True,
            )
            if n
        ]
        if len(reasons) == 1:
            verb = "did not exist in" if reasons[0][1] == "defined after it" else "are not in"
            absence = f"{verb} Ensembl r{parsed.release}: they were {reasons[0][1]}"
        else:
            absence = f"are not in Ensembl r{parsed.release}: " + ", ".join(f"{n:,} {text}" for n, text in reasons)
        # Both ends, not just the earliest. Genes are retired as well as born --
        # ENSG00000130723 exists r76-r102 and then stops -- so the releases that
        # explain a file form a window, and naming only its start reads as "use
        # this release or later" when every later release fails too.
        # "Consistent with" rather than "contains every gene here": the range is
        # pinned by genes -- one born late rules out everything earlier, one
        # retired early rules out everything later -- so no release in it is more
        # the answer than any other, and we are not identifying one.
        #
        # An end that reaches the table's floor or ceiling is ours, not the
        # genes': a gene retired at r102 pins the upper end, but "from r76" only
        # means "as far back as this reference data goes", and that gene is in
        # GRCh37 r75. Every prod file has both ends gene-pinned, so the range is
        # not currently overstating anything; it resolves with #724.
        # Reported as runs rather than min to max: a resurrected gene punches a
        # hole, and min-max would name releases that do not explain the file --
        # the same release the message is reporting as wrong.
        window = f"{scope} consistent with {_format_runs(r for r, missing in shortfall.items() if not missing)}"
        # Drawn from the known genes only, so the examples are a sample of the
        # very genes the count is of; an unknown gene is absent at every release
        # and has its own message above.
        examples = heapq.nsmallest(
            3,
            (
                g
                for g in ensg
                if g not in unknown and not any(first <= parsed.release <= last for first, last in table[g])
            ),
        )
        said.append(
            f"obs['gene_annotation_version'] is {parsed.raw!r}, but {missing_here:,} of this file's "
            f"{datable:,} {noun} {absence} -- for example {', '.join(examples)}. "
            f"{window}{context}.{_SCOPE_TOO_EARLY}"
        )
    return said


# ---------------------------------------------------------------------------
# Retired feature identifiers (#728)
# ---------------------------------------------------------------------------

_EVENTS_PATH = Path(__file__).parent / "gene_id_events.csv.gz"
# Reads the identifier back out of a per-identifier warning, so each one can be
# annotated with its own verdict. The wording is ours -- _validate_feature_ids
# writes it -- and the same prefix is what both warning sorters key on.
_FEATURE_ID_IN_WARNING = re.compile(r"Feature ID '([^']+)' in ")
# How many identifiers each finding names. Enough to recognise the group and go
# and look at one; the point of this check is that the full list is the pile it
# summarises, so a finding that reproduced it would defeat itself.
_EXAMPLE_CAP = 5
# What "current" means in these findings, said once. An identifier can be alive
# in Ensembl and still be unusable here, because the gene set a file is validated
# against is not all of Ensembl: it is GENCODE's reference annotation, which
# covers the primary assembly only. Measured against r114, Ensembl lists 86,364
# human genes and this set holds 78,894 of them -- every one of the 7,470 absent
# sits on a patch, scaffold or alt contig, and none on a chromosome. Aligners
# count against the primary assembly for the same reason it is drawn that way:
# include a region and its alternate copy and reads map to both.
#
# Derived from the vendored gene_info.yml rather than written out, so bumping
# cellxgene-schema moves this sentence with it.
# The Ensembl release the allowed gene set corresponds to. Genes first issued
# after it are newer than the allowed set rather than wrong, which is a different
# finding from one the reference structurally excludes.
_REFERENCE_RELEASE = int(_gene_info["human"]["version"]) + _GENCODE_ENSEMBL_OFFSET
_REFERENCE_LABEL = (
    f"GENCODE v{_gene_info['human']['version']} "
    f"(Ensembl {int(_gene_info['human']['version']) + _GENCODE_ENSEMBL_OFFSET})"
)
_REFERENCE_SCOPE = f"That set is {_REFERENCE_LABEL} restricted to the primary assembly: no patch or alt sequences."

# One retired identifier's row group: its successors in the session that retired
# it, and where the old gene sat in the last release that still carried it. A
# span is None when the server had no coordinates for it.
#
# The table's `event` column says what Ensembl did -- retired, renamed, merged,
# split -- and is used for exactly that: the words a finding reports. It is not
# used to classify: split-ness is derived from the length of `successors`, so
# there is one definition of what the validator acts on rather than two that can
# disagree.
GeneEvent = namedtuple("GeneEvent", "event successors old_span")


@functools.lru_cache(maxsize=1)
def _gene_id_events() -> tuple[dict[str, GeneEvent], dict[str, tuple]]:
    """Read the shipped event table: retired id -> what became of it, and successor spans.

    Returns ``(by_old, new_spans)``. The second is keyed by successor rather than
    by the identifier it replaced, because a chain is resolved by following
    several rows and the span wanted at the end belongs to whichever identifier
    the chain stopped on.
    """
    by_old: dict[str, GeneEvent] = {}
    new_spans: dict[str, tuple] = {}
    with _shipped_table(_EVENTS_PATH) as lines:
        for row in csv.DictReader(lines):
            old, new = row["old_id"], row["new_id"]
            entry = by_old.get(old)
            if entry is None:
                entry = GeneEvent(row["event"], [], _span(row, "old"))
                by_old[old] = entry
            if new:
                entry.successors.append(new)
                span = _span(row, "new")
                if span is not None:
                    new_spans[new] = span
    return by_old, new_spans


def _span(row: dict, side: str) -> tuple | None:
    """One side's (chromosome, start, end, strand), or None where it is absent.

    Absent is a real state rather than a defect: 42 successors have been retired
    themselves since, so the current release has no span for them, and a row
    recording no successor has nothing to give coordinates for.
    """
    chrom = row[f"{side}_chrom"]
    if not chrom:
        return None
    return (chrom, int(row[f"{side}_start"]), int(row[f"{side}_end"]), int(row[f"{side}_strand"]))


def _never_retired_class(gene: str) -> str:
    """Why an identifier Ensembl never retired is still absent from the reference.

    Three unrelated populations used to share one bucket. The shipped interval
    table separates them offline, and the separation is clean: of the genes it
    holds that the reference does not, 7,470 were already there at the reference's
    release and every one of those sits on a patch or alt contig, while 87 were
    first issued afterwards and every one of those is on a primary chromosome.
    No crossover, and nothing that the table knows has vanished without a
    retirement event being recorded for it.

    - excluded     -- present by the reference's release and still absent from it,
                      so the reference excludes it structurally. Patch and alt
                      sequences are what the reference leaves out.
    - newer        -- first issued after the allowed set's release. The gene is real
                      and current; the reference is simply older than the file.
    - unclassified -- the table has never heard of it, so nothing here can say.
    """
    table, _, last_covered = _gene_release_intervals()
    runs = table.get(gene)
    if runs is None:
        return "unclassified"
    if max(last for _, last in runs) < last_covered:
        # Gone from Ensembl with no retirement recorded. The table holds no such
        # gene today; classified as unknown rather than guessed at.
        return "unclassified"
    return "newer" if min(first for first, _ in runs) > _REFERENCE_RELEASE else "excluded"


def _terminals(gene: str, by_old: dict[str, GeneEvent], checker, seen: set[str] | None = None) -> set[str]:
    """Every current gene reachable from an identifier, however the path bends.

    _resolve follows a single chain and stops at a division, which is the right
    shape for a rename and the wrong one for a split whose pieces have histories
    of their own. This walks every branch, through renames and further splits,
    and returns the genes at the ends that the allowed gene set carries. The
    shared seen-set is the cycle guard; a gene reached twice by different
    branches is counted once.
    """
    seen = set() if seen is None else seen
    if gene in seen:
        return set()
    seen.add(gene)
    entry = by_old.get(gene)
    if entry is None:
        return {gene} if checker.is_valid_id(gene) else set()
    ends: set[str] = set()
    for successor in entry.successors:
        ends |= _terminals(successor, by_old, checker, seen)
    return ends


def _resolve(gene: str, by_old: dict[str, GeneEvent]) -> tuple[str | None, list[str]]:
    """Follow an identifier's successors to the end of its chain.

    Ensembl may replace A with B in one release and B with C in a later one, so
    the first hop is not the answer: renaming A to B leaves an identifier
    CELLxGENE still rejects. Every hop is a row in the shipped table -- the
    notebook this came from had to go back to the server for them, because it
    only knew about the identifiers in one atlas -- so the walk is local.

    Returns ``(terminal, split_into)``. A terminal is an identifier Ensembl
    records nothing further about, and is None when the chain instead ends in a
    deletion, in a division, or in a loop. ``split_into`` carries the successors
    of a division and is empty otherwise -- handed back rather than merely
    flagged, because whether those successors are in the allowed gene set
    decides what a curator can do about them.

    The seen-set is not defensive bookkeeping: the table is Ensembl's history and
    nothing forbids A -> B -> A across three releases, which would otherwise hang
    the validator rather than report anything.
    """
    seen: set[str] = set()
    current = gene
    while True:
        entry = by_old.get(current)
        if entry is None:
            return current, []
        if current in seen or not entry.successors:
            return None, []
        seen.add(current)
        if len(entry.successors) > 1:
            return None, list(entry.successors)
        current = entry.successors[0]


# How the old gene's span sits against its successor's. Stated as geometry and
# nothing more, because geometry is all the check knows: a label like "the
# genome disagrees" attached a verdict to a fact, and "trimmed" a story.
#   new contains old - the ordinary merge shape, 1,186 of 1,239. Not flagged.
#   old contains new - the successor is the smaller span. 4 of 1,239.
#   overlap          - they share positions, but neither contains the other.
#   disjoint         - no shared positions, or a different chromosome or strand.
_NEW_CONTAINS_OLD, _OLD_CONTAINS_NEW, _OVERLAP, _DISJOINT = (
    "new contains old",
    "old contains new",
    "overlap",
    "disjoint",
)
# Backwards names used by the tests and the flag table; the outcome strings
# above are what a reader sees.
_CONTAINED, _REVISED, _CONTRADICTED = _NEW_CONTAINS_OLD, _OVERLAP, _DISJOINT


def _compare_spans(old_span: tuple | None, new_span: tuple | None) -> str | None:
    """How the old gene's position relates to its successor's. None when unknowable.

    The claim being tested is Ensembl's, not ours: a replacement says these
    identifiers describe the same piece of DNA. The outcome is named by where the
    two spans sit and by nothing else.

    Chromosome and strand must agree before any of this: a successor on the other
    strand is not the same locus however the coordinates fall.
    """
    if old_span is None or new_span is None:
        return None
    old_chrom, old_start, old_end, old_strand = old_span
    new_chrom, new_start, new_end, new_strand = new_span
    if old_chrom != new_chrom or old_strand != new_strand:
        return _DISJOINT
    if new_start <= old_start and old_end <= new_end:
        return _NEW_CONTAINS_OLD
    if old_start <= new_start and new_end <= old_end:
        return _OLD_CONTAINS_NEW
    return _OVERLAP if old_start <= new_end and new_start <= old_end else _DISJOINT


def _examples(items) -> str:
    """Name a few of a group's identifiers, and say how many were not named."""
    shown = sorted(items)[:_EXAMPLE_CAP]
    rest = len(items) - len(shown)
    return ", ".join(shown) + (f" and {rest:,} more" if rest else "")


def _retired_findings(adata):
    """Classify the retired Ensembl identifiers behind the feature ID warnings. #728.

    A retired identifier is a warning here and an error at CELLxGENE, so every
    atlas heading for CZI has to clear them -- but on its own each warning says
    only that an identifier is not in the current GENCODE table. The breast v1
    integrated object emits 1,482 of them for 741 distinct identifiers, counted
    once in ``var`` and once in ``raw.var``, which tells a curator nothing about
    what to do next.

    Ensembl records what became of each one. This reads the shipped
    ``gene_id_events.csv.gz`` and sorts the identifiers into groups that imply
    different actions:

    - **same gene as another column** -- the successor is already a column here,
      or several of these identifiers share one successor, so remapping would
      leave columns sharing a name. The decision is the producer's.
    - **remappable** -- the successor is current and absent, so it is a rename.
    - **split** -- the old locus became several genes, and the coordinates say
      which part each successor covers.
    - **dead** -- no successor recorded, or the chain of replacements ends in one
      retired in turn. Only dropping is left.
    - **off the reference** -- Ensembl recorded a successor, but it is not in the
      allowed gene set, so no column can be named after it. Dropping again.
    - **version suffix** -- a current gene written as ``ENSG...18``. Not retired
      at all; the form is the whole problem.
    - **unclassified** -- in neither the current reference nor the GRCh38 event
      history, so nothing here can say what it was.

    The counts are over distinct identifiers, not warnings, which is where 1,482
    becomes 741. The per-identifier warnings are left alone: this is the summary
    that explains them, not a replacement for them.

    Claimed replacements are checked against the genome offline, using spans the
    table carries rather than anything fetched at validation time.

    Returns:
        ``(warnings, errors, verdicts)``. Everything is a warning, matching the
        severity of the per-identifier warnings it summarises; ``verdicts`` maps
        each feature as written to the clause that annotates its own warning.
    """
    # The same population the per-identifier warnings are raised over, derived
    # the same way, so the summary can never describe a different set from the
    # pile beneath it. Both dataframes, de-duplicated into one set: an identifier
    # in var and raw.var is one identifier with one history, and counting it
    # twice is what makes the current output read as 1,482 problems.
    # Held per dataframe rather than only as a set, because both counts come out
    # of this one pass: the identifiers, and how many warnings they produced.
    # Counting the second from a set would under-report a duplicated label, and
    # walking the indexes again to recount is a second pass over 37,000 features
    # to recover what this one already had.
    indexes = [
        [str(i) for i in df.index]
        for df_name in ("var", "raw.var")
        if (df := getattr_anndata(adata, df_name)) is not None
    ]
    features = {feature for index in indexes for feature in index}
    if not features:
        return [], [], {}

    checker = get_gene_checker(gencode.SupportedOrganisms.HOMO_SAPIENS)
    # Only human genes, matched exactly: gorilla identifiers are ENSGGOG... and a
    # prefix test would class them as human genes nobody can find. Everything
    # else is left alone rather than tested against the human table, which would
    # call a spike-in or a mouse gene missing -- the base validator checks each
    # feature against its own organism's table, and ERCC-00002 is valid there.
    #
    # GENCODE's _PAR_Y suffix falls through here, deliberately. Nothing upstream
    # of our files issues one: Ensembl r114 and r116 carry no gene id containing
    # "PAR" at all (PLCXD1 and SHOX appear once each, on X), the shipped GENCODE
    # table is Ensembl's primary assembly and has none either, and Cell Ranger
    # masks the region and drops those genes from its GTF. Measured: 0 of 217
    # readable prod h5ads carry such a feature. A reference built straight from
    # GENCODE's GTF could still produce them, and they would then be warned about
    # per identifier without appearing in this summary -- worth widening the match
    # for if one ever turns up, not before.
    candidates = {f: m.group(1) for f in features if (m := _HUMAN_ENSG_RE.fullmatch(f))}
    present = set(candidates.values())
    # What the base validator warns about, for these features and by its own
    # test: an identifier absent from the human table, whether because it is
    # retired or because the version suffix makes the lookup miss.
    warned = {f for f in candidates if not checker.is_valid_id(f)}
    if not warned:
        return [], [], {}

    by_old, new_spans = _gene_id_events()

    # Two shapes, and the shape says what the group holds: a replacement names
    # where the identifier went, and the rest have nowhere to point, so they are
    # sets rather than dicts mapping every member to None.
    #
    # Keyed throughout by the feature as written, never by the bare gene the
    # lookup used. A file writing ENSG00000112096.3 has no column called
    # ENSG00000112096, and naming the bare form sends a curator searching their
    # var index for a string that is not in it -- while saying nothing about the
    # suffix, which the rename also has to drop. The bare form stays available
    # through `candidates` for anything that needs to read the shipped table.
    replacements: dict[str, dict[str, str]] = {"same_gene": {}, "remappable": {}}
    # Why a replacement cannot simply be renamed, per feature. Without it the
    # annotated line reads "renamed to X [combine]", which states an action that
    # contradicts the fact beside it and never says what makes the difference.
    # Phrased against "this file" rather than "this dataset", which in HCA names a
    # source dataset as against an integrated object, or "column", which is the
    # matrix's word for it and belongs in the legend where the mechanics are.
    collides: dict[str, str] = {}
    # Where a chain ends in a division, keyed by feature. A -> B where B later
    # splits is a split, and reading the first hop's event called it a merge --
    # or, in the pile, "retired, no successor".
    splits: dict[str, list[str]] = {}
    plain: dict[str, set[str]] = {
        "dead": set(),
        "split": set(),
        "off_reference": set(),
        "versioned": set(),
        "excluded": set(),
        "newer": set(),
        "unclassified": set(),
    }
    for feature in warned:
        gene = candidates[feature]
        if gene not in by_old:
            # The bare identifier being valid means the gene is current and only
            # the written form is wrong, which is a different fix from any below.
            # Keyed by the feature as written, since that is what must change.
            group = "versioned" if checker.is_valid_id(gene) else _never_retired_class(gene)
            plain[group].add(feature)
            continue
        terminal, split_into = _resolve(gene, by_old)
        if split_into:
            # Every branch followed to every current gene it reaches, through
            # renames and further splits alike. Ensembl split ENSG00000157828 into
            # two genes at r76 and later brought both back together as one;
            # ENSG00000207555's pieces split again before reaching five current
            # genes. Stopping at the first split, or one level below it, reported
            # dead ends for both and told the curator to drop columns that have
            # current genes to point at. Six identifiers in the table move.
            ends = _terminals(gene, by_old, checker)
            if len(ends) == 1:
                # Out as several pieces, back as one gene: a replacement, not a
                # split, so it takes the ordinary rename-or-decide rules below
                # including the collision check.
                terminal, split_into = ends.pop(), []
            else:
                splits[feature] = sorted(ends) or sorted(split_into)
                plain["split" if ends else "off_reference"].add(feature)
                continue
        if split_into:
            splits[feature] = split_into
            # A split is only worth reporting as one if at least one piece is in
            # the reference. 46 of the table's 94 splits divide into genes none of
            # which are, and offering their spans would send a curator after
            # coordinates they cannot map a column onto.
            group = "split" if any(checker.is_valid_id(s) for s in split_into) else "off_reference"
            plain[group].add(feature)
        elif terminal is None:
            # Ensembl recorded no successor, or the chain ends where it began.
            plain["dead"].add(feature)
        elif not checker.is_valid_id(terminal):
            # Replaced, and the replacement is alive -- but off the reference gene
            # set, so there is still nothing here to point a column at.
            plain["off_reference"].add(feature)
        elif terminal in present:
            collides[feature] = "in file"
            replacements["same_gene"][feature] = terminal
        else:
            replacements["remappable"][feature] = terminal

    # A rename is only safe if the name it frees up is unclaimed afterwards, and
    # "already a column here" is only half of that test. Where several of these
    # identifiers share one successor, renaming each of them -- individually
    # unobjectionable -- leaves that many columns under one name. It is the same
    # Ensembl event as the branch above, several genes collapsing into one, and
    # the same decision for the producer; the only difference is whether the
    # surviving name is already in the file. Breast v1 has nine such groups
    # covering 21 identifiers, one of them four columns deep.
    claimed = Counter(replacements["remappable"].values())
    for feature, terminal in list(replacements["remappable"].items()):
        if claimed[terminal] > 1:
            collides[feature] = "shared"
            replacements["same_gene"][feature] = replacements["remappable"].pop(feature)

    # Every warned identifier lands in exactly one group, so this is non-empty
    # whenever `warned` is; it drops the groups with nothing in them so each
    # finding below can assume it has something to report.
    found = {name: group for name, group in (replacements | plain).items() if group}
    n_distinct = sum(len(group) for group in found.values())
    occurrences = sum(feature in warned for index in indexes for feature in index)
    spans = _span_verdicts(found, candidates, by_old, new_spans)
    warnings = [_retired_summary_message(n_distinct, occurrences)]
    warnings.extend(_retired_summary_table(found))
    warnings.append(_retired_detail_block(found, collides, spans, candidates, by_old, splits))
    return warnings, [], _feature_verdicts(found, candidates, by_old, collides, spans, splits)


def check_retired_feature_ids(adata):
    """The findings alone, for callers that do not hold the warning list. #728."""
    warnings, errors, _ = _retired_findings(adata)
    return warnings, errors


# Each class as a reader of the report meets it: what Ensembl did, then what to
# do about it. The two are not the same and do not map one to one -- the same
# merge is a rename when its target is absent from the file and a judgement call
# when it is already a column -- so they are kept apart rather than fused into a
# single phrase.
#
# The action is a bracketed tag so it is greppable and so the reasoning behind it
# is stated once, in the finding that counts the class, rather than repeated on
# every line. On a file with 625 identifiers in one class that is the difference
# between a report and a wall.
_ACTIONS = {
    "same_gene": "review",
    "remappable": "rename",
    "split": "drop or re-align",
    "dead": "drop",
    "off_reference": "drop",
    "excluded": "drop",
    "newer": "none",
    "versioned": "strip suffix",
    "unclassified": "ask",
}
# What Ensembl did, for the classes where the table records an event. The rest
# are not events at all -- a gene the reference never carried, one issued after
# it, a suffix -- and say what they are instead.
_EVENT_PHRASES = {
    "retired": "retired, no successor",
    "renamed": "renamed to {successor}",
    "merged": "merged into {successor}",
    "split": "split into {successors}",
}


def _what_happened(feature: str, name: str, successor: str | None, candidates: dict, by_old: dict, splits: dict) -> str:
    """What Ensembl did to this identifier, in as few words as carry it.

    Compact because it repeats on every line of a pile that runs to thousands.
    An arrow where there is a successor to name, a phrase where there is not.
    """
    if name == "excluded":
        return "patch or alt sequence"
    if name == "newer":
        return f"issued after {_REFERENCE_LABEL}"
    if name == "versioned":
        return "version suffix"
    if name == "unclassified":
        return "no event recorded"

    if pieces := splits.get(feature):
        # The chain's own ending, not the first hop's: A -> B where B later splits
        # is a split, whatever Ensembl called the first step.
        return f"split into {', '.join(sorted(pieces))}"
    if name == "off_reference":
        return "successor not in the allowed set"
    if successor is None:
        return "retired, no successor"
    return f"now {successor}"


# A claimed replacement the genome does not simply confirm, said on the row of
# the gene it concerns and nowhere else. A roll-up line counting them restated
# what those rows already show, one scroll away from the genes it was about.
_SPAN_FLAGS = {
    _OLD_CONTAINS_NEW: "old contains new",
    _OVERLAP: "overlap",
    _DISJOINT: "disjoint",
}


def _feature_verdicts(
    found: dict, candidates: dict, by_old: dict, collides: dict, spans: dict, splits: dict
) -> dict[str, str]:
    """One ``what happened [action]`` clause per feature, as written."""
    verdicts = {}
    for name, group in found.items():
        for feature in group:
            successor = group[feature] if isinstance(group, dict) else None
            happened = _what_happened(feature, name, successor, candidates, by_old, splits)
            flags = [f for f in (collides.get(feature), _SPAN_FLAGS.get(spans.get(feature, ""))) if f]
            marked = f"{happened} ({', '.join(flags)})" if flags else happened
            verdicts[feature] = f"{marked} [{_ACTIONS[name]}]"
    return verdicts


def _span_verdicts(found: dict, candidates: dict, by_old: dict, new_spans: dict) -> dict[str, str]:
    """How the genome answers each claimed replacement, per feature."""
    claims = {**found.get("same_gene", {}), **found.get("remappable", {})}
    return {
        feature: verdict
        for feature, successor in claims.items()
        if (verdict := _compare_spans(by_old[candidates[feature]].old_span, new_spans.get(successor)))
    }


def annotate_feature_id_warnings(warnings: list[str], verdicts: dict[str, str]) -> list[str]:
    """Append each identifier's verdict to the warning that names it.

    The summary above the pile can only afford a handful of examples per class,
    so on a file with 625 identifiers in one class it describes the shape of the
    problem and withholds the data needed to fix it. Annotated, the pile is the
    per-gene answer and the summary is its index: a curator greps "rename in
    place" and has their list.

    Warnings naming an identifier this check did not classify -- a spike-in,
    another species -- are returned unchanged.
    """
    annotated = []
    for warning in warnings:
        matched = _FEATURE_ID_IN_WARNING.search(warning)
        verdict = verdicts.get(matched.group(1)) if matched else None
        annotated.append(f"{warning.rstrip('.')}: {verdict}" if verdict else warning)
    return annotated


# One row per class: the short description for the summary table, and the action
# tag. The description says what Ensembl did and what it means for this file; the
# action says what to do. Order is the order they are reported in.
_CLASS_ROWS = (
    ("remappable", "renamed"),
    ("same_gene", "replaced; successor already in file or shared"),
    ("dead", "retired; no successor"),
    ("off_reference", "successor not in the allowed set"),
    ("split", "split into several genes"),
    ("excluded", "not on primary assembly"),
    ("versioned", "version suffix only"),
    ("newer", "issued after the allowed set"),
    ("unclassified", "no event recorded"),
)
_CLASS_TEXT = dict(_CLASS_ROWS)
# What each action means is documented in the package README and in
# docs/gene-id-contract.md, not printed on every run: a log says what is true of
# this file, and the same paragraph of guidance repeated on every validation is
# editorial rather than finding.
#
# A gene on a patch or alt sequence is [drop], not [drop or re-align]: re-aligning
# against a primary-assembly reference does not recover that feature, because the
# feature is not in such a reference at all. Re-alignment is the right answer to
# the file -- said once in the note below -- rather than to the gene. A split gene
# is different: its reads really are recoverable under the successors' names.
_ACTION_GUIDE = {
    "rename": "Replace the ID with its successor.",
    "review": "Needs a decision rather than a fix: these IDs are now one gene, and their counts may "
    "not be independent.",
    "drop": "Remove the feature. Its counts are not retained.",
    "drop or re-align": (
        "Remove the feature, or re-quantify from source: the reads are recoverable under the successors' names."
    ),
    "strip suffix": "Remove the version suffix; the gene itself is in the allowed gene set.",
    "none": "Nothing to change. The gene is newer than the allowed gene set, not wrong.",
    "ask": "Ask which reference built the file.",
}


def _retired_summary_message(n_distinct: int, occurrences: int) -> str:
    """The headline: how many identifiers, and how many warnings they produced.

    Two short lines rather than a paragraph. Both numbers appear in the report,
    and a reader who meets them without explanation assumes one is wrong.
    """
    counted = f"\n{occurrences:,} warnings across var and raw.var." if occurrences > n_distinct else ""
    return (
        f"{n_distinct:,} gene {'ID is' if n_distinct == 1 else 'IDs are'} not in "
        f"{_REFERENCE_LABEL[:-1]}, primary assembly only).{counted}"
    )


def _retired_summary_table(found: dict) -> list[str]:
    """How many identifiers fall in each class, and what each class needs.

    A table rather than a paragraph per class: the counts are what a reader scans
    for, and prose between them turns that scan into a read. What an action means
    is not explained here -- that is the same guidance on every run, and it lives
    in the package README and docs/gene-id-contract.md.

    Identifiers are not listed either. Every one is in the detail block below.
    """
    rows = [(name, text) for name, text in _CLASS_ROWS if found.get(name)]
    if not rows:
        return []
    count_width = max(len(f"{len(found[name]):,}") for name, _ in rows)
    text_width = max(len(text) for _, text in rows)
    lines = [f"  {len(found[name]):>{count_width},}  {text:<{text_width}}  [{_ACTIONS[name]}]" for name, text in rows]

    # Only the actions this file actually produces, so a report does not carry a
    # definition for a case it has none of.
    actions = dict.fromkeys(_ACTIONS[name] for name, _ in rows)
    tag_width = max(len(f"[{a}]") for a in actions)
    guide = [f"  {f'[{a}]':<{tag_width}}  {_ACTION_GUIDE[a]}" for a in actions]
    return ["Summary:\n" + "\n".join(lines), "Actions:\n" + "\n".join(guide)]


def _retired_detail_block(
    found: dict, collides: dict, spans: dict, candidates: dict, by_old: dict, splits: dict
) -> str:
    """Every identifier, once, in three aligned columns, grouped by action.

    One row per identifier rather than one per warning: an identifier in var and
    raw.var is one gene with one history, so the pile's 6,122 lines are 3,061
    facts. Grouped by action because that is what a reader acts on -- every
    [rename] together, so the list for a class is a block rather than a grep.

    The pile below carries the same identifiers under the base validator's own
    wording; this is the answer, that is the record.
    """
    rows = []
    for name, _ in _CLASS_ROWS:
        group = found.get(name)
        if not group:
            continue
        for feature in sorted(group):
            successor = group[feature] if isinstance(group, dict) else ""
            status = _CLASS_TEXT[name]
            if name in ("remappable", "same_gene", "off_reference"):
                event = "split" if feature in splits else by_old[candidates[feature]].event
                status = event if event in ("renamed", "merged", "split") else "replaced"
                if reason := collides.get(feature):
                    status += f"; successor {'already in file' if reason == 'in file' else 'shared'}"
                if name == "off_reference":
                    status += "; successor not in the allowed set"
            if flag := _SPAN_FLAGS.get(spans.get(feature, "")):
                status = f"{status}; {flag}"
            rows.append((feature, successor or "", status, f"[{_ACTIONS[name]}]"))

    old_w = max(len(r[0]) for r in rows)
    new_w = max(len(r[1]) for r in rows)
    status_w = max(len(r[2]) for r in rows)
    arrow = " -> " if new_w else "  "
    lines = [
        f"  {old:<{old_w}}{arrow if new else ' ' * len(arrow)}{new:<{new_w}}  {status:<{status_w}}  {tag}".rstrip()
        for old, new, status, tag in rows
    ]
    return "Details:\n" + "\n".join(lines)
