#!/usr/bin/env python3
"""Check how a built distribution declares its dependencies on sibling packages.

Run against the artifacts in a package's dist/ before they are published.

A sibling is a package published from this repo. During development each one is
resolved from the local checkout via [tool.uv.sources], and uv strips that
redirect at build time, so what reaches PyPI is whatever [project] dependencies
says. Two ways that goes wrong, both of which are invisible locally because the
path override means uv sync, pytest, and pyright all pass regardless:

  1. No version bound. The dependency publishes as a bare `Requires-Dist: foo`,
     which accepts every version of foo ever released, including future
     breaking ones.

  2. A bound that excludes the sibling's current version. uv discards the
     specifier entirely when a path source overrides it, so a sibling can be
     minor-bumped past its own declared bound and nothing complains. The wheel
     then tells consumers to install a version of the sibling that this package
     was never built against — the exact ship-vs-test divergence the bounds
     exist to prevent.

Both only surface in a consumer's environment after the wheel is on PyPI, so the
built metadata has to be read directly. Wheels and sdists are both published, so
both are checked.

Needs `packaging`, and `tomllib` (so Python >= 3.11, above this repo's 3.10
floor). Run it the way the publish workflow does:

    uv run --no-project --python 3.12 --with packaging python \
        scripts/check_sibling_deps.py <dist>...
"""

import sys
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

PACKAGES_DIR = Path(__file__).resolve().parent.parent / "packages"


def siblings() -> dict[str, Version]:
    """Every package published from this repo, mapped to its current version.

    Derived from the tree rather than hardcoded: a new package under packages/
    is protected automatically, instead of silently going unchecked until
    someone remembers to update a list here.
    """
    found = {}
    for pyproject in sorted(PACKAGES_DIR.glob("*/pyproject.toml")):
        project = tomllib.loads(pyproject.read_text())["project"]
        found[canonicalize_name(project["name"])] = Version(project["version"])
    return found


def read_requires_dist(dist: Path) -> list[str]:
    """Requires-Dist entries from a wheel (.whl) or an sdist (.tar.gz)."""
    if dist.suffix == ".whl":
        with zipfile.ZipFile(dist) as zf:
            names = [n for n in zf.namelist() if n.endswith(".dist-info/METADATA")]
            if not names:
                raise ValueError(f"{dist}: no .dist-info/METADATA in wheel")
            with zf.open(names[0]) as fh:
                metadata = BytesParser().parse(fh)
    else:
        with tarfile.open(dist) as tf:
            names = [n for n in tf.getnames() if n.endswith("PKG-INFO")]
            if not names:
                raise ValueError(f"{dist}: no PKG-INFO in sdist")
            # The distribution's own PKG-INFO is the shallowest one.
            handle = tf.extractfile(min(names, key=lambda n: n.count("/")))
            if handle is None:
                raise ValueError(f"{dist}: PKG-INFO is not a regular file")
            with handle:
                metadata = BytesParser().parse(handle)

    return metadata.get_all("Requires-Dist") or []


def problems(dist: Path, known: dict[str, Version]) -> list[str]:
    found = []
    for raw in read_requires_dist(dist):
        req = Requirement(raw)
        name = canonicalize_name(req.name)
        if name not in known:
            continue

        current = known[name]
        if req.url is not None:
            found.append(f"{raw!r} is a direct reference, not a version bound")
        elif not req.specifier:
            found.append(f"{raw!r} has no version bound")
        elif not req.specifier.contains(current, prereleases=True):
            found.append(
                f"{raw!r} excludes {name} {current}, the version in this repo — "
                f"the wheel would require a version it was not built against"
            )
    return found


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check_sibling_deps.py <dist> [<dist> ...]", file=sys.stderr)
        return 2

    known = siblings()
    failed = False
    for arg in argv:
        dist = Path(arg)
        found = problems(dist, known)
        if found:
            failed = True
            print(f"FAIL {dist.name}")
            for problem in found:
                print(f"       {problem}")
        else:
            print(f"ok   {dist.name}")

    if failed:
        print(
            "\nA sibling must be declared in [project] dependencies with a bound that"
            "\nadmits its current version, e.g. hca-anndata-tools>=0.6,<0.7. See #472.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
