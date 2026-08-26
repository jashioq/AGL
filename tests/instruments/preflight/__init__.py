"""Three workflow *modules* for `tests/sdk/test_preflight.py`, because a namespace is the claim.

Since UF1.3 a workflow's roles are the `@role(model=…)` factories bound in the module its `def` was
executed in - §3.11's "One declaration, not two" - so a claim about *which* roles preflight demands
a provider for is a claim about a module namespace. Three of that suite's claims therefore cannot
be made inside it: `tests/sdk/test_preflight.py` is one namespace and holds six factories over two
models, which is the right shape for the claims about dedup and ordering and the wrong shape for
every claim about what a namespace does *not* contain.

So they live here, as three modules that are each nothing but the thing they are about:

  * `unstaffed` - no role factory at all, so preflight asks no backend anything. `workflows/noop/`'s
    shape, and what keeps a workflow that runs no agent runnable on a machine with no harness.
  * `unused` - one factory imported and never stepped with, which is the stage's "known cost,
    accepted": the run is refused for a provider it was never going to use.
  * `late` - a factory written *below* the workflow function, which is not bound when the decorator
    runs and is bound by the time preflight reads the namespace.

They are modules on disk rather than `types.ModuleType` values built in a fixture, because what is
being measured is what an author's own file does to a namespace. A synthetic module would need its
workflow function's `__module__` set by hand, which is the one fact the whole mechanism turns on.

Nothing here is collected by pytest - the names carry no `test_` prefix - and each is reached the
way an installed workflow is, through an `EntryPoint` naming `<module>:<attribute>`.
"""

from dataclasses import dataclass
from typing import Final

entered: Final[list[str]] = []
"""Which workflow functions were awaited, shared with `tests/sdk/test_preflight.py`'s own.

One list rather than one per module, because every test that asserts on it is asking the same
question - did this run reach its workflow, or was it refused first - and a refusal at preflight
must leave it empty whichever module the workflow was written in."""


@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing, and still has a params class to derive no flags from.

    Here rather than once per module so that the three below differ only in what this package
    exists to vary, which is which role factories are bound where."""
