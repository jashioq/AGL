"""Empty on purpose. This file exists so that `tests/` is on `sys.path`.

pytest's prepend import mode inserts, for every file it imports, that file's *basedir* - the
first ancestor directory that is not itself a package - at the front of `sys.path`. `tests/`
holds no `__init__.py`, so this conftest's basedir is `tests/`, and conftest files are imported
before collection starts. That is the whole of what makes `from contracts.store import
StoreContract` resolve from any test module under `tests/`, whichever directory pytest was
invoked from and whether it was invoked on the whole suite or on one file.

Nothing else belongs here, and the emptiness is the design rather than an absence. A fixture a
contract suite needs is that suite's own, declared on the class an implementer subclasses, so
that pointing a suite at an implementation is one visible override and never a hunt through
conftest files for what else the suite quietly reads.
"""
