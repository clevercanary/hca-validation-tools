# hca-anndata-tools

Library for inspection, summarization, and statistics of AnnData h5ad files.

## Installation

```bash
pip install hca-anndata-tools
```

## Usage

```python
from hca_anndata_tools import get_summary, get_descriptive_stats, locate_files

# Find h5ad files
files = locate_files("/path/to/data")

# Get structural overview
summary = get_summary("/path/to/my_atlas.h5ad")

# Get column statistics
stats = get_descriptive_stats("/path/to/my_atlas.h5ad", columns=["cell_type"], value_counts=True)
```

## API

- **locate_files** - Find all .h5ad files in a directory
- **get_summary** - Structural overview: cell/gene counts, columns, embeddings, layers
- **get_storage_info** - HDF5 compression, chunking, sparse format details
- **get_descriptive_stats** - Descriptive statistics and value counts for obs/var columns
- **view_data** - View slices of any attribute (obs, var, X, obsm, uns, etc.)
- **plot_embedding** - UMAP/PCA scatter plots as base64 PNG
- **get_cap_annotations** - Inspect CAP cell annotation metadata
