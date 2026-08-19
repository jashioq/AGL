"""The AglError hierarchy, organised by meaning, with the exit-code mapping as data.

Every error AGL raises on purpose is an `AglError`. Adapters translate what they catch - a
`CalledProcessError`, an `OSError`, a vendor exception - into one of these at their boundary,
so nothing above an adapter ever handles anything else: a workflow catches
`UpstreamUnavailable`, never whatever the thing underneath happened to throw.

Exit codes are public API - a script branches on them - so the mapping is data, in exactly one
place, and this is it: `EXIT_CODES`. It sits beside the classes so the layer that defines an
error also states what it costs, and so nothing has to import `cli` to know. `cli/exit_codes.py`
re-exports these two names and adds nothing of its own; what to do with an exception that is
*not* an `AglError` is that module's decision, not this one's.

Resolution walks the class tree instead of looking up the exact class, because workflows
subclass `Stop` with reasons of their own (`ReviewNotConverging`) and those subclasses must
exit 7 without appearing in any table. Call `exit_code_for`; never index `EXIT_CODES` directly.

    AglError                             (unmapped: resolves to 70 - see InternalError)
    |-- InputError               ->  2
    |-- NotFoundError            ->  3
    |-- ConflictError            ->  4
    |-- DeniedError              ->  5
    |-- UpstreamError            ->  6
    |   |-- UpstreamUnavailable        inherits 6
    |   `-- UpstreamUnexpected         inherits 6
    |-- Stop                     ->  7
    `-- InternalError            -> 70

`DeniedError` is the one name that differs from the plan, which calls it `PermissionError`.
It is renamed because that is a builtin, and the collision is not merely cosmetic: an adapter
that imports the plan's name and then writes `except PermissionError` to translate an OS
permission failure silently stops catching the OS error and starts catching an AGL error that
is never raised there, letting the real one escape untranslated. The plan's name is worth less
than that trap costs.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

__all__ = [
    "EXIT_CODES",
    "AglError",
    "ConflictError",
    "DeniedError",
    "InputError",
    "InternalError",
    "NotFoundError",
    "Stop",
    "UpstreamError",
    "UpstreamUnavailable",
    "UpstreamUnexpected",
    "exit_code_for",
]


class AglError(Exception):
    """Base of every error AGL raises deliberately. Do not raise it directly.

    Choose the subclass by what the *reader of the exit code* should do about it, not by
    which component noticed: the same missing directory is an `InputError` when the user
    named it and an `InternalError` when we are the ones who created it.

    A bare `AglError`, or a subclass on a branch nobody mapped, resolves to 70 (see
    `InternalError`): arriving at the top of the CLI with no decided meaning is our bug.
    """


class InputError(AglError):
    """What the caller supplied cannot be used, and nothing was attempted.

    Bad flags, a config file that is malformed or unreadable, a setting whose value is out
    of range, a run label or namespace carrying characters that are not filesystem- and
    git-ref-safe, a workflow parameter that is missing or of the wrong type.

    Against `NotFoundError`: this is input we could not make sense of; that is input we
    understood perfectly and then could not find.
    """


class NotFoundError(AglError):
    """The caller named something well-formed that does not exist.

    A run label with no record under `AGL_HOME`, a workflow name no installed package
    registers, a project or base ref that is not in the repository.

    Not for a thing that exists but is unusable: that is `ConflictError` if something else
    holds it, `InputError` if the name itself was wrong.
    """


class ConflictError(AglError):
    """The world already holds something this operation would have to take or overwrite.

    The run label is in use, `agl/<label>` already exists as a git ref, another process
    holds the run's lock or the integration lease on a target.

    Nothing has been changed when this is raised - the caller picks another name, waits, or
    clears the old run. It is the exact mirror of `NotFoundError`.
    """


class DeniedError(AglError):
    """The operation is well-formed and possible, and something refused to allow it.

    Policy refused (a role asked for a tool or a model the configuration forbids; an agent
    lacks a capability the role requires), or the far side refused on authorisation (a
    remote rejected the push, an API answered "not permitted", the filesystem refused the
    write).

    Refusal, not absence: something reachable said no. If nothing answered at all, that is
    `UpstreamUnavailable`.

    Named `DeniedError` rather than the plan's `PermissionError` so that the builtin of that
    name stays usable at every call site - see the module docstring.
    """


class UpstreamError(AglError):
    """Something outside AGL was asked to do work and no usable answer came back.

    Raise one of the two subclasses below; this class exists to be caught. Both exit 6, so a
    caller that does not care which it was catches this and a script still sees one code.
    """


class UpstreamUnavailable(UpstreamError):
    """It could not be reached, or could not start at all.

    The agent backend cannot open a session, its CLI is not on `PATH`, `git` cannot reach the
    remote or reports the directory is not a repository, the build command cannot be run.

    Nothing happened on the far side, so the same call may well succeed later.
    """


class UpstreamUnexpected(UpstreamError):
    """It answered, and the answer is not something we can act on.

    An agent finished with no reporting-tool payload, or one that does not match the shape
    the tool declared; `git` printed output the adapter cannot parse; a subprocess exited
    with a status the adapter has no meaning for.

    The far side is working - our understanding of it is what failed - so retrying the same
    call unchanged tends to produce the same answer.
    """


class Stop(AglError):
    """End the run deliberately. Nothing is broken; there is simply nothing more to do.

    Everything already persisted stays, and a resume continues from where it stopped. Raise
    it when the work is genuinely over, or genuinely needs a person: a review loop that is
    not converging, a backlog with nothing left to pick up.

    It carries a message and nothing else, on purpose - no reason code, no category, no
    status - because the framework has no business defining a vocabulary of reasons that
    every workflow would then have to conform to. Workflows subclass it under their own
    names (`ReviewNotConverging`, `BacklogStalled`), and those subclasses exit 7 as well,
    which is how a script tells "needs you" (7) from "broken" (6, 70).

    It is an `AglError`, so a broad `except AglError` catches it too: anything that means to
    tell a deliberate end from a failure - the CLI's top-level handler, a retry loop in a
    workflow - has to catch `Stop` first, or it will report finished work as broken.

    Defined here rather than in `sdk/` because `ports` may not import `sdk`; `sdk/workflow.py`
    re-exports it, and that is where a workflow author imports it from.
    """


class InternalError(AglError):
    """AGL is broken: an invariant we alone control does not hold.

    A journal entry whose fingerprint cannot be recomputed, a state we thought unreachable,
    a service missing from a bundle the container is supposed to have built whole.

    Never for anything the user, the filesystem, or an upstream did - if the cause is outside
    our own code, one of the other subclasses says so far more usefully. Exit 70 reads as
    "file a bug", so raising this for a user's typo sends the reader hunting in the wrong
    codebase.
    """


# The one exception -> exit-code table in the codebase, keyed by the class that *introduces* a
# code. Subclasses inherit theirs through `exit_code_for`, which is why UpstreamUnavailable and
# UpstreamUnexpected are deliberately absent - they resolve to their parent's 6 - and why a
# workflow's own Stop subclass resolves to 7 without anybody editing this. The codes are public
# API: a number here never changes meaning, and a new meaning takes a new number.
EXIT_CODES: Final[Mapping[type[AglError], int]] = MappingProxyType(
    {
        InputError: 2,
        NotFoundError: 3,
        ConflictError: 4,
        DeniedError: 5,
        UpstreamError: 6,
        Stop: 7,
        InternalError: 70,
    }
)


def exit_code_for(error: AglError | type[AglError]) -> int:
    """The process exit code for an error, resolved through the class tree.

    Takes an instance or a class, and walks the MRO to the nearest class `EXIT_CODES` maps -
    so a workflow's `ReviewNotConverging(Stop)` gets 7 while appearing in no table. Always
    call this: a direct `EXIT_CODES[type(err)]` raises `KeyError` on precisely the subclasses
    the hierarchy exists to allow.

    An `AglError` on a branch nothing maps - including a bare `AglError` - resolves to
    `InternalError`'s code, because an unmapped branch means the hierarchy grew and this table
    did not, which is our bug, which is what 70 says. That is deliberately not an exception:
    this runs on the way out of a failure, and the path that reports a failure must not become
    one. Exceptions that are not `AglError` are `cli/exit_codes.py`'s problem, not this one's.
    """
    cls = error if isinstance(error, type) else type(error)
    for ancestor in cls.__mro__:
        code = EXIT_CODES.get(ancestor)
        if code is not None:
            return code
    return EXIT_CODES[InternalError]
