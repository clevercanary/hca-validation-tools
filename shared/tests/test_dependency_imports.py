"""Guard tests for dependency-resolution regressions.

These import top-level packages that fail at import time when an incompatible
transitive version is resolved. `import linkml` in particular breaks when
linkml-runtime >= 1.10 is installed against the exact-pinned linkml==1.9.2
(Format.JSON was removed upstream). The rest of the suite never triggers a
top-level `import linkml`, so without this test a bad resolution ships silently.
"""


def test_import_linkml():
    import linkml  # noqa: F401


def test_import_linkml_runtime():
    import linkml_runtime  # noqa: F401
