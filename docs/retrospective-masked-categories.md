# Retrospective: the masked-categories arc (#651 / #652)

**Date:** 2026-08-29
**Outcome:** #652 closed unmerged after ~1,200 lines and 17 commits; #653 records the
gap in the contract instead. Nothing shipped except documentation and a scan script.

This is the conversation that ended it, kept because the diagnosis generalises well
beyond this issue.

---

## Q: Why is this so difficult? Have we reached the end of what vibe coding can do? What is wrong with my setup/process?

Honest diagnosis, in order of how much each factor actually contributed.

### Most of it is one repeating mistake, and it's mine

Every single break was the same shape: I wrote a universal quantifier — *"every write
refuses,"* *"no clean verdict is possible,"* *"covered by construction"* — and
implemented a **roster**, a list of places to look. Then each review found a place not
on the list. Six rounds broke the container roster, one broke the control-flow roster
(which returns carry the notice), one broke the failure roster (what happens when the
walk itself breaks). I wasn't learning the lesson between rounds; I was patching the
specific hole and re-asserting the same universal. That's a writing habit as much as a
coding one: confident prose is cheap, and I kept generating claims the code then had to
live up to.

### The contract amplified it

That document is the best process artifact here — it's why the reviews could find
anything at all, since a reviewer with no context could hold code against a written
standard. But it was written as both spec *and* advertisement. "Every write refuses the
shape" reads well and is unverifiable; "the scan covers obs, var, raw.var, obsm frames,
and uns" is duller and checkable. **A spec should only contain a universal when
something mechanical enumerates the domain behind it.**

### The domain is genuinely hard, but that's maybe 25% of it

HDF5 is an open world — links, cycles, arbitrary containers, groups anndata never reads
— and any "every element" claim is a claim about a *format*, not about your code. A
human expert would also have missed bare categoricals in `obsp`. But a human expert
probably wouldn't have *claimed* to cover them.

### What's actually wrong with the setup: less than you'd think

Three concrete gaps:

1. **No property-based testing.** This domain is the textbook case for it. One
   Hypothesis strategy generating arbitrary h5ad structures with a masked categorical
   planted at a random path, asserting *"no write produces a file anndata can't open,"*
   would have collapsed six of eight review rounds into one afternoon. Every
   example-based test was written by the same mind that wrote the code, so both
   encoded the same blind spot.
2. **The adversarial review is used as a backstop, not a design tool.** It runs *after*
   a claim of done. Run it *before* — "here's the claim I intend to make, refute it" —
   and it becomes a spec review costing one round instead of eight.
3. **The issue was too big.** #651 should have been three issues. Seventeen commits on
   one branch means every review re-reads a growing diff, and fixes land on fixes.

### Have we hit the ceiling of vibe coding?

No — but this session shows exactly where the ceiling is. The code got genuinely better,
and the process found ~14 real defects including two that would have corrupted user
files. What it *can't* do is make the model a reliable judge of its own completeness.

The two highest-yield things in the whole session were the **real-file smoke test** and
the **fresh-context adversarial reviews**. The mocks and the automated PR reviewer found
almost nothing by comparison. That's the signal for where to invest.

And one thing worth calibrating against: the model said *"merge-ready"* five or six
times before it was. Discount that phrase specifically.

---

## Postscript: how it actually resolved

Two questions ended the arc, both from the human side, and both cheaper than any round
of review that preceded them.

**"Does this shape exist?"** — 4 seconds to answer.

| | count |
|---|---|
| real h5ad files scanned (~809 GB) | 223 |
| holding masked categories (the trigger) | **0** |
| holding masked string values at all | **0** |
| holding *unmasked* nullable elements (#641 shape) | 9 — real, already handled |

No supported pandas or anndata path can *originate* the shape either. Eight review
rounds had been spent defending a universal about files that do not exist.
Reproducible via `scripts/scan_masked_elements.py`.

**"What if we just open the file with anndata first?"** — collapsed ~400 lines of
scanning machinery into three.

The property is *"can anndata read this file."* `ad.read_h5ad(path, backed="r")`
answers it directly and refuses all six placements (obs, uns, obsm, varm, layers,
obsp), because it **is** the oracle — no roster to enumerate, no walker to keep in step
with the format. Measured cost: 0.13 s on 0.53 GB, 0.97 s on a 10 GB / 1M-cell atlas,
6.7 s on 21.6 GB / 2.1M cells — in front of a snapshot copy of the same file, which
costs more.

**And the precedent was upstream all along.** `cellxgene-schema` enumerates no
corruption whatsoever: `utils.read_h5ad` catches `(OSError, TypeError)`, logs *"Unable
to open … with AnnData"*, and calls `sys.exit(1)`; the whole of `validate()` sits under
one `except Exception`. No walker, no element names, no defect taxonomy. Their
complexity goes to schema questions, which is where their domain knowledge is.

That last point puts a boundary on principle 11 (*every error a user sees is one we
wrote*): it is right for refusals about **our** semantics, but applied to arbitrary file
corruption it forces the roster problem, because naming an element means enumerating
elements.

---

## What changed as a result

- `docs/anndata-tools-contract.md` gained a **How to write in this document** section:
  an "every X" claim belongs there only when something mechanical enumerates X.
- The false "covered by construction" sentence is replaced with the verified truth,
  the gap recorded as known-and-accepted with its evidence and reopen condition.
- `scripts/scan_masked_elements.py` is committed, so the 0-of-223 number is
  reproducible rather than asserted.
- Claims about file shapes get checked against the corpus *before* they are written
  down.
