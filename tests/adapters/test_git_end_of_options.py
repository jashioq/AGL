"""`--end-of-options` wherever a value from outside reaches git, asserted over the package's source.

`_runner.py` will not place this flag and says why: "where it goes depends on the subcommand, so
placing it would mean this module knowing the subcommands, which is the one thing it must not
know". So it lives at the call sites - twenty-two across three modules as this is written - and a
call site is the kind of thing the next deliverable adds one more of.

**Nothing behavioural notices when one is missing.** The flag can be deleted from all six sites in
`workspace.py` and all four in `history.py` and the suite stays green, because every value AGL
passes today is a branch name or a commit id `ids.py` and `tree_layout.py` already made safe. The
hazard is the value they do not constrain: `--from` is what a person typed, and `history.py` says
what it costs - `diff-tree` accepts `--output=<file>`, so a ref spelled `--output=/etc/anything` is
a *write* performed by a port whose whole promise is that it changes nothing.

So a probe per site is the wrong instrument, for the reason the hermeticity test in
`test_claude_code_runner.py` gives about its own clause: where the property is structural, the
structural assertion is the one that does not go stale when a site is added. This is that shape's
fourth application - `test_shell_verifier.py` established it at stage 6 - and like both siblings it
parses source and runs nothing.

## The rule, which is four docstrings' and not this file's

`_runner.py` says the flag belongs at the call site; `workspace.py` says when, "wherever an
argument could begin with a dash"; `history.py` says where it goes, "after every option and before
the two revisions; `diff-tree` rejects its own flags if it comes any earlier"; and `integrator.py`
says when it is not wanted at all, of `merge --abort`: "It takes no ref, so nothing from outside
this module reaches its arguments and there is no option for `--end-of-options` to protect - the
whole command is these two words." Together, and this is what is asserted below:

**Every argv this package hands git carries `--end-of-options` in front of every word that came
from outside the source, and an argv holding no such word needs nothing.**

Two argvs would fail that sentence as written - `worktree add -b <branch> --end-of-options <path>
<base>` puts the branch *before* the flag, and `commit --no-verify --no-gpg-sign --message
<message>` carries no flag at all - and both are the one shape the rule below is widened for. See
`BINDING`, where the widening is argued beside the list it is made of.

## What it refuses to guess

An argv is read exactly as literally as it is written. A string constant is a literal; `*NAME` is
expanded from the tuple `NAME` is assigned in this module or in the enclosing function, both
branches where that assignment is a conditional - `workspace.py::open` picks its `worktree add`
form that way and both forms must satisfy the rule; anything else is a value from outside. A
construct that is none of those fails loudly, and so does a `run` or `answers` call reached
through anything but `self._git`; `_unreadable` argues why that is never a skip. The cost is that
an unrelated `.run(` added to this package - `asyncio.run`, say - fails here until this file is
taught about it, and of the two mistakes that is the cheaper one.

Named `test_git_end_of_options.py`, for the invariant rather than for a module, because it is the
only test in `tests/adapters/` that is about all three git adapters at once and belongs in none of
their files: `tests/` carries no `__init__.py` - see `tests/conftest.py` for why it must not - so
pytest's module names are the bare filenames and two files of one name would collide at import.
"""

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agl.adapters import git as git_package

# The two members of `GitRunner` that turn arguments into an argv, and the attribute all three
# adapters reach them through. Both take their arguments variadically, so a call's positional
# arguments *are* the argv and its keywords - `cwd`, `refusal`, `timeout` - are not.
MEMBERS: Final = frozenset({"run", "answers"})
RUNNER: Final = "_git"

# The word itself, spelled once. git stops reading options at it, so everything after it is a
# revision, a path or a pathspec however it begins.
FENCE: Final = "--end-of-options"

# The options this package puts a value from outside directly after, and the one widening of the
# rule the module docstring states. git binds the next word to each of these - `git commit
# --message --foo` sets the message to `--foo`, and `-b --foo` names a branch, badly, and never an
# option - so that word cannot be re-read as an option and there is nothing there for the fence to
# protect, which is `_MERGING`'s own argument about a command built of literals.
#
# Deliberately not "any word beginning with a dash": `--no-verify-signatures` is what stands in
# front of `source.branch` the moment `_MERGING`'s flag is deleted, and a rule excusing that would
# excuse the one call site the package already had a behavioural witness for. A closed list, so
# that the next option taking a value is a decision somebody makes rather than a hole that opens.
BINDING: Final = frozenset({"-b", "--message"})

# How many call sites carried a value from outside when this was written: one in `integrator.py`,
# four in `workspace.py` and four in `history.py`. The floor is the hermeticity test's `sessions
# >= 2` - every assertion below passes silently over an argv that has nothing to fence, so a
# version of this file that found none of them would be green and checking nothing.
FENCED_TODAY: Final = 9

type _Scopes = tuple[Mapping[str, list[ast.expr]], ...]


@dataclass(frozen=True, slots=True)
class _Word:
    """One argv word as the source spells it: a constant's own value, or `ast.unparse`'s rendering
    of the expression standing there, so that a failure quotes what a reader will find on the line.
    Whether it is a literal is the whole question this file asks about it."""

    text: str
    literal: bool


@dataclass(frozen=True, slots=True)
class _Site:
    """One call to the runner: where it is, and every argv it can hand git. More than one only
    where a conditional picks the form - `workspace.py::open` and nothing else today - and both
    are asserted, a rule holding on one branch being a rule about half the provisionings."""

    where: str
    argvs: tuple[tuple[_Word, ...], ...]


def test_every_git_argv_that_carries_a_value_from_outside_fences_it_with_end_of_options() -> None:
    """The package's own source, parsed, with every argv it can build read word by word.

    Two assertions, and the second is what keeps the first honest. Every argv carrying a word from
    outside carries `--end-of-options` in front of it - which fails for a flag that was deleted and
    for one that was moved alike, placement being the half of the rule `history.py` insists on. And
    at least as many such argvs are found as exist today, so that a file which stopped recognising
    call sites fails rather than passing vacuously. The exempt sites are counted though nothing is
    asserted about them: the two numbers are only readable together, and nine of nine would say
    the reader is looking at a test that no longer sees the other thirteen.
    """
    package = Path(git_package.__file__).parent
    fenced: list[str] = []
    exempt: list[str] = []
    for source in sorted(package.glob("*.py")):
        for site in _sites(source):
            for argv in site.argvs:
                exposed = _exposed(argv)
                assert not exposed, (
                    f"{site.where} runs `git {' '.join(word.text for word in argv)}`, and "
                    f"{exposed[0].text!r} is a value from outside this package with no `{FENCE}` "
                    f"in front of it - so git is free to read it as one of its own options. That "
                    f"is `diff-tree --output=<file>` on a port that promises to change nothing, "
                    f"and `merge --abort` spelled as a branch name. The flag goes after every "
                    f"option and before the first word that came from outside"
                )
            (fenced if any(_outside(argv) for argv in site.argvs) else exempt).append(site.where)

    assert len(fenced) >= FENCED_TODAY, (
        f"only {len(fenced)} of the {len(fenced) + len(exempt)} runner calls under {package} were "
        f"read as carrying a value from outside, and there were {FENCED_TODAY} when this was "
        f"written: {sorted(fenced)}. Every assertion above is silent about an argv built of "
        f"literals, so a test that found none of the others would be green and checking nothing"
    )


def _sites(path: Path) -> list[_Site]:
    """Every runner call in one module, with the argvs each of them can hand git."""
    found: list[_Site] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    _visit(tree, (_bound(tree),), path.name, found)
    return found


def _visit(node: ast.AST, scopes: _Scopes, module: str, found: list[_Site]) -> None:
    """Walk `node`, carrying the scopes a name could be assigned in, innermost first. A function is
    entered with its own assignments in front of the module's, which is what makes `*adding` in
    `workspace.py::open` resolvable at all."""
    for child in ast.iter_child_nodes(node):
        inner = scopes
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            inner = (_bound(child), *scopes)
        elif isinstance(child, ast.Call) and getattr(child.func, "attr", None) in MEMBERS:
            found.append(_site(child, scopes, module))
        _visit(child, inner, module, found)


def _site(call: ast.Call, scopes: _Scopes, module: str) -> _Site:
    """One call read into its argvs, or the failure for a receiver this file cannot vouch for.
    Matched on the member name alone, whatever it was reached through, which is what makes a
    runner laundered through some other name a failure rather than a blind spot."""
    where = f"{module}:{call.lineno}"
    receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
    if not isinstance(receiver, ast.Attribute) or receiver.attr != RUNNER:
        raise _unreadable(where, call, f"a runner member not reached through {RUNNER}")
    return _Site(where, tuple(tuple(argv) for argv in _argvs(call.args, scopes, where)))


def _argvs(args: Sequence[ast.expr], scopes: _Scopes, where: str) -> list[list[_Word]]:
    """Every argv these arguments can produce - one per form each of them can take."""
    grown: list[list[_Word]] = [[]]
    for arg in args:
        grown = [built + option for built in grown for option in _options(arg, scopes, where)]
    return grown


def _options(arg: ast.expr, scopes: _Scopes, where: str) -> list[list[_Word]]:
    """One argument as the words it contributes, once per form it can take.

    A string constant is itself; a splatted name is the tuple it was assigned, expanded in place
    and recursively, since a tuple's elements are arguments of the same three kinds. Everything
    else - a name, an attribute, an f-string, a `str()` call - is a value from outside, which is
    the direction the doubt has to fall in: a word wrongly read as a literal is one this file
    would then decline to require a fence for.
    """
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return [[_Word(arg.value, literal=True)]]
    if not isinstance(arg, ast.Starred):
        return [[_Word(ast.unparse(arg), literal=False)]]
    if not isinstance(arg.value, ast.Name):
        raise _unreadable(where, arg, "a splat of something this file cannot look up by name")
    spread: list[list[_Word]] = []
    for elements in _forms(arg.value, scopes, where):
        spread.extend(_argvs(elements, scopes, where))
    return spread


def _forms(name: ast.Name, scopes: _Scopes, where: str) -> list[list[ast.expr]]:
    """The tuple, or the two tuples, that `name` can hold - read out of the nearest scope. Two
    shapes and no others: a tuple, and a conditional choosing between two of them, which is how
    `workspace.py::open` decides whether a `worktree add` makes a branch or attaches to one. Both
    of its branches are handed back, so that both are asserted."""
    for scope in scopes:
        assigned = scope.get(name.id)
        if assigned is None:
            continue
        if len(assigned) != 1:
            raise _unreadable(where, name, f"a name its scope assigns {len(assigned)} times")
        value = assigned[0]
        if isinstance(value, ast.Tuple):
            return [list(value.elts)]
        if isinstance(value, ast.IfExp):
            if isinstance(value.body, ast.Tuple) and isinstance(value.orelse, ast.Tuple):
                return [list(value.body.elts), list(value.orelse.elts)]
        raise _unreadable(where, value, "a splatted name that is not a tuple of arguments")
    raise _unreadable(where, name, "a splatted name nothing in this module assigns")


def _bound(scope: ast.AST) -> dict[str, list[ast.expr]]:
    """Every plain name this scope assigns, to the expressions it was assigned. A list and not one
    expression, so that a name assigned twice fails at the call site that splats it rather than
    being read as whichever assignment happened to come last."""
    bound: dict[str, list[ast.expr]] = {}
    for node in _statements(scope):
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bound.setdefault(target.id, []).append(value)
    return bound


def _statements(scope: ast.AST) -> list[ast.AST]:
    """Everything in `scope` that is not inside a scope of its own."""
    inside: list[ast.AST] = []
    for child in ast.iter_child_nodes(scope):
        inside.append(child)
        if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            inside.extend(_statements(child))
    return inside


def _outside(argv: Sequence[_Word]) -> list[tuple[int, _Word]]:
    """The words of `argv` that came from outside and that git has not already bound to an option:
    a word standing directly after one of `BINDING` is that option's value and git can read it as
    nothing else, which is the widening `BINDING` argues."""
    return [
        (at, word)
        for at, word in enumerate(argv)
        if not word.literal
        and not (at > 0 and argv[at - 1].literal and argv[at - 1].text in BINDING)
    ]


def _exposed(argv: Sequence[_Word]) -> list[_Word]:
    """Those of them git is still free to read as options: the ones standing before the fence.

    An argv holding no fence exposes every one, which is how a deleted flag and a misplaced one
    fail the same way and for one reason - a flag that has slipped behind a revision is protecting
    nothing that was ever in danger.
    """
    fence = next(
        (at for at, word in enumerate(argv) if word.literal and word.text == FENCE), len(argv)
    )
    return [word for at, word in _outside(argv) if at < fence]


def _unreadable(where: str, node: ast.AST, what: str) -> AssertionError:
    """The failure for an argv this file cannot read. Returned, so call sites `raise` it.

    `_runner.py::unreadable` is the shape, for its reason: what AGL says about something it cannot
    parse is said once, where a reader meets it. What differs is that this one is never tolerated -
    a skip would make the test agree with whatever it could not understand, and an argv it could
    not understand is the one most likely to be composing something.
    """
    return AssertionError(
        f"{where} builds its argv out of {ast.unparse(node)!r}, which is {what}. This test cannot "
        f"say whether `{FENCE}` stands in front of the values in it, and an argv it passed over "
        f"quietly is exactly where the next unfenced value would sit - so it fails here instead. "
        f"Spell the arguments as literals and splatted tuples of them, or teach this file the "
        f"construct"
    )
