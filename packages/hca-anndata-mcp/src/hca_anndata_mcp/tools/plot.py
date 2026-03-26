"""Embedding and expression plots for AnnData files."""

import base64
import gc
import io

import anndata as ad
from mcp.types import ImageContent


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
) -> ImageContent | dict:
    """Plot a 2D embedding (UMAP, PCA, etc.) colored by an obs column or gene.

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
    """
    adata = None
    plt = None
    try:
        # Lazy imports — scanpy/matplotlib are heavy and only needed for plotting
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import scanpy as sc
        # Full read required — scanpy plotting needs in-memory data
        adata = ad.read_h5ad(path)

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

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        data = base64.standard_b64encode(buf.read()).decode("utf-8")

        return ImageContent(type="image", data=data, mimeType="image/png")

    except Exception as e:
        return {"error": str(e)}
    finally:
        if adata is not None:
            del adata
            gc.collect()
        if plt is not None:
            plt.close("all")
