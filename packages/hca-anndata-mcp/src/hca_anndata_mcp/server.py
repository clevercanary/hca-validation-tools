"""FastMCP server definition and tool registration."""

from fastmcp import FastMCP

from hca_anndata_mcp.tools.backfill import backfill_obs_from_source
from hca_anndata_mcp.tools.drop import drop_obs_columns
from hca_anndata_mcp.tools.label import label_h5ad
from hca_anndata_mcp.tools.merge_categories import merge_obs_categories
from hca_anndata_mcp.tools.plot import plot_embedding_mcp
from hca_anndata_mcp.tools.populate import populate_labels
from hca_anndata_mcp.tools.producer_uns import set_producer_uns
from hca_anndata_mcp.tools.rename import rename_cell_ids
from hca_anndata_mcp.tools.rename_column import rename_obs_column
from hca_anndata_mcp.tools.strip import strip_forbidden_obs_columns
from hca_anndata_mcp.tools.strip_cap import strip_cap_annotations
from hca_anndata_mcp.tools.validate import validate_cell_annotation, validate_schema
from hca_anndata_tools import (
    check_raw_counts,
    check_schema_type,
    check_x_normalization,
    compress_h5ad,
    convert_cellxgene_to_hca,
    copy_cap_annotations,
    get_cap_annotations,
    get_descriptive_stats,
    get_storage_info,
    get_summary,
    list_uns_fields,
    locate_files,
    normalize_raw,
    replace_placeholder_values,
    set_uns,
    validate_marker_genes,
    view_data,
    view_edit_log,
)

mcp = FastMCP(
    name="hca-anndata-mcp",
    instructions=(
        "Explore AnnData h5ad files interactively. "
        "Use locate_files to find files, get_summary for an overview, "
        "get_storage_info for HDF5 compression/chunk details, "
        "get_descriptive_stats for distributions, view_data to inspect raw values, "
        "plot_embedding to visualize UMAP/PCA embeddings, "
        "get_cap_annotations to inspect CAP cell annotation metadata, "
        "list_uns_fields to see HCA dataset metadata and what's missing, "
        "set_uns to update HCA dataset metadata fields with schema validation, "
        "set_producer_uns to correct a producer-owned uns field that set_uns cannot "
        "reach — a nested, non-schema namespace such as uns['ihbca_provenance'] — "
        "addressed by path segments (['ihbca_provenance', 'git_dirty']) rather than a "
        "slash-joined string; it overwrites existing scalars only (never creates a key, so "
        "a misspelled segment is an error rather than junk metadata), and refuses a value "
        "whose type differs from the stored dtype — writing False into a string field would "
        "store 'false' and no validator would object, because the namespace has no schema; "
        "it writes the whole batch in one snapshot with one edit-log entry, reads every "
        "field back (value and dtype) before accepting the result, and refuses HCA schema "
        "fields (use set_uns) and our own uns['provenance'] namespace, "
        "convert_cellxgene_to_hca to convert CellxGENE files to HCA format, "
        "strip_forbidden_obs_columns to remove HCA-forbidden obs columns "
        "(self_reported_ethnicity*) from HCA-layout files — use this when "
        "the file is already HCA-layout and the SRE columns survived from "
        "upstream; on CellxGENE-layout files convert_cellxgene_to_hca strips "
        "them automatically as a side-effect, "
        "drop_obs_columns to remove caller-named obs columns — producer "
        "columns the schema doesn't name (ethnicity_verbatim, race, "
        "cell_type_label, ...) and schema-named columns alike; it drops all "
        "or nothing and guarantees a coherent file, not a valid one — run "
        "validate_schema afterwards for the verdict; it refuses what breaks "
        "coherence — the obs index, names containing '/', columns referenced "
        "by uns['batch_condition'], CAP annotation-set columns, any file "
        "using the deprecated top-level CAP layout — and, being all-or-"
        "nothing, a name absent from obs fails the whole request, "
        "merge_obs_categories to fold one category of a categorical obs column into "
        "another — the remedy for a typo-split value (nee2023's tissue_label carries "
        "'Prophylatctic Mastectomy' beside the correctly spelled 'Prophylactic "
        "Mastectomy'); both values must already be categories, every cell in from_value "
        "is recoded to to_value and the empty category dropped, and the recoded cell "
        "count is reported so you can confirm the split was the size you expected; it "
        "refuses the obs index, names containing '/', a non-categorical column (or one "
        "with non-string categories), a CAP annotation-set column, a file using the "
        "deprecated top-level CAP layout, and a derived label whose "
        "'<col>_ontology_term_id' is present (correct the term IDs and regenerate "
        "instead); it trims the merged-away category's entry from uns['<col>_colors'] so "
        "the surviving colours stay aligned, and returns stale_label_column when you "
        "merged a term-ID column — drop that label column and run populate_labels to "
        "rebuild it, "
        "rename_obs_column to rename one obs column whose data is real but whose name "
        "misdescribes it (nee2023's cell_type_label holds the authors' own cell-type "
        "calls, not derived labels) — the counterpart to drop_obs_columns, which is for "
        "columns whose data is redundant; it preserves position, dtype, categories and "
        "compression, moves the column's color palette with it; promoting a producer column "
        "into its canonical schema name is allowed; it refuses a destination that already holds "
        "values (drop it first) but overwrites one that is entirely empty; it rewrites an "
        "uns['batch_condition'] entry naming the column, and refuses CAP annotation-set "
        "columns (the '--' names declared in uns['cap_metadata']) — strip the set and "
        "re-copy it from CAP rather than renaming its columns, "
        "rename_cell_ids to rename the cell IDs (obs index) of rows selected by an obs "
        "column value, substituting one ID prefix for another — the remedy for a sample "
        "whose IDs lost a distinguishing segment in a pipeline; HCA-layout files only "
        "(refuses CellxGENE-layout files such as CAP exports — renaming an export forks a "
        "record its source system would overwrite), errors on zero matches, on selected "
        "IDs not carrying the expected prefix, and on any rename that would produce "
        "duplicate IDs, and note it renames only this file: a renamed file no longer "
        "joins against unrenamed copies elsewhere (e.g. copy_cap_annotations sources), "
        "backfill_obs_from_source to copy obs values from a source h5ad into a target joined "
        "on cell ID, filling only cells whose target value is missing (NaN, empty, or a "
        "placeholder like 'unknown') — the remedy for metadata lost in integration; it never "
        "overwrites a set value (disagreements are counted and reported as conflicts, not "
        "written), silently skips source cells absent from the target (integration filters "
        "cells), reports per-column filled counts and how full each column is afterward, and "
        "writes nothing when there is nothing to fill; run it once per source dataset, and "
        "run any rename_cell_ids repair first — it joins by cell identity and trusts the join, "
        "validate_marker_genes to check CAP marker genes against var, "
        "copy_cap_annotations to copy CAP annotations from a source into an HCA target file, "
        "strip_cap_annotations to remove ALL CAP annotation material from an HCA-layout file — "
        "the deprecated top-level uns keys, a nested uns['cap_metadata'] block, older-era CAP "
        "provenance (uns['provenance']['cap'], top-level cap_* keys), every '--' obs column "
        "('--' is CAP's serializer's separator), and removed columns' _colors palettes; the "
        "remediation for files the toolkit refuses as deprecated-top-level-CAP-layout, and the "
        "precursor to a fresh copy_cap_annotations run from a current CAP export. It only undoes "
        "our own imports: CAP uns metadata is stripped only when the edit log carries "
        "import_cap_annotations, so raw CAP exports are refused (as are CellxGENE-layout files), "
        "and it errors without writing when the file has no CAP material, "
        "replace_placeholder_values to replace banned placeholder values with NaN in obs columns, "
        "compress_h5ad to rewrite a file with HDF5 gzip compression applied, "
        "normalize_raw to normalize raw counts in X (normalize_total + log1p) — moving them to raw.X "
        "first when raw.X is absent, or leaving raw.X as it is when it already holds the same counts, "
        "check_x_normalization to classify X as raw-counts / normalized / indeterminate, "
        "check_raw_counts to walk the raw count matrix (raw.X, else X) once, read-only and in "
        "bounded chunks, and report values a count cannot hold — negative, NaN/Inf, fractional — "
        "plus cells with no counts and (raw.X only) genes detected nowhere; an empty findings "
        "list means clean, "
        "check_schema_type to identify CellxGENE vs HCA layout and report the schema version, "
        "validate_schema to run the HCA schema validator and report is_valid / errors / warnings, "
        "validate_cell_annotation to run the HCA Cell Annotation validator (structural CAP checks: "
        "annotation-set presence, well-formed semver in uns['cap_metadata']['cellannotation_schema_version'], "
        "per-set metadata is a dict, required --<suffix> obs columns), complementary to validate_schema, "
        "populate_labels to fill var['feature_name'] (+ feature_reference/biotype/length/type) and "
        "obs ontology labels (tissue, cell_type, ...) from *_ontology_term_id columns — the labeler "
        "for HCA-layout files, and the one to run before copy_cap_annotations so marker-gene "
        "validation has canonical gene symbols to match against. Per-column fill/verify: fills empty "
        "columns, skips columns already matching canonical, and writes nothing at all if any "
        "populated value mismatches or a missing column's source resolves no canonical value "
        "for any row (empty *_ontology_term_id, unrecognized term IDs, or a non-Ensembl var.index), "
        "reporting row-level evidence. Never writes observation_joinid, "
        "and refuses on CellxGENE-imported files where add-labels already ran upstream, "
        "label_h5ad fills the same labels but also writes observation_joinid, which makes "
        "populate_labels refuse the file from then on — prefer populate_labels for HCA curation, "
        "and view_edit_log to inspect the edit history recorded in a file."
    ),
)

mcp.tool()(get_summary)
mcp.tool()(get_storage_info)
mcp.tool()(get_descriptive_stats)
mcp.tool()(view_data)
mcp.tool()(locate_files)
mcp.tool()(plot_embedding_mcp)
mcp.tool()(get_cap_annotations)
mcp.tool()(list_uns_fields)
mcp.tool()(set_uns)
mcp.tool()(set_producer_uns)
mcp.tool()(convert_cellxgene_to_hca)
mcp.tool()(strip_forbidden_obs_columns)
mcp.tool()(drop_obs_columns)
mcp.tool()(merge_obs_categories)
mcp.tool()(rename_obs_column)
mcp.tool()(rename_cell_ids)
mcp.tool()(backfill_obs_from_source)
mcp.tool()(validate_marker_genes)
mcp.tool()(copy_cap_annotations)
mcp.tool()(strip_cap_annotations)
mcp.tool()(replace_placeholder_values)
mcp.tool()(compress_h5ad)
mcp.tool()(normalize_raw)
mcp.tool()(view_edit_log)
mcp.tool()(check_x_normalization)
mcp.tool()(check_raw_counts)
mcp.tool()(check_schema_type)
mcp.tool()(validate_schema)
mcp.tool()(validate_cell_annotation)
mcp.tool()(label_h5ad)
mcp.tool()(populate_labels)
