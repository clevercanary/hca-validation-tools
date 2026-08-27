# Contract: hca-anndata-tools / MCP / skills

**Status:** Draft — principles under discussion
**Date:** 2026-08-26
**Prompted by:** PR #642 review (issues #637, #638, #641). The review found the code sound where a rule existed and wrong exactly where no rule had been written down. This document is that rule set.

## Problem

The package grew one hand-rolled h5py read per tool, so one upstream encoding
(`nullable-string-array`) produced six different opaque failures. The fix
(#637/#642) centralized reads — and the review of that fix showed the same
pattern one layer up: callers of the new readers each improvised their own
policy for what the readers now return, and the write boundary was guarded
tool-by-tool. Every finding traced to a missing contract, not to a wrong line.

This document states the contract once. Code review checks changes against it;
the skills reference it instead of enumerating per-tool behavior that drifts.

## The one-line contract

**Read wide, write narrow.** We read everything anndata reads; we write only
the **CellxGENE-compatible profile**. For strings that means anndata's plain
`string-array` encoding, never `nullable-string-array` (pandas `StringDtype`'s
values + mask serialization): a tool that touches one converts it to plain
strings or refuses by name; it never emits it. The *numeric* nullable
encodings (`nullable-integer` / `nullable-boolean`, from pandas `Int64` /
`boolean`) are **inside** the profile: anndata — cellxgene-schema's own pin —
reads and writes them ungated, so the CxG toolchain itself produces and
accepts them, and refusing them would block files nothing downstream
rejects.

## Worked example: the liver obs index

Every principle below has a concrete face in this file. In the liver
integrated objects, the obs index is not a dataset of strings — it is a group:

```
/obs/_index                (Group, encoding-type = "nullable-string-array")
    values   (Dataset: 8811 strings, gzip, chunked)
    mask     (Dataset: 8811 bools — True means "this cell has no ID")
```

This is how anndata serializes a pandas `StringDtype` column. Strings have no
in-band "missing" the way floats have NaN — any sentinel (`""`, `"NA"`) is
also a legitimate value — so missingness moves out of band: `mask[i] == True`
means `values[i]` is meaningless fill and the entry is `pd.NA`. The encoding
is *more* faithful than a plain string array, not less; the files are not
malformed.

We still do not write it, for two independent reasons:

1. **Compatibility (the load-bearing one).** Our output must ingest at
   CellxGENE and CAP, so we deliberately emit the non-nullable profile —
   plain string arrays. The environment enforces this by default: anndata
   0.11.4's `allow_write_nullable_strings` ships False and raises on
   `StringArray`. Writing the nullable encoding would produce files our own
   downstream refuses, even where technically easy.
2. **Mechanics.** The in-place surgical writer (`replace_string_dataset` →
   `storage_like`) mirrors the chunking and compression of an existing
   Dataset; a Group has neither. `is_writable_element` tests exactly that.

And the conversion to the profile splits cleanly on the mask:

- **mask all zero** (every liver file we hold): flattening to a plain string
  array is provably lossless — this is the #641 write path.
- **any mask bit set**: there is no faithful conversion — a masked cell *has
  no ID*, every fill fabricates one, `str(pd.NA)` collapses all masked rows
  to the same `"<NA>"`, and pandas joins NA to NA, so the fabrication then
  silently *matches things*. This is a data problem to refuse by name, not
  an encoding problem to paper over. One shape sits outside even the
  read-wide guarantee: a *categorical* whose **categories** are masked is a
  file anndata itself cannot read ("Categorical categories cannot be
  null"), so principle 2 does not apply to it — tools that hit it owe a
  named refusal, nothing more.

## The anndata pin, precisely

Where the version constraint actually lives matters for maintenance:

- `hca-anndata-tools` declares `anndata>=0.11,<0.12` — capped below 0.12 so
  CI, which resolves fresh (package locks are gitignored), tests the writer
  this profile is defined against; the cap moves when cellxgene-schema's
  pin moves. (0.12 already serializes some encodings differently — its
  first CI run failed the encoding-matrix tests on exactly that.)
- `hca-schema-validator` declares `anndata==0.11.4`, and its pyproject says
  why: these are **cellxgene-schema 7.0.1's pins, not ours** — the vendored
  validator must reproduce that environment to behave identically, so they
  must not be relaxed to suit another package.
- `hca-anndata-mcp` depends on both siblings, so the environment every MCP
  tool actually runs in resolves anndata to **0.11.4** via the validator.
  `hca-anndata-tools`' own lock resolves 0.11.4 today as well.

Consequences: (a) do not upgrade anndata to chase writer features — the pin
follows cellxgene-schema, and moves only when the vendored validator moves;
(b) anndata 0.11.4 is the writer the profile is defined against — its
`allow_write_nullable_strings=False` default and its `StringArray` refusal
are the versioned facts behind principle 5; (c) when cellxgene-schema does
bump anndata someday, this document's write-profile claims are the checklist
of behaviors to re-verify.

## The tool taxonomy

Every tool belongs to exactly one class, and its class — not its name —
determines what files it must accept.

| Class | What it does | Examples | Must accept |
|---|---|---|---|
| **Read-only** | Reads, never writes | `get_summary`, `view_data`, `get_storage_info`, `validate_*` | Anything anndata reads. No exceptions. |
| **Copy-and-transplant** | Reads source, writes a *fresh* file through anndata, moves elements between files | `convert_cellxgene_to_hca` | Anything anndata reads on the source side; the file it writes contains only profile encodings |
| **In-place surgical** | Snapshots, then rewrites *specific elements* preserving the rest byte-for-byte | `rename_cell_ids`, `merge_obs_categories`, `backfill_obs_from_source` (target side), `replace_placeholder_values` | Reads everything; refuses **before the snapshot** when a touched element fails `is_writable_element` |
| **Full rewrite** | Streams the whole file through anndata's writer | `compress_h5ad`, `normalize_raw` | Reads everything; the file it writes contains only profile encodings (nullable input: #641 normalize-on-write) |

A tool's *read* side is never allowed to be stricter than its class requires.
Concretely: a surgical tool's read-only **source** (backfill's source file, a
selector column) must accept everything anndata reads, even when its write
target is constrained.

## Principles

### Reading

1. **Read through anndata's registry.** Every read of a stamped element goes
   through `anndata.io.read_elem` (via `_io.read_element` / `read_index`).
   A raw h5py read is permitted only where the job is the storage layer
   itself — inspecting or preserving chunking, compression, dtype, attrs —
   and the reason must be stated at the site. "It seemed simpler" is not a
   reason; that is how six divergent failures happened.

2. **We read everything anndata reads.** If `ad.read_h5ad` accepts a file,
   our readers accept it. "Cannot read" is never a valid failure for such a
   file — the only valid refusals are semantic (principle 4) or write-side
   (principles 5–6).

3. **`pd.NA` is a legal reader output, and every caller names its policy.**
   Readers pass masked values through as `pd.NA`; they do not stringify,
   fill, or drop them. Each caller must do exactly one of:
   - **refuse by name** — identifiers and join keys (`read_index` refuses a
     masked index: `str(pd.NA)` is `"<NA>"` and NA joins NA, silently);
   - **skip** — aggregations where absence is ordinary (a masked
     placeholder value is simply not a placeholder match);
   - **propagate** — when the consumer is NA-aware (pandas factorize).

   Translation is never on the menu: where the HCA schema defines a spelling
   for "unknown" (an `unknown` ontology term, a categorical NaN), writing that
   spelling is a curator decision made with schema knowledge — never a
   read-time default a tool applies silently.

   `str(value)`, `value.lower()`, `sorted(set_containing_values)` on reader
   output without an NA check are each a bug by definition — the three shapes
   the #642 review caught.

4. **Semantic refusals stay with the caller that owns the remedy.** Duplicate
   IDs, masked indexes, missing columns — these are data problems with
   caller-specific remedies, and two refusals with different remedies must
   not be flattened into one (rename distinguishes "duplicates already
   exist: repair the file" from "the rename would create them: change the
   arguments"). Readers detect only what makes the *read itself* unsafe.

### Writing

5. **We write one profile: CellxGENE-compatible, with strings plain.**
   Output compatibility is the deliberate design center, not a limitation:
   whatever we emit must ingest at CellxGENE and CAP. Nullable *string*
   encodings are legal input and never output — a tool that rewrites one
   either converts it to plain strings losslessly (mask all zero — #641's
   normalize-on-write) or refuses by name (any mask set: the data has no
   faithful plain representation). No tool silently emits a nullable string,
   and no tool "supports" writing them — that would be a bug against this
   principle, not a feature. The boundary is drawn where the evidence is:
   anndata 0.11.4 gates exactly nullable strings
   (`allow_write_nullable_strings`) and nothing else, so nullable
   integer/boolean columns pass through every tool untouched and unflagged.

6. **One predicate judges in-place writability, and nothing else does.**
   `is_writable_element` — container, not encoding name — is the only code
   allowed to decide whether an element can be rewritten in place today. No
   tool may carry its own encoding check or hardcoded encoding refusal.
   (Backfill's hand-rolled "nullable-dtype layout" check was the violation:
   it refused readable source files and leaked h5py internals on the liver
   shape.)

7. **Refuse before expensive work, with the remedy named.** A tool that will
   fail must fail before its multi-gigabyte snapshot or stream, and the
   message names the element, the encoding, and the tracking issue (#641) —
   not after, and never with a library-internal message.

8. **Enforcement lives at the chokepoint; per-tool preflights are a courtesy.**
   The write boundary is enforced once, at the funnel every full rewrite
   passes through (`write_h5ad`), so a new tool is covered by construction.
   Per-tool preflights (rename, merge) exist to fail *earlier*, before the
   snapshot — they are an optimization on top of the chokepoint, never a
   substitute for it. A guard added tool-by-tool is the smell that the
   chokepoint is missing.

9. **A failed write leaves no plausible artifact.** If a write fails partway,
   the partial output is removed (or written to a name the lineage resolver
   ignores). A truncated file matching the `-edit-<timestamp>` snapshot
   pattern is indistinguishable from a good snapshot, which is worse than no
   file.

### Agreement

10. **Inspection and enforcement answer from the same predicate.** A file
    `get_storage_info` calls clean cannot be refused by a tool for encoding
    reasons, and everything it flags is flagged for the reason a tool would
    actually refuse. When inspection cannot see everything enforcement
    checks, the inspection report says so explicitly (today the scanned
    dataframes — obs, var, raw.var, obsm frames — cover indexes, plain
    nullable columns, and categorical categories; varm and uns are checked
    only by the write funnel).

### Errors

11. **Every error a user sees is one we wrote.** No h5py or anndata internal
    (`'Group' object has no attribute 'dtype'`) may reach a user, including
    laundered through a broad `except` into an error dict. If a broad except
    is the last line of defense, the defect is upstream of it.

12. **No guards against things that cannot happen.** No runtime isinstance
    checks on internal paths whose callers are all statically known and
    guarded; no defensive handling for states an upstream refusal already
    excludes. Every guard must name a reachable input. (Standing answer to
    the recurring Copilot suggestion on `_io.py`'s Group-typed parameters:
    the module docstring declares it the narrowing boundary — that is the
    contract, not a gap.)

### Change discipline

13. **Library-first, minimal diff.** Prefer deleting our code in favor of
    anndata/pandas/numpy over adding to it. Keep hand-rolled code only where
    it does something the library will not (layout-preserving writes), and
    record the reason next to it.

14. **A reader or writer change is never local.** Widening what a reader
    accepts widens the value domain of every caller; the caller audit is part
    of the same change, not a follow-up. (#642's read fix was correct and
    still produced five caller bugs — the audit was the missing half.)

### MCP layer

15. **Tools return structured refusals, mutate all-or-nothing, and log.**
    Every MCP tool returns an error dict with a message under principle 11,
    never a traceback. An edit either fully applies or leaves the file
    untouched. Every mutation lands in the edit log. Tools guarantee a
    *coherent* file, not a valid one — `validate_schema` owns the verdict.

### Skills layer

16. **Skills state the boundary by class, not by tool list.** The gate in
    curate/evaluate speaks in the taxonomy's terms ("in-place surgical tools
    refuse up front; full rewrites are blocked at the write — #641") rather
    than naming tools one by one, so a new tool does not silently fall out of
    the prose. Any specific behavioral claim a skill does make about a tool
    must be pinned by a test.

### Testing

17. **Fixtures are independent of the code under test** (a fixture built
    through the reader it exercises hides the reader's bugs), **boundaries
    are pinned at both ends** (one test that X is accepted, one that Y is
    refused), and **the suite passes with zero warnings**.

## How writing works

Two write paths, one safety model. The model: **a destination name is
written only after an O_EXCL claim creates it** (`_try_claim` /
`_claim_snapshot_path` in `write.py`) — a same-second timestamp collision
waits out the boundary and regenerates; a claim that still fails refuses
(`SameSecondSnapshotError`), and an explicitly supplied output name that is
already taken is refused outright. Because the claim *created* the file, whatever
sits at that name afterwards is ours, so **failure cleanup unlinks it
unconditionally and can never delete pre-existing data** — and no partial
file is ever left wearing the `-edit-<timestamp>` name `resolve_latest`
selects by. Success then retires the previous snapshot
(`cleanup_previous_version`), keeping original + latest on disk.

| Path | Used by | Mechanism |
|---|---|---|
| **Copy-and-patch** | in-place surgical tools (rename, merge, backfill, replace_placeholder, copy_cap) | `snapshot_copy` / `snapshot_copy_hashed`: claim → streamed copy (digest inline) → h5py-patch the copy → unlink the claim on any failure |
| **Full rewrite** | anndata-based tools (compress, normalize, convert, set_uns, …) | `write_h5ad`: profile refusal (`nullable_string_locations`) *before* mutating `adata` → edit log stamped → claim → `adata.write_h5ad` streams → unlink the claim on any failure |

Any destination h5ad — a snapshot or a converted output — is named and
written through one of these two functions (scratch files in temp dirs are
exempt) —
hand-rolling output-path handling around either is how `write_h5ad` itself
accumulated three data-loss hazards before adopting the claim (the #642
review rounds). The edit log is written into the output as part of the same
operation, so a snapshot and its provenance can never disagree.

## The two spellings of "missing"

The schema layer defines how a missing value is spelled, and the answer is
opposite in the two column families — which is the concrete reason principle
3 forbids tools from translating NA silently:

| Column family | Missing is spelled | NaN is | Defined by |
|---|---|---|---|
| Controlled ontology columns (`cell_type_ontology_term_id`, `sex_...`, `development_stage_...`, …) | the in-band token `"unknown"` (`"na"` in named special cases) | an **error** — "must not contain NaN values" (`_vendored/.../validate.py:731`) | cellxgene schema; HCA inherits it unchanged |
| Free-text producer columns (`library_id`, `library_preparation_batch`, `library_sequencing_run`) | **NaN / blank** (categorical code -1) | a warning with a count (`strongly_recommended`) | HCA only — the `placeholder_blocklist` in `hca_schema_definition.yaml` |

For the second family the blocklist makes `"unknown"`, `"na"`, `"n/a"`,
`"none"`, … an **error**, and the validator's message commands the blank
spelling outright: "Placeholder values are not allowed. Leave the value
missing (NaN/None) if not known" (`validator.py`). The rationale: in a
controlled vocabulary, `unknown` is an unambiguous schema token; in a
free-text ID column any word is indistinguishable from a real identifier —
`"unknown"` as a library ID silently becomes *a batch* in downstream
grouping. Out-of-band blank is the only spelling that cannot be mistaken for
data.

`DEFAULT_PLACEHOLDERS` in `_io.py` is the same list as the yaml blocklist:
`replace_placeholder_values` is the mechanical remedy for the family-2 error,
which is why the curate skill restricts it to those columns and routes every
other placeholder-looking value through curator-reviewed mappings.

## Decisions (2026-08-26)

1. **The `write_h5ad` chokepoint guard lands in #642**, together with
   principle 9's remove-partial-output-on-failure. In #642 the guard only
   *refuses* (named message, #641 reference); #641 then upgrades the same
   chokepoint from refusal to normalize-on-write. The only argument for
   deferring was diff minimality, and the partial-artifact hazard outweighs
   it.

2. **Backfill's refusal is fixed in #642.** In plain terms: backfill copies
   values from a *source* file into a *target* file. The source is only ever
   read — but one shared code path serves both sides and carries a
   hand-rolled "nullable-dtype layout is not supported" refusal. So today it
   wrongly refuses a source file the readers handle fine, and on the target
   side it refuses for the right reason but with its own message instead of
   the shared predicate's. Fix: the source side just reads; the target side
   refuses through `unwritable_element_reason` like every other surgical
   tool. In scope for #642 because the branch's own SKILL.md already claims
   backfill works on these files.

3. **NA policy: tools never translate; they refuse, skip, or propagate.**
   - *Refuse* = stop the whole operation with a named error, because one
     missing value poisons the result — identifiers and join keys
     (`read_index`).
   - *Skip* = that entry contributes nothing and the operation continues —
     aggregations (`validate_marker_genes`: a masked evidence value simply
     yields no genes; report the skip count).
   - *Propagate* = hand the NA to machinery that natively understands it
     (pandas factorize in backfill).
   Converting an NA into a schema spelling of "unknown" is real work the
   schema sometimes defines — and it is *curator* work, done deliberately
   per column, never a tool's silent default (principle 3).
   `replace_placeholder_values` on masked nullable categories: refuse by
   name (the target is unwritable there anyway).

4. **#641 is normalize-on-write.** Flatten nullable → plain where the mask
   is all zero (covers every liver file we hold); refuse by name where any
   mask bit is set. Not "nullable write support" — principle 5 rules that
   out as a goal.

5. **"Leave blank → becomes NaN" in the curation instructions is correct,
   and profile-compatible — for the columns it governs.** The mechanism:
   `replace_placeholder_values` works on *categorical* columns, and blanking
   sets the category code to **-1** — the categorical encoding's own in-band
   missing marker, which pandas reads back as NaN. A categorical with -1
   codes is still a plain codes+categories pair: no mask, no nullable
   encoding, fully inside the profile. Float columns likewise carry NaN
   in-band. The one shape with **no** in-band missing is a plain
   (non-categorical) *string* dataset — strings have no NaN, which is
   exactly why pandas invented the values+mask nullable encoding. So the
   write-side rule for a genuine NA is by column type:
   | Column type | Missing on disk | In profile? |
   |---|---|---|
   | categorical | code -1 | yes |
   | float | NaN | yes |
   | plain string | *(none exists)* | no — convert the column to categorical, or refuse |
