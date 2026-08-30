"""`ClaudeCodeRunner` against the `AgentRunner` contract, plus the clauses that suite cannot see.

The first class is the port in full: `AgentContract` with its two fixtures overridden and nothing
else touched. That suite was written against the port's docstrings and before any adapter
existed, which is the inversion `tests/contracts/` rests on and why nothing below re-asserts it.

**Six of its eight tests start a real agent, and none of them runs - anywhere, on any machine.**
Five of the six read a *model's* conduct as their evidence: that it called a tool, that it
corrected a refused call, that it ignored a repository's instructions. No free instrument can supply
that, so running them means a paid turn, and the build's rule is that no test spends tokens, ever -
"not gated, not opt-in, not 'only when you set the env var'". They are deferred to the manual QA
pass instead. The gate is delivered by the `runner` fixture handing back a runner whose `run`
skips: the criterion is "does this test start an agent", and that is a fact about the *port member*
rather than about a test's name, so no list here goes stale when a test in that suite is renamed.
`capabilities` and `check_ready` are the real thing in every case and run unconditionally - and
`check_ready` now genuinely starts a CLI on every `scripts/check`, because the far side is the
loopback described next. It used to be the one paid call in this build.

**Every test in this module points a `claude` process at a loopback**, and that is what makes the
rest of the file free. `instruments/loopback.py` binds `127.0.0.1`, answers the two paths a session
touches, and forwards nothing anywhere; a session-scoped autouse fixture in `tests/conftest.py`
exports `ANTHROPIC_BASE_URL` and `ANTHROPIC_API_KEY` at it for every test in the repository, always,
not only for the tests that spawn something. So "no test here reaches a model" is structural rather
than a promise: there is no outbound socket in the instrument, and one test below asserts the
redirection itself rather than leaving it to be believed.

That fixture was written here and later moved to `tests/conftest.py`. A module-scoped autouse
fixture protects the file it is written in and no other, so a second adapter test file inherited
nothing;
`harness` below is now an accessor onto the session's endpoint rather than a second listener. What
this file still owns is the assertion that the guard reached *it* - the endpoint the CLI is pointed
at being the same object these tests read their traffic off, which no repo-wide check can ask.

Two things follow, and both are wanted. `check_ready` is now exercised on the branch where it
**returns** - a success path this project had never observed, because the only machine that had ever
run it was logged out - and it costs nothing. And the four tests below that read a real session's
`init` now run a session **to completion**, where they used to wrap themselves in
`pytest.raises(UpstreamUnavailable)` and pass because a logged-out machine could not authenticate.
That is a failure this file has actually had: four tests were green because the harness could not
authenticate - they asserted the run would fail, and would have passed with no harness installed at
all. No test in this file passes because a run failed.

**`AGL_LIVE_AGENT=1` is still the opt-in, and it now buys something real - but only what it says.**
It gates the tests that spawn a CLI, together with `claude` being on `PATH`, and it means exactly
those two things: the binary is installed and the operator agreed to have processes started. It is
*not* an authentication gate, and there is nothing here that could make it one: the spike proved the
`init` message is byte-identical whether the far side authenticates or refuses, and `init`'s
`apiKeySource` reports `"none"` for a perfectly good subscription session (see the comment above
`_READY_PROMPT` in `runner.py`), so no free instrument can tell logged in from logged out. The skip
reasons say that and claim no more. `tests/contracts/agent.py` is written against the failure mode
where a suite passes against nothing, and a skip that reads like a pass is that failure mode wearing
a green tick.

What follows the contract subclass is what the suite lists as beyond it, in roughly its order:

  * **That the session is hermetic** (its gap 1, and gap 2 - a configuration an adapter loaded that
    the agent then ignored is invisible to it). Asserted here from the CLI's own `init` message,
    which arrives before any model call and so needs no authentication: a repository carrying the
    contract suite's poison *plus* a `.mcp.json`, a project subagent and a project slash command,
    and an `init` that registers none of them. Plus the options the real `run` actually built,
    captured on the way past rather than rebuilt by this file. And plus the composed request itself,
    read off the loopback: the poison is absent from what actually left the machine, with the
    workspace's own `CLAUDE.md` proved present as the control, which is the measurement that settled
    the question in the first place.
  * **That the workspace path never reaches a command line** (no gap of the suite's, because the
    suite chooses no hostile path). Fired first as a control, then handed to the adapter, in the
    shape `tests/adapters/test_shell_verifier.py` established.
  * **That a value which would parse as a flag is refused before anything starts** - the model, the
    CLI path, and a deny rule - which the suite cannot provoke because it supplies none of them.
  * **That every session this package opens is opened hermetically**, asserted by parsing the
    package rather than by running it, so a second session added later (a readiness probe, a
    version check) cannot quietly omit the two options whose SDK defaults are the leaky ones -
    nor name either one and hand it the leaky value, which naming alone does not rule out.
  * **That a tool call, a refusal, a handler that raises, an activity line and a question
    round-trip work at all** (its gaps 7 and 12: most of that suite is behavioural and reads a
    model's conduct as evidence). Driven offline through a scripted `Transport`, which is the SDK's
    own injection point, so the real adapter, the real SDK message parsing and the real in-process
    MCP servers all run with no CLI and no model anywhere. The handler that raises comes with a
    control that measures what the *vendor* does with one, since that is the reason AGL catches
    where it does. **This is supplementary evidence and never acceptance**: a subagent's
    own test double is exactly what `tests/contracts/` exists not to rely on, and every
    clause below that it covers is covered *again*, for real, by the gated suite above.
  * **That `stop_reason` is read honestly** (its gap 10: it cannot make a run reach a limit and has
    no second source for the fact). Every string this adapter recognises, and one it does not.

Named `test_claude_code_runner.py`, for the module it covers: `tests/` carries no `__init__.py`
(see `tests/conftest.py` for why it must not), so pytest's module names are the bare filenames and
two files of one name under different directories would collide at import.
"""

import ast
import asyncio
import ipaddress
import json
import os
import shutil
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from functools import cache
from pathlib import Path
from typing import Any, Final, NoReturn
from urllib.parse import urlsplit

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ProcessError, SdkMcpTool
from claude_agent_sdk._internal.transport import Transport

from agl.adapters.claude_code import _session, _tools
from agl.adapters.claude_code import runner as runner_module
from agl.adapters.claude_code.runner import ClaudeCodeRunner
from agl.adapters.claude_code.translate import Restraint
from agl.ports.agent import (
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Capability,
    Claude,
    ModelId,
    OpenAI,
    Restriction,
    StopReason,
    Tool,
    ToolResult,
)
from agl.ports.errors import InputError, InternalError, UpstreamUnavailable
from agl.ports.run import JsonValue
from contracts._agent_hermeticity import CONFIGURATIONS, markers_in, plant
from contracts._agent_tasks import Activity, Notes, ReporterFailed, ToolFailed, workspace
from contracts.agent import AgentContract
from instruments.loopback import DUMMY_KEY, REPLY, Loopback, wire_text

# The opt-in. It turns on the tests that spawn a real `claude` process against the loopback, and it
# does not turn on the six contract tests behind `_NeverRuns` - five of them read a model's
# conduct, which nothing free can produce, and the sixth needs a session this suite has no way to
# arrange. Two gates rather than one, because "the operator agreed to have processes started" and
# "there is a binary to start" are different facts with different fixes.
LIVE = "AGL_LIVE_AGENT"

# What a person is told when the six deferred contract tests do not run, which is always. Long on
# purpose: the whole point of this suite is that a green run means something, and a skip that reads
# like a pass is the failure `tests/contracts/agent.py` is written against.
_SKIPPED: Final = (
    "UNVERIFIED: this run did not start a real agent, so the ClaudeCodeRunner's entire run-path - "
    "the outcome, the refused tool call, the tool handler that raised, the activity, the activity "
    "reporter that raised and the poisoned repository - is unverified by this run, and by every "
    "run. DEFERRED TO THE MANUAL QA PASS, with no switch here that changes it: five of the six "
    "read a model's conduct as their evidence - that it called a tool, that it corrected a refused "
    "call, that it ignored a poisoned repository - which no free instrument can supply, so running "
    "one costs a paid turn and no test in this build spends tokens. The sixth, "
    "the activity reporter that raised, needs no conduct at all; it is deferred only because the "
    "contract suite's one knob is the runner and a real ClaudeCodeRunner reports nothing without a "
    "session, and it is asserted for real offline further down this file, against the same "
    "adapter. Run the other five by hand against an authenticated CLI, or do not believe them. "
    "What did run is everything below the contract subclass: a real CLI composing a real session "
    "against a loopback endpoint, so the options, the argv discipline, the registered tools and "
    "the request that left the machine are all asserted for real - plus the tool and activity "
    "plumbing driven offline through a scripted transport. None of that covers a model "
    "deciding anything, and this skip is not a pass."
)

# The one extra sentence a machine carrying the opt-in gets. Appended rather than folded in, because
# it is true of one reader's environment and not of the deferral itself.
_OPTED_IN: Final = (
    f" ({LIVE}=1 is set here and it did turn on the live tests further down, which spawn a real "
    f"CLI against a loopback endpoint. It does not turn these six on and no variable can: five "
    f"read a model's conduct, and a loopback answers with whatever it was told to say.)"
)

# What a person is told when the CLI itself is missing. A different gate from the one above and kept
# separate on purpose: these tests need a process that starts, composes a session and prints its
# `init` message, which costs nothing and needs no authentication, so the only thing that can stop
# them is the binary not being there at all.
_NO_CLI: Final = (
    "UNVERIFIED: the Claude Code CLI is not on PATH, so nothing here could start it and read back "
    "the session it composed. The hermeticity options, the argv discipline and the composed "
    "request are asserted against a real CLI driven at a loopback endpoint that answers out of "
    "canned data - install Claude Code and these run again, on any machine, logged in or not, "
    "because the far side is a socket this suite owns and no model is behind it."
)

# What a person is told when the CLI is there and the opt-in is not. Honest about what the opt-in
# means, which is less than an opt-in usually means: these tests spend nothing, and asking for it is
# about spawning processes on somebody's machine rather than about spending their allowance. It
# cannot be an authentication gate either - `init` is byte-identical logged in or out, and
# `apiKeySource` says `"none"` for a working subscription - so nothing here claims to know.
_NOT_OPTED_IN: Final = (
    f"UNVERIFIED: {LIVE}=1 is not set, so no `claude` process was spawned and the hermeticity "
    f"options, the argv discipline and the composed request are unverified by this run. "
    f"They cost nothing to check - the CLI is pointed at a loopback endpoint that answers out of "
    f"canned data, so no model is reached and no tokens are spent - and the opt-in is about "
    f"starting processes on this machine, not about paying for them. It says nothing about whether "
    f"the CLI is authenticated, because nothing free can: run `{LIVE}=1 pytest` on this file."
)


@cache
def _live() -> bool:
    """Whether the operator asked for `claude` processes to be spawned. Half of the live gate.

    An environment read and nothing else - deliberately, and this is the second time that has had to
    be said. It used to be this *and* `check_ready` returning, which made deciding whether to spend
    a paid turn cost a paid turn; and it never even reached that, because `_live()` awaited
    `check_ready` through `asyncio.run` from inside the loop pytest-asyncio was already running, so
    `AGL_LIVE_AGENT=1` produced six errors rather than six runs. There is nothing to probe now: the
    far side is a loopback this suite starts, so the only questions left are whether there is a
    binary (`_cli`) and whether the operator wants it started (this).

    Cached because a dozen tests ask it and the answer cannot change inside one run.
    """
    return os.environ.get(LIVE) == "1"


def _cli() -> bool:
    """Whether there is a `claude` binary to start at all. The other half, and a different fix."""
    return shutil.which("claude") is not None


@pytest.fixture
def harness(loopback: Loopback) -> Loopback:
    """*The* loopback - the session-scoped one from `tests/conftest.py` - under this file's name.

    An accessor and deliberately nothing more. The redirection this file rests on used to be a
    module-scoped autouse fixture right here, which protected this file and no other; a second
    adapter test file arrived, so it moved to `tests/conftest.py` where a module that has not been
    written yet is covered too. What did *not* move is the name: `harness` reads correctly in the
    dozen tests below that ask this object what request left the machine.

    It returns the session's endpoint rather than starting one, and that is the whole safety
    property. A second listener here would leave the CLI pointed at conftest's address while these
    tests read a different one - the failure
    `test_no_test_in_this_module_can_reach_a_paid_endpoint` catches by asserting the two are equal.
    """
    return loopback


def test_no_test_in_this_module_can_reach_a_paid_endpoint(harness: Loopback) -> None:
    """The guard, asserted rather than promised. Everything else in this file rests on it.

    A docstring saying "these tests are free" is worth nothing on the day the fixture in
    `tests/conftest.py` is edited, renamed, or quietly dropped from a reshuffle - and the failure
    would be silent, because a test that spends money looks exactly like a test that does not until
    the bill arrives. So the redirection is a checked fact: the variable the CLI reads is set, it
    names an address that is a loopback literal, and it is the address of the endpoint the tests
    here read their traffic off.

    That last clause is what stops the guard from moving out of this file and quietly stopping
    covering it. `scripts/check`'s paid-endpoint gate asks the wider question - whether a module
    added today inherits anything at all - and it cannot ask this one, because it knows nothing
    about which endpoint *these* tests read.

    `127.0.0.1` is asserted by parsing rather than by prefix, and the hostname has to be an IP
    literal: `localhost` would pass a string comparison and resolve through whatever the machine's
    resolver says it means. `ANTHROPIC_API_KEY` is checked in the same breath because an unset one
    is not a missing precaution but an active leak - see `tests/conftest.py`.
    """
    base = os.environ.get("ANTHROPIC_BASE_URL", "")
    host = urlsplit(base).hostname or ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False

    assert loopback, (
        f"ANTHROPIC_BASE_URL is {base!r}, whose host {host!r} is not a loopback address. Every "
        f"test in this file spawns or may spawn a real `claude`, and the only thing standing "
        f"between that and a paid model call is this variable pointing at a socket this suite owns"
    )
    assert base == harness.url, (
        f"ANTHROPIC_BASE_URL is {base!r} and the loopback these tests read is listening on "
        f"{harness.url!r}. A CLI pointed at some other loopback is a CLI whose requests this file "
        f"cannot read, and whatever is on that port was not started by this suite"
    )
    assert os.environ.get("ANTHROPIC_API_KEY"), (
        f"ANTHROPIC_API_KEY is {os.environ.get('ANTHROPIC_API_KEY')!r}, which the CLI treats as no "
        f"key at all: it then falls back to the operator's own OAuth bearer token and sends it to "
        f"whatever is listening on the redirected base URL. Non-empty is the whole requirement, "
        f"and it is asserted separately from the value below because emptiness is the failure mode"
    )
    assert os.environ.get("ANTHROPIC_API_KEY") == DUMMY_KEY, (
        f"ANTHROPIC_API_KEY is {os.environ.get('ANTHROPIC_API_KEY')!r}. Unset, the CLI sends the "
        f"operator's real OAuth bearer token to whatever is listening on the redirected base URL - "
        f"so this is not a second layer of protection, it is the line that keeps a live credential "
        f"off a local socket"
    )


class _NeverRuns(ClaudeCodeRunner):
    """The runner the contract suite gets: real, except that `run` skips and always skips.

    Subclassed rather than mocked, so `capabilities` and `check_ready` are the adapter's own and
    the two tests that ask them are testing the real thing. `run` skips, loudly, which puts the
    gate on the *port member that starts an agent* instead of on a list of test names - the suite's
    tests can be renamed, split or added to and this keeps deciding correctly.

    Unconditionally, because there is no condition worth writing: five of the six tests behind
    it assert a model's conduct, the only instrument that can answer is a paid one, and a test that
    spends money on a flag is still a test that spends money. They are deferred to the manual QA
    pass and the skip reason says so.

    The sixth is `test_an_activity_reporter_that_raises_ends_the_run_with_its_own_exception`, and
    it is the one clause here a free instrument could reach: it asks the agent for nothing. What
    stops it is the shape of the contract suite rather than the price of a turn - its one knob is
    the runner, and a real `ClaudeCodeRunner` handed a scripted transport is not something the
    suite has a way to build. Marking that one test by name would put a list of test names in this
    file after all, for a clause this file already asserts against the same adapter, offline, in
    `test_an_activity_reporter_that_raises_comes_out_of_this_adapters_run`. So it skips with the
    five and the skip reason says which of the two reasons applies to it.
    """

    async def run(self, *args: object, **kwargs: object) -> NoReturn:
        pytest.skip(_SKIPPED + (_OPTED_IN if _live() else ""))


class TestClaudeCodeRunner(AgentContract):
    """The port in full, against the real adapter: two of its eight tests today, and six deferred.

    Two overrides and nothing else, which is what the suite asks for. The gate lives inside the
    `runner` fixture because that is one of the two, and because the alternative - marking
    individual tests - would mean this file naming tests that belong to a suite it does not own.
    """

    @pytest.fixture
    def runner(self) -> AgentRunner:
        """The adapter, resolving `claude` from `PATH`, with `run` skipping.

        Nothing else is configured, because there is nothing else: the model, the workspace, the
        tools and the restrictions all arrive per call, and the hermeticity settings are not
        settings but obligations the adapter carries whoever built it. `check_ready` and
        `capabilities` are reached through this object exactly as they would be through a
        `ClaudeCodeRunner`, because that is what it is.
        """
        return _NeverRuns()

    @pytest.fixture
    def model(self) -> ModelId:
        """The cheapest model this adapter serves, since every live test is a one-shot errand."""
        return Claude.HAIKU


# --- Gap 1 and 2: the session the adapter actually opened, read back off the CLI's own init ------

# A project subagent, a project slash command and a project MCP server: three configuration
# channels the `init` message reports by name, which is what makes them assertable with no model
# call. The contract suite's own poison rides three channels an *agent* has to act on, and says so
# about itself - "the poison is instructions, so it only lands if the agent acts on it". These
# three land or do not land before the agent exists.
LEAKY_AGENT: Final = "agl-leaky-agent"
LEAKY_COMMAND: Final = "agl-leaky-command"
LEAKY_SERVER: Final = "agl-leaky-server"

NOTE_SCHEMA: Final[Mapping[str, JsonValue]] = {
    "type": "object",
    "properties": {"note": {"type": "string"}},
    "required": ["note"],
}

def poisoned(root: Path) -> Path:
    """The contract suite's poisoned repository, plus the three channels `init` can see.

    `plant` is imported rather than reproduced: the rows in `CONFIGURATIONS` are the fixture, this
    file has no business owning a second copy of them, and a row added there arrives here for free.
    """
    repo, _ = plant(root)
    (repo / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "agents" / f"{LEAKY_AGENT}.md").write_text(
        f"---\nname: {LEAKY_AGENT}\ndescription: planted by AGL's own test\n---\nLeak.\n",
        encoding="utf-8",
    )
    (repo / ".claude" / "commands").mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "commands" / f"{LEAKY_COMMAND}.md").write_text("Leak.\n", encoding="utf-8")
    (repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {LEAKY_SERVER: {"command": "false", "args": []}}}),
        encoding="utf-8",
    )
    return repo


def task_in(repo: Path, *, tools: tuple[Tool, ...] = ()) -> AgentTask:
    """One ordinary task in `repo`, with restrictions so the deny rules are on the wire too."""
    return AgentTask(
        instructions="Read README.md and say in one sentence what this project does.",
        workspace=repo,
        model=Claude.HAIKU,
        restrictions=frozenset({Restriction.NO_SHELL, Restriction.NO_NETWORK}),
        tools=tools,
    )


class Watched:
    """A stand-in for `query` that records what it was handed and then delegates to the real one.

    The point is that the adapter composes the session and this only *watches*. Rebuilding the
    options in this file and asserting on the rebuild would assert that this file can call
    `ClaudeAgentOptions`, which nobody doubts; capturing what `run` actually passed is the only
    version of the assertion that fails when `run` changes.
    """

    def __init__(self) -> None:
        self.options: ClaudeAgentOptions | None = None
        self.prompt = ""
        self.messages: list[object] = []

    def __call__(self, *, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        self.options = options
        self.prompt = prompt
        return self._watched(prompt, options)

    async def _watched(self, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        from claude_agent_sdk import query

        async for message in query(prompt=prompt, options=options):
            self.messages.append(message)
            yield message

    def init(self) -> Mapping[str, Any]:
        """The `init` system message's payload, or a failed assertion naming what did arrive."""
        for message in self.messages:
            data = getattr(message, "data", None)
            if getattr(message, "subtype", None) == "init" and isinstance(data, dict):
                return data
        raise AssertionError(
            f"the CLI started and never announced a session: "
            f"{[type(seen).__name__ for seen in self.messages]}. "
            f"The init message arrives before any model call, so its absence is not an "
            f"authentication problem - it is the CLI failing to start at all"
        )


@pytest.fixture
def watched(monkeypatch: pytest.MonkeyPatch) -> Iterator[Watched]:
    """Wrap the `query` the session module calls, so a run can be watched without being changed."""
    watcher = Watched()
    monkeypatch.setattr(_session, "query", watcher)
    yield watcher


async def spawn(task: AgentTask, **kwargs: Any) -> AgentOutcome:
    """Run `task` for real against the loopback, and insist that the run finished.

    This replaces a helper called `watch`, which wrapped the same call in
    `pytest.raises(UpstreamUnavailable)` and called the failure "the expected end of every run in
    this file". It was, on the machine it was written on - a logged-out one - and that is the whole
    problem: the four tests underneath it were green because the environment was broken, and would
    have been green with no `claude` installed at all. Nothing here is allowed to pass because a run
    failed, so the outcome is asserted whole. If a run legitimately cannot happen, the gates above
    skip it with a reason; there is no third option where a failure counts as evidence.

    Equality against `REPLY` and not merely `COMPLETED`: the text is what the loopback was told to
    say, so getting it back is proof the run went end to end through the harness this suite owns,
    rather than ending somewhere plausible on the way.
    """
    outcome = await ClaudeCodeRunner().run(task, **kwargs)
    assert outcome == AgentOutcome(stop_reason=StopReason.COMPLETED, text=REPLY), (
        f"the run answered {outcome!r} and the loopback was told to say {REPLY!r}, completing. "
        f"Everything this file asserts afterwards is about a session that ran; a run that ended "
        f"any other way is a failure to report and not a fixture to work around"
    )
    return outcome


@pytest.mark.asyncio
@pytest.mark.skipif(not _cli(), reason=_NO_CLI)
@pytest.mark.skipif(not _live(), reason=_NOT_OPTED_IN)
async def test_no_configuration_in_the_workspace_reaches_the_session_it_composes(
    tmp_path: Path, watched: Watched
) -> None:
    """Hermeticity through the one window that needs no model: what the CLI says it registered.

    The contract suite's own hermeticity test can only see a leak an *agent acted on*, and says so
    about itself. This one sees the leak earlier and more certainly: a project subagent, a project
    slash command and a project MCP server planted in the workspace are all things the CLI reports
    by name on its `init` message, before a model exists to ignore them.

    The run **completes**, against the loopback, and the outcome is asserted before anything here is
    read. It used to end in `UpstreamUnavailable` and this test used to require that - which meant
    it passed on a machine with no session, and would have passed on a machine with no CLI.

    **The caveat, stated so that the next reader does not "tighten" this into a flaky test.**
    `init.agents`, `init.slash_commands` and `init.skills` all come back **non-empty**, and that is
    correct rather than a leak: what is in them is the *operator's own* machine-level
    configuration, which is deliberately out of scope - AGL inherits the parent environment - and
    some of it may not even be settings discovery, since this test process is itself running inside
    a Claude Code session and a spawned CLI inherits an environment. The hermeticity claim is about
    **the target repository**, so what is asserted is that the three *planted* names are absent.
    `assert not announced["agents"]` would be asserting something never claimed, against a value
    that changes with whoever is running the suite.

    The fixture is asserted before the runner is touched, for the reason the contract suite gives
    about its own: a test whose failure mode is to pass has to prove its poison is loaded.
    """
    repo = poisoned(tmp_path)
    assert (repo / "CLAUDE.md").is_file() and (repo / ".mcp.json").is_file(), (
        "the poisoned repository was not planted, so this test proves nothing"
    )

    await spawn(task_in(repo))

    announced = watched.init()
    assert announced.get("cwd") == str(repo), (
        f"the CLI says it is standing in {announced.get('cwd')!r} and the workspace is "
        f"{str(repo)!r}: a run happening somewhere else is a run this test cannot speak for"
    )
    assert LEAKY_AGENT not in announced.get("agents", []), (
        f"the workspace's .claude/agents/{LEAKY_AGENT}.md registered a subagent for this session. "
        f"the target repo contributes source code and nothing else - setting_sources=[] is "
        f"what refuses it, and the SDK's own default for that field is None, which does not"
    )
    assert LEAKY_COMMAND not in announced.get("slash_commands", []), (
        f"the workspace's .claude/commands/{LEAKY_COMMAND}.md registered a command for this "
        f"session, so the repository got to add to what the agent can be asked to do"
    )
    servers = [entry.get("name") for entry in announced.get("mcp_servers", [])]
    assert LEAKY_SERVER not in servers, (
        f"the workspace's .mcp.json server reached the session: {servers}. Two options refuse it "
        f"and the four combinations were measured apart rather than assumed: with "
        f"setting_sources=[] the server stays out whatever strict_mcp_config says, and with "
        f"setting_sources=None it stays out only while strict_mcp_config is True. So this rule is "
        f"the second lock and not the first - which is the reason to keep setting it, since the "
        f"day setting_sources changes it is the only thing still holding"
    )
    assert sorted(servers) == ["agl"], (
        f"the session's MCP servers are {servers}, and AGL supplies exactly one: the workflow's "
        f"own tools. There were two while AGL registered an asking tool of its own; a question is "
        f"an ordinary tool a workflow declares now, so it arrives on this server with the rest"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not _cli(), reason=_NO_CLI)
@pytest.mark.skipif(not _live(), reason=_NOT_OPTED_IN)
async def test_the_options_the_run_actually_built_are_the_hermetic_ones(
    tmp_path: Path, watched: Watched
) -> None:
    """The three hermeticity settings, and the four values deliberately left off the command
    line.

    Read off what `run` passed rather than off this file's own reconstruction. Two of these have a
    leaky SDK default (`setting_sources=None`, `strict_mcp_config=False`) and one is a channel that
    exists only if something opens it (`settings`), which is why each is asserted by value rather
    than by "it was set to something".

    The run is a real one and it finishes. An options object could be captured from a run that died
    on its first message, and that is what this test used to do - so the options were asserted, the
    session was not, and a set of options the CLI would have refused would have read as a pass.
    """
    await spawn(task_in(poisoned(tmp_path)))
    options = watched.options
    assert options is not None

    assert options.setting_sources == [], (
        f"setting_sources is {options.setting_sources!r}. It has to be the empty list: None is the "
        f"SDK's default and means the CLI discovers what it likes, and it is also what the SDK's "
        f"`skills` option quietly replaces with ['user', 'project']"
    )
    assert options.strict_mcp_config is True, "strict_mcp_config defaults to False in the SDK"
    assert options.settings is None, (
        f"a settings document was passed ({options.settings!r}). --settings adds a configuration "
        f"to a session that has just been told to read none, and the only safe path is the one "
        f"that is not there"
    )
    assert options.add_dirs == [] and options.extra_args == {}, (
        f"add_dirs={options.add_dirs!r} extra_args={options.extra_args!r}: both put values on the "
        f"command line and this adapter needs neither"
    )
    assert options.permission_mode == "bypassPermissions", (
        "an unapproved tool call in any other mode waits for a person, and there is none"
    )
    assert "AskUserQuestion" in options.disallowed_tools, (
        "the vendor's own asking mechanism is left available, and it bypasses AGL's terminal "
        "entirely: what it puts up is drawn by the CLI, to whoever is at *its* stdout, and no "
        "workflow sees the question or the answer. That reason does not depend on AGL supplying a "
        "replacement and did not change when it stopped: a run started by `agl run` in a cron job "
        "has nobody at that prompt, and a run started at a terminal has a person looking at AGL's "
        "screens rather than at the CLI's - so the question either waits on an answer that cannot "
        "arrive, or is answered somewhere the workflow that asked it will never hear about"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not _cli(), reason=_NO_CLI)
@pytest.mark.skipif(not _live(), reason=_NOT_OPTED_IN)
async def test_the_tools_a_task_carries_are_registered_and_the_denied_ones_are_gone(
    tmp_path: Path, watched: Watched
) -> None:
    """Tool supply and `Restriction`, both read off the session's registered tool list.

    The deny half is the same evidence `translate.py` was accepted on - a bare name in a deny rule
    removes the tool from the session - checked here through the adapter that composes the rules
    rather than through a hand-built options object. `Read` is the control: nothing denies it, and
    a session that had simply registered nothing would fail on it rather than passing quietly.

    The session runs to the end, so the tool list read here belongs to a session that worked. A
    deny rule the CLI rejects outright would previously have looked identical to one it honoured.

    **One of the four names below is weaker than the other three and it is worth knowing which.**
    Removing `Bash` from `NO_SHELL`'s rules makes `Bash` appear here, and removing `WebFetch` and
    `WebSearch` from `NO_NETWORK`'s makes both of those appear - measured. Removing
    `AskUserQuestion` from `ASKING_MECHANISMS_DENIED` changes nothing, because the CLI measured here
    does not offer that tool to an SDK session at all: the assertion is true today whether or not
    the deny rule exists. It is kept because a later CLI may start offering it and this is where
    that would be caught, and the deny rule itself is pinned where it *can* fail - on
    `disallowed_tools` in `test_the_options_the_run_actually_built_are_the_hermetic_ones`.
    """
    notes = Notes()
    await spawn(task_in(poisoned(tmp_path), tools=(notes.tool,)))
    registered = watched.init().get("tools", [])

    assert f"mcp__agl__{notes.tool.name}" in registered, (
        f"the task's own tool is not in the session's tool list: {registered}. A tool the model "
        f"cannot see is a tool no handler will ever be called for"
    )
    assert "Read" in registered, "nothing denies Read, so a session missing it registered nothing"
    for gone in ("Bash", "WebFetch", "WebSearch", "AskUserQuestion"):
        assert gone not in registered, (
            f"{gone} is registered for a task declaring NO_SHELL and NO_NETWORK, and the vendor's "
            f"own asking mechanism is denied for every task: {registered}"
        )


# --- What the loopback makes free: a check_ready that returns, and the request that left ---------


@pytest.mark.asyncio
@pytest.mark.skipif(not _cli(), reason=_NO_CLI)
@pytest.mark.skipif(not _live(), reason=_NOT_OPTED_IN)
async def test_check_ready_returns_against_a_harness_that_answers(harness: Loopback) -> None:
    """The branch of `check_ready` this project had never seen: the one where nothing is wrong.

    `check_ready` has been exercised, in this suite and by hand, only ever *refusing* - because the
    machine it was written on had no session, and because the contract suite's preflight clauses are
    about how it refuses. "It returns when the harness works" was therefore an untested claim about
    the member whose whole job is to decide whether a forty-minute run is allowed to start, and a
    `check_ready` that raised unconditionally would have passed every test in the build.

    Free because the far side is the loopback: the probe is one turn of a few hundred tokens against
    an endpoint answering out of canned data. `runner.py` argues that this turn is the only honest
    test of "is this session authenticated", and that remains true - what is asserted here is that a
    *working* far side produces a clean return, not that this machine is logged in.

    The turn is read back afterwards so that the test cannot pass vacuously: a `check_ready` that
    returned by doing nothing at all would satisfy `await` and nothing else.
    """
    await ClaudeCodeRunner().check_ready(Claude.HAIKU)

    sent = wire_text(harness.composed())
    assert runner_module._READY_PROMPT in sent, (
        f"check_ready returned without the readiness probe reaching the far side: the loopback was "
        f"handed {[(seen.method, seen.path) for seen in harness.requests]}. A probe that answers "
        f"'ready' without asking anything is a preflight that admits a run it knows nothing about"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not _cli(), reason=_NO_CLI)
@pytest.mark.skipif(not _live(), reason=_NOT_OPTED_IN)
async def test_nothing_the_repository_wrote_reaches_the_model_in_the_request_that_leaves(
    tmp_path: Path, harness: Loopback
) -> None:
    """The measurement that settled the `CLAUDE.md` question, run again on every build.

    `runner.py`'s docstring records it: a repository carrying a `CLAUDE.md` with a unique marker, a
    local endpoint standing in for the model API, and the marker present under
    `setting_sources=None` and under `["user","project","local"]` and absent under `[]` - injected
    as `<system-reminder> ... # claudeMd ... Contents of <repo>/CLAUDE.md (project instructions,
    checked into the codebase)`. That was a one-off spike and this is the same measurement wired
    into the suite, which is the difference between a claim that was true once and one that stays
    true.

    It is the third and outermost of three hermeticity assertions, and each sees something the
    others cannot. The contract suite sees a leak an agent *acted on*. `init` above sees a
    configuration channel the harness *registered*. This sees what was actually put in front of the
    model - the case where nothing was registered, nothing was acted on, and the file's contents
    went out in a system reminder anyway.

    The workspace's own `CLAUDE.md` is asserted present first, and with its marker in it. Without
    that control, "no marker in the request" and "no marker anywhere to find" are the same green.
    """
    repo = poisoned(tmp_path)
    planted = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert markers_in(planted), (
        f"the workspace's CLAUDE.md carries none of the {len(CONFIGURATIONS)} markers, so this "
        f"test would report a clean request whether or not anything is being kept out of it"
    )

    await spawn(task_in(repo))
    sent = wire_text(harness.composed())

    assert not markers_in(sent), (
        f"the request that left the machine carries {markers_in(sent)}, planted in the workspace "
        f"by the contract suite's own fixture. The target repo contributes source code and "
        f"nothing else, and there are {len(CONFIGURATIONS)} rows in that table which are none of "
        f"AGL's to forward"
    )
    assert "claudeMd" not in sent, (
        "the request carries a `# claudeMd` block, which is how Claude Code injects a repository's "
        "CLAUDE.md into a session - the exact shape `setting_sources=[]` was measured to suppress. "
        "A marker-free block would be this leak with nothing planted in it to notice"
    )


# --- The workspace path is a directory and never program text ------------------------------------

MARKER: Final = "AGL-A-SHELL-EVALUATED-THE-PATH"

# One path component that is a whole command line: a substitution that leaves a file behind, a
# semicolon, a pipeline, quotes, spaces - and `--output=x`, which is the shape that was found
# making a read-only git port write a file. `/` and NUL are the only bytes a filename cannot hold.
LOADED_NAME: Final = f"agl $(touch {MARKER}); echo leaked | cat & 'q' \"d\" --output=x tree"


@pytest.mark.asyncio
@pytest.mark.skipif(not _cli(), reason=_NO_CLI)
@pytest.mark.skipif(not _live(), reason=_NOT_OPTED_IN)
async def test_a_workspace_whose_name_would_run_a_command_never_runs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, watched: Watched
) -> None:
    """The workspace reaches the CLI as `cwd=` and as nothing else.

    The control fires first, because a green result has to be readable: "nothing interpolated this
    path" and "this path had nothing in it to interpolate" are the same observation otherwise. So
    the directory name is pasted into a real command line, the marker file it creates is proved to
    exist, the marker is removed, and only then is the adapter asked to work in that directory.

    Two witnesses afterwards. No marker file anywhere under the temporary directory, which is what
    a substitution reaching any shell would leave; and the CLI's own `init` echoing the directory
    back **whole**, which is what tells `cwd=` from a path that was split on spaces, truncated at
    the semicolon, or quietly ignored.

    The third witness is that the run completes. A session that never started could not have run a
    command either, so "no marker appeared" is only evidence once there was a session to leave one.
    """
    monkeypatch.chdir(tmp_path)
    repo = workspace(tmp_path / LOADED_NAME)

    subprocess.run(f"cd {repo}", shell=True, cwd=tmp_path, capture_output=True, check=False)
    fired = sorted(tmp_path.rglob(MARKER))
    assert fired, (
        f"the control did not fire: pasting this directory name into a command line was supposed "
        f"to run `touch {MARKER}`, and no such file appeared. A fixture that is not dangerous "
        f"disarms this test silently, which is the failure it exists to avoid"
    )
    for stray in fired:
        stray.unlink()

    await spawn(task_in(repo))

    assert not sorted(tmp_path.rglob(MARKER)), (
        f"a session ran with a workspace holding `$(touch {MARKER})` in its name and the file "
        f"appeared, so the path reached a shell as text. It is passed as `cwd=` precisely so it "
        f"cannot: the SDK spawns an argument list with no shell, and a directory is not an argument"
    )
    assert watched.init().get("cwd") == str(repo), (
        f"the CLI says it is standing in {watched.init().get('cwd')!r}. The workspace was "
        f"{str(repo)!r}, whole, including the spaces and the `--output=x`"
    )


def test_a_cli_path_that_would_parse_as_a_flag_is_refused_at_construction() -> None:
    """The argv rule, on the one value the composition root supplies.

    `cli_path` reaches the command line as its own argument, and the SDK appends most options as
    two tokens - so a value beginning with `-` is not the flag's value but a flag of its own. The
    SDK says exactly that in its own source and closes it for four options that are not this one.
    """
    with pytest.raises(InputError) as refused:
        ClaudeCodeRunner(Path("--dangerously-skip-permissions"))
    assert "cli_path" in str(refused.value), (
        f"the refusal does not name which value was refused: {refused.value}"
    )


@pytest.mark.asyncio
async def test_a_model_that_would_parse_as_a_flag_is_refused_before_anything_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same rule on the value that is *rendered* rather than supplied.

    `translate.model_name` answers out of a closed table today, so no `ModelId` can produce this -
    which is exactly why the guard is worth a test: the reason it cannot happen lives in another
    module, and nothing in this one would notice that module gaining an entry. Substituting the
    renderer is how the guard is reached at all, and the assertion is that the refusal happens
    before a process exists rather than being caught by the CLI afterwards.
    """
    monkeypatch.setattr(runner_module, "model_name", lambda model: "--append-system-prompt")
    started = False

    def never(**kwargs: object) -> AsyncIterator[Any]:
        nonlocal started
        started = True
        raise AssertionError("a session was opened with a model that parses as a flag")

    monkeypatch.setattr(_session, "query", never)

    with pytest.raises(InputError):
        await ClaudeCodeRunner().run(task_in(workspace(tmp_path)))
    assert not started, "the refusal came too late to be a refusal"


@pytest.mark.asyncio
async def test_a_deny_rule_the_cli_tokenizer_would_ruin_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deny rules are joined on commas into one argument, so two shapes destroy a restriction.

    A rule holding a comma silently becomes two rules; a rule beginning with `-` turns the whole
    argument into a flag. Either way the restriction stops being enforced while still appearing in
    the list that was passed - which is the failure `translate.py`'s whole docstring is about, one
    layer further out. `InternalError` and not `InputError`, because the strings are AGL's own.
    """
    monkeypatch.setattr(
        runner_module,
        "restraint",
        lambda restrictions: Restraint(("Bash(git commit, push *)",), "in words"),
    )
    with pytest.raises(InternalError) as refused:
        await ClaudeCodeRunner().run(task_in(workspace(tmp_path)))
    assert "Bash(git commit, push *)" in str(refused.value), (
        f"the refusal does not quote the rule it refused: {refused.value}"
    )


# The three hermeticity settings, and the source text each has to be given, as `ast.unparse`
# normalises it.
# Values and not merely names, because the name is satisfied by the leak:
# `setting_sources=["user", "project", "local"]` names the option and is precisely what the empty
# list exists to displace.
#
# Two of the three have a leaky SDK default and the third does not, which is why `settings` was
# once left out of this table and why leaving it out was wrong. `settings` is not a default that
# reads the repository; it is a **channel that exists only if something opens it**, and
# `settings="~/.claude/settings.json"` opens it one line after `setting_sources=[]` closed
# everything else - handing the session the operator's own configuration document, which is the
# difference between reading no settings file and reading theirs. `runner.py`'s "Why no settings
# file" section argues the choice, and this is where the choice is held. One list rather than a list
# plus an exception: all three names are here, so a session added later is measured against all
# three or against none.
HERMETIC: Final[Mapping[str, str]] = {
    "setting_sources": "[]",
    "strict_mcp_config": "True",
    "settings": "None",
}


def test_every_session_this_package_opens_is_opened_hermetically() -> None:
    """A structural assertion, so a session added later cannot quietly omit a hermeticity setting.

    Two of the three hermeticity options have a *leaky* SDK default, so omitting them is not a
    session that fails to start - it is a session that reads the target repository and works. The
    third, `settings`, defaults to the closed value and is held here anyway: what it guards is a
    channel nothing opens by accident and everything opens by one line, and the only way that line
    is ever noticed is if its absence is written down. The tests above cover the one
    `ClaudeAgentOptions` that `run` builds; this one covers every `ClaudeAgentOptions` in the
    package, and it does it by parsing the source rather than by running anything -
    `check_ready`'s session included, and any that arrives later.

    **The value each is given, and not only that it was named.** This test began asserting presence
    alone, which reads as a check and is not one: `setting_sources=["user", "project", "local"]`
    satisfies "the keyword is there" and is the exact value the empty list displaces, so both
    settings could have been flipped to their leaky spellings with this test still green. What is
    compared now is the source text of the argument, `ast.unparse`d - which makes reformatting
    invisible to it and a value spelled anywhere else visible: a name, a `list()`, a constant
    imported from elsewhere all fail, deliberately, because a hermeticity setting whose value lives
    in another module is one this test cannot read and a reviewer cannot see at the call site.

    **Why this rather than moving the behavioural tests off their gate.**
    `test_the_options_the_run_actually_built_are_the_hermetic_ones` asserts the same three values
    against a session that really started, and where it runs it is the stronger evidence. But it
    spawns a `claude` process, which is exactly what `AGL_LIVE_AGENT=1` is declared to mean, and it
    is *also* behind the binary being on `PATH` - so taking it off the opt-in would still leave the
    invariant unasserted on every machine with no CLI installed. This one needs no binary, no
    socket and no opt-in, it runs on the default gate, and it holds for call sites that do not
    exist yet. Where the property is structural, the structural assertion is the one that does not
    go stale when a second session is added.

    `tests/adapters/test_shell_verifier.py` established the shape, for the same kind of
    clause: a promise about how a module is written is worth more as a fact about the code than as
    a paragraph in a docstring. `test_openai_runner.py` carries this test's sibling, over the `cwd=`
    that every child of that package is started with, and against the same table of permitted source
    texts - a working directory has no single right value the way a hermeticity setting does, so
    what it holds is the small set of directories that adapter chooses.
    """
    package = Path(runner_module.__file__).parent
    sessions = 0
    for source in sorted(package.glob("*.py")):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "id", None) != "ClaudeAgentOptions":
                continue
            sessions += 1
            given = {keyword.arg: keyword.value for keyword in node.keywords}
            assert HERMETIC.keys() <= given.keys(), (
                f"{source.name}:{node.lineno} opens a session without naming all three "
                f"hermeticity settings: {sorted(HERMETIC.keys() - given.keys())} are missing, "
                f"and it passes "
                f"{sorted(name for name in given if name)}. `setting_sources` and "
                f"`strict_mcp_config` default to None and False, both of which read the target "
                f"repository; `settings` defaults to the closed value and is named anyway, because "
                f"a channel that is shut because nobody opened it is one nobody can see was decided"
            )
            for setting, required in HERMETIC.items():
                written = ast.unparse(given[setting])
                assert written == required, (
                    f"{source.name}:{node.lineno} opens a session with `{setting}={written}`, and "
                    f"hermeticity wants `{setting}={required}`. Naming the option is not the "
                    f"guarantee: "
                    f"`setting_sources=['user', 'project', 'local']` names it and hands the "
                    f"session the repository's settings, its CLAUDE.md, its subagents and its "
                    f"commands, `strict_mcp_config=False` names it and loads the repository's "
                    f".mcp.json, and any `settings=` path at all adds a configuration document to "
                    f"a session that has just been told to read none"
                )
    assert sessions >= 2, (
        f"only {sessions} ClaudeAgentOptions call(s) were found in {package}, and there are at "
        f"least two - the run and the readiness probe. This test found nothing to check, which "
        f"means it is no longer checking anything"
    )


# --- Offline: the whole adapter, driven through a scripted transport, with no CLI anywhere -------

_PROTOCOL: Final = "2025-06-18"


class Scripted(Transport):
    """A `Transport` that plays a script instead of starting a process. Supplementary evidence.

    The SDK takes a `transport=` on `query()` and `Transport` is its own ABC, so this is the
    vendor's supported injection point rather than a monkeypatch of its internals. What that buys
    is that everything *above* the process boundary is the real thing: the real `ClaudeCodeRunner`,
    the real option assembly, the real SDK control protocol, the real in-process MCP servers with
    the real JSON Schema validation, the real `_tools.py` wrappers and the real `_session.py`
    reading. What is fake is one process and one model.

    **It is never acceptance.** `tests/contracts/agent.py` exists because a subagent that writes
    its own tests writes tests that pass, and a test double written in the same hour as the code it
    exercises is that risk exactly. Every clause this covers is covered again by the gated contract
    suite above, against a real agent, and the value here is that a regression is caught in a
    second on a laptop with no session.

    The script is an async callable handed this object, which offers `say` (put a CLI message on
    the stream) and `call` (make the session invoke one of the adapter's own MCP tools, the way
    Claude Code would). The MCP handshake is done once per server on first use, because mcp's
    server refuses anything before `initialize`.
    """

    def __init__(self, play: Callable[[Scripted], Awaitable[None]]) -> None:
        self._play = play
        self._outbound: asyncio.Queue[dict[str, Any] | Exception | None] = asyncio.Queue()
        self._waiting: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._playing: asyncio.Task[None] | None = None
        self._greeted: set[str] = set()
        self._counter = 0
        self._ready = False
        self.written: list[dict[str, Any]] = []

    async def connect(self) -> None:
        self._ready = True

    def is_ready(self) -> bool:
        return self._ready

    async def end_input(self) -> None:
        """Nothing to end: this transport has no stdin and the script decides when it is done."""

    async def close(self) -> None:
        self._ready = False
        if self._playing is not None:
            self._playing.cancel()
        await self._outbound.put(None)

    async def write(self, data: str) -> None:
        """Everything the SDK says, which is three things and each is answered in place.

        A `control_request` is the SDK's `initialize` handshake and is answered with an empty
        success, which is what a CLI with no extra capabilities to declare would send. A
        `control_response` is the answer to something this transport asked for - a tool call - and
        goes to whoever is waiting on it. A `user` message is the prompt arriving, which is the
        cue to start playing.
        """
        for line in data.splitlines():
            if not line.strip():
                continue
            message = json.loads(line)
            self.written.append(message)
            match message.get("type"):
                case "control_request":
                    await self._outbound.put(
                        {
                            "type": "control_response",
                            "response": {
                                "subtype": "success",
                                "request_id": message["request_id"],
                                "response": {},
                            },
                        }
                    )
                case "control_response":
                    body = message["response"]
                    pending = self._waiting.pop(body.get("request_id", ""), None)
                    if pending is not None and not pending.done():
                        pending.set_result(body)
                case "user" if self._playing is None:
                    self._playing = asyncio.create_task(self._play_out())

    async def read_messages(self) -> AsyncIterator[dict[str, Any]]:
        while (item := await self._outbound.get()) is not None:
            if isinstance(item, Exception):
                raise item
            yield item

    async def _play_out(self) -> None:
        try:
            await self._play(self)
        finally:
            await self._outbound.put(None)

    async def fail(self, error: Exception) -> None:
        """End the stream the way a CLI that exited non-zero does, rather than by running out.

        This is the half of the real thing a script that simply stops cannot reproduce: Claude Code
        yields its result and *then* exits non-zero, and the SDK turns the trailing `ProcessError`
        into a `ResultError` carrying what the result already said. Every error a run can end on -
        a logged-out session, an exhausted allowance, a limit reached - arrives that way, so a
        transport with no way to raise could not exercise a single one of them.
        """
        await self._outbound.put(error)

    async def say(self, message: dict[str, Any]) -> None:
        """Put one CLI message on the stream, in the CLI's own wire shape."""
        await self._outbound.put(message)

    async def call(self, server: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke one of the adapter's own MCP tools the way Claude Code would, and read back
        what it answered."""
        if server not in self._greeted:
            self._greeted.add(server)
            await self._rpc(
                server,
                {
                    "jsonrpc": "2.0",
                    "id": self._next(),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": _PROTOCOL,
                        "capabilities": {},
                        "clientInfo": {"name": "agl-scripted", "version": "1"},
                    },
                },
            )
            await self._rpc(server, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        answered = await self._rpc(
            server,
            {
                "jsonrpc": "2.0",
                "id": self._next(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )
        result = answered.get("result")
        assert isinstance(result, dict), f"the MCP server answered {answered!r}"
        return result

    async def listed(self, server: str) -> list[dict[str, Any]]:
        """What the server advertises, which is how a tool's schema is observed on the wire."""
        await self.call(server, "__none__", {})  # handshake, and an error result nobody reads
        answered = await self._rpc(
            server, {"jsonrpc": "2.0", "id": self._next(), "method": "tools/list", "params": {}}
        )
        tools = answered["result"]["tools"]
        assert isinstance(tools, list)
        return tools

    async def _rpc(self, server: str, message: dict[str, Any]) -> dict[str, Any]:
        request_id = f"agl-scripted-{self._next()}"
        pending: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._waiting[request_id] = pending
        await self._outbound.put(
            {
                "type": "control_request",
                "request_id": request_id,
                "request": {
                    "subtype": "mcp_message",
                    "server_name": server,
                    "message": message,
                },
            }
        )
        body = await pending
        assert body.get("subtype") == "success", f"the SDK refused an MCP message: {body!r}"
        answered = body["response"]["mcp_response"]
        assert isinstance(answered, dict)
        return answered

    def _next(self) -> int:
        self._counter += 1
        return self._counter


def init(cwd: Path) -> dict[str, Any]:
    """The CLI's session announcement, in its wire shape."""
    return {"type": "system", "subtype": "init", "session_id": "scripted", "cwd": str(cwd)}


def says(text: str, *, nested: bool = False) -> dict[str, Any]:
    """One assistant turn carrying text. `nested` marks it as a subagent's, not the agent's."""
    return {
        "type": "assistant",
        "message": {"model": "claude-haiku", "content": [{"type": "text", "text": text}]},
        "parent_tool_use_id": "parent" if nested else None,
    }


def uses(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """One assistant turn carrying a tool call, which is what an activity line is made of."""
    return {
        "type": "assistant",
        "message": {
            "model": "claude-haiku",
            "content": [{"type": "tool_use", "id": "t1", "name": name, "input": payload}],
        },
        "parent_tool_use_id": None,
    }


def ends(**fields: Any) -> dict[str, Any]:
    """The result message, with the three fields `stop_reason` is read from left to the caller."""
    return {
        "type": "result",
        "subtype": "success",
        "duration_ms": 1,
        "duration_api_ms": 1,
        "is_error": False,
        "num_turns": 1,
        "session_id": "scripted",
        **fields,
    }


async def offline(
    play: Callable[[Scripted], Awaitable[None]],
    task: AgentTask,
    monkeypatch: pytest.MonkeyPatch,
    **kwargs: Any,
) -> Any:
    """Run the real adapter against a scripted CLI. Returns whatever `run` returns."""
    transport = Scripted(play)

    def scripted(*, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        from claude_agent_sdk import query

        return query(prompt=prompt, options=options, transport=transport)

    monkeypatch.setattr(_session, "query", scripted)
    return await ClaudeCodeRunner().run(task, **kwargs)


@pytest.mark.asyncio
async def test_a_tool_call_reaches_its_handler_as_a_mapping_and_its_text_goes_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The port's uniform rule: invoke the handler, put its `text` back into the conversation.

    The contract suite asserts the same thing through a model's conduct and says so about itself.
    Here the call is made directly, so what is observed is the wiring: the payload arrives parsed,
    the handler's text comes back as the tool result, and nothing about which tool it is was read.
    """
    notes = Notes()
    repo = workspace(tmp_path)

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        result = await cli.call("agl", notes.tool.name, {"note": "one module"})
        assert result["content"][0]["text"] == "Noted. Nothing else is needed from this tool."
        assert result.get("isError") is False
        await cli.say(ends(result="done", terminal_reason="completed"))

    outcome = await offline(play, task_in(repo, tools=(notes.tool,)), monkeypatch)

    assert [dict(payload) for payload in notes.received] == [{"note": "one module"}], (  # type: ignore[call-overload]
        f"the handler was handed {notes.received}, and the port declares a Mapping"
    )
    assert isinstance(notes.received[0], Mapping), (
        "an adapter that passed on the raw text its backend produced would make every handler in "
        "the framework parse a payload the port says is already parsed"
    )
    assert outcome == AgentOutcome(stop_reason=StopReason.COMPLETED, text="done")


@pytest.mark.asyncio
async def test_a_refused_tool_result_carries_the_mechanisms_own_error_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ToolResult.rejected` becomes Claude Code's error frame rather than prose in the text.

    The port lets an adapter render a refusal into the text when its backend has no error channel,
    and this one has one - so the assertion is that it is used. The contract suite deliberately
    cannot see this: it asserts the outcome (the handler called again) and never the mechanism.
    """
    notes = Notes(reject_first=1)
    repo = workspace(tmp_path)

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        refused = await cli.call("agl", notes.tool.name, {"note": "no file named"})
        assert refused["isError"] is True, f"a refusal came back as an ordinary result: {refused}"
        assert "not accepted" in refused["content"][0]["text"]
        accepted = await cli.call("agl", notes.tool.name, {"note": "README.md says so"})
        assert accepted["isError"] is False
        await cli.say(ends(result="done", terminal_reason="completed"))

    await offline(play, task_in(repo, tools=(notes.tool,)), monkeypatch)
    assert len(notes.received) == 2, "both calls reached the handler inside one run"


@pytest.mark.asyncio
async def test_a_tool_handler_that_raises_ends_the_run_with_its_own_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The catch is AGL's own, at AGL's own boundary, and the test below says why it has to be.

    `_tools.Caller.handled` wraps every call to a workflow's handler: it records the exception,
    answers the in-flight call with a result the model can read rather than leaving a session
    waiting on a tool that never replied, and `_session.py` then breaks out of the stream at the
    next message and raises it out of `run`. That is the asking path's mechanism applied to the
    other piece of caller code a session invokes, and `tests/contracts/agent.py` argues in full why
    a handler that raises ends a run where a `ToolResult(rejected=True)` does not.

    **The exception never reaches the SDK**, which is the point of catching inside `_wrapped`
    rather than around the session: the vendor turns an exception out of an `SdkMcpTool` handler
    into an ordinary error result and carries the session on, so a mechanism that waited for one to
    surface would wait forever. That claim is measured in the test immediately below, against this
    same adapter with the catch removed.

    Two calls back to back with no message between them, because that is what a session issuing
    parallel tool calls looks like and a stream check cannot come between them: the second one is
    refused where the first was caught, and the handler is not asked again.
    """
    repo = workspace(tmp_path)
    notes = Notes(raise_first=1)
    told: list[dict[str, Any]] = []

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        told.append(await cli.call("agl", notes.tool.name, {"note": "one module"}))
        told.append(await cli.call("agl", notes.tool.name, {"note": "another"}))
        await cli.say(says("carrying on"))
        await cli.say(ends(result="done", terminal_reason="completed"))

    with pytest.raises(ToolFailed) as raised:
        async with asyncio.timeout(30):
            await offline(play, task_in(repo, tools=(notes.tool,)), monkeypatch)

    assert raised.value is notes.failure, (
        f"the run ended with {raised.value!r} rather than with the handler's own exception, so a "
        f"workflow's Stop or a headless terminal's refusal would be reported as something else"
    )
    assert len(notes.received) == 1, (
        f"the handler was called {len(notes.received)} time(s) against a session that called the "
        f"tool twice before any message arrived. Once a caller's own code has failed, no more of "
        f"it runs - the run is already over and the second call is answered without it"
    )
    assert [answer["isError"] for answer in told] == [True, True], (
        f"the session was handed {told}. Both calls are still answered - a session waiting on a "
        f"tool result that never comes is a hang - and both are errors rather than results"
    )
    assert "the notebook this tool writes into is not there" in told[0]["content"][0]["text"]
    assert "already being stopped" in told[1]["content"][0]["text"], (
        f"the second call was answered {told[1]!r}. It never reached the handler, so it is not a "
        f"refusal of what it carried - it is the session being told the task is over"
    )


@pytest.mark.asyncio
async def test_the_vendor_sdk_absorbs_a_handlers_exception_which_is_why_the_catch_is_agls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the clause above, and it is a measurement of the vendor rather than of AGL.

    `_tools._wrapped` is the one line between a workflow's handler and an `SdkMcpTool`, and this
    replaces it with a wrapper that does **not** catch - the shape this adapter had before the
    handler-failure mechanism existed. Everything else is the real thing: the real runner, the real
    in-process MCP server, the real `_session.py` reading.

    What comes back is an ordinary error result carrying the exception's text, and the run then
    ends normally with an `AgentOutcome`. So there is nothing for a session-level `try` to catch:
    an adapter that waited for a handler's exception to surface out of `query()` would wait for
    something the SDK has already swallowed, the model would be told to try again, and a step whose
    tool could not do its job would record an answer anyway. That is why the catch is written at
    AGL's own boundary and why deleting it is not a simplification.

    It measures the installed SDK rather than asserting a documented promise, so a vendor that
    changes its mind here fails this test and names the assumption that moved.
    """
    repo = workspace(tmp_path)
    notes = Notes(raise_first=1)
    told: list[dict[str, Any]] = []

    def uncaught(declared: Tool, caller: _tools.Caller) -> Any:
        async def invoked(payload: dict[str, Any]) -> dict[str, Any]:
            outcome = await declared.handler(payload)
            return {
                "content": [{"type": "text", "text": outcome.text}],
                "is_error": outcome.rejected,
            }

        return SdkMcpTool(
            name=declared.name,
            description=declared.description,
            input_schema={**dict(declared.payload_schema), "type": "object"},
            handler=invoked,
        )

    monkeypatch.setattr(_tools, "_wrapped", uncaught)

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        told.append(await cli.call("agl", notes.tool.name, {"note": "one module"}))
        await cli.say(ends(result="done", terminal_reason="completed"))

    async with asyncio.timeout(30):
        outcome = await offline(play, task_in(repo, tools=(notes.tool,)), monkeypatch)

    assert outcome == AgentOutcome(stop_reason=StopReason.COMPLETED, text="done"), (
        f"the run ended as {outcome!r} with AGL's catch removed. If the exception had come out of "
        f"the session there would be nothing here to assert, and the mechanism `_tools.Caller` "
        f"implements could have been a `try` around `query()` instead"
    )
    assert told[0]["isError"] is True, (
        f"the SDK answered {told[0]!r} for a handler that raised. This test is the reason the "
        f"clause above catches where it does, and it has stopped measuring that"
    )
    assert "the notebook this tool writes into is not there" in told[0]["content"][0]["text"], (
        f"the SDK answered {told[0]!r}, which no longer carries what the handler said - the "
        f"measurement this control is made of has changed shape"
    )
    assert len(notes.received) == 1, "and the handler was reached, so the exception was real"


@pytest.mark.asyncio
async def test_a_malformed_payload_never_reaches_the_handler_and_is_told_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tool's `payload_schema` is enforced on the wire, which is what makes it worth carrying.

    The port says the schema "is data, not a type: this module never validates against it" - so
    the validation has to happen somewhere, and this is where. A call missing a required property
    is answered with an error the model can read, in the same conversation, and the handler is
    never troubled with it.
    """
    notes = Notes()
    repo = workspace(tmp_path)

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        refused = await cli.call("agl", notes.tool.name, {"nothing": "useful"})
        assert refused["isError"] is True, (
            f"a payload that breaks the schema was accepted: {refused}"
        )
        await cli.say(ends(result="done", terminal_reason="completed"))

    await offline(play, task_in(repo, tools=(notes.tool,)), monkeypatch)
    assert notes.received == [], (
        f"the handler was called with {notes.received} for a payload the schema refuses"
    )


@pytest.mark.asyncio
async def test_a_schema_carrying_only_a_type_survives_the_crossing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SDK re-reads a dict with no `properties` as a `{name: type}` shorthand, and must not.

    A `payload_schema` of `{"type": "object"}` is a legal JSON Schema and the port's own words for
    what a `payload_schema` is. Handed over untouched it would reach the model as an object with
    one property called `type`, whose value is a string - a tool nobody could call correctly, with
    no error anywhere. This is the assertion that the shape is normalised on the way out.
    """
    repo = workspace(tmp_path)
    bare = Tool(
        name="ping",
        description="Say that you are here.",
        payload_schema={"type": "object"},
        handler=_always(ToolResult(text="here")),
    )
    seen: list[dict[str, Any]] = []

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        seen.extend(await cli.listed("agl"))
        await cli.say(ends(result="done", terminal_reason="completed"))

    await offline(play, task_in(repo, tools=(bare,)), monkeypatch)

    advertised = next(entry for entry in seen if entry["name"] == "ping")
    assert advertised["inputSchema"] == {"type": "object", "properties": {}}, (
        f"the schema on the wire is {advertised['inputSchema']!r}. A property called 'type' there "
        f"is the SDK's shorthand branch having read a JSON Schema as a mapping of names to types"
    )


@pytest.mark.asyncio
async def test_a_tools_schema_reaches_the_wire_as_the_workflow_declared_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The schema a client reads off this adapter's server is the one the workflow handed over.

    The mirror of `test_openai_runner.py::test_a_tools_schema_reaches_the_model_as_the_workflow_
    declared_it`, and it is here for the same reason: `sdk/tools.py::_object_schema` writes a
    qualified type name into every derived payload schema as a `title`, because `base_of` hashes a
    tool's name, description and schema and nothing else, so the schema is the only term a payload
    type's identity can travel in. Nothing between here and the wire is entitled to rewrite it -
    `_schema` above supplies `type` and `properties` when they are missing and touches nothing
    else - and until this test existed every free measurement of a tool reaching a real harness on
    this backend was taken on a schema with no annotation in it.

    `Notes` rather than a schema built here, so that removing the `title` from `_NOTE_SCHEMA` fails
    this test rather than making it vacuous. What is still deferred to the manual pass is a
    *vendor's* acceptance of the annotation at registration, which needs an installed CLI and is
    deferred to the manual QA pass. `title` is a standard JSON Schema annotation keyword with no
    validating behaviour in any draft, which is why it was chosen over `$id` and `description`, and
    the expectation is that both vendors take it without comment - but neither has been asked.
    """
    repo = workspace(tmp_path)
    notes = Notes()
    seen: list[dict[str, Any]] = []

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        seen.extend(await cli.listed("agl"))
        await cli.say(ends(result="done", terminal_reason="completed"))

    await offline(play, task_in(repo, tools=(notes.tool,)), monkeypatch)

    advertised = next(entry for entry in seen if entry["name"] == notes.tool.name)
    assert advertised["inputSchema"] == dict(notes.tool.payload_schema), (
        f"the workflow's tool reached the wire as {advertised['inputSchema']!r}, and it declared "
        f"{dict(notes.tool.payload_schema)!r}. Nothing here is entitled to rewrite it"
    )
    assert "title" in advertised["inputSchema"], (
        "the fixture this test is pointed at no longer carries a `title`, so it now asserts "
        "nothing about the annotation `_object_schema` writes - see `_NOTE_SCHEMA`"
    )


@pytest.mark.asyncio
async def test_activity_is_the_tools_own_name_and_one_line_of_its_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The activity line, formed by `translate.activity` and passed through untouched.

    The contract suite can only assert that whatever arrives is a `str`, because it cannot know
    what the adapter meant to say. This one knows: a `Read` of a file inside the workspace renders
    relative to it, and an MCP tool's fully qualified name passes through with no interpretation.
    """
    repo = workspace(tmp_path)
    lines: list[str] = []

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(uses("Read", {"file_path": f"{repo}/README.md"}))
        await cli.say(uses("mcp__agl__record_note", {"note": "one module"}))
        await cli.say(ends(result="done", terminal_reason="completed"))

    await offline(play, task_in(repo), monkeypatch, on_activity=lines.append)

    assert lines == ["Read: README.md", "mcp__agl__record_note: one module"], (
        f"the activity lines were {lines}. The tool's own name passes through verbatim, an MCP "
        f"name included, and a value that begins with the workspace is shown relative to it"
    )


@pytest.mark.asyncio
async def test_an_activity_reporter_that_raises_comes_out_of_this_adapters_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The contract suite's activity-reporter clause, against the real adapter, for free.

    That clause is the one test of a `run` in `AgentContract` that reads no model conduct, which is
    what makes it reachable here: the reporter fails on whatever the session reports, and a scripted
    transport reports two tool uses without an agent deciding anything. Against `_NeverRuns` it
    skips with the other five, so this is where the real `ClaudeCodeRunner` is actually held to it
    - the same shape as `test_the_options_the_run_actually_built_are_the_hermetic_ones` having a
    structural sibling that needs no binary.

    What it forbids is a `try` around `_read`'s `on_activity(...)`. That is one line to add, it
    would look like defensive good manners, and every other test in this build would stay green
    while a broken reporter went unmentioned for the length of every run.
    """
    repo = workspace(tmp_path)
    failing = Activity(raise_first=1)

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(uses("Read", {"file_path": f"{repo}/README.md"}))
        await cli.say(uses("Grep", {"pattern": "greet"}))
        await cli.say(ends(result="done", terminal_reason="completed"))

    with pytest.raises(ReporterFailed):
        await offline(play, task_in(repo), monkeypatch, on_activity=failing)

    assert len(failing.lines) == 1, (
        f"the reporter was called {len(failing.lines)} time(s) and it raised on the first, so the "
        f"session caught the exception and went on reporting. `ports/agent.py` puts no `try` "
        f"around that call by design"
    )


# There were five tests here and there is one. Four were about the `agl_ask` MCP server AGL used to
# register on every task on every backend - its advertised schema, a question answered with nobody
# listening, a blank question refused back into the conversation, and a question handler that raised
# ending the run - and the fifth was the two-round negotiation below. The server is gone: a question
# is an ordinary tool a workflow supplies, so its schema is derived from the workflow's own payload
# class, its blank-question refusal is the workflow's handler's, and a handler that raises is the
# tool-handler clause pinned above. What could not go with them is the *round-trip* claim, which is
# about this adapter rather than about questions - so it is kept here, spelled as what it always
# measured: two `tools/call` exchanges inside one session.


@pytest.mark.asyncio
async def test_two_tool_calls_and_two_results_inside_one_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each result is serialised back into the same session, so a negotiation is rounds.

    One `run`, one transport, one session, two `tools/call` round-trips - which is the clause in
    the smallest form that can hold it, and which the contract suite can only see by watching a
    model choose to call twice. A workflow's asking tool is what this is for: an agent proposes,
    is answered, revises, and is answered again, all inside the session that holds the reasoning
    behind the proposal.

    The payloads differ and the answers differ, because an adapter that carried one exchange and
    replayed its result into the second would satisfy a single token.
    """
    repo = workspace(tmp_path)
    asked: list[Mapping[str, JsonValue]] = []

    async def handler(payload: Mapping[str, JsonValue]) -> ToolResult:
        asked.append(payload)
        return ToolResult(text=f"answer-{len(asked)}")

    declared = Tool(
        name="ask_the_operator",
        description="Ask the person running this task, and wait for their answer.",
        payload_schema={
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
        handler=handler,
    )

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        first = await cli.call("agl", declared.name, {"question": "Which path?"})
        assert first["content"][0]["text"] == "answer-1"
        second = await cli.call("agl", declared.name, {"question": "And after that?"})
        assert second["content"][0]["text"] == "answer-2"
        await cli.say(ends(result="answer-1 answer-2", terminal_reason="completed"))

    outcome = await offline(play, task_in(repo, tools=(declared,)), monkeypatch)

    assert [payload["question"] for payload in asked] == ["Which path?", "And after that?"]
    assert outcome.text == "answer-1 answer-2"


@pytest.mark.asyncio
async def test_a_subagents_last_words_are_not_the_runs_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`text` is the agent's closing message, and a nested conversation's last line is not it.

    `parent_tool_use_id` is what tells them apart. Activity is the other way round and covered
    above: a subagent grepping a file is as much "what is happening right now" as the parent doing
    it, and the router has no licence to interpret either string.
    """
    repo = workspace(tmp_path)

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(says("the agent's own answer"))
        await cli.say(says("a subagent reporting to its parent", nested=True))
        await cli.say(ends(terminal_reason="completed"))

    outcome = await offline(play, task_in(repo), monkeypatch)
    assert outcome.text == "the agent's own answer", (
        f"the run answered {outcome.text!r}, which is what a nested conversation said to the "
        f"agent rather than what the agent said to AGL"
    )


# Every string this adapter recognises, in the field it is recognised in, and two it does not.
# Written as data because the mapping *is* data - a table a reader can check against the CLI - and
# a test of five separate scripts would hide that.
STOPPED: Final[tuple[tuple[dict[str, Any], StopReason | None], ...]] = (
    ({"terminal_reason": "completed"}, StopReason.COMPLETED),
    ({"terminal_reason": "max_turns"}, StopReason.LIMIT),
    ({"terminal_reason": "aborted_streaming"}, None),
    ({"terminal_reason": "aborted_tools"}, None),
    ({"subtype": "error_max_turns", "is_error": True}, StopReason.LIMIT),
    ({"stop_reason": "end_turn"}, StopReason.COMPLETED),
    ({"stop_reason": "stop_sequence"}, StopReason.COMPLETED),
    ({"stop_reason": "tool_use"}, StopReason.COMPLETED),
    ({"stop_reason": "max_tokens"}, StopReason.LIMIT),
    ({"stop_reason": "refusal"}, None),
    ({}, None),
    # The order matters and this is what pins it: the query loop's own statement outranks the
    # model's, so an aborted run is not reported as one the model finished.
    ({"terminal_reason": "aborted_streaming", "stop_reason": "end_turn"}, None),
    ({"terminal_reason": "max_turns", "stop_reason": "end_turn"}, StopReason.LIMIT),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("fields", "expected"), STOPPED)
async def test_why_a_run_stopped_is_read_off_three_fields_and_may_be_none(
    fields: dict[str, Any],
    expected: StopReason | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The contract suite pins the legal values and cannot pin that any of them is true (gap 10).

    So this is the other half: every string this adapter claims to read, read. `None` is asserted
    for the aborted pair and for a string nobody has seen, because the port made `None` legal
    precisely so that "this backend did not say anything this port can read" has a spelling that
    is not a lie - and inventing `COMPLETED` for a cancelled turn is the lie it prevents.
    """
    repo = workspace(tmp_path)

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(ends(result="done", **fields))

    outcome = await offline(play, task_in(repo), monkeypatch)
    assert outcome.stop_reason is expected, (
        f"a result carrying {fields} was read as {outcome.stop_reason!r} and should be "
        f"{expected!r}. Three fields, consulted in the order of how much each one knows"
    )


@pytest.mark.asyncio
async def test_an_agent_that_said_nothing_answers_with_the_empty_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`""` and never `None`: the port's only content channel does not get a second way to be empty.

    Also the `result`-then-last-text precedence, in the case where the CLI kept no result: what the
    session watched go past is the fallback, and an agent that said nothing at all leaves neither.
    """
    repo = workspace(tmp_path)

    async def silent(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(ends(terminal_reason="completed"))

    assert (await offline(silent, task_in(repo), monkeypatch)).text == ""

    async def spoke(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(says("what the agent said"))
        await cli.say(ends(terminal_reason="completed"))

    assert (await offline(spoke, task_in(repo), monkeypatch)).text == "what the agent said", (
        "with no `result` from the CLI, the last thing the agent said is the honest fallback"
    )


@pytest.mark.asyncio
async def test_a_run_the_backend_stopped_is_an_outcome_and_not_an_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one place this adapter answers where the SDK would have raised.

    Claude Code exits non-zero for **every** error result, so "it ran out of turns" and "it could
    not authenticate" arrive as the same class of exception - and only the first is something the
    port has a member for. `ports/agent.py`: "A backend that imposes its own limit reports having
    done so through `StopReason.LIMIT` - a fact about what happened, rather than a knob here."

    The script reproduces both halves: the error result, and the non-zero exit behind it, which the
    SDK turns into the `ResultError` a real logged-out CLI produces (observed, and quoted in this
    file's own skip reason). Without the second half this would be testing a case that does not
    happen.
    """
    repo = workspace(tmp_path)

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(says("I had more to say"))
        await cli.say(
            ends(
                subtype="error_max_turns",
                is_error=True,
                terminal_reason="max_turns",
                result=None,
            )
        )
        await cli.fail(ProcessError("Command failed with exit code 1", exit_code=1))

    outcome = await offline(play, task_in(repo), monkeypatch)
    assert outcome == AgentOutcome(stop_reason=StopReason.LIMIT, text="I had more to say"), (
        f"a run stopped at a limit answered {outcome!r}. Reporting it as an unavailable backend "
        f"would send a person to check their network for an agent that simply ran out of turns"
    )


@pytest.mark.asyncio
async def test_an_error_result_that_is_not_a_limit_is_translated_and_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The adapter translates what its backend throws, at its own boundary, and nothing above an
    adapter sees a vendor exception.

    The contract suite's gap 7 says in as many words that it cannot provoke one - "nothing here can
    make a backend fail on demand ... so no test provokes a translation" - and this is the case a
    person actually meets: a session that is not authenticated. What is asserted is that the CLI's
    own words survive into the message, because that is the whole of what makes the error
    actionable, and that the class is the one preflight and every workflow catch.
    """
    repo = workspace(tmp_path)
    said = "Failed to authenticate: OAuth session expired and could not be refreshed"

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(ends(is_error=True, result=said, stop_reason="stop_sequence"))
        await cli.fail(ProcessError("Command failed with exit code 1", exit_code=1))

    with pytest.raises(UpstreamUnavailable) as raised:
        await offline(play, task_in(repo), monkeypatch)
    assert said in str(raised.value), (
        f"the refusal does not carry what the CLI said: {raised.value}. An UpstreamUnavailable "
        f"whose message does not name the cause is the same dead end as no message at all"
    )


@pytest.mark.asyncio
async def test_a_prompt_with_nothing_standing_around_it_is_the_instructions_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A workflow author's prompt is the whole of what they wrote, and reaches the agent unedited.

    The other half is asserted with it: standing context, the restrictions in words and `plan_only`
    all reach the agent, above the instructions, with the instructions still last. Read off the
    prompt the adapter handed the SDK, which is where a hostile value would land too - none of
    this text is on a command line, because the prompt travels on the CLI's standard input.
    """
    repo = workspace(tmp_path)
    seen: list[str] = []

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(ends(result="done", terminal_reason="completed"))

    def capture(*, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        from claude_agent_sdk import query

        seen.append(prompt)
        return query(prompt=prompt, options=options, transport=Scripted(play))

    bare = AgentTask(
        instructions="Read README.md and say what this is.",
        workspace=repo,
        model=Claude.HAIKU,
        restrictions=frozenset(),
        tools=(),
    )
    monkeypatch.setattr(_session, "query", capture)
    await ClaudeCodeRunner().run(bare)
    assert seen == ["Read README.md and say what this is."], (
        f"a task with no context, no restrictions and no plan_only was rewritten: {seen!r}"
    )

    seen.clear()
    dressed = AgentTask(
        instructions="Read README.md and say what this is.",
        workspace=repo,
        model=Claude.HAIKU,
        restrictions=frozenset({Restriction.NO_SHELL}),
        tools=(),
        context="This repository is a teaching example.",
        plan_only=True,
    )
    await ClaudeCodeRunner().run(dressed)
    composed = seen[0]
    assert composed.endswith("Read README.md and say what this is."), (
        f"the instructions are not last in the composed prompt: {composed!r}"
    )
    assert "This repository is a teaching example." in composed, "the standing context is dropped"
    assert "Do not run shell commands" in composed, (
        "the restrictions in words did not reach the agent, so it was handed a partial deny list "
        "presented as a whole one - which is what `Restraint` refuses to let a caller do"
    )
    assert "examine and propose" in composed, "plan_only reached the agent as nothing at all"


@pytest.mark.asyncio
async def test_no_marker_from_the_contract_suites_own_poison_is_in_what_the_agent_is_told(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The composed prompt carries the workflow's words and nothing the repository wrote.

    A cheap, offline complement to the `init` assertions above and to the contract suite's own
    hermeticity test: those two cover what the *harness* loaded, and this covers what this adapter
    itself put in front of the model. It would fail an adapter that read a `CLAUDE.md` and helpfully
    prepended it - which is a thing an adapter could do without any harness option being wrong.

    `test_nothing_the_repository_wrote_reaches_the_model_in_the_request_that_leaves` asserts the
    same absence in the request a real CLI sent, which is where the harness's own injection would
    show up. This one is the adapter's half alone, and it needs no CLI to run.
    """
    repo = poisoned(tmp_path)
    seen: list[str] = []

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(ends(result="done", terminal_reason="completed"))

    def capture(*, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        from claude_agent_sdk import query

        seen.append(prompt)
        return query(prompt=prompt, options=options, transport=Scripted(play))

    monkeypatch.setattr(_session, "query", capture)
    await ClaudeCodeRunner().run(task_in(repo))

    assert not markers_in(seen[0]), (
        f"the prompt this adapter composed carries {markers_in(seen[0])}, planted in the "
        f"workspace by the contract suite's own fixture. There are {len(CONFIGURATIONS)} rows in "
        f"that table and none of them is AGL's to read"
    )


def _always(result: ToolResult) -> Callable[[Mapping[str, JsonValue]], Awaitable[ToolResult]]:
    """A tool handler that answers the same thing however it is called."""

    async def handler(payload: Mapping[str, JsonValue]) -> ToolResult:
        return result

    return handler


def test_capabilities_are_the_ports_own_members_and_not_equivalent_strings() -> None:
    """The suite asserts this too; what it cannot assert is *which* four, and why they are static.

    `Capability` is a `StrEnum`, so this is a statement about the members and not about a set that
    compares equal to them today. The three are all of them: Claude Code edits files, runs a shell
    and calls tools, on every build and on every machine, so none of the three is conditional on a
    feature flag.

    There were four while `MID_RUN_QUESTIONS` existed, and this docstring used to argue that one at
    length - it was unconditional because AGL registered an asker of its own rather than depending
    on the harness's. The member went when a question became an ordinary tool: what a role needs of
    a backend in order to ask is `TOOL_CALLING`, which is already here.
    """
    assert asyncio.run(ClaudeCodeRunner().capabilities(Claude.OPUS)) == frozenset(Capability), (
        "this adapter reports every capability the port has a member for, and a member added to "
        "the port is a question about this backend that somebody has to answer here"
    )


def test_a_model_this_adapter_does_not_serve_is_refused_by_both_query_members() -> None:
    """`src/agl/ports/agent.py`: an adapter handed a `ModelId` it does not serve raises
    `InputError` and never silently substitutes.

    The contract suite can only ever name a model the adapter serves - it has one `model` fixture -
    so the refusal is invisible to it. Both members are asserted because a `capabilities` that
    ignored its argument would answer "I can do all four" for a model this runner would then refuse
    to run, which is a preflight that admits a run and kills it at second one.
    """
    with pytest.raises(InputError):
        asyncio.run(ClaudeCodeRunner().capabilities(OpenAI.SOL))
    with pytest.raises(InputError):
        asyncio.run(ClaudeCodeRunner().check_ready(OpenAI.SOL))
