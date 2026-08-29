"""`run.terminal`, the context `api.run` opens around a workflow, and the two re-export facades.

Wiring, and this suite is written as wiring: `tests/contracts/terminal.py` already pins the
port against all three implementations, `tests/adapters/test_rich_terminal*.py` pin the redraw loop,
the diff, the slot, the queues and preemption, and none of that is re-proved here. What is left is
the four seams that only exist above the adapter, and each of them is a place where a plausible
implementation would pass every existing test.

**`run.terminal` is the bundle's own object.** Asserted by identity, because that is the only form
of the claim with teeth: a `Run` that built or wrapped a terminal of its own would satisfy every
`isinstance` and every "can it show" check, and would be a different object in every namespace.

**A child reaches the same one.** A single answerer is assumed, and the argument is that this
is structural rather than maintained - `_child` copies `services` across, so there is exactly one
terminal in a run tree and no line that could make a second. A terminal per `Run` gives a run with
four children five slots and five sets of queues, four of them drawing over each other; every test
in the adapter suite passes on such a build, because each of the five works perfectly alone.

**The context is genuinely open around `wf.fn`, and around nothing else.** `ports/terminal.py`
makes `show` outside the context an `InternalError`, so until the context was opened here every
screen in a real run raised. Three assertions, because each of the other two is satisfied by a
build that gets the third wrong: it is open while the workflow runs, it is shut when `api.run`
returns, and it was never entered at all by a run that died before the workflow - which is where
the `async with`'s placement after the record and after `_base` becomes observable.

**And the same three lines are asserted of `api.resume`, which is the other half of this file.**
The hazard, in as many words: "`api.resume` needs `async with services.terminal` exactly as
`api.run` does, and nothing in the repository would notice its absence" - because no test drove a
`show` through an `api` entry point at all until this file, and every SDK terminal test builds its
own `Run`, where the context never comes into it. That is the shape of the hole rather than one
instance of it, so what closes it is one test *per entry point* that goes red when the line is
deleted: `showing` is driven through `api.run` above and through `api.resume` below, and both were
checked by deleting the line and watching them fail. A resumed run shows the same screens the run
showed, and there is nothing weaker than a `show` that can tell whether a terminal was entered.

**A view's arguments are registered, not evaluated.** The port promises that `show` keeps the
function and its arguments and that the loop invokes it again per frame, which is what makes
`Text(run.activity)` live and what lets a workflow pass the live dict of child runs. What this layer
could get wrong is handing the terminal something else - a `Screen` already computed, a copy of the
arguments, a wrapper that normalises them - so `_Recording` below keeps what arrived, the test
mutates the workflow's own object afterwards and invokes the view again. It is deliberately not a
redraw loop: one invocation by hand is the whole of the claim being made here.

`container.fakes()` builds a `HeadlessTerminal`, which no-ops a passive `Screen` and refuses a
`Screen[T]` with `UpstreamUnavailable`, and that is what the port-level assertions drive; the three
that count something the port does not expose substitute `_Recording` into the bundle instead.
Nothing here asks a question: an interactive screen needs somebody to answer it, and there is
nobody in a test process either.
"""

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, replace
from importlib.metadata import EntryPoint
from pathlib import Path
from types import TracebackType
from typing import Final, Self, cast

import pytest

from agl import api
from agl.config import container, registry
from agl.ports import questions as ports_questions
from agl.ports import terminal as ports_terminal
from agl.ports.errors import ConflictError, InternalError
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.terminal import Rows, Screen, Terminal, Text
from agl.ports.tree_layout import TreesRoot
from agl.ports.workspace import Workspace, WorkspaceProvider
from agl.sdk import errors as sdk_errors
from agl.sdk import questions as sdk_questions
from agl.sdk import terminal as sdk_terminal
from agl.sdk.workflow import Run, workflow

# `asyncio_mode = "strict"`, so every async test below carries its own marker.

PROJECT: Final = ProjectName("myapp")
LABEL: Final = RunLabel("auth")
SCOPE: Final = RunScope(PROJECT, LABEL)

# A resolved commit, in the shape `RunSpec.base_sha` pins. Nothing here takes a step, so it is never
# spent against a repository - `test_run_step.py` is where a base is real.
BASE: Final = "4a91c07f2b3e8d15c6a0f31d8e2b47c9a6013f5e"


@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing, and still has a params class to derive no flags from."""


# --- the views these tests show ------------------------------------------------------------------


def board(lines: list[str]) -> Screen:
    """The board, reduced to what a wiring test can assert: a table of one cell per line.

    Passive - no responses - so `HeadlessTerminal` drops it and answers `None` rather than refusing
    it, and so the mutation test below is about registration and not about anybody answering.

    It takes a `list` on purpose. The design's own example passes `runs`, the live dict of child
    `Run`s, and the whole point of the per-frame design is that arguments need not be values; a view
    here that took a tuple would be one whose argument could not be mutated to show the difference.
    """
    return Screen(Rows([ports_terminal.Row(Text(line)) for line in lines]))


def cells(screen: Screen[object]) -> list[str]:
    """The text of a `board` screen, row by row - what "reflects the mutation" reads as here."""
    assert isinstance(screen.body, Rows)
    return [cell.value for row in screen.body.rows for cell in row.cells]


# --- a recording terminal, for the one claim the headless one cannot answer -----------------------


class _Recording(Terminal):
    """A `Terminal` that keeps what `show` was handed and draws none of it.

    Substituted into the bundle with `FakeServices.with_terminal`, which swaps it in the port-typed
    bundle and in the sibling field at once. A `dataclasses.replace(harness.services, terminal=...)`
    - which is what this was, and what `tests/test_api.py` still does for its refusing workspace
    provider, that port having no sibling field - reaches only the first of the two, so
    `harness.terminal` would afterwards name the `HeadlessTerminal` this replaced.

    It is not a second headless terminal and makes no claim to be: `tests/contracts/terminal.py` is
    what says a `Terminal` behaves, and this one deliberately does not. It exists so that a test can
    ask the one question no conforming implementation exposes - *what were you given* - because both
    real implementations answer that by drawing, and a passive screen on either leaves nothing
    behind to read.
    """

    def __init__(self) -> None:
        self.shown: list[tuple[Callable[..., Screen[object]], dict[str, object]]] = []
        """One entry per `show`, holding the view and its arguments exactly as they arrived."""

        self.entered = 0
        """How many times the framework opened this terminal. The port allows one."""

    async def show[T](
        self,
        view: Callable[..., Screen[T]],
        /,
        *,
        priority: int = 0,
        **params: object,
    ) -> T:
        self.shown.append((cast("Callable[..., Screen[object]]", view), dict(params)))
        return cast("T", None)

    @property
    def pending(self) -> Mapping[int, int]:
        return {}

    async def __aenter__(self) -> Self:
        self.entered += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def redraw(self) -> Screen[object]:
        """Invoke the registered view again, with the arguments it was registered with.

        One invocation, by hand, which is the port's per-frame contract exercised once. Proving that
        a loop does this ten times a second is `tests/adapters/test_rich_terminal.py`'s job and is
        not repeated here; what this is for is that the view and its arguments survived the trip
        through `run.terminal` unevaluated.
        """
        view, params = self.shown[-1]
        return view(**params)


# --- workflows, reached through hand-constructed entry points -------------------------------------

# What each workflow saw, at module level because the workflows have to be: `EntryPoint.load`
# imports a module and reads an attribute in it, and sees no local.
answers: Final[list[object]] = []
terminals: Final[list[Terminal]] = []
live: Final[list[str]] = []


@workflow(version="1")
async def showing(run: Run[NoParams]) -> None:
    """Shows one passive board and returns, which is the whole of what `api.run` has to allow."""
    terminals.append(run.terminal)
    answers.append(await run.terminal.show(board, lines=live))


def _point(name: str, attribute: str) -> EntryPoint:
    """The `probe = "agl.workflows.probe:probe"` entry point, pointed at this module instead."""
    return EntryPoint(name=name, value=f"{__name__}:{attribute}", group=registry.GROUP)


POINTS: Final = (_point("showing", "showing"),)


def _fakes(tmp_path: Path) -> container.FakeServices:
    """End-to-end on fakes alone: no network, no git, no process, and a `HeadlessTerminal`."""
    return container.fakes(TreesRoot(tmp_path / "trees"), files={"src/a.txt": b"one\n"})


def _run(services: container.Services) -> Run[None]:
    """A root `Run` on a bundle, with no repository behind it - nothing here takes a step."""
    return Run(params=None, services=services, scope=SCOPE, base=BASE)


# --- run.terminal is the bundle's terminal --------------------------------------------------------


def test_run_terminal_is_the_object_in_the_bundle(tmp_path: Path) -> None:
    """Identity, which is the only form of this claim worth making.

    `Services.terminal` is a port-typed field and `api.run` is handed one already built, so
    `Run`'s sixth member is a read of it and not a second reference to it. A `Run` that constructed,
    wrapped or memoised a terminal of its own would pass every check that asked what type came back
    or whether it could be shown on; `is` is what says the workflow and the composition root are
    holding one object.
    """
    harness = _fakes(tmp_path)

    assert _run(harness.services).terminal is harness.services.terminal
    assert _run(harness.services).terminal is harness.terminal


def test_a_child_worktree_reaches_the_same_terminal_as_its_parent(tmp_path: Path) -> None:
    """The single answerer, asserted as the structural fact it is.

    `worktree()` cuts a child that shares this run's params, ports, counter and namespace table, so
    a child's terminal is the run's terminal - one slot, one set of queues, one display, and a
    `pending` that counts every question in the tree. This is the assertion that fails the moment
    anybody builds a terminal per `Run`: nothing in the adapter suite would notice, because five
    terminals each behave perfectly on their own and only their sum is wrong.

    Two levels, because a child that copied the bundle and a grandchild that rebuilt one would look
    identical at one level - and `_child` is the only thing that makes either.
    """
    harness = _fakes(tmp_path)
    parent = _run(harness.services)

    child = parent.worktree("T-01")
    grandchild = child.worktree("sub-b")

    assert child.terminal is parent.terminal
    assert grandchild.terminal is parent.terminal
    assert grandchild.terminal is harness.terminal


def test_two_sibling_worktrees_share_one_terminal(tmp_path: Path) -> None:
    """The other shape of the same claim, and the one the terminal's queues are actually about.

    Siblings are AGL's only real concurrency - steps serialize within a namespace, so an
    author who wants two agents running at once opens two worktrees - and two agents asking at once
    is exactly the case "a human answers one thing at a time" exists for. Two terminals here would
    queue one question each and neither would wait for the other.
    """
    parent = _run(_fakes(tmp_path).services)

    assert parent.worktree("T-01").terminal is parent.worktree("T-02").terminal


def test_the_terminal_is_a_read_and_not_a_field(tmp_path: Path) -> None:
    """A property over `services.terminal`, which is what makes the two unable to disagree.

    Not style. A field would be one object under two names on a frozen dataclass, and `_child` would
    have to copy it across in step with `services` for `run.terminal` and `run.services.terminal` to
    go on naming the same thing - a second obligation, kept by hand, whose failure is a child
    answering into a display nobody is watching. Asserted from both ends: `Run.terminal` is a
    `property` on the class, and swapping the bundle swaps what the member reads.
    """
    assert isinstance(Run.terminal, property)

    harness = _fakes(tmp_path)
    other = container.fakes(TreesRoot(tmp_path / "other"))
    run = _run(harness.services)

    assert replace(run, services=other.services).terminal is other.terminal
    assert run.terminal is harness.terminal


# --- api.run opens the context, and closes it -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_workflow_can_show_a_screen_through_api_run(tmp_path: Path) -> None:
    """The gap this closes, and it was a real one.

    `ports/terminal.py` refuses a `show` outside the context, so until `api.run` entered the
    terminal every screen in every real run raised `InternalError` - a failure invisible from the
    SDK's own suite, where a test that constructs a `Run` never goes through `api.run` at all. What
    this asserts is that the workflow got all the way through a `show` and returned: the exception
    would come straight back out of `api.run`, which catches nothing.

    `None` is asserted beside it because that is the port's passive answer and the value a workflow
    branches on nothing having received. A `show` that had been skipped, or a member that answered
    without reaching a terminal, would return `None` too - so the second assertion is that the
    terminal the workflow held is the bundle's own object, which the tests above pin from the other
    side and this one re-checks through the composition root that actually builds it.
    """
    answers.clear()
    terminals.clear()
    harness = _fakes(tmp_path)

    await api.run(harness.services, PROJECT, "showing", LABEL, (), points=POINTS)

    assert answers == [None]
    assert terminals == [harness.terminal]
    assert terminals[0] is harness.terminal


@pytest.mark.asyncio
async def test_the_terminal_is_shut_again_when_api_run_returns(tmp_path: Path) -> None:
    """The other half: a context opened and never left satisfies the test above and nothing else.

    The terminal is an async context manager precisely so there is a way to stop a redraw
    loop and hand a display back; a run that left one open would leave a person's terminal owned by
    a process that has finished with it. What is observable from here is the port's own rule - a
    `show` after the context is `InternalError` on every implementation - so that is what is asked.

    Deliberately not asserted through a flag on `HeadlessTerminal`: `_open` is that adapter's own
    state, and a test reading it would pass against a `RichTerminal` that never restored anything.
    """
    harness = _fakes(tmp_path)
    await api.run(harness.services, PROJECT, "showing", LABEL, (), points=POINTS)

    with pytest.raises(InternalError) as caught:
        await harness.terminal.show(board, lines=[])

    assert "not inside its context" in str(caught.value)


@pytest.mark.asyncio
async def test_the_terminal_is_entered_once_around_the_workflow(tmp_path: Path) -> None:
    """Once, which every implementation requires - a second `__aenter__` is refused by each.

    A `HeadlessTerminal` would have said so by raising, and a raise is a weaker assertion than a
    count: it cannot tell "entered once" from "entered zero times", which is the state this whole
    section exists to rule out. So the count is read off a terminal substituted into the bundle.
    """
    harness = _fakes(tmp_path)
    recorder = _Recording()
    services = harness.with_terminal(recorder).services

    await api.run(services, PROJECT, "showing", LABEL, (), points=POINTS)

    assert recorder.entered == 1


@pytest.mark.asyncio
async def test_a_workflow_can_show_a_screen_through_api_resume(tmp_path: Path) -> None:
    """The same gap, one entry point over - and the one that took building something to notice.

    A resumed run shows the same screens the run showed, so `api.resume` needs the `async with`
    `api.run` has; without it every `show` in a resumed run raises `InternalError` by the port's own
    rule, and the failure is invisible to every existing terminal test because those build a `Run`
    directly and never enter a context at all. This is the test that goes red when the line is
    deleted from `api.resume`, exactly as the one above goes red when it is deleted from `api.run`.

    The record is written by the first invocation, which is what makes a resume possible at all;
    everything the assertions read is cleared afterwards, so what they see belongs to the resume.
    """
    harness = _fakes(tmp_path)
    await api.run(harness.services, PROJECT, "showing", LABEL, (), points=POINTS)
    answers.clear()
    terminals.clear()

    await api.resume(harness.services, PROJECT, LABEL, points=POINTS)

    assert answers == [None]
    assert terminals == [harness.terminal]


@pytest.mark.asyncio
async def test_the_terminal_is_entered_once_around_a_resumed_workflow(tmp_path: Path) -> None:
    """Once for the resume too, which a raise cannot say and a count can.

    Both implementations refuse a second `__aenter__` while they are open, so a `HeadlessTerminal`
    would report an ordering bug by raising - but a raise cannot tell "entered once" from "entered
    zero times", and zero is the state this section exists to rule out. The recorder's count is
    reset after the first invocation so that what is counted is the resume's own entry, and the
    terminal is entered again rather than for a second time: `api.run` left its context before this
    one opened, which is the case `ports/terminal.py` deliberately leaves open.
    """
    harness = _fakes(tmp_path)
    recorder = _Recording()
    services = harness.with_terminal(recorder).services
    await api.run(services, PROJECT, "showing", LABEL, (), points=POINTS)
    recorder.entered = 0

    await api.resume(services, PROJECT, LABEL, points=POINTS)

    assert recorder.entered == 1


class _Refusing(WorkspaceProvider):
    """A provider that provisions nothing, so that `api.run` fails on its last line before the
    workflow. `tests/test_api.py` carries the same stub for the same one failure `container.fakes()`
    cannot arrange; the two teardown verbs exist only because the port has four members, and `hold`
    is granted because `api.run` takes the run's claim before the line under test."""

    async def open(self, label: RunLabel, namespace: Namespace | None, base: str) -> Workspace:
        raise ConflictError("this provider refused to provision anything, deliberately")

    async def remove(self, label: RunLabel, namespace: Namespace | None) -> None:
        raise AssertionError("nothing in `api.run` takes a workspace back")

    async def discard(self, label: RunLabel, namespace: Namespace | None) -> None:
        raise AssertionError("nothing in `api.run` deletes a line of work")

    def hold(self, label: RunLabel) -> AbstractAsyncContextManager[None]:
        return _granted()


@asynccontextmanager
async def _granted() -> AsyncIterator[None]:
    """A run claim nothing contends for - what `hold` is when the test is about something else."""
    yield


@pytest.mark.asyncio
async def test_a_run_that_fails_before_the_workflow_never_opens_the_terminal(
    tmp_path: Path,
) -> None:
    """Where the `async with` sits, asserted from the one side it is visible from.

    The terminal's context is the region in which `show` is legal, and the only thing in `api.run`
    that can `show` is the workflow - so it opens after the record and after `_base`, and a run that
    dies before the workflow has taken nobody's display over. Opened at the top of `api.run`
    instead, every refusal a person has to read would arrive through a redraw loop starting and
    stopping around work that drew nothing, and `RichTerminal.__aenter__` takes the console for
    real.

    A provisioning that cannot succeed is what isolates it: it is the last thing `api.run` does
    before the workflow, so a terminal entered here was entered too early by any reading.
    """
    harness = _fakes(tmp_path)
    recorder = _Recording()
    services = replace(harness.with_terminal(recorder).services, workspaces=_Refusing())

    with pytest.raises(ConflictError, match="refused to provision"):
        await api.run(services, PROJECT, "showing", LABEL, (), points=POINTS)

    assert recorder.entered == 0


# --- what reaches the terminal is the view and its arguments -------------------------------------


@pytest.mark.asyncio
async def test_show_registers_the_view_and_its_arguments_rather_than_a_screen(
    tmp_path: Path,
) -> None:
    """The per-frame design, asserted at the one seam this layer owns.

    "`show` registers the view function **and its arguments**; the terminal's redraw loop calls it
    again every frame." That is the port's promise, and what this layer could break is what it hands
    over: a `run.terminal` that evaluated the view and passed the resulting `Screen`, or that copied
    the arguments on the way past, would leave a terminal holding a value where a registration
    belongs - and every frame after the first would redraw the state the workflow had when it called
    `show`, which is the version of this bug that looks like the feature working.

    So the workflow shows a board over a list it goes on holding, the test appends to that same list
    afterwards, and the view is invoked once more by hand. The redraw loop and the diff are
    `tests/adapters/test_rich_terminal.py`'s and are not repeated: what is proved here is only that
    the terminal was handed the author's own function and the author's own object.

    The identity assertion is the sharper half. A `dict(params)` of references is what arrived; a
    deep copy, a `tuple(...)` or a rendered snapshot would all still re-invoke cleanly and would all
    show the old lines.
    """
    live.clear()
    live.append("T-01 implement")
    harness = _fakes(tmp_path)
    recorder = _Recording()
    services = harness.with_terminal(recorder).services

    await api.run(services, PROJECT, "showing", LABEL, (), points=POINTS)

    view, params = recorder.shown[-1]
    assert view is board
    assert params["lines"] is live
    assert cells(recorder.redraw()) == ["T-01 implement"]

    live.append("T-02 review")
    assert cells(recorder.redraw()) == ["T-01 implement", "T-02 review"]


# --- the two facades -----------------------------------------------------------------------------


def test_the_terminal_facade_re_exports_the_ports_objects_themselves() -> None:
    """Identity, name by name. `sdk/terminal.py` is a pure re-export facade, holding no logic.

    Equality would be satisfied by a facade that redefined `Text` as its own frozen dataclass with
    the same field - and every view built through it would then produce a `Screen` whose body no
    adapter's exhaustive `match` over `Component` could draw, which is a failure at the far end of
    the system from the file that caused it. `is` is the whole claim.
    """
    for name in ports_terminal.__all__:
        assert getattr(sdk_terminal, name) is getattr(ports_terminal, name)


def test_the_questions_facade_re_exports_the_ports_objects_themselves() -> None:
    """The same claim for `Question` and `Answer`, and here the cost of a copy is a live session.

    An adapter builds a `Question` out of what a model produced and reads back whatever the
    workflow's handler returned. A second `Answer` class defined in `sdk/` would type-check against
    a handler annotated with it and then fail whatever the adapter does to narrow what came back.
    """
    for name in ports_questions.__all__:
        assert getattr(sdk_questions, name) is getattr(ports_questions, name)


def test_the_facades_re_export_the_whole_of_each_ports_surface() -> None:
    """Every name, not a chosen subset - which is the part of "no logic" that can rot quietly.

    A curated facade is one that decided which names an author needs, and the decision would be
    found by whoever needed the missing one and reached into `agl.ports` for it, which is the exact
    thing these modules exist to prevent. Asserted as list equality so that order drifts loudly too:
    the lists are written out by hand in both modules and there is nothing else to keep them level.
    """
    assert sdk_terminal.__all__ == ports_terminal.__all__
    assert sdk_questions.__all__ == ports_questions.__all__


def test_the_facades_declare_nothing_of_their_own() -> None:
    """No alias, no wrapper, no subclass, no helper. `tests/sdk/test_services.py` asks `vars()` the
    same question of `Services`, for the same reason: "holds no logic" is a claim about what is in
    the module, and the module is the only thing that can be asked.

    `sdk/tools.py` is deliberately not held to this - it re-exports `Tool` *and* carries the
    reporting-tool declaration, and says so in its first paragraph - so this is a test about the
    three modules that are pure re-export facades and no fourth.

    **`sdk/errors.py` is compared against its own `__all__` where the other two are compared
    against their port's**, and that is the one asymmetry here. It joined late and it takes the
    `AglError` hierarchy out of `ports/errors.py` while leaving that module's exit-code table to
    `cli/exit_codes.py` - a seam the port itself draws, which is why the test above asserts whole-
    surface equality for two modules and not for three. Where that cut falls is pinned in
    `tests/sdk/test_front_door.py`, in both directions and over `ports.errors.__all__`, so a class
    added to the hierarchy and left off the facade fails there. What is asserted *here* is the
    claim this test is about and it is the same for all three: the module declares nothing beyond
    the names it re-exports.
    """
    facades = (
        (sdk_terminal, ports_terminal.__all__),
        (sdk_questions, ports_questions.__all__),
        (sdk_errors, sdk_errors.__all__),
    )
    for facade, expected in facades:
        public = {name for name in vars(facade) if not name.startswith("_")}
        assert public == set(expected)
