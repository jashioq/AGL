"""Free instruments: things a test drives a real vendor process against, with no model behind them.

`tests/contracts/` holds suites written against a port. This package holds the opposite kind of
thing - a stand-in for something *outside* AGL, built so that a test can start a real vendor binary,
watch what it composes, and read back what it would have sent, without a paid endpoint existing
anywhere in the picture.

The build's rule is that **no test spends tokens, ever** (`docs/agl-build-stages.md`), and the
failure that rule was written against is a suite that is green because the environment is broken. An
instrument here is how a claim moves from "deferred to the manual QA pass" to "asserted on every
run": the CLI genuinely starts, genuinely composes its session, genuinely sends its request - and
the far side is a socket on `127.0.0.1` that this package owns.

Importable as `instruments.<module>` from any test, by the same mechanism that makes `contracts.*`
resolve: `tests/` carries no `__init__.py`, so pytest's prepend import mode puts `tests/` itself on
`sys.path` (see `tests/conftest.py`). This directory carries one, so it is a package and its modules
are addressed by a name rather than by a path.

Two rules for anything added here. **It opens no outbound socket** - an instrument that could reach
a vendor's endpoint is an instrument that could be pointed at one by accident, and the whole value
of the package is that the guarantee is structural rather than a promise in a docstring. And **it
redacts credentials before recording anything**: an instrument's job is to be handed whatever a
vendor process sends, which on a developer machine includes live tokens.
"""
