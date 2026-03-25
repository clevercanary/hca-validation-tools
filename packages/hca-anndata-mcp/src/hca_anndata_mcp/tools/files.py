"""Locate AnnData files on disk."""

from pathlib import Path


def locate_files(
    directory: str,
    recursive: bool = True,
) -> dict:
    """Find all AnnData files (.h5ad and .zarr) in a directory.

    Args:
        directory: Absolute path to the directory to search.
        recursive: Whether to search subdirectories. Defaults to True.

    Returns:
        A dict with 'h5ad' and 'zarr' lists of absolute file paths.
    """
    path = Path(directory)
    if not path.is_dir():
        return {"error": f"Not a directory: {directory}"}

    prefix = "**/" if recursive else ""
    h5ad = sorted(str(p) for p in path.glob(f"{prefix}*.h5ad"))
    zarr = sorted(str(p) for p in path.glob(f"{prefix}*.zarr"))
    return {"h5ad": h5ad, "zarr": zarr, "total": len(h5ad) + len(zarr)}
