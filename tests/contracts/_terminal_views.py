"""What this suite puts in front of a terminal - four views - and the answer responding produces.

A contract suite has one knob per implementation and builds everything else itself (`store.py`
argues that at more length), so every screen below is assembled out of the port's own component
types and none of it comes from an implementer. There is no styling to pick, no size to choose and
no layout to describe: `Screen`, `Rows`, `Row`, `Text`, `Choice` and `TextInput` are the whole of
what a view is, and drawing one is `adapters/`'.

**Every view takes its data as parameters and none of them closes over anything.** `show` registers
the function *and its arguments* and invokes it again every frame, so a suite whose views carried
their own data would exercise the registration and never the arguments - and two tests here turn on
an argument being mutated long after `show` was called.

**The interactive view offers both kinds of response**, as §3.7's own approval screen does. `Choice`
carries the value that picking it produces and `TextInput` carries the function that turns what was
typed into one, and those are two routes to a single `T`. A terminal that handles one and not the
other is a terminal half the framework's screens cannot use.

**The lambda in `maps` is rebuilt on every invocation and is excluded from comparison.** That is
what makes two independently built frames of one interactive view compare equal, and one test below
depends on it out loud: "two `show` calls are two registrations" is only worth asserting because two
identical calls produce screens nothing can tell apart.

`5` and `10` are §3.7's own numbers - an agent question and a merge conflict - and they are here as
two integers that differ, never as a vocabulary. The port refuses named levels because `MEDIUM` and
`HIGH` would encode one workflow's concepts; this suite refuses them for the same reason and would
pass just as well on `1` and `2`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from agl.ports.terminal import Choice, Row, Rows, Screen, Text, TextInput


@dataclass(frozen=True, slots=True)
class Approval:
    """§3.7's own answer type, in shape: what responding to one of these screens produces.

    Frozen, so two of them built from the same parts compare equal and a test can say *which*
    answer came back rather than only that something did. `label` is the question it came from -
    every interactive view here is parametrised by one - so an answer that reached the wrong `show`
    call says so instead of being indistinguishable from the right one.
    """

    label: str
    """The question this answer came back from."""

    said: str
    """What the response produced: `APPROVED` from the choice, or whatever was typed."""


# The two responses `question` offers, in the order it offers them, because a driver names a
# response by position and a test that wrote `0` and `1` would be naming nothing a reader can see.
APPROVE: Final = 0
SAY_MORE: Final = 1

APPROVED: Final = "approved"
"""What the `Choice` carries. `Choice.value` *is* the answer, so this is the whole of it."""

TYPED: Final = "not yet - land the other one first"
"""What a person types into the `TextInput`, in the one test that has them type."""

# The options `offer` is given, in the one test that grows a view's responses after showing it.
STANDING: Final = "the option the view was shown with"
GROWN: Final = "the option that arrived after it"

# The questions. Sentences rather than tokens, because every one of them ends up in a failure
# message saying which screen was displayed when another one should have been.
EARLY: Final = "the question that was asked first"
LATE: Final = "the question that was asked second"
LAST: Final = "the question that was asked third"
URGENT: Final = "the conflict holding the merge queue"

# The dashboards.
RUNNING: Final = "two children running"
LANDED: Final = "one child landed, one still running"

# §3.7's board, and the activity lines its own example shows.
TICKET: Final = "T-01"
OTHER: Final = "T-02"
READING: Final = "Read: connectors/api/backend.ts"
EDITING: Final = "Edit: domain/usecase.kt"

# §3.7's two priorities: an agent question and a merge conflict.
AGENT: Final = 5
CONFLICT: Final = 10


def dashboard(line: str) -> Screen:
    """A passive screen with one line on it, annotated the way §3.7 annotates a dashboard.

    `Screen` and not `Screen[None]`: PEP 696's default is what makes the bare spelling mean "returns
    nothing", and a suite that wrote the parameter out would be exercising a spelling no workflow
    author uses. Empty `responses` is what the terminal actually dispatches on, and it is empty
    here because a view with nothing to answer is what a dashboard is.
    """
    return Screen(line)


def board(rows: Mapping[str, str]) -> Screen:
    """§3.7's own board, over a mapping the caller keeps a reference to.

    This exists for one test: `show` registers the function and its arguments, so mutating the
    mapping afterwards reaches the screen with no second `show` and no notification of any kind.
    `dashboard` could not show that - a `str` argument cannot be mutated - and a view that took a
    mapping and did not read it every time would not either.

    Rows in the mapping's own order, because sorting is the view's business and §3.7's purity rule
    is about how much of it there is. An empty activity is an ordinary cell: `Text`'s docstring says
    a blank one is the honest thing to show for a ticket with no run behind it yet.
    """
    return Screen(Rows([Row(name, activity) for name, activity in rows.items()]))


def question(label: str) -> Screen[Approval]:
    """§3.7's approval screen: a body to read, a choice to pick, and a field to type into.

    Both response kinds on one screen, because that is what §3.7's example does and because they
    are the two ways a `T` is produced. The `maps` lambda closes over `label`, so the answer names
    the question it came from however it was given - which is how a test tells an answer that
    reached the right `show` call from one that reached any other.

    A fresh lambda is built here on every invocation, and `TextInput.maps` is excluded from
    comparison, so two invocations with the same `label` compare equal. That is not incidental: it
    is what lets a redraw loop skip the write, and it is what makes "two identical `show` calls are
    still two registrations" a claim worth pinning rather than a tautology.
    """
    return Screen(
        body=Text(label),
        responses=[
            Choice("Approve", value=Approval(label=label, said=APPROVED)),
            TextInput("Say more", maps=lambda typed: Approval(label=label, said=typed)),
        ],
    )


def offer(label: str, options: Sequence[str]) -> Screen[Approval]:
    """An interactive screen whose *responses* come from a live argument rather than its body.

    The interactive half of what `board` does for the slot, and the sharper half: a response that
    only exists after the argument was mutated cannot be picked by a terminal holding a `Screen`
    value from registration time, and can be picked by one that invokes the view again. It needs no
    driver to report anything - which response was picked is visible in what `show` returns.
    """
    return Screen(
        body=Text(label),
        responses=[Choice(option, value=Approval(label=label, said=option)) for option in options],
    )
