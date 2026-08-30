"""`api.py` catches nothing at all, asserted over its own source: no `except` clause, of any width.

That module's docstring said it in one sentence - "So there is no `except` in this file, and there
never may be" - and the sentence went when `src/` was stripped of its prose. It is the one clause
the strip left recorded nowhere else in the repository. This file is that sentence made mechanical.

## Why an `except` here is worse than an `except` anywhere else

`Stop` descends from `AglError` (`ports/errors.py`), so the two are not separable by width: a
handler that catches the base catches a workflow's deliberate end along with everything else, and
`EXIT_CODES` maps `Stop` to 7, `UpstreamError` to 6 and `InternalError` to 70. In `cli/` that
hazard is *reporting* - answering before consulting the table gives 6 or 70 where the contract
promises 7. In this module it is *wrapping*. Any `except AglError` that translated, annotated or
re-raised would turn a workflow's `ReviewNotConverging(Stop)` into something else on the way out,
and `cli/exit_codes.exit_status` would then be answering about AGL's object instead of the
workflow's - right by accident today and wrong on the next edit.

What the module does instead is nothing. A workflow's exception leaves `api.run` as the object it
raised, with its own traceback under it, and `exit_status` answers 7 for it without either module
having learned what `ReviewNotConverging` is. That is stronger than catching `Stop` first, which is
why the rule is "no `except`" rather than "the handlers in the right order": an ordering is a thing
somebody has to keep getting right, and an absence is not.

## The hole, measured rather than argued

`tests/test_api.py` pins the behavioural half by identity - `assert caught.value is raised[0]` - and
its docstring says why identity rather than class: an `isinstance` check passes against a `run` that
caught the workflow's `ReviewNotConverging`, threw it away and raised a fresh one of the same class,
where the exit code is still 7 and the traceback names `api` instead of the step that stopped.
Identity is the strongest assertion available from outside the module, and it is still not strong
enough for this clause. `except AglError: raise` re-raises *the same object*: it passes that test,
passes every other test in the suite, and changes no behaviour whatsoever. It is one edit - a `raise
InternalError(...) from error`, an `.add_note()`, a `log.exception()` - from being the bug the
paragraph above describes, and nothing red would then say which edit did it. So the structural half
is asserted here, and the pair is the whole of what the docstring used to carry.

## The subtlety, and why this file counts handlers and not statements

**`api.py` contains a `try` and must keep it.** The framework takes a lease per integration target
and makes `run` exit the sweeper rather than the lifetime, so the last two lines of `_walked` - the
tail `run` and `resume` both call, and the only place in this module either of them reaches the
workflow's function - are a `finally` around it. A `finally` sees no exception, names no class and
can decide nothing: control leaves it carrying whatever arrived, `Stop` subclass and all.
The `async with services.terminal` inside it is in the same position and survives for a second
reason besides - `Terminal.__aexit__` is annotated `-> None` on the port, suppressing an exception
from a context manager means returning something *truthy*, `None` is falsy, and `mypy --strict` is
a gate - so no conforming terminal can swallow a workflow's `Stop`, and that is a fact about the
signature rather than a promise an implementation keeps. What would break the criterion is an
`except` of any width, which is why the rule is written about that word and not about `try`.

So the node type asserted absent below is `ast.ExceptHandler`, and `ast.Try` is asserted *present*.
One `try` statement stands in that file today and a version of this test that forbade it would be
red against the correct source - which is the mistake worth naming here, because it is the one a
reader who has only heard the rule as "no exception handling in `api.py`" would make.

One walk covers both spellings: `except*` parses to an `ast.TryStar` whose `handlers` are ordinary
`ast.ExceptHandler` nodes, so nothing has to know about PEP 654 to catch it. The last assertion
demonstrates that on a fabricated snippet rather than leaving it as a claim in this paragraph.

## The shape, and the name

Where the property is structural, the structural assertion is the one that does not go stale when a
line is added - `test_claude_code_runner.py`'s argument about its own clause. This is that shape's
sixth application: `test_shell_verifier.py` established it, `test_claude_code_runner.py` and
`test_openai_runner.py` carry the two hermeticity siblings, `test_git_end_of_options.py` is the
fourth and `test_filesystem_no_lock.py` the fifth. Like all five, this file parses source and runs
nothing. `ARCHITECTURE.md` states the criterion the fifth one shares with this one, of the lock it
guards: it "leaves every store test green". An `except` here does exactly that.

Named for the invariant and kept out of `tests/test_api.py`, which drives `api` over the all-fakes
bundle and is a file of awaited behaviour. This one imports the module to find its file on disk and
never calls it, so the two have no fixture, no marker and no import in common. `tests/` carries no
`__init__.py` - see `tests/conftest.py` for why it must not - so pytest's module names are the bare
filenames, and this one has to be distinct from `test_api.py`'s rather than a second `test_api`.
"""

import ast
from pathlib import Path
from typing import Final

from agl import api as api_module

# The floor, in the spirit of `test_filesystem_no_lock.py`'s `MODULES_TODAY`. The assertion below
# is silent about a file that holds no handler, which is what a green run looks like and also what
# a run against an empty file, a wrong path or a parse that gave up looks like. `api.py` is 1,279
# AST nodes as this is written; 300 is under a quarter of that, so an ordinary edit never moves it
# and only something that stopped reading the real module can fail it.
NODES_TODAY: Final = 300

# The `try` statements, asserted present. One today, in `_walked` - the tail `run` and `resume`
# share - a `finally` giving back the integration leases the workflow was still holding. There were
# two, one written out per caller, until that tail was folded into one function; the number came
# down on purpose and the witness survives, which is what this paragraph is for. A measurement
# rather than a floor with a life of its own: if the sweep is ever written some other way this
# number is lowered again, by somebody who has read the paragraph above and knows they are removing
# this file's witness that the rule is about `except`. What must not happen instead is the assertion
# above being widened from `ast.ExceptHandler` to `ast.Try` to make the two agree again.
SWEEPS_TODAY: Final = 1

# A fabricated `except*`, for the last assertion. Nothing in AGL spells one; it is here so that the
# claim "one walk catches both spellings" is checked against the interpreter running the suite
# instead of being trusted to a docstring.
EXCEPT_STAR: Final = "try:\n    work()\nexcept* ValueError:\n    pass\n"


def test_api_holds_no_except_clause_of_any_width_anywhere_in_it() -> None:
    """`api.py`'s own source, parsed, with every `except` clause in it counted. There are none.

    Four assertions, and the last three are what keep the first honest. No handler - which fails
    for `except AglError`, for a bare `except:`, for `except Exception` and for an `except*` alike,
    because what is forbidden is the word and not any particular width of it, and fails for one
    that only re-raises, because a re-raise is a wrap that has not been written yet. Then the node
    count, so that a scan which found nothing to read cannot be green. Then the `try` statements,
    present and counted, which is the distinction this whole file rests on stated as a measurement:
    the sweep stays, the handlers may not exist. And last, the walk shown to see an `except*` too.
    """
    source_path = api_module.__file__
    assert source_path is not None, (
        "`agl.api` reports no source file, so there is nothing here to parse. This test reads the "
        "module's own text and asserts about it; it cannot be run against an import alone"
    )
    module = Path(source_path)
    tree = ast.parse(module.read_text(encoding="utf-8"))

    handlers = _handlers(tree)
    assert not handlers, (
        f"{module.name}:{handlers[0].lineno} catches {_caught(handlers[0])}, and this module may "
        f"not catch anything at all ({len(handlers)} handler(s) here in total). `Stop` descends "
        f"from `AglError`, so a handler on the base catches a workflow's deliberate end with it, "
        f"and `cli/exit_codes.exit_status` then answers 6 or 70 for a run whose contract promises "
        f"7. Re-raising is not an exemption: `except AglError: raise` changes no behaviour today "
        f"and is one edit - a `raise ... from error`, an `.add_note()`, a log line - from turning "
        f"a workflow's `ReviewNotConverging(Stop)` into something else on the way out, after which "
        f"the exit code is right by accident. Catching `Stop` first is not the fix either. What "
        f"this module does instead is nothing, so a workflow's exception leaves `api.run` as the "
        f"object it raised, with its own traceback under it, and neither module ever learns what "
        f"`ReviewNotConverging` is. The `try`/`finally` that sweeps the leases and the `async "
        f"with` around the terminal both stay: a `finally` sees no exception and names no class, "
        f"and `Terminal.__aexit__` is annotated `-> None` on the port, so suppressing would mean "
        f"returning something truthy and `mypy --strict` is a gate. The rule is about the word "
        f"`except` and about nothing else. `tests/test_api.py`'s `assert caught.value is "
        f"raised[0]` is the behavioural half of it - identity, not class - and a handler that "
        f"re-raises the same object passes that one; this is the half that does not"
    )

    nodes = sum(1 for _ in ast.walk(tree))
    assert nodes >= NODES_TODAY, (
        f"{module} parsed to {nodes} AST nodes and held 1,279 when this was written. "
        f"{NODES_TODAY} is a floor rather than a measurement, so reaching it means something "
        f"stopped parsing, or this is not the module it is meant to be reading - not that "
        f"somebody wrote less code. The assertion above is silent about a file with nothing in it"
    )

    sweeps = sum(1 for node in ast.walk(tree) if isinstance(node, ast.Try | ast.TryStar))
    assert sweeps >= SWEEPS_TODAY, (
        f"{module} holds {sweeps} `try` statement(s) and held {SWEEPS_TODAY} when this was "
        f"written, in `_walked` - the tail `run` and `resume` share - a `finally` releasing the "
        f"integration leases the workflow was still holding. A `try` is legal here and a handler "
        f"is not - that "
        f"is the whole distinction this file exists to hold, and this assertion is its witness. If "
        f"a sweep genuinely went away, lower `SWEEPS_TODAY`. Do not reconcile the two by making "
        f"the assertion above forbid `ast.Try`: that fails against the correct source"
    )

    assert _handlers(ast.parse(EXCEPT_STAR)), (
        "an `except*` clause did not parse to an `ast.ExceptHandler` on this interpreter, so the "
        "walk above is blind to the second spelling and the first assertion is weaker than it "
        "reads. `except*` produces an `ast.TryStar` whose `handlers` are ordinary `ExceptHandler` "
        "nodes (PEP 654); if that has changed, this file needs a second node type, not a rewrite"
    )


def _handlers(tree: ast.AST) -> list[ast.ExceptHandler]:
    """Every `except` clause in `tree`, whichever of the two statements wrote it.

    `ast.Try` and `ast.TryStar` both hold their clauses in `handlers` as `ast.ExceptHandler`, so
    one walk for that node type is the whole scan and neither statement is named anywhere in it. A
    `try` with only a `finally` produces none, which is the case this file is careful to allow.
    """
    return [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]


def _caught(handler: ast.ExceptHandler) -> str:
    """What one clause names, as a reader will find it on the line, for quoting in the failure.

    A bare `except:` names nothing, and rendering it as an empty string would print a sentence with
    a hole in it, so it is spelled as what it does instead - and what it does is the widest catch
    of the lot.
    """
    return "everything" if handler.type is None else ast.unparse(handler.type)
