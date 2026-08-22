"""One table, consumed - and the one decision this module makes on top of it.

Three properties carry this file.

**The re-exported names are the port's own objects**, asserted by identity rather than by value. A
copy of `EXIT_CODES` would compare equal on the day it was made and would then be a second table,
free to drift from the first with nothing to notice; a copy of `exit_code_for` would answer
correctly about everything except the classes that arrived after it.

**The published numbers are pinned by hand.** They are the API a script branches on, so a change to
one should have to be typed twice - `tests/ports/test_errors.py` says the same about the table where
it lives, and this file says it again through the door `cli/` actually opens. Exhaustiveness is not
pinned by hand: the hierarchy is walked, so a branch added to `errors.py` and forgotten here fails.

**The decision is asserted structurally, not only behaviourally.** That a non-`AglError` exits 70 is
one assertion; that this module holds no table of its own is a scan of its source for an integer
literal, because "70 is not written here" is the actual claim and a passing behaviour test would go
on passing the moment somebody typed it. `KeyboardInterrupt` is settled the same way: the parameter
is annotated `Exception`, so `except BaseException` at the call site is a type error rather than a
convention, and the pair of assertions below is what makes that annotation load-bearing.
"""

import ast
import inspect
from typing import Final, get_type_hints

from agl.cli import exit_codes
from agl.cli.exit_codes import EXIT_CODES, exit_code_for, exit_status
from agl.ports import errors
from agl.ports.errors import (
    AglError,
    ConflictError,
    DeniedError,
    InputError,
    InternalError,
    NotFoundError,
    Stop,
    UpstreamError,
    UpstreamUnavailable,
    UpstreamUnexpected,
)

# Every class the hierarchy defines, and the code a script sees for it. Written out, including the
# three that inherit rather than introduce one - `UpstreamUnavailable`, `UpstreamUnexpected` and the
# unmapped base - because what a caller of this module needs pinned is the answer, not the route.
_PUBLISHED: Final[tuple[tuple[type[AglError], int], ...]] = (
    (AglError, 70),
    (InputError, 2),
    (NotFoundError, 3),
    (ConflictError, 4),
    (DeniedError, 5),
    (UpstreamError, 6),
    (UpstreamUnavailable, 6),
    (UpstreamUnexpected, 6),
    (Stop, 7),
    (InternalError, 70),
)


class ReviewNotConverging(Stop):
    """§3.1's own example of a workflow's reason to stop - in no table, and still worth 7."""


def _hierarchy() -> list[type[AglError]]:
    """Every class `agl.ports.errors` itself defines, walked rather than listed.

    The same discovery `tests/ports/test_errors.py` uses, for the same reason: a list is what goes
    stale the day somebody adds a branch. The `__module__` filter keeps `ReviewNotConverging` above,
    and any workflow's own subclass, out of the module's exhaustiveness.
    """
    seen: set[type[AglError]] = set()
    queue: list[type[AglError]] = [AglError]
    while queue:
        cls = queue.pop()
        if cls in seen:
            continue
        seen.add(cls)
        queue.extend(cls.__subclasses__())
    return sorted(
        (cls for cls in seen if cls.__module__ == AglError.__module__), key=lambda cls: cls.__name__
    )


# --- the re-export ------------------------------------------------------------------------------


def test_the_re_exported_names_are_the_ports_own_objects() -> None:
    """Not copies: a second `EXIT_CODES` is the second table this module exists not to have."""
    assert EXIT_CODES is errors.EXIT_CODES
    assert exit_code_for is errors.exit_code_for


def test_this_module_writes_no_number_of_its_own() -> None:
    """The claim "holds no table of its own", made mechanical.

    An integer literal anywhere in this module would be a code decided here rather than read out of
    `ports/errors.py` - which is how a second table starts, one number at a time. The answer for a
    non-`AglError` is `exit_code_for(InternalError)` precisely so that nothing has to be typed.
    """
    written = [
        node.value
        for node in ast.walk(ast.parse(inspect.getsource(exit_codes)))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ]
    assert not written, (
        f"agl/cli/exit_codes.py writes {written}, and it may write no number at all: the one "
        f"exception-to-exit-code table is `ports/errors.py`'s, and this module consumes it"
    )


# --- every class in the hierarchy ----------------------------------------------------------------


def test_every_published_class_resolves_to_its_published_code() -> None:
    """The numbers, through the door `cli/` opens, on an instance and on the class alike."""
    for cls, code in _PUBLISHED:
        assert exit_code_for(cls) == code, cls.__name__
        assert exit_status(cls("something happened")) == code, cls.__name__


def test_the_published_list_covers_every_class_the_hierarchy_defines() -> None:
    """Exhaustiveness by walking: a branch added to `errors.py` cannot skip the list above."""
    listed = {cls for cls, _ in _PUBLISHED}
    missing = sorted(cls.__name__ for cls in _hierarchy() if cls not in listed)
    assert not missing, f"error classes with no published code asserted here: {missing}"


def test_a_workflows_own_stop_subclass_resolves_to_seven_without_being_listed() -> None:
    """The MRO walk, from this side: 7 is how a script tells "needs you" from "broken"."""
    assert exit_status(ReviewNotConverging("two rounds and no convergence")) == 7


# --- the one decision ----------------------------------------------------------------------------


def test_an_exception_that_is_not_an_agl_error_is_our_bug() -> None:
    """The module's only decision. An adapter that failed to translate is what 70 reports."""
    assert exit_status(ValueError("something an adapter did not translate")) == 70
    assert exit_status(ValueError("x")) == exit_code_for(InternalError)


def test_an_unmapped_branch_and_an_untranslated_exception_agree() -> None:
    """One meaning for 70, arrived at from both sides - an unmapped `AglError` and no `AglError`
    at all are the same fault seen twice, and a script can act on neither differently."""

    class _UnmappedBranch(AglError):
        """A branch of the hierarchy nobody remembered to map."""

    assert exit_status(_UnmappedBranch("no code")) == exit_status(OSError("not ours to see"))


def test_a_keyboard_interrupt_is_not_this_modules_to_answer_for() -> None:
    """The decision, enforced by the annotation rather than by a sentence.

    `KeyboardInterrupt` and `SystemExit` are `BaseException`, so the `except Exception` a top-level
    handler writes never sees one and the interpreter's own ending stands: `SIG_DFL` restored and
    `SIGINT` re-raised, so the process dies of the signal instead of exiting with a number that
    merely looks like it. Passing one here is a `mypy --strict` error at the call site.
    """
    assert get_type_hints(exit_status)["error"] is Exception
    assert not isinstance(KeyboardInterrupt(), Exception)
    assert not isinstance(SystemExit(), Exception)
