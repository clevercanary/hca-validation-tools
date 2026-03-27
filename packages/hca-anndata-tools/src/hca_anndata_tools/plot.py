"""Embedding and expression plots for AnnData files."""

import base64
import io

from ._io import open_h5ad


def plot_embedding(
    path: str,
    color: str = "cell_type_atlas",
    embedding: str = "X_umap",
    title: str | None = None,
    palette: str | None = None,
    legend_loc: str = "right margin",
    frameon: bool = False,
    dpi: int = 150,
    width: float = 8,
    height: float = 6,
) -> dict:
    """Plot a 2D embedding (UMAP, PCA, etc.) colored by an obs column or gene.

    Returns a dict with base64-encoded PNG data on success, or an error dict.

    Args:
        path: Absolute path to an .h5ad file.
        color: Column in obs or gene name to color by. Defaults to 'cell_type_atlas'.
        embedding: Key in obsm to use for coordinates (e.g. 'X_umap', 'X_pca'). Defaults to 'X_umap'.
        title: Plot title. Defaults to '{color} — {embedding}'.
        palette: Matplotlib colormap or scanpy palette name.
        legend_loc: Legend location. One of 'right margin', 'on data', 'none'.
        frameon: Whether to show axis frame.
        dpi: Image resolution.
        width: Figure width in inches.
        height: Figure height in inches.

    Returns:
        On success: {"data": "<base64 PNG>", "mime_type": "image/png"}
        On error: {"error": "<message>"}
    """
    fig = None
    plt = None
    try:
        # Lazy imports — scanpy/matplotlib are heavy and only needed for plotting
        import matplotlib
        if matplotlib.get_backend().lower() != "agg":
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import scanpy as sc

        # Full read required — scanpy plotting needs in-memory data
        with open_h5ad(path, backed=None) as adata:
            basis = embedding.replace("X_", "")
            plot_title = title or f"{color} — {embedding}"

            kwargs = dict(
                color=color,
                basis=basis,
                title=plot_title,
                legend_loc=legend_loc,
                frameon=frameon,
                show=False,
            )
            if palette:
                kwargs["palette"] = palette

            fig, ax = plt.subplots(figsize=(width, height))
            sc.pl.embedding(adata, ax=ax, **kwargs)

        with io.BytesIO() as buf:
            fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
            buf.seek(0)
            data = base64.standard_b64encode(buf.read()).decode("utf-8")

        return {"data": data, "mime_type": "image/png"}

    except Exception as e:
        return {"error": str(e)}
    finally:
        if fig is not None and plt is not None:
            plt.close(fig)
