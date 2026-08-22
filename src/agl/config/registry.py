"""Workflow discovery through the `agl.workflows` entry points. No dynamic import, no `getattr`.

§1.2's first charge is the one this module answers, and it is worth quoting rather than
paraphrasing: the old code did `importlib.import_module(f"agl.workflows.{name}.workflow")` and then
`getattr(module, "resume", None)`. A module path built by interpolating a string the operator typed,
followed by attribute probing for a name spelled in a literal - no `Workflow` type anywhere, nothing
`mypy` could check, and a workflow that "existed" exactly when two guesses about a package's insides
both happened to come true. `CLAUDE.md` forbade dynamic imports at the time and `cli.py` was built
on them, which is the part worth keeping in view: the rule was written down and the dispatch was
written anyway, because nothing mechanical was ever going to notice.

What replaces it is one line in the package that owns the workflow:

    [project.entry-points."agl.workflows"]
    tickets = "agl.workflows.tickets:tickets"

`pyproject.toml` declares the group already and it is deliberately empty; `workflows/noop/` at stage
10 is the first entry in it. Adding a workflow is that line and a package, and there is no central
table here or anywhere else to edit - measurable target #1, and §3.3's "no `importlib`, no
`getattr`, no central dispatch to edit" in all three of its parts.

## The prohibition, read correctly - because this module imports `importlib.metadata`

The rule being kept is about a *pair*: `importlib.import_module` with a module path built from a
string, and `getattr` with an attribute name built from a string. That pair is what makes a dispatch
uncheckable, because neither half has anything a type checker can look at - the module does not
exist until the format string is evaluated, and the attribute is a name in a namespace no
declaration mentions.

`importlib.metadata.entry_points()` and `EntryPoint.load()` are not that. They are the sanctioned
mechanism for exactly this problem, and the differences are the ones that matter: the group is
declared in packaging metadata, so what is discoverable is a fact about what is *installed* rather
than about what a path happens to name; the resolution is the interpreter's, from a declaration the
package author wrote and a build tool recorded; and the name a caller supplies **indexes a group**
rather than being interpolated into an import path. `agl run ../../etc/passwd` finds no entry point;
`importlib.import_module(f"agl.workflows.{name}.workflow")` was a different kind of question.

So this module names `importlib` and keeps the rule. What it does not contain, anywhere, is a
`getattr`, an `import_module`, or a module path with a `{` in it.

## The typing problem, and why the registry is generic

`EntryPoint.load()` returns `Any` - it must, since only the loaded object knows what it is. Under
`mypy --strict` that `Any` may not escape this module, and the obvious ways to stop it are both
wrong here. Narrowing with `hasattr` would be the duck-typing being repaired, wearing a different
spelling. Nominal narrowing needs a class to narrow *to*, and the only such class is the object
`@workflow` produces in `sdk/workflow.py`, which does not exist until stage 10.2 - and which
`config` may not import from anyway on the day it does, contract 1's layering putting `sdk` below
`config` but `workflows` in between.

**The resolution is that the registry is generic over the type its caller expects.** `load` takes
that type as a parameter and narrows with `isinstance`, so the `Any` is converted at the one place
that has a class to convert it against, and the caller gets back the type it named:

    def load[T](points, name, kind: type[T]) -> T

This is complete today. It typechecks under `--strict` with no `cast`, it builds none of stage 10's
surface, and at 10.3 `api.py` passes the `Workflow` type and gets a `Workflow` back. The registry
never learns what a workflow is, which is the same reason `ports/` never learns what a ticket is.

Two alternatives were considered and both are worse:

**A `runtime_checkable` `Protocol`.** Its `isinstance` is `hasattr` with a type annotation on top -
the runtime check tests for the presence of member *names* and nothing about their signatures, so
an object with a `resume` attribute of the wrong arity passes. That is exactly the check §1.2
charges, re-implemented with better manners, and it would have the framework claim a nominal
guarantee that the runtime does not make.

**Returning `object`.** It typechecks, and it moves the narrowing to every caller - which means the
`getattr` or the `cast` reappears one layer up, in `api.py`, where there are fewer facts to write a
refusal from. Deferring a deliverable is not the same as completing it.

## A pure core, and one line that is not

The split `sources.py` established, for the same reason and with the same payoff. `names` and `load`
take the entry points as an argument, so a test drives them with `EntryPoint` values it constructs
itself - a public, constructible type - and no package has to be installed, no distribution built,
and no `sys.path` arranged for the suite to cover every branch here. `installed` is the one impure
entry point: one line that asks the interpreter what is installed in this environment. Everything
about this module that depends on the machine it runs on is in that line.

## The surface: two operations, and `names` never loads anything

Listing every registered name is `agl workflows` (§3.10, "list what's registered"), and it is sorted
so that the listing is stable across environments rather than ordered by whatever sequence a
metadata scan happened to produce. Loading one workflow by name is what `agl run` needs.

**`names` never calls `load`.** Nothing is imported to list what is registered, which is not an
optimisation: it means one workflow package that fails to import still appears in the listing, and
every other workflow still runs. A registry that imported the world to print a list would let any
broken third-party package take down the command an operator runs to find out what they have.

## Errors, and the class each one takes

`agl.ports.errors` only, and nothing here catches `Exception`.

**A name in no entry point is `NotFoundError`** - exit 3, which stage 10's acceptance criterion
pins. It is the class's own example ("a workflow name no installed package registers"), and the
message lists what *is* registered, because the overwhelmingly likely cause is a typo and the answer
is three names away. An empty registry gets a different sentence: "nothing is installed" is a
different situation from "not that one", and a refusal ending in an empty list would read as a bug.

**Two distributions registering one name is `ConflictError`** - exit 4. The argument for it is the
class's own words, "the world already holds something this operation would have to take": the
operation is claiming a name, and the name is held twice. It is not `NotFoundError`, which is the
exact mirror - zero matches rather than more than one. It is not `InputError`: the name the operator
typed is well-formed and was understood perfectly. It is not `InternalError`: which packages are
installed together is nobody's invariant but the operator's.

What the class choice must not be is silence. Preferring the first match, or the one from the
alphabetically earlier distribution, is how an operator ends up running a workflow they did not
install - the failure being invisible at exactly the moment it matters, since both candidates answer
to the same name and only one of them was meant. So the refusal is raised while *indexing*, which
means `agl workflows` refuses as well as `agl run`: a listing showing one row for two installed
workflows tells the operator something false, and the row it showed is the coin flip they were about
to make. The message names both entry-point values, which is what a `pip uninstall` needs.

**An entry point that will not load, and one that loads the wrong thing, are both `InputError`** -
exit 2. Neither is `InternalError`: the declaration was written by a package the operator installed,
and AGL only read it, so exit 70's "file a bug against AGL" sends the reader to the wrong codebase.
Neither is `UpstreamUnavailable` either, and that one is worth arguing because `container.py` raises
it for a failed import a few lines away. That case is a *missing pip extra* - §3.2.1's "a missing
binary is `UpstreamUnavailable`, not `InputError`", with a package manager standing in for a `PATH`
lookup - and its class carries a promise this case cannot keep: `UpstreamUnavailable` means nothing
happened on the far side and the same call may well succeed later. A workflow package whose module
raises on import does not succeed later. It succeeds when the operator changes their installation,
and "what you supplied cannot be used" is what `InputError` says. The exit code carries the same
distinction to a script: 6 reads as transient, 2 reads as fix-what-you-passed.

Both refusals name the entry point and its value, because `agl.workflows.tickets:tickets` is the
string the author has to go and correct, and the load failure **chains the original exception** with
`raise ... from`: a workflow author debugging their own package needs the real `ModuleNotFoundError`
with the real traceback under it, not a sentence saying one happened.

The two exceptions caught are the two `EntryPoint.load` itself raises - `ImportError` for a module
that is not there or will not import, `AttributeError` for a module that is there without the name.
A workflow module that raises something of its own at import time propagates untouched, and
deliberately: that exception is the package's own report of what is wrong with it, and there is
nothing this module could add to it except a class it has no grounds to choose.

## Deliberately not built

No cached or module-level registry: `installed` is called once at the edge for the same reason
`sources.resolve` is, and a memoised copy would be a second answer to a question already closed. No
second discovery path - no scan of a workflows directory, no `--workflow-path`, no
`agl.workflows.<name>` module convention kept "for compatibility". A second path is a second way for
`agl run tickets` to mean two things, and the one being replaced is the one this module exists to
delete. No "did you mean" suggestion: the whole registry is a handful of names and the refusal
already prints all of them, so a guess would add a way to be wrong about a list the reader can see.
"""

from collections.abc import Iterable, Mapping
from importlib.metadata import EntryPoint, entry_points
from typing import Final

from agl.ports.errors import ConflictError, InputError, NotFoundError

__all__ = ["GROUP", "installed", "load", "names"]

# The group name, spelled here and in `pyproject.toml` and nowhere else. It is public because it is
# the contract a workflow package is written against: an author reads it here and types it there.
GROUP: Final = "agl.workflows"


def installed() -> tuple[EntryPoint, ...]:
    """The one impure entry point: what the `agl.workflows` group holds in this environment."""
    return tuple(entry_points(group=GROUP))


def names(points: Iterable[EntryPoint]) -> tuple[str, ...]:
    """Every registered name, sorted. `agl workflows` (§3.10) is this and nothing else.

    Nothing is imported to answer it - see the module docstring - so a workflow package that will
    not load still appears here, which is the listing an operator can act on.
    """
    return tuple(sorted(_index(points)))


def load[T](points: Iterable[EntryPoint], name: str, kind: type[T]) -> T:
    """The workflow registered under `name`, narrowed to the type the caller expects.

    `kind` is what makes this checkable: the `Any` that `EntryPoint.load` must return is converted
    here, against a class the caller named, and nothing untyped leaves this function. At stage 10.3
    `api.py` passes `Workflow` and gets a `Workflow`.
    """
    index = _index(points)
    point = index.get(name)
    if point is None:
        raise NotFoundError(_unknown(name, index))
    try:
        loaded = point.load()
    except (ImportError, AttributeError) as error:
        raise InputError(
            f"the workflow {name!r} is registered as {point.value!r}, and loading it failed: "
            f"{error}. That declaration is in the {GROUP} entry points of the package that "
            f"provides {name!r}, so the fix is in that package or in how it is installed - AGL "
            f"only read what it declared. The original error is chained below this one"
        ) from error
    if not isinstance(loaded, kind):
        raise InputError(
            f"the workflow {name!r} is registered as {point.value!r}, which loaded and turned "
            f"out to be a {_describe(type(loaded))} rather than a {_describe(kind)}. The "
            f"{GROUP} entry point of the package that provides {name!r} is pointing at the wrong "
            f"object - AGL only read what it declared"
        )
    return loaded


def _index(points: Iterable[EntryPoint]) -> Mapping[str, EntryPoint]:
    """Name to entry point, refusing a name held twice. Both operations go through here.

    Which is the point: the duplicate is refused when the group is *indexed*, so `agl workflows`
    refuses it too rather than printing one row and letting the operator pick the wrong one blind.
    """
    index: dict[str, EntryPoint] = {}
    for point in points:
        held = index.get(point.name)
        if held is not None:
            raise ConflictError(
                f"two installed packages both register a workflow named {point.name!r}, as "
                f"{held.value!r} and as {point.value!r}. AGL will not choose between them: running "
                f"the wrong one of two workflows that answer to the same name is a mistake nothing "
                f"downstream could report, so the name stays ambiguous until one of the two "
                f"packages is uninstalled"
            )
        index[point.name] = point
    return index


def _unknown(name: str, index: Mapping[str, EntryPoint]) -> str:
    """The refusal for a name no entry point holds, with an empty registry saying so in its own
    words - "not that one" and "none at all" are different situations for the reader.

    It takes the built index rather than the entry points, so that `points` is walked exactly once
    per call: an `Iterable` may be an iterator, and a refusal is no place to discover that.
    """
    registered = tuple(sorted(index))
    if not registered:
        return (
            f"there is no workflow named {name!r}, and in fact no workflow is installed at all: "
            f"the {GROUP} entry point group is empty in this environment. A workflow arrives as a "
            f"package that declares one entry point in that group; install one, then `agl "
            f"workflows` lists it"
        )
    return (
        f"there is no workflow named {name!r}. Installed and registered under {GROUP}: "
        f"{', '.join(registered)}. `agl workflows` prints the same list"
    )


def _describe(kind: type[object]) -> str:
    """A class named the way an operator can search for it: module path and qualified name."""
    return f"{kind.__module__}.{kind.__qualname__}"
