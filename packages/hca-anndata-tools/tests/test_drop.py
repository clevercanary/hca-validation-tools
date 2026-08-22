"""Tests for drop_obs_columns."""

import json
import os
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd

from hca_anndata_tools._io import _decode_bytes, read_obs_column_names
from hca_anndata_tools.cap import _LEGACY_CAP_MARKERS
from hca_anndata_tools.drop import drop_obs_columns
from hca_anndata_tools.write import EDIT_LOG_KEY, make_edit_entry


def _add_obs_cols(path, *names):
    """Add categorical obs columns to the fixture file, in place.

    Deliberately does *not* touch ``uns['schema_version']``: the fixture sets
    it, which is the marker ``strip_forbidden_obs_columns`` refuses on, so
    leaving it proves drop makes no such refusal (R6).
    """
    adata = ad.read_h5ad(path)
    for name in names:
        adata.obs[name] = pd.Categorical(["value"] * adata.n_obs)
    adata.write_h5ad(path)


def _set_uns(path, **entries):
    """Set uns keys on the fixture file, in place.

    Written through anndata rather than h5py so nested dicts land as real groups,
    which is how a CAP block arrives in practice.
    """
    adata = ad.read_h5ad(path)
    adata.uns.update(entries)
    adata.write_h5ad(path)


# The CAP block the legacy tests start from. Written nested and then downgraded
# by the `downgrade_cap_to_legacy` fixture, so its keys become the deprecated
# top-level ones.
_LEGACY_CAP_BLOCK = {
    "cellannotation_metadata": {"myset": {}},
    "cellannotation_schema_version": "0.2.0",
}


def _no_snapshot_written(path):
    """True when no timestamped edit snapshot appeared beside the source."""
    return not any("-edit-" in p.name for p in Path(path).parent.iterdir())


# --- R1: all-or-nothing ------------------------------------------------------


def test_drop_absent_column_errors_and_writes_nothing(sample_h5ad_for_write):
    """A name that isn't in obs is a mistake, not a no-op. Nothing is written."""
    result = drop_obs_columns(str(sample_h5ad_for_write), ["nonexistent_column"])

    assert "error" in result
    assert "not present in obs" in result["error"]
    assert "nonexistent_column" in result["error"]
    assert _no_snapshot_written(sample_h5ad_for_write)


def test_drop_is_atomic_across_valid_and_invalid(sample_h5ad_for_write):
    """The load-bearing R1 case: one bad name in a list of good ones drops
    nothing at all. A partial drop would silently half-curate a file."""
    _add_obs_cols(sample_h5ad_for_write, "ethnicity_verbatim")
    before = Path(sample_h5ad_for_write).read_bytes()

    result = drop_obs_columns(
        str(sample_h5ad_for_write),
        ["ethnicity_verbatim", "typo_column"],
    )

    assert "error" in result
    assert _no_snapshot_written(sample_h5ad_for_write)
    # The source file must be untouched, not merely un-snapshotted.
    assert Path(sample_h5ad_for_write).read_bytes() == before
    assert "ethnicity_verbatim" in ad.read_h5ad(sample_h5ad_for_write).obs.columns


def test_drop_reports_every_problem_at_once(sample_h5ad_for_write):
    """A caller who names two bad columns learns about both in one round trip."""
    result = drop_obs_columns(str(sample_h5ad_for_write), ["donor_id", "typo_column"])

    assert "error" in result
    # donor_id is schema-required *and* absent from the fixture; the schema
    # verdict is what matters, but the absent list must still be populated by
    # the other name rather than short-circuited away.
    assert "required" in result["error"]
    assert "typo_column" in result["error"]


def test_drop_empty_column_list_errors(sample_h5ad_for_write):
    result = drop_obs_columns(str(sample_h5ad_for_write), [])

    assert "error" in result
    assert "No columns given" in result["error"]
    assert _no_snapshot_written(sample_h5ad_for_write)


def test_drop_dedupes_repeated_names(sample_h5ad_for_write):
    """A repeated name is harmless — it drops once and reports once."""
    _add_obs_cols(sample_h5ad_for_write, "ethnicity_verbatim")

    result = drop_obs_columns(
        str(sample_h5ad_for_write),
        ["ethnicity_verbatim", "ethnicity_verbatim"],
    )

    assert "error" not in result
    assert result["obs_columns_dropped"] == ["ethnicity_verbatim"]


# --- R1: names must be plain column names, not HDF5 link paths ---------------


def test_drop_refuses_names_containing_a_slash(sample_h5ad_for_write):
    """h5py resolves '/X' from the file root and 'a/b' into subgroups, so an
    unguarded `c in obs` check accepts names pointing outside obs and the
    delete then unlinks them. Every other check here compares plain strings, so
    a path-shaped name would otherwise slip past all of them."""
    for name in ("/X", "/raw/X", "/var", "/uns", "/obsm/X_umap", "raw/X"):
        result = drop_obs_columns(str(sample_h5ad_for_write), [name])

        assert "error" in result, f"{name!r} must be refused"
        assert "cannot contain" in result["error"]
        assert _no_snapshot_written(sample_h5ad_for_write)

    # The matrix and the other top-level groups are still there.
    with h5py.File(sample_h5ad_for_write, "r") as f:
        assert "X" in f
        assert "var" in f
        assert "uns" in f


def test_drop_slash_path_cannot_bypass_the_schema_guard(sample_h5ad_for_write):
    """'/obs/donor_id' resolves to the same dataset as 'donor_id' but would not
    match the schema-required name set, so it must be refused by the path check
    rather than sliding past the tier comparison."""
    _add_obs_cols(sample_h5ad_for_write, "donor_id")

    result = drop_obs_columns(str(sample_h5ad_for_write), ["/obs/donor_id"])

    assert "error" in result
    assert "donor_id" in ad.read_h5ad(sample_h5ad_for_write).obs.columns


def test_drop_slash_path_cannot_erase_provenance(sample_h5ad_for_write):
    """The edit log lives at uns/provenance/edit_history. Reaching it through a
    link path would let a caller replace an audit trail with a fresh one that
    records only its own operation."""
    adata = ad.read_h5ad(sample_h5ad_for_write)
    adata.uns.setdefault("provenance", {})[EDIT_LOG_KEY] = json.dumps(
        [
            {
                **make_edit_entry(operation="prior_op", description="seed", details={}),
                "source_file": "seed.h5ad",
                "source_sha256": "0" * 64,
            }
        ]
    )
    adata.write_h5ad(sample_h5ad_for_write)

    result = drop_obs_columns(str(sample_h5ad_for_write), [f"/uns/provenance/{EDIT_LOG_KEY}"])

    assert "error" in result
    log = json.loads(ad.read_h5ad(sample_h5ad_for_write).uns["provenance"][EDIT_LOG_KEY])
    assert [e["operation"] for e in log] == ["prior_op"]


def test_drop_refuses_a_bare_string_for_columns(sample_h5ad_for_write):
    """columns="race" instead of ["race"] would iterate as characters and report
    'not present in obs: [r, a, c, e]' — a plausible slip from an MCP client
    with a useless error, so it is named explicitly.

    The ignore is deliberate and must stay: the annotation already rejects this
    statically, and the point of the test is the runtime guard that protects
    MCP callers, who get no type checking at all."""
    result = drop_obs_columns(str(sample_h5ad_for_write), "race")  # pyright: ignore[reportArgumentType]

    assert "error" in result
    assert "not a single string" in result["error"]
    assert _no_snapshot_written(sample_h5ad_for_write)


def test_drop_refuses_non_string_entries(sample_h5ad_for_write):
    """This is an MCP-exposed tool, so columns arrives as decoded JSON and may
    hold numbers or nulls. Every check downstream assumes strings, so they are
    rejected up front with a message that says so rather than surfacing
    "argument of type 'int' is not iterable"."""
    for bad in ([123], [None], ["race", 123]):
        result = drop_obs_columns(str(sample_h5ad_for_write), bad)  # pyright: ignore[reportArgumentType]

        assert "error" in result
        assert "only strings" in result["error"], f"{bad!r} gave: {result['error']}"
        assert _no_snapshot_written(sample_h5ad_for_write)


def test_drop_accepts_a_tuple_of_names(sample_h5ad_for_write):
    """Nothing depends on the argument being a list specifically, so a tuple
    from a caller that built one should not be an error — and the annotation
    says so, which is why this call needs no type-checker exemption."""
    _add_obs_cols(sample_h5ad_for_write, "race")

    result = drop_obs_columns(str(sample_h5ad_for_write), ("race",))

    assert "error" not in result
    assert result["obs_columns_dropped"] == ["race"]


def test_drop_refuses_blank_names(sample_h5ad_for_write):
    result = drop_obs_columns(str(sample_h5ad_for_write), ["  "])

    assert "error" in result
    assert "cannot contain" in result["error"]


def test_drop_reports_each_bad_name_once(sample_h5ad_for_write):
    """A malformed name is necessarily absent from obs too, so it would appear
    under both problems unless the absent check excludes it.

    Listing '/X' as merely "not present in obs" implied its only fault was a typo
    and sent the reader past the path-name rule that actually explains it.
    """
    result = drop_obs_columns(str(sample_h5ad_for_write), ["/X", "definitely_not_here"])

    error = result["error"]
    assert error.count("/X") == 1, error
    # The genuinely-absent name is still reported, and under the right problem.
    absent_part = error.split("not present in obs:")[1]
    assert "definitely_not_here" in absent_part
    assert "/X" not in absent_part


# --- R2: guard tiers ---------------------------------------------------------


def test_drop_refuses_schema_required_column(sample_h5ad_for_write):
    """donor_id is required; dropping it would leave an invalid file."""
    _add_obs_cols(sample_h5ad_for_write, "donor_id")

    result = drop_obs_columns(str(sample_h5ad_for_write), ["donor_id"])

    assert "error" in result
    assert "required" in result["error"]
    assert "donor_id" in result["error"]
    assert _no_snapshot_written(sample_h5ad_for_write)


def test_drop_refuses_schema_optional_column(sample_h5ad_for_write):
    """author_batch_notes is optional per the schema but holds producer data
    that cannot be reconstructed, so it is refused too."""
    _add_obs_cols(sample_h5ad_for_write, "author_batch_notes")

    result = drop_obs_columns(str(sample_h5ad_for_write), ["author_batch_notes"])

    assert "error" in result
    assert "author_batch_notes" in result["error"]
    # Reported as the optional tier, not the required one — the distinction is
    # the seam a future force flag would use.
    assert "optional" in result["error"]
    assert "required" not in result["error"]
    assert _no_snapshot_written(sample_h5ad_for_write)


def test_drop_refuses_obs_index(sample_h5ad_for_write):
    """The index is a dataset in the obs group like any column, so a caller can
    name it. Deleting it would destroy the file's cell identities."""
    with h5py.File(sample_h5ad_for_write, "r") as f:
        index_name = _decode_bytes(f["obs"].attrs.get("_index", "_index"))

    result = drop_obs_columns(str(sample_h5ad_for_write), [index_name])

    assert "error" in result
    assert "obs index" in result["error"]
    assert _no_snapshot_written(sample_h5ad_for_write)


# --- R2: the columns #538 made visible to the guard --------------------------
#
# These four were invisible to annDataLocation-walking until #538 (PR #545), so an
# earlier revision of this tool deleted all of them without complaint. The LinkML
# schema was the real defect: `Cell` was a bare `pass` with nowhere for the cell
# annotation to live, and two `Sample` slots carried no annotation. A hardcoded
# column list here was considered and rejected — the premise of #531 is that such
# lists rot.
#
# Pinned here because the guard's coverage of them is a property of *this* tool,
# and nothing else in this suite would notice if a future schema regeneration
# silently dropped an annotation.


def test_drop_refuses_the_columns_538_made_visible(sample_h5ad_for_write):
    """All three at once, and the error must name every one of them.

    Refusing two of three would be worse than refusing none: the caller would see
    an error, assume nothing happened, and the tool's all-or-nothing contract (R1)
    is what makes that assumption safe.
    """
    columns = ["cell_type_ontology_term_id", "is_primary_data", "sample_collection_method"]
    _add_obs_cols(sample_h5ad_for_write, *columns)

    result = drop_obs_columns(str(sample_h5ad_for_write), columns)

    assert "error" in result
    for column in columns:
        assert column in result["error"], f"{column} fell through the guard"
    assert _no_snapshot_written(sample_h5ad_for_write)


def test_drop_splits_the_538_columns_across_tiers(sample_h5ad_for_write):
    """`sample_collection_method` is schema-required; the other two are optional.

    The tiers are reported apart because that seam is what a future `--force` flag
    would act on, so a column landing in the wrong tier would become droppable
    once that flag exists.
    """
    columns = ["cell_type_ontology_term_id", "is_primary_data", "sample_collection_method"]
    _add_obs_cols(sample_h5ad_for_write, *columns)

    error = drop_obs_columns(str(sample_h5ad_for_write), columns)["error"]

    required_part, _, optional_part = error.partition("; ")
    assert "required" in required_part
    assert "sample_collection_method" in required_part
    assert "optional" in optional_part
    assert "cell_type_ontology_term_id" in optional_part
    assert "is_primary_data" in optional_part


def test_drop_refuses_cell_type_ontology_term_id(sample_h5ad_for_write):
    """The worst of the four to lose: it is unrecoverable.

    `populate_labels` derives `cell_type` *from* this column, not the reverse, so
    once it is gone the file's cell annotation cannot be reconstructed from
    anything else in the file. It is schema-*optional* (matching the h5ad
    validator's `requirement_level`), which is exactly why the guard has to refuse
    the optional tier too rather than only the required one.
    """
    _add_obs_cols(sample_h5ad_for_write, "cell_type_ontology_term_id")

    result = drop_obs_columns(str(sample_h5ad_for_write), ["cell_type_ontology_term_id"])

    assert "error" in result
    assert "cell_type_ontology_term_id" in result["error"]
    assert "optional" in result["error"]
    assert _no_snapshot_written(sample_h5ad_for_write)


def test_drop_refuses_author_cell_type(sample_h5ad_for_write):
    """#538 gave `Cell` this slot too, so it is now guarded.

    Deliberate: it holds the author's own cell-type naming, which no other column
    can reconstruct once removed. Distinct from the derived labels below, which are
    unguarded precisely because they are regenerable.
    """
    _add_obs_cols(sample_h5ad_for_write, "author_cell_type")

    result = drop_obs_columns(str(sample_h5ad_for_write), ["author_cell_type"])

    assert "error" in result
    assert "author_cell_type" in result["error"]
    assert _no_snapshot_written(sample_h5ad_for_write)


# --- R3: derived labels are not guarded --------------------------------------


def test_drop_allows_canonical_derived_labels(sample_h5ad_for_write):
    """cell_type/sex/tissue are outputs populate_labels regenerates from the
    matching *_ontology_term_id columns, so they carry no guard."""
    result = drop_obs_columns(str(sample_h5ad_for_write), ["cell_type", "sex", "tissue"])

    assert "error" not in result
    written = ad.read_h5ad(result["output_path"])
    for col in ("cell_type", "sex", "tissue"):
        assert col not in written.obs.columns


# --- R4: the guard must not block the use case the tool exists for -----------


def test_drop_removes_ethnicity_under_noncanonical_names(sample_h5ad_for_write):
    """The reason this tool exists. These five names are how the breast-v1
    source datasets carry ethnicity; none is a schema field, so none is
    guarded. If this test fails the tool cannot do its job."""
    aliases = [
        "self_reported_ethnicity_label",
        "ethnicity_verbatim",
        "ethnicity_grouped",
        "reported_ethnicity",
        "race",
    ]
    _add_obs_cols(sample_h5ad_for_write, *aliases)

    result = drop_obs_columns(str(sample_h5ad_for_write), aliases)

    assert "error" not in result
    assert result["obs_columns_dropped"] == aliases
    written = ad.read_h5ad(result["output_path"])
    for col in aliases:
        assert col not in written.obs.columns


def test_drop_removes_producer_label_columns(sample_h5ad_for_write):
    """The other target class: derived labels under non-canonical names, which
    differ per dataset and so cannot be a fixed list in code."""
    labels = ["cell_type_label", "assay_label", "tissue_label"]
    _add_obs_cols(sample_h5ad_for_write, *labels)

    result = drop_obs_columns(str(sample_h5ad_for_write), labels)

    assert "error" not in result
    written = ad.read_h5ad(result["output_path"])
    for col in labels:
        assert col not in written.obs.columns


# --- uns references: delete what the column owns, refuse what references it --


def test_drop_deletes_the_palette_the_column_owns(sample_h5ad_for_write):
    """scanpy stores a categorical's colours at uns['<col>_colors']. The palette
    belongs to the column, so it goes with it — left behind it is orphaned, and
    the validator rejects a colors field with no matching obs column."""
    _add_obs_cols(sample_h5ad_for_write, "cell_type_label")
    adata = ad.read_h5ad(sample_h5ad_for_write)
    adata.uns["cell_type_label_colors"] = np.array(["#111111", "#222222"])
    adata.uns["unrelated_colors"] = np.array(["#333333"])
    adata.write_h5ad(sample_h5ad_for_write)

    result = drop_obs_columns(str(sample_h5ad_for_write), ["cell_type_label"])

    assert "error" not in result
    assert result["uns_keys_dropped"] == ["cell_type_label_colors"]
    written = ad.read_h5ad(result["output_path"])
    assert "cell_type_label_colors" not in written.uns
    # A palette belonging to some other column is none of our business.
    assert "unrelated_colors" in written.uns


def test_drop_reports_no_uns_keys_when_there_is_no_palette(sample_h5ad_for_write):
    _add_obs_cols(sample_h5ad_for_write, "race")

    result = drop_obs_columns(str(sample_h5ad_for_write), ["race"])

    assert result["uns_keys_dropped"] == []


def test_drop_refuses_column_referenced_by_batch_condition(sample_h5ad_for_write):
    """uns['batch_condition'] is typed match_obs_columns, so its entries must
    name obs columns. It declares which columns define the experiment's
    batches — rewriting that claim is a curation decision, not cleanup."""
    _add_obs_cols(sample_h5ad_for_write, "producer_batch")
    adata = ad.read_h5ad(sample_h5ad_for_write)
    adata.uns["batch_condition"] = np.array(["producer_batch"])
    adata.write_h5ad(sample_h5ad_for_write)

    result = drop_obs_columns(str(sample_h5ad_for_write), ["producer_batch"])

    assert "error" in result
    assert "batch_condition" in result["error"]
    assert "producer_batch" in ad.read_h5ad(sample_h5ad_for_write).obs.columns


def test_drop_reads_scalar_batch_condition(sample_h5ad_for_write):
    """A bare string lands on disk as a scalar bytes dataset rather than an
    array, so iterating it would yield individual characters. Covers the
    scalar branch of _read_batch_condition, which the array-valued tests
    above never reach."""
    _add_obs_cols(sample_h5ad_for_write, "producer_batch")
    adata = ad.read_h5ad(sample_h5ad_for_write)
    adata.uns["batch_condition"] = "producer_batch"
    adata.write_h5ad(sample_h5ad_for_write)

    with h5py.File(sample_h5ad_for_write, "r") as f:
        assert f["uns"]["batch_condition"].shape == (), "fixture must produce a scalar, not an array"

    result = drop_obs_columns(str(sample_h5ad_for_write), ["producer_batch"])

    assert "error" in result
    assert "batch_condition" in result["error"]


def test_drop_allows_column_absent_from_batch_condition(sample_h5ad_for_write):
    """The batch_condition check must key on membership, not on the key merely
    existing — otherwise any file with batches becomes undroppable."""
    _add_obs_cols(sample_h5ad_for_write, "producer_batch", "race")
    adata = ad.read_h5ad(sample_h5ad_for_write)
    adata.uns["batch_condition"] = np.array(["producer_batch"])
    adata.write_h5ad(sample_h5ad_for_write)

    result = drop_obs_columns(str(sample_h5ad_for_write), ["race"])

    assert "error" not in result


def test_drop_refuses_cap_annotation_set_columns(sample_h5ad_for_write):
    """CAP set columns are named '<set>--<suffix>' and are not schema-named, so
    nothing else catches them. uns['cap_metadata'] would still declare the set,
    leaving it broken — the set has to go, not its columns."""
    _add_obs_cols(sample_h5ad_for_write, "myset--cell_type")
    _set_uns(sample_h5ad_for_write, cap_metadata={"cellannotation_schema_version": "1.0.0"})

    result = drop_obs_columns(str(sample_h5ad_for_write), ["myset--cell_type"])

    assert "error" in result
    assert "cap_metadata" in result["error"]
    assert "myset--cell_type" in ad.read_h5ad(sample_h5ad_for_write).obs.columns


def test_drop_allows_double_dash_when_no_cap_metadata(sample_h5ad_for_write):
    """Without a CAP declaration there is no set to break, so the '--' shape is
    just a column name."""
    _add_obs_cols(sample_h5ad_for_write, "odd--name")

    result = drop_obs_columns(str(sample_h5ad_for_write), ["odd--name"])

    assert "error" not in result


def test_drop_still_works_on_a_nested_cap_file(sample_h5ad_for_write):
    """The nested layout is supported, so a plain producer column drops from a
    CAP file exactly as it would from a file with no CAP at all.

    Paired with the legacy tests below: together they pin that the refusal keys
    on the *layout* and not merely on CAP being present, which is the way an
    over-broad guard would break the use case this tool exists for."""
    _add_obs_cols(sample_h5ad_for_write, "race", "myset--cell_type")
    _set_uns(sample_h5ad_for_write, cap_metadata={"cellannotation_schema_version": "1.0.0"})

    result = drop_obs_columns(str(sample_h5ad_for_write), ["race"])

    assert "error" not in result
    obs = ad.read_h5ad(result["output_path"]).obs
    assert "race" not in obs.columns
    # The CAP column is untouched, so the drop was surgical rather than the
    # guard simply having nothing to protect.
    assert "myset--cell_type" in obs.columns


# --- legacy CAP layout: the file is refused, not the columns (#552) ----------
#
# Built through the `downgrade_cap_to_legacy` fixture, which is the suite's one
# spelling of "a legacy-layout file" (test_cap.py and test_copy_cap.py use it
# too). Going nested-then-downgrade rather than writing the top-level keys by
# hand also mirrors how these files really arose.


def test_drop_refuses_legacy_cap_layout_for_any_column(sample_h5ad_for_write, downgrade_cap_to_legacy):
    """The bug this closes. The '--' guard reads uns['cap_metadata'], so in the
    top-level layout it sees no declaration and every CAP column looks
    droppable — `race` here proves the refusal is not keyed on the request:
    naming an ordinary producer column is refused too, because it is the file
    that is unsupported."""
    _add_obs_cols(sample_h5ad_for_write, "race")
    _set_uns(sample_h5ad_for_write, cap_metadata=_LEGACY_CAP_BLOCK)
    downgrade_cap_to_legacy(sample_h5ad_for_write)

    result = drop_obs_columns(str(sample_h5ad_for_write), ["race"])

    assert "error" in result
    assert "not supported" in result["error"]
    # The message names the keys actually detected. Asserted because
    # LEGACY_LAYOUT_DESCRIPTION renders them from _LEGACY_CAP_MARKERS, and the
    # whole point of deriving it is that the two cannot drift — a broken join
    # would render "the deprecated top-level CAP layout ()" and every other
    # assertion in this file would still pass.
    for marker in _LEGACY_CAP_MARKERS:
        assert f"uns[{marker!r}]" in result["error"]
    assert _no_snapshot_written(sample_h5ad_for_write)
    assert "race" in ad.read_h5ad(sample_h5ad_for_write).obs.columns


def test_drop_refuses_legacy_cap_annotation_columns(sample_h5ad_for_write, downgrade_cap_to_legacy):
    """The data actually at risk: hand-curated CAP columns in the legacy layout,
    which deleted silently before #552."""
    _add_obs_cols(sample_h5ad_for_write, "myset--cell_type", "myset--rationale")
    _set_uns(sample_h5ad_for_write, cap_metadata=_LEGACY_CAP_BLOCK)
    downgrade_cap_to_legacy(sample_h5ad_for_write)

    result = drop_obs_columns(
        str(sample_h5ad_for_write),
        ["myset--cell_type", "myset--rationale"],
    )

    assert "error" in result
    assert "not supported" in result["error"]
    assert _no_snapshot_written(sample_h5ad_for_write)
    obs = ad.read_h5ad(sample_h5ad_for_write).obs
    assert {"myset--cell_type", "myset--rationale"} <= set(obs.columns)


def test_drop_refuses_mixed_cap_layout(sample_h5ad_for_write):
    """A file carrying both layouts is refused on the legacy keys rather than
    letting the nested block win — the same clean-break rule `copy_cap` applies.

    Worth its own test because the tempting refactor is to make the legacy check
    conditional on `cap_metadata` being absent, which reads as tidier and would
    let every mixed file through. Hand-rolled rather than fixture-built because
    `downgrade_cap_to_legacy` removes the nested block by design, as the mixed
    cases in test_cap.py and test_copy_cap.py also do."""
    _add_obs_cols(sample_h5ad_for_write, "race")
    _set_uns(
        sample_h5ad_for_write,
        cap_metadata={"cellannotation_schema_version": "1.0.0"},
        **_LEGACY_CAP_BLOCK,
    )

    result = drop_obs_columns(str(sample_h5ad_for_write), ["race"])

    assert "error" in result
    assert "not supported" in result["error"]
    assert _no_snapshot_written(sample_h5ad_for_write)


# --- R5/R6: result shape and mechanics ---------------------------------------


def test_drop_preserves_caller_order_and_leaves_other_columns(sample_h5ad_for_write):
    _add_obs_cols(sample_h5ad_for_write, "race", "ethnicity_verbatim")

    result = drop_obs_columns(str(sample_h5ad_for_write), ["race", "ethnicity_verbatim"])

    assert result["obs_columns_dropped"] == ["race", "ethnicity_verbatim"]
    written = ad.read_h5ad(result["output_path"])
    # Untouched columns survive, including the numeric one.
    for col in ("sex", "tissue", "cell_type", "n_counts"):
        assert col in written.obs.columns


def test_drop_succeeds_on_cellxgene_layout(cellxgene_h5ad):
    """Unlike strip_forbidden_obs_columns, this makes no layout refusal —
    removing an arbitrary column is layout-agnostic."""
    _add_obs_cols(cellxgene_h5ad, "ethnicity_verbatim")

    result = drop_obs_columns(str(cellxgene_h5ad), ["ethnicity_verbatim"])

    assert "error" not in result
    assert "ethnicity_verbatim" not in ad.read_h5ad(result["output_path"]).obs.columns


def test_drop_updates_column_order(sample_h5ad_for_write):
    """column-order must lose exactly the dropped names and keep the survivors
    in their original relative order, or the file stops round-tripping."""
    _add_obs_cols(sample_h5ad_for_write, "race")
    before = read_obs_column_names(str(sample_h5ad_for_write))

    result = drop_obs_columns(str(sample_h5ad_for_write), ["race", "cell_type"])
    after = read_obs_column_names(result["output_path"])

    assert "race" not in after
    assert "cell_type" not in after
    assert after == [c for c in before if c not in ("race", "cell_type")]


def test_drop_preserves_existing_edit_log(sample_h5ad_for_write):
    """An h5ad already carrying edit-log entries must get the new entry
    appended, not replacing history."""
    adata = ad.read_h5ad(sample_h5ad_for_write)
    adata.obs["race"] = pd.Categorical(["value"] * adata.n_obs)
    prior_entry = make_edit_entry(
        operation="prior_synthetic_op",
        description="Synthetic prior entry to verify the drop tool appends.",
        details={"shape_before": [adata.n_obs, adata.n_vars]},
    )
    seed_log = json.dumps([{**prior_entry, "source_file": "synthetic-seed.h5ad", "source_sha256": "0" * 64}])
    adata.uns.setdefault("provenance", {})[EDIT_LOG_KEY] = seed_log
    adata.write_h5ad(sample_h5ad_for_write)

    result = drop_obs_columns(str(sample_h5ad_for_write), ["race"])
    assert "error" not in result

    log = json.loads(ad.read_h5ad(result["output_path"]).uns["provenance"][EDIT_LOG_KEY])
    assert len(log) == 2, f"Expected 2 entries (prior + drop), got {len(log)}"
    assert log[0]["operation"] == "prior_synthetic_op"
    assert log[1]["operation"] == "drop_obs_columns"
    assert log[1]["details"]["obs_columns_dropped"] == ["race"]


def test_drop_missing_file():
    result = drop_obs_columns("/nonexistent/path/file.h5ad", ["race"])

    assert "error" in result
    assert "File not found" in result["error"]


def test_drop_same_second_snapshot_refused(sample_h5ad_for_write, monkeypatch):
    """A collision that survives the boundary wait is refused before anything is
    touched — otherwise the output would be named after its own source and the
    failure path would unlink that source snapshot. Patching generate_output_path
    to the identity makes the retry collide too, which is the unresolvable case."""
    _add_obs_cols(sample_h5ad_for_write, "junk_col")
    monkeypatch.setattr("hca_anndata_tools.write.generate_output_path", lambda p: p)
    slept = []
    monkeypatch.setattr("hca_anndata_tools.write.time.sleep", slept.append)

    result = drop_obs_columns(str(sample_h5ad_for_write), ["junk_col"])

    assert slept == [1], "the boundary wait should be attempted once before refusing"

    # Asserted before the message: unguarded, this file is unlinked (#598).
    assert sample_h5ad_for_write.is_file()
    assert "junk_col" in ad.read_h5ad(sample_h5ad_for_write).obs.columns  # nor modified
    assert "error" in result
    assert "already exists" in result["error"]


def test_drop_same_second_collision_resolves_after_waiting(sample_h5ad_for_write, monkeypatch):
    """The common case: a snapshot written this second collides, the tool waits
    out the boundary, and the retry gets a fresh name (mirrors copy_cap). Only a
    collision that survives the wait is refused."""
    _add_obs_cols(sample_h5ad_for_write, "junk_col")
    fresh = sample_h5ad_for_write.with_name("fresh-edit-2026-08-22-00-00-01.h5ad")
    names = iter([str(sample_h5ad_for_write), str(fresh)])
    monkeypatch.setattr("hca_anndata_tools.write.generate_output_path", lambda p: next(names))
    slept = []
    monkeypatch.setattr("hca_anndata_tools.write.time.sleep", slept.append)

    result = drop_obs_columns(str(sample_h5ad_for_write), ["junk_col"])

    assert slept == [1]
    assert "error" not in result
    assert result["obs_columns_dropped"] == ["junk_col"]
    assert Path(result["output_path"]).name == "fresh-edit-2026-08-22-00-00-01.h5ad"


def test_drop_failed_copy_leaves_no_partial_snapshot(sample_h5ad_for_write, monkeypatch):
    """A copy that dies partway (ENOSPC on a multi-GB h5ad) must not leave the
    partial file behind: it carries the newest -edit- timestamp, so resolve_latest
    would hand that truncated file to every later call on the dataset."""
    _add_obs_cols(sample_h5ad_for_write, "junk_col")
    written = {}

    def die_partway(src, dst, *args, **kwargs):
        Path(dst).write_bytes(b"partial")
        written["dst"] = dst
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("hca_anndata_tools.write.shutil.copy2", die_partway)

    result = drop_obs_columns(str(sample_h5ad_for_write), ["junk_col"])

    assert "error" in result
    assert not Path(written["dst"]).exists(), "partial snapshot was left behind"
    assert sample_h5ad_for_write.is_file()  # and the source is untouched


def test_drop_alias_of_source_is_refused_without_unlinking(sample_h5ad_for_write, monkeypatch):
    """An alias of the source — a hard link, or a './'-prefixed path — is not
    caught by the string-equality guard, but copy2 compares inodes and refuses
    before writing. That must return, not fall through to the unlink, or the
    source is deleted (the #598 defect by another route)."""
    _add_obs_cols(sample_h5ad_for_write, "junk_col")
    alias = sample_h5ad_for_write.with_name("alias-edit-2026-08-22-00-00-01.h5ad")
    os.link(sample_h5ad_for_write, alias)
    monkeypatch.setattr("hca_anndata_tools.write.generate_output_path", lambda p: str(alias))

    result = drop_obs_columns(str(sample_h5ad_for_write), ["junk_col"])

    assert "error" in result
    assert "already exists" in result["error"]
    assert alias.is_file(), "the source was unlinked through its alias"
    assert sample_h5ad_for_write.is_file()
    assert "junk_col" in ad.read_h5ad(sample_h5ad_for_write).obs.columns
