"""The error hierarchy's contract: every branch has an exit code, and subclasses inherit it.

Exhaustiveness is checked by walking the class tree, never by listing it: a list is the thing
that goes stale the day someone adds a branch. The published numbers are the one thing pinned
by hand, on purpose - they are the API a script branches on, so a change to one should have to
be typed twice.
"""

from typing import cast

import pytest

from agl.ports import errors
from agl.ports.errors import (
    EXIT_CODES,
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
    exit_code_for,
)


class ReviewNotConverging(Stop):
    """A workflow's own reason to stop - the case a table keyed on the exact class fails."""


class _StopSubSubclass(ReviewNotConverging):
    """Two levels down, to show resolution walks the MRO rather than checking one parent."""


class _UnmappedBranch(AglError):
    """A new branch of the hierarchy that nobody remembered to add to the table."""


def _error_classes() -> list[type[AglError]]:
    """Every class in the hierarchy that agl.ports.errors itself defines, `AglError` included.

    Discovered by walking `__subclasses__`, so a class added to the module is covered the
    moment it exists. The `__module__` filter keeps the workflow-style subclasses defined
    above - and any a later stage defines anywhere - out of the module's own exhaustiveness.
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
        (cls for cls in seen if cls.__module__ == AglError.__module__),
        key=lambda cls: cls.__name__,
    )


def test_every_error_class_in_the_module_has_a_mapped_ancestor() -> None:
    """Exhaustiveness: no branch can be added to the hierarchy without giving it a code.

    The check is for a mapped ancestor, not merely that `exit_code_for` returns a number:
    the documented fallback answers 70 for an unmapped branch, so asking the resolver here
    would pass every class trivially. `AglError` is the one deliberate exception - it is the
    unmapped base, and the fallback test below is what pins its behaviour.
    """
    classes = [cls for cls in _error_classes() if cls is not AglError]
    assert classes, "walked the class tree and found nothing - the discovery helper is broken"
    unmapped = sorted(
        cls.__name__
        for cls in classes
        if not any(ancestor in EXIT_CODES for ancestor in cls.__mro__)
    )
    assert not unmapped, f"error classes with no exit code: {unmapped}"


def test_the_published_exit_codes_are_the_ones_scripts_branch_on() -> None:
    """Pinned by hand, deliberately: these numbers are public API, not an implementation."""
    assert exit_code_for(InputError) == 2
    assert exit_code_for(NotFoundError) == 3
    assert exit_code_for(ConflictError) == 4
    assert exit_code_for(DeniedError) == 5
    assert exit_code_for(UpstreamError) == 6
    assert exit_code_for(UpstreamUnavailable) == 6
    assert exit_code_for(UpstreamUnexpected) == 6
    assert exit_code_for(Stop) == 7
    assert exit_code_for(InternalError) == 70


def test_no_two_table_entries_share_an_exit_code() -> None:
    """One code, one meaning. Two branches landing on the same number is the accident here."""
    by_code: dict[int, list[str]] = {}
    for cls, code in EXIT_CODES.items():
        by_code.setdefault(code, []).append(cls.__name__)
    shared = {code: sorted(names) for code, names in by_code.items() if len(names) > 1}
    assert not shared, f"exit codes claimed by more than one table entry: {shared}"


def test_classes_that_resolve_to_one_code_are_one_family() -> None:
    """Inheritance is the only sanctioned way to share a code.

    `UpstreamUnavailable` and `UpstreamUnexpected` both answer 6 because they are both
    `UpstreamError`s - a caller catching the parent gets one code for both, which is the
    point. Two *unrelated* branches arriving at the same number is the thing that must fail,
    and this catches it whether the second one is mapped in the table or reaches the code
    through a different ancestor.
    """
    by_code: dict[int, list[type[AglError]]] = {}
    for cls in _error_classes():
        if cls is not AglError:
            by_code.setdefault(exit_code_for(cls), []).append(cls)
    for code, classes in by_code.items():
        root = min(classes, key=lambda cls: len(cls.__mro__))
        strays = sorted(cls.__name__ for cls in classes if not issubclass(cls, root))
        assert not strays, (
            f"exit {code} is reached from unrelated branches: "
            f"{strays} are not subclasses of {root.__name__}"
        )


def test_the_upstream_pair_inherits_six_instead_of_repeating_it() -> None:
    """The one intended duplicate, and the shape that makes it intentional rather than luck."""
    assert EXIT_CODES[UpstreamError] == 6
    assert UpstreamUnavailable not in EXIT_CODES
    assert UpstreamUnexpected not in EXIT_CODES
    assert exit_code_for(UpstreamUnavailable) == exit_code_for(UpstreamUnexpected) == 6


def test_a_workflow_subclass_of_stop_still_exits_seven() -> None:
    """The case the plain table gets wrong, which is the whole reason `exit_code_for` exists."""
    assert exit_code_for(ReviewNotConverging) == 7
    assert exit_code_for(ReviewNotConverging("no progress in three rounds")) == 7
    assert exit_code_for(_StopSubSubclass()) == 7
    with pytest.raises(KeyError):
        EXIT_CODES[ReviewNotConverging]


def test_exit_code_for_takes_an_instance_or_a_class() -> None:
    """Callers hold instances (`except AglError as err`); tests and tables hold classes."""
    assert exit_code_for(NotFoundError("no run named 'x'")) == exit_code_for(NotFoundError)
    assert exit_code_for(Stop("done")) == exit_code_for(Stop)


def test_an_unmapped_branch_resolves_to_the_internal_error_code() -> None:
    """The documented fallback: an unmapped branch means the table went stale, which is a bug.

    It answers rather than raising, because this runs on the way out of a failure and the
    path that reports one must not become one.
    """
    assert exit_code_for(_UnmappedBranch()) == EXIT_CODES[InternalError]
    assert exit_code_for(AglError("raised with no decided meaning")) == EXIT_CODES[InternalError]


def test_every_error_class_is_exported() -> None:
    """`cli/exit_codes.py` and `sdk/workflow.py` are pure re-exports over this module.

    A class missing from `__all__` is a class those facades will not carry, and a name left
    in `__all__` after a rename breaks `from ... import *` at whichever stage tries it.
    """
    defined = {cls.__name__ for cls in _error_classes()}
    exported = set(errors.__all__)
    assert defined - exported == set(), f"error classes missing from __all__: {defined - exported}"
    assert exported - defined == {"EXIT_CODES", "exit_code_for"}, (
        f"__all__ names something the module does not define: {exported - defined}"
    )


def test_the_table_cannot_be_mutated_at_runtime() -> None:
    """It is data, and it stays one table - not one table plus whatever a caller bolted on."""
    with pytest.raises(TypeError):
        cast(dict[type[AglError], int], EXIT_CODES)[InputError] = 99
    assert EXIT_CODES[InputError] == 2
