"""Tests for notebooks/retired-ensembl-identifiers.ipynb.

A notebook is a poor place for logic, so these cover the two things worth
covering: that the committed file is in a shareable state, and that the pure
helper functions behave. Each logic test pulls the function's defining cell out
of the notebook and executes it in a fresh namespace, so the notebook stays
self-contained rather than importing from here.

The cells that talk to Ensembl or open an .h5ad are not exercised; that is what
`nbmake` would be for, and it needs network and a real atlas.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd
import pytest

NOTEBOOK = Path(__file__).resolve().parents[1] / "retired-ensembl-identifiers.ipynb"


@pytest.fixture(scope="module")
def nb() -> dict:
    return json.loads(NOTEBOOK.read_text())


@pytest.fixture(scope="module")
def code_cells(nb) -> list[str]:
    return ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]


def load_function(code_cells, name):
    """Execute just enough of the cell defining `name` to get a callable back.

    Takes the function definition wherever it sits (including inside an `if`
    block) plus any simple constant assignments and imports from the same cell,
    and skips everything else — so no cell needs to be runnable to be tested.
    """
    for src in code_cells:
        tree = ast.parse(src)
        target = next((n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and n.name == name), None)
        if target is None:
            continue
        preamble = [
            n for n in tree.body
            if isinstance(n, ast.Import | ast.ImportFrom)
            or (isinstance(n, ast.Assign)
                and isinstance(n.value, ast.Constant | ast.Set | ast.List | ast.Dict | ast.Tuple))
        ]
        namespace: dict = {"pd": pd}
        module = ast.Module(body=[*preamble, target], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), "<notebook>", "exec"), namespace)
        return namespace[name]
    raise AssertionError(f"no cell defines {name}()")


# --- the committed file is shareable -------------------------------------

def test_notebook_is_valid_json(nb):
    assert nb["nbformat"] == 4
    assert nb["cells"], "notebook has no cells"


def test_every_code_cell_parses(code_cells):
    for src in code_cells:
        ast.parse(src)  # raises SyntaxError naming the offending cell


def test_no_stored_outputs(nb):
    """Outputs bloat the diff and can leak one machine's paths."""
    with_outputs = [i for i, c in enumerate(nb["cells"]) if c.get("outputs")]
    assert not with_outputs, f"cells {with_outputs} have stored outputs"


def test_no_absolute_local_paths(nb):
    """The configuration cell must ship placeholders, not one person's disk."""
    text = json.dumps(nb)
    for leak in ("/Users/", "/home/", "C:\\\\"):
        assert leak not in text, f"notebook contains an absolute path ({leak})"


# --- pure logic ----------------------------------------------------------

def test_strip_version_removes_only_ensembl_suffixes(code_cells):
    strip_version = load_function(code_cells, "strip_version")
    assert strip_version("ENSG00000123456.5") == "ENSG00000123456"
    assert strip_version("ENSG00000123456") == "ENSG00000123456"
    # not an Ensembl id, or not a numeric suffix: leave alone
    assert strip_version("MIR1302-2HG") == "MIR1302-2HG"
    assert strip_version("ENSG00000123456.beta") == "ENSG00000123456.beta"
    assert strip_version("SOME.GENE.1") == "SOME.GENE.1"


def test_declared_releases_parses_and_refuses(code_cells):
    declared_releases = load_function(code_cells, "declared_releases")
    assert declared_releases("v87") == [87]
    assert declared_releases("v87,v98") == [87, 98]
    assert declared_releases("87") == [87]
    # the RefSeq form the HCA schema also permits must not be silently accepted
    assert declared_releases("GCF_000001405.40") == []
    assert declared_releases("unknown") == []


def test_coerce_gives_numeric_columns_numeric_dtypes(code_cells):
    """A cached run must compare coordinates numerically, not lexicographically."""
    coerce = load_function(code_cells, "_coerce")
    df = coerce(pd.DataFrame({"stable_id": ["ENSG1"], "chrom": ["5"],
                              "start": ["10000"], "end": ["9999"], "score": ["0.99"]}))
    assert df["start"].iloc[0] > df["end"].iloc[0], "numeric comparison expected"
    assert df["chrom"].iloc[0] == "5", "chromosome must stay a string"


def test_resolve_follows_a_chain_beyond_the_atlas(code_cells):
    """A -> B -> C where B was never a column here must still reach C."""
    resolve = load_function(code_cells, "resolve")
    resolve.__globals__.update(
        edges={"A": "B", "B": "C"},      # B is an intermediate, not in gencode
        gencode={"C": {"symbol": "GENE_C"}},
    )
    assert resolve("A") == ("C", 2)
    assert resolve("B") == ("C", 1)


def test_resolve_reports_no_successor_when_the_chain_dies(code_cells):
    resolve = load_function(code_cells, "resolve")
    resolve.__globals__.update(edges={"A": "B"}, gencode={})
    final, hops = resolve("A")
    assert final is None


def test_resolve_terminates_on_a_cycle(code_cells):
    """Run in a worker thread: a missing cycle guard would otherwise hang the suite."""
    import threading

    resolve = load_function(code_cells, "resolve")
    resolve.__globals__.update(edges={"A": "B", "B": "A"}, gencode={})

    result: list = []
    worker = threading.Thread(target=lambda: result.append(resolve("A")), daemon=True)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive(), "resolve() did not terminate on a cyclic chain"
    assert result[0][0] is None


# --- the knee estimator --------------------------------------------------


def knee_from_notebook(code_cells, curve):
    """Run the notebook's own knee rule over `curve`.

    The rule is inline in the section 8 cell rather than a function, so we lift
    the statements that compute it and evaluate them against a supplied curve.
    Testing a restatement of the rule would pass even if the notebook reverted
    to the strict minimum, which is the regression this is here to catch.
    """
    for src in code_cells:
        if "knee" not in src or "tail" not in src:
            continue
        lines = [ln.strip() for ln in src.splitlines()]
        wanted = [ln for ln in lines if ln.startswith(("start ", "tail ", "knee "))]
        assert wanted, "section 8 no longer computes a knee"
        namespace = {"curve": curve, "ordered": sorted(curve), "best": [min(curve, key=curve.get)]}
        exec("\n".join(wanted), namespace)
        return namespace["knee"]
    raise AssertionError("no cell computes a knee")


def test_knee_ignores_a_trailing_outlier(code_cells):
    """A strict minimum is set by whichever gene is accounted for last, so a
    handful of strays drag it many releases right. The knee must not follow."""
    curve = {87: 230, 90: 38, 92: 3, 93: 3, 100: 2, 105: 0}
    assert knee_from_notebook(code_cells, curve) == 92
    assert min(curve, key=curve.get) == 105, "the strict minimum is the thing being avoided"


def test_knee_is_the_minimum_when_there_is_no_tail(code_cells):
    curve = {87: 100, 92: 50, 98: 0, 104: 0}
    assert knee_from_notebook(code_cells, curve) == 98
