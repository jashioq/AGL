"""The target, the two children that land into it, and the collision every conflict here is made of.

Split out of `integration.py` so that both halves of that suite build their situations the same
way. There is only one situation: §3.4's merge train, which is a run's own workspace with children
landing into it one at a time. That is what `open_a_target_and_two_children` makes, and what
`hold_a_target` drives one step further into the state the conflict protocol is about.

**Everything here is `_workspace_files`' vocabulary rather than a parallel set of its own.** The
names, the files, the bodies and the one commit helper are that module's, because a suite for
`Integrator` needs exactly what a suite for `History` needed - two isolated places, some work
recorded in them, and no idea what a line of work is made of - and a second set of constants would
be a second thing to keep in step. That module argues why writing into `Workspace.path` is the
port's own invitation rather than a backdoor, and the argument carries here unchanged: making a
workspace dirty is still the only vocabulary either port offers, and landing work still needs work
to land.

## The target is the run's own workspace, addressed by `None`

Not an arbitrary choice of two available ones. §3.9 lands children into the run's own `_base`
checkout, and `run.integrate()` is the only caller of this port, so the pair below is the pair the
framework actually forms. It also keeps the suite honest about a thing that is easy to get wrong
from a diagram: source and target are two isolated places over one repository, not two repositories
and not two names for one place.

## A conflict is built out of two children creating one file

The port gives no way to declare a conflict, so a suite has to cause one, and it has to cause one
that no honest implementation can combine. Two children each create the same path, with contents
sharing not one line, and neither of them existed in the state both were cut from. There is no
combination of those two states that is anybody's answer: an implementation that returns a head
here has picked a side, which is precisely what §3.4 forbids - "not resolved by guessing" - and
the assertion in `hold_a_target` says so where it happens.

`body` derives every line from its marker, so the two versions differ everywhere rather than in one
place. That is the point: a heuristic combining two files that agree on most lines is doing its job,
and a suite that leant on one would be asserting a threshold nobody specified.
"""

from dataclasses import dataclass
from typing import Final

from agl.ports.integration import IntegrationOutcome, Integrator
from agl.ports.workspace import Workspace, WorkspaceProvider

from ._workspace_files import (
    ALPHA,
    BETA,
    CHILD,
    LABEL,
    SIBLING,
    TRACKED,
    assert_absent,
    body,
    read,
    record,
    write,
)

# The two states of one file that cannot be combined, and the file they are both of. Written by two
# children of one run, neither of which has ever seen the other's - which is an ordinary afternoon,
# and is what the gate and the conflict screen exist for.
CHILD_WORK: Final = body("the child's own work")
RIVAL_WORK: Final = body("the sibling's own work, sharing not one line with the child's")


@dataclass(frozen=True, slots=True)
class HeldTarget:
    """A target left mid-landing, and what it has to look like again once the hold is released.

    Handed back by `hold_a_target` so that a test can say "put it back where it was" without
    re-deriving where that was. The two recorded values are taken *after* the first child landed
    and before the second one collided, because that - and not the state the run started in - is
    what `abort` promises to restore.
    """

    target: Workspace
    """The run's own workspace, held mid-landing and owing a `retry` or an `abort`."""

    outcome: IntegrationOutcome
    """The conflicted outcome that put it there, with the `Conflict` a workflow would screen."""

    head: str
    """Where the target was before the landing that conflicted."""

    contents: str
    """What `TRACKED` held there - the first child's work, which the second one collided with."""


async def open_a_target_and_two_children(
    provider: WorkspaceProvider, base: str
) -> tuple[Workspace, Workspace, Workspace]:
    """The shape of every integration in AGL: a run's own workspace, and two children of it.

    All three cut from one base, because that is what a run does and because two children that
    never shared a state would have nothing to collide over. The guard is `_workspace_files`'
    reason: a fixture may hand over somebody's real project, and a test asserting that a file
    *arrived* in the target is wrong about one that was already there.
    """
    target = await provider.open(LABEL, None, base)
    child = await provider.open(LABEL, CHILD, base)
    sibling = await provider.open(LABEL, SIBLING, base)
    for workspace in (target, child, sibling):
        assert_absent(workspace, TRACKED, ALPHA, BETA)
    return target, child, sibling


async def hold_a_target(
    integrator: Integrator, provider: WorkspaceProvider, base: str
) -> HeldTarget:
    """Land one child, collide the next one with it, and hand back the hold that leaves.

    The merge train in four lines. Two children create one file with contents that agree nowhere;
    the first lands, and the second cannot. What comes back is the state §3.4 leaves behind: the
    target held mid-landing, owing a `retry` or an `abort`, with a `Conflict` for the workflow's
    own screen.

    The two assertions on the way through are about the implementation and not about the fixture,
    and they are here rather than in each test because every test in the conflict half of the suite
    starts by needing this state to exist. A failure in either of them names what it is: an
    implementation that cannot land the first child at all, or one that combined two files sharing
    no line and called it a landing.
    """
    target, child, sibling = await open_a_target_and_two_children(provider, base)
    write(child, TRACKED, CHILD_WORK)
    await record(child, "the child's own work")
    write(sibling, TRACKED, RIVAL_WORK)
    await record(sibling, "the sibling's own work")

    first = await integrator.land(child, target)
    assert first.conflicted is False, (
        f"landing the first child's work into a target that has none reported a conflict: "
        f"{first.conflict}. Nothing has collided yet - this is the state every conflict in this "
        f"suite is built on, and a suite cannot ask about a hold it was never able to create"
    )
    settled = await target.head()
    assert read(target, TRACKED) == CHILD_WORK, (
        "the first child's work is not in the target after a landing that reported no conflict, "
        "so there is nothing there for the second child to collide with"
    )

    outcome = await integrator.land(sibling, target)
    assert outcome.conflicted is True, (
        f"two children each created {TRACKED} with contents sharing not one line, and landing the "
        f"second one reported success with head {outcome.head!r}. There is no combination of "
        f"those two states that is anybody's answer, so an implementation that produced one "
        f"resolved by guessing - which is the one thing §3.4 says a conflict may never be"
    )
    return HeldTarget(target=target, outcome=outcome, head=settled, contents=CHILD_WORK)
