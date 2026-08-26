"""Which names a run has taken, and the child `Run` each one carries - what `run.worktree` is.

`worktree(name)` is a namespace and a checkout at once, and the two live under different rules.
§3.9 states both, and the asymmetry between them is the whole of this module:

    AGL_HOME/.../runs/auth/worktrees/T-01/worktrees/sub-b/steps/...      <- nests, arbitrarily
    .trees/auth/_base/   .trees/auth/T-01/   .trees/auth/sub-b/          <- flat, always

**`AGL_HOME` nests**, because it is recording the parent-child structure of the run.
`home_layout.scope_dir` is the one loop that walks that nesting and `RunScope.inside` composes with
itself, so arbitrary depth costs this module one call and no arithmetic. **Nothing here computes a
path**, which is the same rule `ports/home_layout.py` states from its own side: `steps/` and
`worktrees/` are deliberately not addressable, so a caller has nothing to join a namespace onto and
a second copy of the nesting rule cannot drift from the first. It is also what makes
`worktree("review")` and a step named `review` in one `Run` two different subtrees under one scope
rather than one collision (§3.6).

**The trees root is flat**, because a worktree inside another worktree's working tree appears to the
parent as untracked files: the parent's `git status` and its build gate would both see the child's
entire checkout, and an agent asked to commit its work would commit that too. So every checkout in a
run is a sibling of every other, addressed by one namespace whatever depth that namespace holds in
the run's own tree - which is why `WorkspaceProvider.open` takes a single `Namespace` and not a
path.

**Therefore a namespace is unique within the run and not merely among siblings** (§3.9, §3.3). A
flat trees root cannot tell `T-01`'s child `sub-b` from a top-level `sub-b`: two scopes under
`AGL_HOME`, one directory under `.trees/<label>/`, and whichever of the two opened second would be
handed the first one's checkout with the first one's work in it. This module is that uniqueness -
the run's table of taken names, run-wide, compared by `Namespace.collision_key`.

## The table is the run's, and a parent hands *its own* to every child

Same seam and same argument as `Fingerprints`, one field over: a constructor keyword on `Run` with a
default, filled by the root with a fresh one and by `worktree()` with the object it already holds. A
table built privately per `Run` would be a table per *namespace*, and a table per namespace cannot
see a name taken anywhere else in the tree - which is sibling-wide uniqueness with the run-wide
check written out in full above it and unreachable. The failure is not an exception: two namespaces
flatten onto one directory, `WorkspaceProvider.open` finds a checkout already on some *other* line
of work there, and what the second child gets is a `ConflictError` from git about a place it never
asked for - or, if the branch happens to match, the first child's working tree.

## Reopen, refusal, and the malformed name

**The same `Run` asking twice for one name gets the same child object back.** §3.3: "Idempotent: an
existing name reopens rather than recreates, which is what makes replay work" - a replay walks the
same calls in the same order, and the second `worktree("T-01")` in that walk has to land in the
namespace the first one made. The *same object* and not an equal one, because a second `Run` over
one namespace is a second `Steps`, a second lazily opened checkout, a second `Journal` - which is
"two locks over one namespace, which is not a lock at all" (`Journal.__init__`) - and a second
`last_good` chain that starts where the namespace began rather than where it has got to.

**One name means one spelling**, which is where the fold below stops. `worktree("T-01")` and
`worktree("t-01")` on one `Run` are a collision and not a reopen: they are one directory to the
filesystem and two of everything else - two `Namespace` values, two scopes, two `steps/` subtrees,
two branches - so the second is refused rather than quietly handed the first one's child under a
name it will then record its steps beside. `open` carries the argument at the line where the two
comparisons differ.

**A different `Run` asking for a name taken anywhere in the tree is refused**, with both scopes
named. `ports/errors.py` says `ConflictError` is "the world already holds something this operation
would have to take or overwrite", which is exactly a flat trees root already holding that directory;
and it says "nothing has been changed when this is raised", which is true here because the refusal
happens before anything is built and long before anything is provisioned.

**A malformed name is `InputError` and comes out of `Namespace(...)` itself**, on the first line,
before the table is consulted and before a child exists. `ids.py` owns that language -
`[A-Za-z0-9._-]`, non-empty, no leading `.` or `-`, `_base` reserved - and owns it because "these
names are frequently agent output": `decompose` invents the ticket ids that become namespaces.

## `collision_key`, and the half of it that is vestigial

The table is keyed by `Namespace.collision_key`, which casefolds. §3.9: "`T-01` and `t-01` are two
refs to git and one directory on macOS", so comparing the names as typed would admit both and then
hand them one checkout on the machine most of this is developed on, and two on the machine the CI
runs on. Equality is deliberately *not* what is compared: `Namespace("T-01") != Namespace("t-01")`,
and both are perfectly good names - what is refused is the second one *in a run that already holds
the first*.

The NFC half of `collision_key` is vestigial and nothing here rests on it: §3.3's ASCII allowlist
admits no character with two spellings, so no two accepted names differ by normalisation alone.

## Why the child is built by a callback rather than here

`sdk/workflow.py` imports `sdk/_engine/`, and `_engine/` never imports it back, so a module that
constructed a `Run` would be an import cycle before it was anything else. That is the first reason
and the smaller one. The second is the one `steps.py` gives for existing at all: `workflow.py` is
the surface, and a constructor's shape is what every call site is written against, so assembling one
down here would move the surface's own composition into the plumbing under it. `open` therefore
takes a `build` and holds what it produced - the object, because the object is what a reopen has to
hand back.

## Nothing here is async, and that is what defers one decision

`worktree()` is a plain synchronous call. §3.3's own example is `w = parent.worktree(ticket.id,
base=blocker)` followed by `await w.step(...)`, and it is deliberately not a context manager either:
"a context manager would tear the worktree down on exit, destroying exactly what you want to inspect
after a failure. Worktrees persist until `clear`."

So this module cannot `await` anything, and in particular cannot resolve a ref. The base arrives
already decided, as a string, and whether that string is a resolved commit id or a ref expression is
settled one layer down in `Steps._namespace`, which is async and is the one place a
`History.resolve` happens. Nothing here looks at it; it is carried to `build` and no further.
"""

from collections.abc import Callable
from dataclasses import dataclass

from agl.ports.errors import ConflictError
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace

__all__ = ["Worktrees"]


class Worktrees[R]:
    """The run's namespace table: every name taken anywhere in it, and the child each one is.

    One per run, shared down the tree, and generic in the child it holds for the reason the module
    docstring gives - a `Run` is `sdk/workflow.py`'s and naming it here would be a cycle. `R` is
    `Run[object]` at the one call site there is: a table is a mutable container, so this class is
    invariant in `R`, and a `Run` holding a `Worktrees[Run[P]]` would be invariant in `P` - which
    would cost the surface §3.3's own `async def fix(run: Run) -> None`. `Run.worktrees` argues
    that in full, beside the one narrowing it forces.

    The type parameter is still worth having at the erased width: it is what keeps this a table of
    *children* rather than of `object`, so `open` cannot hand back something that was never put in
    and `build` cannot return the wrong kind of thing.

    A plain class and not a dataclass, and deliberately mutable, for `Fingerprints`' reason: it is
    state a run accumulates, it exists to be added to, and a frozen thing returning a new copy would
    leave every caller responsible for threading it - which is the per-`Run` table this module is
    written to refuse, wearing a different hat.

    **No enumeration, no `remove`, no `__contains__`.** Nothing in AGL asks a run what namespaces it
    holds: `clear` takes a run away whole and derives nothing from this, and a workflow that wants
    to know which children it opened is holding them itself - §3.3's own `drive` keeps a
    `dict[str, Run]` for exactly that and registers each child in it. One method is the whole of
    what `run.worktree` needs, and a second one would be a second thing to keep true.
    """

    def __init__(self) -> None:
        # Keyed by `collision_key` and never by the name as typed - see the module docstring. The
        # `Namespace` is kept in the value as well as folded into the key, so that a refusal can
        # print the spelling that took the name beside the spelling that asked for it, which is the
        # difference between "already taken" and a reader learning that case is not compared.
        self._taken: dict[str, _Taken[R]] = {}

    def open(
        self, name: str, *, scope: RunScope, base: str, build: Callable[[RunScope, str], R]
    ) -> R:
        """Take this name for `scope`, or hand back what already holds it. `run.worktree`'s body.

        Three answers, and the module docstring argues each: the same scope asking again for the
        same name gets the same child object; anyone asking for a name this run has already spent
        gets `ConflictError` naming both scopes and both spellings; and anything else is built,
        recorded and returned.

        **The lookup folds case and the reopen does not, and that asymmetry is the whole of the
        first two answers.** A reopen is "this call and that call are the same call", which they are
        only if they wrote the same string: `worktree("T-01")` and `worktree("t-01")` on one `Run`
        are two namespaces to every part of AGL that is not a filesystem - two `Namespace` values,
        two scopes, two `steps/` subtrees, two branches - so handing the second one the first one's
        child would leave a workflow holding two names for one namespace and recording one of them
        under the other's directory. They are still a collision, because they are one directory
        under `.trees/<label>/`, and a collision is what they get.

        `build` is handed `scope.inside(namespace)` and `base` - the child's address and the commit
        its chain starts at - and is called **exactly once per namespace, on the way in**. A reopen
        does not call it, which is what makes "an existing name reopens rather than recreates" a
        fact about this line rather than a rule the caller has to remember.

        **`base` is consulted only when the namespace is new**, exactly as `WorkspaceProvider.open`
        consults its own only when provisioning, and for a version of that method's reason: a reopen
        hands back a namespace that has a chain of its own by now, and starting it again from
        wherever the caller happens to be would be this table deciding a question §3.6 has already
        answered. So `w = parent.worktree("T-01", base=blocker)` on the second walk of a replay is
        the same `Run` as on the first, whatever `blocker` has since become.
        """
        namespace = Namespace(name)
        key = namespace.collision_key
        taken = self._taken.get(key)
        if taken is not None:
            if taken.scope == scope and taken.namespace == namespace:
                return taken.child
            raise ConflictError(_collision(namespace, scope, taken.namespace, taken.scope))
        child = build(scope.inside(namespace), base)
        self._taken[key] = _Taken(namespace, scope, child)
        return child


@dataclass(frozen=True, slots=True)
class _Taken[R]:
    """One name a run has spent: how it was spelled, who spent it, and what they got.

    Frozen because a taken name is a statement about something that has already happened, and
    private because nothing outside this module has any use for it - `open` returns the child, not
    the record of it.
    """

    namespace: Namespace
    """The name as it was first written, which is what a refusal prints beside the name that asked.

    Kept although the key already folds it, because the folded form is not a name anybody typed:
    telling a reader that `t-01` collides with `t-01` teaches nothing, and telling them it collides
    with `T-01` teaches the whole rule in one line."""

    scope: RunScope
    """The `Run` that took it, addressed the way everything below a project is addressed.

    Half of what the reopen compares, and the half that says *who*. A `RunScope` is a frozen value,
    two of them are equal when they name one namespace, and a namespace is unique run-wide - so
    equal scopes mean the same `Run` asking again, and there is no identity question left for this
    table to have an opinion about. It is also what a refusal prints, which is why the scope is kept
    rather than derived from the child."""

    child: R
    """The `Run` built for it, handed back on every reopen.

    The object itself, for the reason the module docstring gives at length: an equal-but-second one
    would be a second `Steps`, a second checkout, a second `Journal` over one namespace, and a
    second `last_good` chain beginning where this namespace started rather than where it has got
    to."""


def _collision(namespace: Namespace, scope: RunScope, held: Namespace, holder: RunScope) -> str:
    """Why one namespace cannot be taken twice in a run, in the words a reader can act on.

    Both scopes are named, because "that name is taken" without saying by whom sends the reader
    looking through a workflow for a call they can already see. The two spellings are printed
    separately for the case that would otherwise read as nonsense: `t-01` refused because `T-01` is
    held is the case-fold rule, and it has to say so where it fires.
    """
    return (
        f"namespace {str(namespace)!r}, asked for by {_where(scope)}, is already taken in run "
        f"{str(holder.label)!r}: {_where(holder)} holds it as {str(held)!r}. Namespace names are "
        f"unique run-wide and not merely among siblings (§3.9), compared case-insensitively, "
        f"because the trees root is flat - both of these are one checkout directory in this run, "
        f"and whichever opened second would be handed the other's working tree. Nothing was "
        f"changed: pick another name"
    )


def _where(scope: RunScope) -> str:
    """A scope as the run's own tree spells it, for a message and for nothing else.

    The namespaces joined by an arrow rather than by a separator, deliberately: this is a sentence
    about parentage and not a path, and the path this run keeps under `AGL_HOME` is
    `home_layout.scope_dir`'s to write - "the one place the `worktrees/` nesting is written down".
    """
    if not scope.namespaces:
        return "the run itself"
    return "the worktree " + " -> ".join(str(name) for name in scope.namespaces)
