"""No module under `agl.adapters.filesystem` names a synchronisation primitive, over its source.

`store.py` predicts this file. Under the heading **"There is no lock in this file, and its absence
is the requirement"** it says what a lock would cost and then says that nothing could catch one: "A
lock here would *pass the contract suite* ... Nothing below the suite can catch its return, so this
paragraph is what guards it." What follows is that paragraph made mechanical.

## The hole, measured rather than argued

A module-level `asyncio.Lock` taken around every write leaves all sixty store tests green. Nothing
in `tests/` so much as says the word: the clause is stated everywhere and checked nowhere.
`ports/store.py` states it - "An implementation that would have to put every write behind one
mutex, because everything it holds is one document, is not satisfying this port" - and §3.6 states
the design decision under it, that separate addresses make each write one `os.replace`, "atomic, no
lock, no coordination". Both store implementations restate it in their own docstrings.

And both places that could have caught it concede that they cannot. `tests/contracts/store.py`
lists "that distinct addresses are written without a shared lock" among the things a green run does
not entitle anybody to believe, and finishes: "through this interface, a global mutex is
invisible". `tests/contracts/_store_concurrency.py` concedes the same clause from the other side -
it observes the store only at the moments an implementation yields, and it refuses threads for a
reason it states. A lock is correct and merely slow, and slow is not a thing either of them can
see. It would surface at stage 13 as concurrency that quietly is not there.

## Why the shape is structural and not a stopwatch

A timing assertion is the obvious instrument and it is the wrong one. Serialised writes differ from
independent ones only in *when* they finish, so the assertion needs a threshold - and a threshold
fails on a loaded machine, on a slow filesystem, and on an honest implementation that is slow for a
reason this repo has already sanctioned: `store.py` names moving `_write_atomically` and `_read`
behind `asyncio.to_thread` as the change to make if a slow network mount under `AGL_HOME` ever
stalls the redraw loop, and that change costs a thread hop per write and breaks no clause at all. A
test that refuses correct code intermittently is worse than no test, because it teaches a reader to
re-run the suite instead of to read it.

What is being forbidden is a thing in the source, so the assertion is about the source. Where the
property is structural, the structural assertion is the one that does not go stale when a module is
added - `test_claude_code_runner.py`'s argument about its own clause, and this is that shape's fifth
application. `test_shell_verifier.py` established it at stage 6, `test_claude_code_runner.py` and
`test_openai_runner.py` carry the two hermeticity siblings, and `test_git_end_of_options.py` is the
fourth. Like all four, this file parses source and runs nothing.

## The closed set, and the two things worth saying about it

`PRIMITIVES` below is a list of *names*, not of modules, and a name in it is refused however it was
reached: `asyncio.Lock`, `threading.Lock`, `multiprocessing.Lock` and a bare `Lock` imported from
any of the three are one entry, because what is forbidden is the same thing in each case. Imports
are read by the name being imported and never by the local alias, so `from asyncio import Lock as
_L` fails at its import line.

**What the set does not cover: a bespoke coordination scheme under another name.** A dict of
`asyncio.Future`s keyed by address and awaited on entry, a hand-rolled spin on a module-level bool,
a `deque` of pending writes drained by one task - each of those serialises exactly as a mutex does
and none of them spells any word below. This file is not a proof that no such thing exists; it is a
fence around the primitives somebody actually reaches for first. `store.py`'s own paragraph still
guards the rest, and still has to.

**Widening it is a one-line change.** The next primitive somebody reaches for goes in the set as a
string, and that is the whole edit - which is the point of the set being a set rather than a
matcher. What must not happen instead is an entry being *removed* to make a new lock legal.

`asyncio` itself is deliberately absent, and so is `to_thread`: awaiting is what the port is `async`
for, and moving a syscall off the loop serialises nothing.

## The floor

Every assertion here is silent about a module that spells none of these names, which is what a
green run looks like and also what a run against nothing at all looks like. So the scan counts what
it walked and asserts it walked the package - the hermeticity test's `sessions >= 2`, for the same
reason it has one.

Named `test_filesystem_no_lock.py`, for the invariant rather than for a module, because the rule is
about the whole package: `memory_store.py` makes the same promise in its own docstring ("No lock,
and every method returns without awaiting") and a test asserting that from inside
`test_filesystem_store.py` would be a test about `FilesystemStore` that is not. That is
`test_git_end_of_options.py`'s reason, in a package with two modules instead of three. `tests/`
carries no `__init__.py` - see `tests/conftest.py` for why it must not - so pytest's module names
are the bare filenames and two files of one name would collide at import.
"""

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from agl.adapters import filesystem as filesystem_package

# The closed set: every name that means "something here waits for something else there". Grouped by
# where each comes from, though the check is by name alone - `Lock` is `Lock` whichever of the three
# modules it was reached through, and a package with no reason to name any of them has no reason to
# name a particular one.
PRIMITIVES: Final = frozenset(
    {
        # asyncio's, which is what a package of `async def`s would reach for first. It has no
        # `RLock`; `threading` and `multiprocessing` do, so the name is here once for all three.
        "Lock",
        "RLock",
        "Semaphore",
        "BoundedSemaphore",
        "Condition",
        "Event",
        "Barrier",
        # The queues, from `asyncio`, `queue` and `multiprocessing` alike. A queue drained by one
        # consumer is a mutex with a nicer name: it makes every write wait for the write before it,
        # which is the arrangement §3.6 gave every step its own address to avoid.
        "Queue",
        "SimpleQueue",
        "LifoQueue",
        "PriorityQueue",
        "JoinableQueue",
        # `threading`'s one name that is nobody else's.
        "allocate_lock",
        # `fcntl`'s two, which lock a *file* rather than a variable. They are the shape that would
        # look most defensible here - "lock the entry while it is written" - and they are the same
        # mistake: a write is one `os.replace` and a reader never sees a partial file, so there is
        # nothing for a file lock to protect and every writer would queue behind one anyway.
        "flock",
        "lockf",
    }
)

# Whole modules that are a lock and nothing else, refused at the import rather than by member. An
# import of one of these is not a dependency this package may take, and `pyproject.toml` lists no
# dependencies at all - AGL's core is stdlib-only.
LOCK_MODULES: Final = frozenset({"filelock"})

# The floor, in the spirit of the hermeticity test's `sessions >= 2`. Three `.py` files today - the
# package's `__init__.py` and the two `Store` implementations - and 1,750 AST nodes across them. The
# node figure is a floor and not a measurement: it is a quarter of what is there, so an ordinary
# edit never moves it, and a scan that stopped parsing cannot clear it.
MODULES_TODAY: Final = 3
NODES_TODAY: Final = 400


def test_no_module_in_the_filesystem_package_names_a_synchronisation_primitive() -> None:
    """The package's own source, parsed, with every name it spells read against the closed set.

    Two assertions, and the second is what keeps the first honest. No module names a primitive -
    which fails for a lock taken around the writes, for one taken around a single method, and for
    one imported and never used, because what is forbidden is the arrangement and not the moment it
    is entered. And the scan is asserted to have found the package and walked it, so that a version
    of this file matching nothing could not be green while checking nothing.

    Both stores are covered, `store.py` and `memory_store.py`, by globbing the package the way
    `test_claude_code_runner.py` globs its own. §1.9's rule is that the fake and the real adapter
    are held to one standard, and a fake that serialised its writes would be a `--dry-run` whose
    concurrency is a fiction the real run does not share.
    """
    package = Path(filesystem_package.__file__).parent
    walked: list[str] = []
    nodes = 0
    for source in sorted(package.glob("*.py")):
        walked.append(source.name)
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            nodes += 1
            for line, name in _spelled(node):
                assert name not in PRIMITIVES, (
                    f"{source.name}:{line} names {name!r}, which is a synchronisation primitive, "
                    f"and this package must not name one. §3.6 gives every step its own address "
                    f"so that a completion is one write - 'no lock, no coordination' - and the "
                    f"port refuses an implementation that would put every write behind one mutex. "
                    f"A lock here passes the whole contract suite: it is correct and merely slow, "
                    f"and slow is the one thing that suite says outright it cannot see. Take it "
                    f"out, or - if this name is not a lock at all - widen the closed set at the "
                    f"top of this file by taking it out of PRIMITIVES, and say why there"
                )
                assert name not in LOCK_MODULES, (
                    f"{source.name}:{line} imports {name!r}, which is a locking library. "
                    f"Everything the assertion above says applies, and this one arrives as a "
                    f"dependency besides: AGL's core is stdlib-only and `pyproject.toml` lists no "
                    f"dependencies at all"
                )

    assert len(walked) >= MODULES_TODAY, (
        f"only {len(walked)} module(s) were found under {package} - {sorted(walked)} - and there "
        f"were {MODULES_TODAY} when this was written: the package's `__init__.py` and the two "
        f"`Store` implementations. Every assertion above is silent about a module that names no "
        f"primitive, so a scan that found none of them would be green and checking nothing"
    )
    assert nodes >= NODES_TODAY, (
        f"the {len(walked)} module(s) under {package} parsed to {nodes} AST nodes, and the package "
        f"held 1,750 when this was written. {NODES_TODAY} is a floor rather than a measurement, so "
        f"reaching it means something stopped parsing rather than that somebody wrote less code"
    )


def _spelled(node: ast.AST) -> Iterator[tuple[int, str]]:
    """Every name one node spells, with the line it spells it on, as the closed set writes them.

    Four kinds of node and no others, which between them are every way a primitive's own name can
    appear in source. An import contributes the names it *imports* - the module's segments and each
    member's real name, never the local alias - so a primitive renamed on the way in is caught at
    its import line and nothing downstream has to recognise the new name. A plain `Name` catches it
    where it is then used, and an `Attribute` catches `asyncio.Lock()` reached through the module.

    A string is not a name: the docstrings above this package's code say "no mutex, no
    `asyncio.Lock`, no queue, nothing serialised", and a scan that read prose would fail on the
    paragraphs promising the thing it is looking for.

    The line is carried out from here rather than read off the node at the call site, because only
    these four types are known to have one - `ast.AST` does not, and the walk hands over every node
    in the tree.
    """
    if isinstance(node, ast.Import):
        for alias in node.names:
            for segment in alias.name.split("."):
                yield node.lineno, segment
    elif isinstance(node, ast.ImportFrom):
        for segment in (node.module or "").split("."):
            yield node.lineno, segment
        for alias in node.names:
            yield node.lineno, alias.name
    elif isinstance(node, ast.Name):
        yield node.lineno, node.id
    elif isinstance(node, ast.Attribute):
        yield node.lineno, node.attr
