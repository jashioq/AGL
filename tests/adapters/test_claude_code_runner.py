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
    no second source for the fact). Every string this adapter recognises, in the field it is
    recognised in, and every one the release declares that it does not - which stop the run instead
    of answering. The list of those is checked against the bundled binary's own schema, and that is
    the only assertion in this file with a real tool on the other side of it.

Named `test_claude_code_runner.py`, for the module it covers: `tests/` carries no `__init__.py`
(see `tests/conftest.py` for why it must not), so pytest's module names are the bare filenames and
two files of one name under different directories would collide at import.
"""

import ast
import asyncio
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from dataclasses import replace
from functools import cache
from mmap import ACCESS_READ, mmap
from pathlib import Path
from typing import Any, Final, NoReturn
from urllib.parse import urlsplit
import claude_agent_sdk
import pytest
from claude_agent_sdk import ClaudeAgentOptions, ProcessError, SdkMcpTool
from claude_agent_sdk._cli_version import __cli_version__
from claude_agent_sdk._internal.transport import Transport
from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
from agl.adapters.claude_code import _session, _tools
from agl.adapters.claude_code import runner as runner_module
from agl.adapters.claude_code._environment import withheld
from agl.adapters.claude_code.runner import ClaudeCodeRunner
from agl.adapters.claude_code.translate import CROSS_SESSION_DENIED, Restraint, restraint
from agl.ports.agent import (
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Capability,
    Claude,
    ClaudeEffort,
    ModelChoice,
    ModelId,
    OpenAI,
    OpenAIEffort,
    Restriction,
    Standing,
    StopReason,
    Tool,
    ToolResult,
)
from agl.ports.errors import InputError, InternalError, UpstreamUnavailable, UpstreamUnexpected
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

def task_in(
    repo: Path, *, tools: tuple[Tool, ...] = (), model: ModelChoice = Claude.HAIKU
) -> AgentTask:
    """One ordinary task in `repo`, with restrictions so the deny rules are on the wire too."""
    return AgentTask(
        instructions="Read README.md and say in one sentence what this project does.",
        workspace=repo,
        model=model,
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

    **One of the names below is weaker than the rest and it is worth knowing which.**
    Removing `Bash` from `NO_SHELL`'s rules makes `Bash` appear here, and removing `WebFetch` and
    `WebSearch` from `NO_NETWORK`'s makes both of those appear - measured, and measured again for
    every member of `CROSS_SESSION_DENIED`, each of which the CLI offers an SDK session by default.
    Removing `AskUserQuestion` from `ASKING_MECHANISMS_DENIED` changes nothing, because the CLI
    measured here does not offer that tool to an SDK session at all: the assertion is true today
    whether or not the deny rule exists. It is kept because a later CLI may start offering it and
    this is where that would be caught, and the deny rule itself is pinned where it *can* fail - on
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
    denied = ("Bash", "WebFetch", "WebSearch", "AskUserQuestion", *CROSS_SESSION_DENIED)
    for gone in denied:
        assert gone not in registered, (
            f"{gone} is registered for a task declaring NO_SHELL and NO_NETWORK, and the vendor's "
            f"own asking mechanism and every route into another session are denied for every "
            f"task: {registered}"
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
                f"{source.name}:{node.lineno} builds a session's options without naming all three "
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
                    f"{source.name}:{node.lineno} builds a session's options with "
                    f"`{setting}={written}`, and "
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
    *,
    printed: tuple[str, ...] = (),
    **kwargs: Any,
) -> Any:
    """Run the real adapter against a scripted CLI. Returns whatever `run` returns.

    `printed` is what the CLI wrote on its stderr, and it is handed to the sink the *adapter*
    built rather than to one this file makes: a scripted `Transport` stands in for the process and
    with it for the SDK's stderr plumbing, so there is no other route to that object, and feeding
    one built here would prove only that this file can call it.
    """
    transport = Scripted(play)

    def scripted(*, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        from claude_agent_sdk import query

        assert options.stderr is not None, "the run opened a session with no stderr sink at all"
        for line in printed:
            options.stderr(line)
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

# --- and which of two failures is the one the run is stopped by -----------------------------------

_LATCH_BOUND: Final = 5.0
"""Seconds either half of the arrangement below is allowed to take.

Nothing here starts a process, opens a socket or touches a repository: two coroutines hand an
`asyncio.Event` back and forth, which takes microseconds. So the bound is not a performance
assertion and cannot fire on a slow machine - it fires when a handler is waiting for something that
is never going to arrive, which is the way a mistake in an arrangement like this one shows itself.
The suite's global 60s timeout is the floor under awaits nobody bounded and reports only that
something hung; this reports which half of the interleaving did not happen."""

_EMPTY_SCHEMA: Final[Mapping[str, JsonValue]] = {"type": "object", "properties": {}}
"""What both tools below advertise. Nothing validates it here - `Caller` is handed a payload that
has already crossed the wire - so it is the smallest object a `Tool` can carry."""

async def _answered(call: Awaitable[ToolResult], what: str) -> ToolResult:
    """Take what one `Caller.handled` call was answered with, under a bound that says what stalled.

    `asyncio.wait_for` and not a bare `await`: a `Caller` that answered one of these calls and left
    the other waiting forever is one of the ways the clause below can fail, and a bare `await` on it
    would hang until the suite's global timeout killed the test with a traceback into the selector.
    """
    try:
        return await asyncio.wait_for(call, _LATCH_BOUND)
    except TimeoutError:
        raise AssertionError(
            f"waited {_LATCH_BOUND:g}s for {what}, and it never happened. Both handlers below are "
            f"released by an event the other half sets, so a wait that does not end is one half of "
            f"the interleaving never reaching the line that releases the other"
        ) from None

@pytest.mark.asyncio
async def test_the_first_of_two_concurrent_failures_is_the_one_the_caller_latches() -> None:
    """`Caller.fail` keeps the *first* exception, and two calls in flight is the only way to see.

    **The clause.** `fail` is written `if self.failure is None: self.failure = raised`, and the
    guard is the whole of it. Every other test in this repository drives one failing handler, and
    against one failure that guard and a bare `self.failure = raised` are the same three lines - so
    the line is untested by everything around it, and a mutation of it survived a session. It is not
    dead code either: `handled` is `async`, and the guard it reads at the top and the assignment it
    makes at the bottom are separated by `await tool.handler(payload)`.

    **Why this interleaving is the only way in, and why it is real.** `fail` is called from one
    place in `_tools.py` - inside `handled`'s own `except` - so `self.failure` can only be set when
    a call has passed the guard, and it can only be *already* set when a second call passed that
    guard before the first one raised. That is two tool calls in flight at once, which this backend
    produces on its own: the model talks to an in-process MCP server and may emit parallel tool
    calls into it, which is the same arrangement
    `test_a_tool_handler_that_raises_ends_the_run_with_its_own_exception` drives through a session
    two calls deep with no message between them.

    **What a last-wins latch would cost.** `_session.py` ends with `raise caller.failure`, so the
    step would be stopped by the *later* exception and would report it as the cause - and
    `_STOPPING`'s `{raised}` would name it to the model too. The run would blame the tool that
    failed because the first one already had, and the failure that actually stopped it would appear
    nowhere: not in the traceback a person reads, not in what the agent was told, and not on the
    journal, since a step that raises records nothing.

    **The arrangement is deterministic and is not a race.** Two `asyncio.Event`s hold both handlers
    inside their own bodies before either raises - the first waits for the second to arrive, the
    second waits until the test has read what was latched - so the guard is reached with
    `self.failure` already set on every run rather than on the runs where the scheduler obliged. A
    test that only sometimes exercised the guard would be no clause at all.

    Written twice, once per adapter, for the reason
    `test_a_tool_handler_that_raises_ends_the_run_with_its_own_exception` is: the two `Caller`
    classes are byte-identical copies, `tests/adapters/test_openai_runner.py` holds this same
    clause under this same name, and a workflow's tool cannot behave two ways depending on which
    adapter happened to serve the step.
    """
    caller = _tools.Caller()
    first = RuntimeError("the notebook this tool writes into is not there")
    second = RuntimeError("and the other tool could not reach the index either")
    entered: list[str] = []
    second_arrived = asyncio.Event()
    first_latched = asyncio.Event()

    async def fails_first(payload: Mapping[str, JsonValue]) -> ToolResult:
        entered.append("record_note")
        await second_arrived.wait()
        raise first

    async def fails_second(payload: Mapping[str, JsonValue]) -> ToolResult:
        entered.append("read_note")
        second_arrived.set()
        await first_latched.wait()
        raise second

    writing = Tool(
        name="record_note",
        description="Write down one note.",
        payload_schema=_EMPTY_SCHEMA,
        handler=fails_first,
    )
    reading = Tool(
        name="read_note",
        description="Read one note back.",
        payload_schema=_EMPTY_SCHEMA,
        handler=fails_second,
    )

    calls = (
        asyncio.create_task(caller.handled(writing, {})),
        asyncio.create_task(caller.handled(reading, {})),
    )
    try:
        early = await _answered(calls[0], "the call whose handler raises first to be answered")
        assert caller.failure is first, (
            f"the first handler raised and `caller.failure` is {caller.failure!r}. Nothing "
            f"concurrent has happened yet - this is the ordinary single-failure path, and the rest "
            f"of this test rests on it"
        )
        first_latched.set()
        late = await _answered(calls[1], "the call whose handler raises second to be answered")
    finally:
        for call in calls:
            call.cancel()

    assert caller.failure is first, (
        f"`caller.failure` is {caller.failure!r} after a second handler failed inside a call that "
        f"had already passed the guard. `fail` is a first-wins latch, and `_session.py` ends "
        f"with `raise caller.failure` - so last-wins means the step is stopped by the later "
        f"exception and reports it as the cause, with the failure that actually stopped the run "
        f"named nowhere at all"
    )

    assert early.rejected is True and str(first) in early.text, (
        f"the call that failed first was answered {early!r}. Both calls are still answered - a "
        f"session waiting on a tool result that never comes is a hang - and each is told what its "
        f"own handler did"
    )
    assert late.rejected is True and str(second) in late.text, (
        f"the call that failed second was answered {late!r}. It reached its handler, so what it is "
        f"told is its own failure and not the first one's"
    )

    stopped = await caller.handled(writing, {})

    assert stopped.rejected is True, f"a call made after the stop was answered {stopped!r}"
    assert str(first) in stopped.text and str(second) not in stopped.text, (
        f"a later call was told {stopped.text!r}. `_STOPPING` interpolates `self.failure`, so this "
        f"is the same latch read from the model's side: the reason the task is being stopped is "
        f"the failure that stopped it, not whichever one happened last"
    )
    assert entered == ["record_note", "read_note"], (
        f"the handlers reached were {entered}. Both had to be inside their own bodies before "
        f"either raised - that is the whole arrangement - and the call above them must have been "
        f"refused at the guard without reaching a handler at all"
    )

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
    ({"terminal_reason": "budget_exhausted"}, StopReason.LIMIT),
    ({"terminal_reason": "aborted_streaming"}, None),
    ({"terminal_reason": "aborted_tools"}, None),
    ({"subtype": "error_max_turns", "is_error": True}, StopReason.LIMIT),
    ({"subtype": "error_max_budget_usd", "is_error": True}, StopReason.LIMIT),
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
    for the aborted pair, for a `stop_reason` nobody has seen and for a result that carries no
    field at all, because the port made `None` legal precisely so that "this backend did not say
    anything this port can read" has a spelling that is not a lie - and inventing `COMPLETED` for a
    cancelled turn is the lie it prevents. An unreadable `terminal_reason` is the case that gets no
    spelling here at all, and `REFUSED_REASONS` below is where it went.
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

# The other fourteen `terminal_reason` values Claude Code 2.1.277 declares: everything
# `_session._TERMINAL_REASONS` does not name. Written out rather than derived from that table,
# because a table checked against itself measures nothing - the release's own list is what this is,
# and the test below reads it off the bundled binary to say so.
REFUSED_REASONS: Final[tuple[str, ...]] = (
    "blocking_limit",
    "rapid_refill_breaker",
    "prompt_too_long",
    "image_error",
    "model_error",
    "api_error",
    "malformed_tool_use_exhausted",
    "stop_hook_prevented",
    "hook_stopped",
    "tool_deferred",
    "background_requested",
    "structured_output_retry_exhausted",
    "tool_deferred_unavailable",
    "turn_setup_failed",
)

@pytest.mark.asyncio
@pytest.mark.parametrize("reason", REFUSED_REASONS)
async def test_a_terminal_reason_this_adapter_cannot_read_stops_the_run_by_name(
    reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A result that looks clean and ended for a reason nothing here can weigh is not an answer.

    `turn_setup_failed` is the sharpest of the fourteen: the CLI's own loop threw before it built
    the turn's parameters, so no tool definition and no instruction ever reached a model. Read as
    `COMPLETED` that is a step recorded, committed and replayed by every resume as work that was
    done. `stop_hook_prevented`, `hook_stopped`, `tool_deferred` and `background_requested` are the
    four the release classes as neither an error nor a cancellation, so `is_error` does not catch
    them and this is the only thing that does.

    The value is required to be in the message, because a refusal that says a version moved without
    saying which string moved leaves a reader with the whole release to search.
    """
    repo = workspace(tmp_path)
    printed = "the CLI wrote this before it stopped"

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(ends(result="half an answer", terminal_reason=reason))

    with pytest.raises(UpstreamUnexpected) as refused:
        await offline(play, task_in(repo), monkeypatch, printed=(printed,))
    assert reason in str(refused.value), (
        f"the run was refused without naming what it was refused over: {refused.value}. The "
        f"string the CLI sent is the whole of what tells a reader where to look"
    )
    assert str(refused.value).endswith(printed), (
        f"the refusal dropped what the CLI printed: {refused.value}. This adapter registers the "
        f"sink that takes that stream off the operator's terminal, so its messages owe it back"
    )

@pytest.mark.asyncio
@pytest.mark.parametrize("reported", ["stop_sequence", "max_tokens"])
async def test_an_unreadable_terminal_reason_outranks_the_stop_reason_reported_beside_it(
    reported: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect this guard was written for, and it is not that the outcome came back as `None`.

    A result carries all three fields at once, and the model's `stop_reason` describes its last
    request rather than the turn: an unauthenticated CLI 2.1.277 sends
    `terminal_reason="api_error"` beside `stop_reason="stop_sequence"`, which is an observed frame
    and not a constructed one. Read left to right with the first field passed over, the second
    answers - so a turn the CLI cut short came back as one the agent finished.

    `max_tokens` is the second parameter because it reaches a different line: `LIMIT` is answered
    with an outcome before `is_error` is consulted at all, so a reason left to fall through there
    is one no refusal further down ever sees.
    """
    repo = workspace(tmp_path)

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(
            ends(result="half an answer", terminal_reason="api_error", stop_reason=reported)
        )

    with pytest.raises(UpstreamUnexpected) as refused:
        await offline(play, task_in(repo), monkeypatch)
    assert "api_error" in str(refused.value), (
        f"a reason this adapter cannot read was overruled by a field that knows less: "
        f"{refused.value}. The query loop's own statement outranks the model's, and a value "
        f"missing from the table is still that statement"
    )

@pytest.mark.asyncio
async def test_an_error_result_is_reported_as_unavailable_before_its_reason_is_judged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eleven of the fourteen are ones that release classes as errors, and that branch says more.

    `UpstreamUnavailable` says the same call may get past this later and carries what the far side
    said; the refusal above says no retry helps and carries a string from a schema. The frame
    scripted here is the one an unauthenticated CLI 2.1.277 sends, field for field - an exhausted
    allowance arrives the same way, so ordering the two the other way round would answer every one
    of them with a version mismatch and drop the only sentence a person could act on.
    """
    repo = workspace(tmp_path)
    said = "Not logged in - Please run /login"

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(
            ends(
                is_error=True,
                result=said,
                terminal_reason="api_error",
                stop_reason="stop_sequence",
            )
        )

    with pytest.raises(UpstreamUnavailable) as raised:
        await offline(play, task_in(repo), monkeypatch)
    assert said in str(raised.value), (
        f"an error result was reported as a reason AGL could not read rather than as the failure "
        f"it is: {raised.value}. What the CLI said is what a person can act on"
    )

def test_the_bundled_binary_declares_every_terminal_reason_this_module_accounts_for() -> None:
    """The one thing in this file that would have caught the drift that produced it.

    Every other test here runs against a fake, so this suite's total was identical either side of
    a bump that moved both agent tools, with this adapter reading four of the nineteen values below
    throughout. This reads the binary the wheel ships: its result schema validates against one
    array literal per group, so the two are found by a value each rather than by the minifier's
    name for them, and a release that adds a twentieth fails here naming it. Failing rather than
    warning is the point - the decision a new value needs is which of the two lists it belongs in,
    and nobody makes that one unprompted.
    """
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    if not bundled.is_file():
        pytest.skip(f"this wheel bundles no binary at {bundled}, so it declares nothing to read")
    declared = _declared_reasons(bundled)
    if not declared:
        pytest.skip(
            f"neither array literal was found in {bundled}: this scan has gone stale against the "
            f"vendor's bundler rather than the tables having gone stale against the vendor"
        )
    accounted = set(_session._TERMINAL_REASONS) | set(REFUSED_REASONS)
    assert declared == accounted, (
        f"the bundled binary declares {sorted(declared - accounted)} that nothing here accounts "
        f"for, and this module claims {sorted(accounted - declared)} it no longer declares. Each "
        f"new one is either a `StopReason` in `_session._TERMINAL_REASONS` or a run refused by "
        f"name in `REFUSED_REASONS`, and reading it as an ordinary answer is neither"
    )

# Found by a member rather than by the identifier assigned to it, because the bundle is minified
# and those identifiers are regenerated on every build; the values are the vendor's and are not.
def _declared_reasons(bundled: Path) -> set[str]:
    found: set[str] = set()
    with bundled.open("rb") as handle, mmap(handle.fileno(), 0, access=ACCESS_READ) as image:
        for anchor in (b"aborted_streaming", b"turn_setup_failed"):
            literal = re.search(rb'\[(?:"[a-z_]+",)*"' + anchor + rb'"(?:,"[a-z_]+")*\]', image)
            if literal is not None:
                found.update(member.decode() for member in re.findall(rb'"([a-z_]+)"', literal[0]))
    return found

# --- The deny rules: that a name still exists, and the seam denied whatever a task asked for -----

def test_no_deny_rule_this_adapter_sends_names_a_tool_the_bundled_binary_removed() -> None:
    """The vendor's own removal channel, read off the binary rather than trusted to stay put.

    A deny rule is enforced by name, so a name the CLI no longer knows is a restriction that has
    quietly stopped existing while the rule still reads like one. The binary keeps a set of the
    names it has retired - `TeamCreate`, `AutofixPr` and nine others in the release
    `_version.TESTED` names - and logs a rule naming one as *removed* rather than as a typo. That
    set is the half of the question a literal answers honestly.

    **The other half is not covered here and it is worth saying which.** A name that was never in
    the registry at all - `MultiEdit` was one until it came out of `translate._DENIALS` - draws a
    different line, and it goes only into the file `--debug-file` names: never stderr, never
    stdout, never the SDK's `stderr` callback. Reading it costs a CLI that starts, composes a
    session and gets far enough to resolve its permission rules, which is not a thing this gate has
    a cheap way to do. So this asserts what a literal can and claims no more.
    """
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    if not bundled.is_file():
        pytest.skip(f"this wheel bundles no binary at {bundled}, so it declares nothing to read")
    retired = _retired_tools(bundled)
    if not retired:
        pytest.skip(
            f"the retired-tool set was not found in {bundled}: this scan has gone stale against "
            f"the vendor's bundler rather than the rules having gone stale against the vendor"
        )
    named = {
        rule.partition("(")[0]
        for rule in (*_every_denial(), *_tools.ASKING_MECHANISMS_DENIED, *CROSS_SESSION_DENIED)
    }
    assert not named & retired, (
        f"these deny rules name tools the release has retired: {sorted(named & retired)}. The "
        f"rule is enforced by name, so what it used to cover is now covered by nothing - either "
        f"the tool's replacement is what belongs in the table, or nothing does"
    )

def _every_denial() -> tuple[str, ...]:
    every = (restraint(frozenset({member})).denied_tools for member in Restriction)
    return tuple(rule for rules in every for rule in rules)

# The same reading as `_declared_reasons` above and for the same reason: found by a member, because
# the identifier the minifier gave the set is regenerated on every build and the names are not.
def _retired_tools(bundled: Path) -> set[str]:
    with bundled.open("rb") as handle, mmap(handle.fileno(), 0, access=ACCESS_READ) as image:
        literal = re.search(rb'\[(?:"[A-Za-z]+",)*"TeamCreate"(?:,"[A-Za-z]+")*\]', image)
        if literal is None:
            return set()
        return {member.decode() for member in re.findall(rb'"([A-Za-z]+)"', literal[0])}

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("restrictions", "what"),
    [(frozenset(), "a task declaring none"), (frozenset(Restriction), "a task declaring all four")],
)
async def test_every_run_denies_the_cross_session_tools_whatever_restrictions_the_task_declares(
    restrictions: frozenset[Restriction], what: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unconditional is the claim, so the unrestricted task is the row that carries it.

    A `Restriction` is a workflow author's statement about what this step is for, and reaching a
    session AGL did not start is outside every one of the four: the CLI listens on a socket per
    process that takes injected user messages from anything running as the same user, so it is not
    the network `NO_NETWORK` speaks about, and an author who declared nothing has asked for a free
    agent rather than for a channel into somebody else's run.

    Read off the options the real `run` composed rather than off a rebuild here, for the reason
    `Watched` gives: a reconstruction asserts that this file can call `ClaudeAgentOptions`.
    """
    repo = workspace(tmp_path)
    sent: list[str] = []

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(ends(result="done", terminal_reason="completed"))

    def capturing(*, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        from claude_agent_sdk import query

        sent.extend(options.disallowed_tools)
        return query(prompt=prompt, options=options, transport=Scripted(play))

    monkeypatch.setattr(_session, "query", capturing)
    await ClaudeCodeRunner().run(replace(task_in(repo), restrictions=restrictions))

    assert set(CROSS_SESSION_DENIED) <= set(sent), (
        f"{sorted(set(CROSS_SESSION_DENIED) - set(sent))} reached the CLI undenied for {what}. "
        f"`SendMessage` takes a recipient and `ListAgents` is what lists the recipients to it; the "
        f"rest arm a turn that fires after this run has answered"
    )

@pytest.mark.asyncio
async def test_a_result_from_an_injected_turn_is_not_the_outcome_the_run_answers_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The last result wins, and this is what stops it being somebody else's last result.

    A string prompt is not a one-shot on the wire: `subprocess_cli` sends every prompt through
    `--input-format stream-json`, which is the mode the SDK's own `MessageOrigin` was added for -
    turns the session injects interleave with the turn this adapter asked for. A result carrying
    one of those is the answer to a question AGL did not put, and answering with it records a step
    on text no fingerprint covers and a stop reason nothing here asked about.

    `peer` is the kind a message from another session arrives under. The injected result is scripted
    *after* AGL's own and carries a `LIMIT` reason, so a reading that kept the last result would
    fail on the text and on the stop reason both, rather than on whichever happened to differ.
    """
    repo = workspace(tmp_path)

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(ends(result="what this run asked for", terminal_reason="completed"))
        await cli.say(
            ends(
                result="what somebody else asked for",
                terminal_reason="max_turns",
                origin={"kind": "peer", "from": "another session"},
            )
        )

    outcome = await offline(play, task_in(repo), monkeypatch)

    answered = AgentOutcome(stop_reason=StopReason.COMPLETED, text="what this run asked for")
    assert outcome == answered, (
        f"the run answered {outcome!r}, which is the injected turn's result and not its own. "
        f"`ResultMessage.origin` is `None` for a prompt `query` sent, and the CLI attributes "
        f"everything else"
    )

@pytest.mark.asyncio
async def test_a_run_that_saw_nothing_but_injected_results_is_refused_rather_than_answered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passing one over is not the same as having one, and the existing refusal is what says so.

    Skipping the injected result leaves this run with no result at all, which is the case
    `outcome_of` already refuses by name - so the seam needs no second refusal of its own and gets
    none. The alternative, reading the injected result because it is the only one there, is the
    defect written the other way round.
    """
    repo = workspace(tmp_path)

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(
            ends(
                result="not this run's answer",
                terminal_reason="completed",
                origin={"kind": "peer"},
            )
        )

    with pytest.raises(UpstreamUnexpected) as refused:
        await offline(play, task_in(repo), monkeypatch)
    assert "never said how the run ended" in str(refused.value), (
        f"a run holding only an injected result was refused as something else: {refused.value}"
    )

@pytest.mark.asyncio
async def test_a_result_stamped_as_a_humans_own_prompt_is_read_as_this_runs_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The vendor's own predicate, followed rather than narrowed, and this is what that buys.

    `MessageOrigin`'s documented test for "a turn this application submitted" is `origin is None or
    origin["kind"] == "human"`, and `human` is the one kind the CLI honours from an SDK host. AGL
    stamps nothing, so its own results arrive unattributed today - but a release that started
    stamping them would, under a stricter reading here, make this adapter discard its own answer
    and refuse every run for a CLI that never said how it ended.
    """
    repo = workspace(tmp_path)

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(
            ends(result="this run's answer", terminal_reason="completed", origin={"kind": "human"})
        )

    outcome = await offline(play, task_in(repo), monkeypatch)

    assert outcome.text == "this run's answer", (
        f"a result the CLI attributed to a human prompt was passed over: {outcome!r}. That kind is "
        f"the SDK's own spelling of a turn the host submitted"
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
async def test_a_cli_that_dies_before_it_says_anything_reports_what_it_printed_instead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure above with its result frame taken away, which is a different code path entirely.

    `_internal/query.py` upgrades a trailing `ProcessError` to a `ResultError` **only** when an
    error result preceded it; a CLI that refuses to start has sent none, so the bare `ProcessError`
    is what arrives - and its `stderr` attribute is the fixed string
    `"Check stderr output for details"` that `_internal/transport/subprocess_cli.py` writes for
    every non-zero exit. Everything actionable is in the stream `Stderr` collected.

    The line scripted here is verbatim what CLI 2.1.277 prints when `CLAUDE_CODE_RESTRICTED`
    reaches it, which `adapters/claude_code/_environment.py` now keeps out of the child - so this
    is the class of failure and not that one cause.
    """
    repo = workspace(tmp_path)
    printed = "Error: bypassPermissions not supported in restricted mode"

    async def play(cli: Scripted) -> None:
        await cli.fail(
            ProcessError(
                "Command failed with exit code 1",
                exit_code=1,
                stderr="Check stderr output for details",
            )
        )

    with pytest.raises(UpstreamUnavailable) as raised:
        await offline(play, task_in(repo), monkeypatch, printed=(printed,))
    assert printed in str(raised.value), (
        f"a run that died carries no word of why: {raised.value}. AGL registers the stderr sink "
        f"that makes the SDK pipe that stream away from the operator's terminal, so this message "
        f"is the only copy there is and a person reading it is told to fix they know not what"
    )

@pytest.mark.asyncio
async def test_an_error_result_with_no_exit_behind_it_also_ends_with_the_printed_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other refusal `_session.py` raises, reached when the stream ends rather than raises.

    Claude Code exits non-zero after every error result, so this branch answers for a CLI that
    did not - a version that stops emitting the exit, or a transport that swallows it. It is the
    branch with no exception to read, which makes the printed line the only thing it has.
    """
    repo = workspace(tmp_path)
    printed = "Error: config file at /etc/claude/managed.json is not readable"

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        await cli.say(ends(is_error=True, result="the run did not finish"))

    with pytest.raises(UpstreamUnavailable) as raised:
        await offline(play, task_in(repo), monkeypatch, printed=(printed,))
    assert str(raised.value).endswith(printed), (
        f"an error result was reported without what the CLI printed beside it: {raised.value}"
    )

def probing(
    monkeypatch: pytest.MonkeyPatch, play: Callable[[Scripted], Awaitable[None]], printed: str
) -> None:
    """Point `check_ready` at a scripted CLI, with `printed` fed to the sink the probe itself built.

    `offline` above does this for `run`; the probe assembles its own options in `runner.py` and
    calls the `query` imported there, so it needs the same treatment against the other name.
    """

    def scripted(*, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        from claude_agent_sdk import query

        assert options.stderr is not None, "the readiness probe registered no stderr sink at all"
        options.stderr(printed)
        return query(prompt=prompt, options=options, transport=Scripted(play))

    monkeypatch.setattr(runner_module, "query", scripted)

@pytest.mark.asyncio
async def test_a_readiness_probe_that_dies_reports_what_the_cli_printed_before_it_died(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`check_ready` built a `Stderr`, handed it to the SDK and then read nothing off it.

    That is the same seam as the run's: an adapter that registers the sink and drops what lands in
    it. It is worth its own test because the object is built in `runner.py` rather than in
    `_session.py` and is threaded through neither - so the run's fix reaches it only if this one
    call site is changed too, and nothing but this would say it was not.
    """
    printed = "Error: bypassPermissions not supported in restricted mode"

    async def play(cli: Scripted) -> None:
        await cli.fail(
            ProcessError(
                "Command failed with exit code 1",
                exit_code=1,
                stderr="Check stderr output for details",
            )
        )

    probing(monkeypatch, play, printed)
    with pytest.raises(UpstreamUnavailable) as raised:
        await ClaudeCodeRunner().check_ready(Claude.HAIKU)
    assert printed in str(raised.value), (
        f"the readiness refusal says nothing about why: {raised.value}. This message is what "
        f"preflight prints and the whole of what an operator gets before a run is abandoned"
    )

@pytest.mark.asyncio
async def test_a_readiness_probe_refused_by_a_result_frame_also_names_what_was_printed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe's other refusal, which reads the error out of a result frame rather than out of an
    exception.

    It is the branch that looks as though it needs nothing more - it has the CLI's own `result`
    text - and the stream is still where a reason the CLI never put in a frame ends up, a managed
    policy's complaint among them. Both of the probe's refusals end the same way for that reason.
    """
    printed = "Error: settings file at /Library/Application Support/ClaudeCode is unreadable"

    async def play(cli: Scripted) -> None:
        await cli.say(ends(is_error=True, subtype="error_during_execution", result=None))

    probing(monkeypatch, play, printed)
    with pytest.raises(UpstreamUnavailable) as raised:
        await ClaudeCodeRunner().check_ready(Claude.HAIKU)
    assert str(raised.value).endswith(printed), (
        f"the readiness refusal stops at the frame's own subtype: {raised.value}"
    )

def test_the_tail_an_error_message_carries_is_bounded_in_lines_and_in_characters() -> None:
    """Both bounds, because either alone lets an exception message become a log file.

    The SDK frames stderr into lines but flushes a partial one only once it passes
    `max_buffer_size` - a megabyte by default - so fifty lines is fifty megabytes and not a bound
    an error message can rely on. Both are taken off the end, which is where a CLI's fatal line is.
    """
    stderr = _session.Stderr()
    for number in range(_session._STDERR_LINES * 3):
        stderr(f"line {number}")
    kept = stderr.tail().splitlines()
    assert len(kept) == _session._STDERR_LINES, f"{len(kept)} lines survived the line bound"
    assert kept[-1] == f"line {_session._STDERR_LINES * 3 - 1}", kept[-1]

    shouting = _session.Stderr()
    shouting("x" * (_session._STDERR_CHARACTERS * 4))
    shouting("Error: the sentence a person needs")
    bounded = shouting.tail()
    assert len(bounded) == _session._STDERR_CHARACTERS, len(bounded)
    assert bounded.endswith("Error: the sentence a person needs"), (
        "the character bound took the front of the stream and dropped the end, which is the half "
        "a failure is described in"
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
    """The suite asserts this too; what it cannot assert is *which* three, and why they are static.

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
    ignored its argument would answer "I can do all three" for a model this runner would then refuse
    to run, which is a preflight that admits a run and kills it at second one.
    """
    with pytest.raises(InputError):
        asyncio.run(ClaudeCodeRunner().capabilities(OpenAI.SOL))
    with pytest.raises(InputError):
        asyncio.run(ClaudeCodeRunner().check_ready(OpenAI.SOL))

# --- Effort: what a chosen level reaches the CLI as, and what a bare model leaves alone ----------

async def opened(task: AgentTask, monkeypatch: pytest.MonkeyPatch) -> ClaudeAgentOptions:
    """Run `task` offline to an ordinary finish and hand back the options its session was opened
    with - the object `run` built, not a rebuild of it in this file."""
    handed: list[ClaudeAgentOptions] = []

    async def play(cli: Scripted) -> None:
        await cli.say(init(task.workspace))
        await cli.say(ends(result="done", terminal_reason="completed"))

    transport = Scripted(play)

    def scripted(*, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        from claude_agent_sdk import query

        handed.append(options)
        return query(prompt=prompt, options=options, transport=transport)

    monkeypatch.setattr(_session, "query", scripted)
    outcome = await ClaudeCodeRunner().run(task)
    assert outcome == AgentOutcome(stop_reason=StopReason.COMPLETED, text="done")
    assert len(handed) == 1, f"one run opened {len(handed)} sessions"
    return handed[0]

def command_line(options: ClaudeAgentOptions) -> list[str]:
    """The argv the vendor SDK would start its CLI with for `options`, composed and not started.

    `_build_command` is the SDK's own composition, so an option that type-checks and is then dropped
    or spelled differently on the way to the process shows up here and nowhere else offline. It
    refuses to compose without a resolved binary, and resolving one is what `connect` would do, so
    a path that is never executed stands in for it.
    """
    unstarted = SubprocessCLITransport("", replace(options, cli_path="/nonexistent/claude"))
    return unstarted._build_command()

def _flag_values(argv: list[str], flag: str) -> list[str]:
    """Every value `flag` is given in `argv`, in the two-token form and the `--flag=value` one."""
    spaced = [argv[at + 1] for at, token in enumerate(argv[:-1]) if token == flag]
    joined = [token.partition("=")[2] for token in argv if token.startswith(f"{flag}=")]
    return spaced + joined

@pytest.mark.asyncio
@pytest.mark.parametrize("effort", list(ClaudeEffort))
async def test_a_model_chosen_at_an_effort_opens_its_session_at_that_level(
    effort: ClaudeEffort, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The level reaches the SDK as `effort`, and the SDK's command line as one `--effort`.

    The model is asserted beside it because a table keyed by the bare member and looked up with
    the whole choice type-checks and misses: `model_name` would refuse the run outright, so a
    session opened on `opus` is the evidence that the lookup was made with `model_of`.
    """
    chosen = Claude.OPUS(effort=effort)
    options = await opened(task_in(workspace(tmp_path), model=chosen), monkeypatch)

    assert options.model == "opus", f"the session was opened on {options.model!r}"
    assert options.effort == effort.value, (
        f"the session was opened at effort {options.effort!r} for a role that chose {effort!r}. "
        f"A level that does not arrive runs the model at the CLI's default under a fingerprint "
        f"that records the level the workflow asked for"
    )
    assert _flag_values(command_line(options), "--effort") == [effort.value]

@pytest.mark.asyncio
@pytest.mark.parametrize("model", list(Claude))
async def test_a_bare_model_opens_its_session_with_no_effort_on_the_command_line(
    model: Claude, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A member written without an effort runs exactly as it did before efforts existed.

    `None` is the SDK's "append nothing", and the command line is read as well as the option,
    because what leaves the CLI its own default is the absence of the flag rather than the value
    of a Python attribute.
    """
    options = await opened(task_in(workspace(tmp_path), model=model), monkeypatch)

    assert options.effort is None, f"a bare {model!r} was opened at effort {options.effort!r}"
    assert _flag_values(command_line(options), "--effort") == []

@pytest.mark.asyncio
async def test_the_readiness_probe_sends_no_effort_to_the_cli_it_asks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`check_ready` is asked about the bare model and spends a turn, so it chooses no level.

    The port hands it a `ModelId` and never a choice, which is what keeps one paid probe per model
    rather than one per level an author wrote; the probe's own session is read back to show the
    level did not come in some other way.
    """
    handed: list[ClaudeAgentOptions] = []

    async def play(cli: Scripted) -> None:
        await cli.say(ends(result="ready", terminal_reason="completed"))

    def scripted(*, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        from claude_agent_sdk import query

        handed.append(options)
        return query(prompt=prompt, options=options, transport=Scripted(play))

    monkeypatch.setattr(runner_module, "query", scripted)
    await ClaudeCodeRunner().check_ready(Claude.OPUS)

    assert len(handed) == 1, f"the probe opened {len(handed)} sessions"
    assert handed[0].effort is None, f"the probe was opened at effort {handed[0].effort!r}"
    assert _flag_values(command_line(handed[0]), "--effort") == []

# What the operator's shell may be carrying when AGL starts, and the four shapes that matter: a
# level, the two words the CLI reads as "send no effort parameter at all", and the variable simply
# not being there. `None` is that last one and is spelled `delenv` below.
AMBIENT_EFFORT: Final[tuple[str | None, ...]] = (None, "low", "unset", "auto")

@pytest.mark.asyncio
@pytest.mark.parametrize("ambient", AMBIENT_EFFORT)
async def test_a_run_opens_its_session_with_the_operators_own_effort_level_cleared(
    ambient: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one variable that outranks the level a workflow chose, held to the same value always.

    `CLAUDE_CODE_EFFORT_LEVEL` wins over `--effort` in the CLI `_version.TESTED` names - measured
    through `get_settings`, which reports `applied.effort` as `low` for a session opened
    `--effort xhigh` with `low` in the environment. `ports/agent.py` says the chosen effort is
    fingerprinted into every step, so an uncleared variable journals a level that never ran and
    replay keys on it, with nothing downstream able to tell. Clearing it is what makes the journal
    true; a warning would leave it false.

    **Asserted on the environment the child is handed rather than on `options.env`**, because those
    are two different things and only the first is the claim. `subprocess_cli.py` composes the
    child's environment by merging `options.env` over the inherited one, so a key there can be *set*
    and never removed; `_environment.withheld` blanks a vendor name the shell is carrying and writes
    nothing for one it is not, so the mapping alone answers differently in the two cases while the
    child's environment answers the same. The merge below is the SDK's own, spelled out.

    **The empty string and not `"unset"`** is what a blank is, and it is
    `test_the_blank_a_withheld_name_gets_is_what_the_cli_reads_as_no_level` that holds it:
    `"unset"` looks like "as if it had not been exported" and is not - the CLI reads it as an
    instruction to send no effort parameter at all, which moves a bare model off the default it
    would otherwise run at.

    Parametrised over what the shell may hold because the answer must not depend on it. A reading
    of the ambient variable here - clearing it only when it is set, or passing it through when it
    says `auto` - would be an adapter whose fingerprints are right on one machine and wrong on the
    next, which is the failure this is about wearing a different hat.
    """
    if ambient is None:
        monkeypatch.delenv("CLAUDE_CODE_EFFORT_LEVEL", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", ambient)
    chosen = Claude.OPUS(effort=ClaudeEffort.XHIGH)

    options = await opened(task_in(workspace(tmp_path), model=chosen), monkeypatch)

    handed = {**os.environ, **options.env}
    assert handed.get("CLAUDE_CODE_EFFORT_LEVEL", "") == "", (
        f"the child would be handed CLAUDE_CODE_EFFORT_LEVEL="
        f"{handed['CLAUDE_CODE_EFFORT_LEVEL']!r} while the shell carried {ambient!r}, out of env "
        f"{options.env!r}. The variable outranks `--effort`, so the run would have been taken at "
        f"the operator's level under a fingerprint recording {ClaudeEffort.XHIGH.value!r}"
    )
    assert options.effort == ClaudeEffort.XHIGH.value, (
        f"the level the role chose stopped reaching the session: {options.effort!r}. Clearing the "
        f"variable is only the half that stops the environment deciding; the flag still has to say"
    )

@pytest.mark.asyncio
async def test_the_readiness_probe_clears_that_level_too_although_its_options_name_no_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe is the row where the environment alone decides, so it needs the clearing most.

    `check_ready` deliberately sends no `--effort` at all -
    `test_the_readiness_probe_sends_no_effort_to_the_cli_it_asks` is that decision - which leaves
    the variable as the only thing choosing a level for it. So an operator who exports
    `CLAUDE_CODE_EFFORT_LEVEL` for their own interactive use is one whose readiness probe is taken
    at that level, and `unset` or `auto` is one whose probe sends no effort parameter where the
    model's own default would otherwise go out.

    That makes this the opposite of a copy of the test above. There the clearing keeps a chosen
    level from being overruled; here there is no chosen level to overrule, and what the clearing
    buys is that the probe asks the same question on every machine.
    """
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "low")
    handed: list[ClaudeAgentOptions] = []

    async def play(cli: Scripted) -> None:
        await cli.say(ends(result="ready", terminal_reason="completed"))

    def scripted(*, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        from claude_agent_sdk import query

        handed.append(options)
        return query(prompt=prompt, options=options, transport=Scripted(play))

    monkeypatch.setattr(runner_module, "query", scripted)
    await ClaudeCodeRunner().check_ready(Claude.OPUS)

    assert len(handed) == 1, f"the probe opened {len(handed)} sessions"
    assert {**os.environ, **handed[0].env}.get("CLAUDE_CODE_EFFORT_LEVEL", "") == "", (
        f"the probe was opened with env {handed[0].env!r}. Its options carry no effort of their "
        f"own, so whatever the shell exported is what the probe would have been taken at"
    )

def test_every_session_this_package_starts_is_opened_on_the_allowlisted_environment() -> None:
    """A structural assertion, so a third session cannot arrive carrying the operator's own.

    `test_every_session_this_package_opens_is_opened_hermetically` is this test's sibling and gives
    the argument for the shape: where a property holds of every session, the assertion that reads
    the package beats the one that runs it, because it covers call sites that do not exist yet.
    Both sessions here are also asserted by running them, above; this is what those two cannot say
    about a third.

    **`cwd=` is the discriminator, and it is a fact about what the options are for rather than a
    list of filenames.** `_version.py` builds a `ClaudeAgentOptions` too, and it is right that it
    carries no `env=`: nothing is ever started with it - `probed` hands it to the SDK's resolver
    purely so `cli_path` can be read back off it, and a child process that is never spawned has no
    environment to compose. A session runs somewhere and says so; that object does not, and a list
    of exempt module names here would go stale the first time one is renamed.

    The expression rather than the mapping is what each call site is required to spell, which is
    where this parts company with the hermeticity scan: that one refuses a name deliberately,
    because three unrelated settings each have one right value and a reader wants to see it at the
    site. Here the two sessions must agree, and what they agree on is a decision taken over 694
    vendor names - not a value any reader could check by looking at it.
    """
    package = Path(runner_module.__file__).parent
    sessions = 0
    for source in sorted(package.glob("*.py")):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "id", None) != "ClaudeAgentOptions":
                continue
            given = {keyword.arg: keyword.value for keyword in node.keywords}
            if "cwd" not in given:
                continue
            sessions += 1
            written = "env" in given and ast.unparse(given["env"]) == "withheld(os.environ)"
            assert written, (
                f"{source.name}:{node.lineno} opens a session in a directory without passing "
                f"`env=withheld(os.environ)`: it passes "
                f"{sorted(name for name in given if name)}. The SDK hands the child the operator's "
                f"whole environment, and 694 names in it configure the CLI - so a session opened "
                f"without this runs under settings AGL neither chose nor records"
            )
    assert sessions >= 2, (
        f"only {sessions} ClaudeAgentOptions call(s) in {package} name a `cwd`, and there are at "
        f"least two - the run and the readiness probe. This test found nothing to check, which "
        f"means it is no longer checking anything"
    )

@pytest.mark.asyncio
@pytest.mark.parametrize("model", list(OpenAI))
async def test_a_model_of_the_other_provider_at_an_effort_is_refused_before_anything_starts(
    model: OpenAI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An effort does not make an OpenAI model one this adapter serves, and nothing is opened."""
    started = False

    def never(**kwargs: object) -> AsyncIterator[Any]:
        nonlocal started
        started = True
        raise AssertionError("a session was opened for a model this adapter does not serve")

    monkeypatch.setattr(_session, "query", never)

    with pytest.raises(InputError) as refused:
        await ClaudeCodeRunner().run(
            task_in(workspace(tmp_path), model=model(effort=OpenAIEffort.HIGH))
        )
    assert str(model) in str(refused.value)
    assert not started, "the refusal came too late to be a refusal"

# --- The environment: what the allowlist lets past, and what a shell no longer decides -----------

# Each of these was measured against the release `_version.TESTED` names, through `connect()` and
# the `get_server_info` and `get_settings` control requests with no user message - so every row
# below cost nothing. The value is what a shell might hold; the comment is what it did.
HAZARDS: Final[tuple[tuple[str, str, str], ...]] = (
    # The CLI refuses `bypassPermissions` outright and the process exits 1, so this one name ends
    # every run AGL takes. Read eight times in the bundle and new in 2.1.248.
    ("CLAUDE_CODE_RESTRICTED", "1", "the run died with a ProcessError instead of starting"),
    # The `opus` row leaves the catalogue and `--model opus` resolves to Haiku, which fingerprints
    # as `Claude.OPUS` and reasons at no effort at all.
    ("ANTHROPIC_DEFAULT_OPUS_MODEL", "claude-haiku-4-5-20251001", "opus resolved to haiku"),
    ("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-haiku-4-5-20251001", "sonnet resolved to haiku"),
    ("ANTHROPIC_DEFAULT_HAIKU_MODEL", "claude-opus-5", "haiku resolved to opus"),
    ("ANTHROPIC_DEFAULT_MODEL", "claude-haiku-4-5-20251001", "the default resolved to haiku"),
    ("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001", "the model resolved to haiku"),
    # The level that outranks `--effort`, under AGENTS.md's "Invariants where a mistake is
    # silent", and the two tests above hold it at the call sites.
    ("CLAUDE_CODE_EFFORT_LEVEL", "low", "a session opened `--effort xhigh` applied `low`"),
    # Where the CLI writes, regardless of what `enable_file_checkpointing` says: the SDK sets this
    # when the option is on and never unsets it when the option is off.
    ("CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING", "true", "the CLI checkpointed to its own store"),
    # A socket path and a token for the parent session's injected-turn seam, both present in a
    # Claude Code desktop session's own environment. A capability rather than a preference, and the
    # half `translate.CROSS_SESSION_DENIED` cannot shut, the child's own socket being unconditional.
    ("CLAUDE_CODE_MESSAGING_SOCKET", "/tmp/cc-socks/1.sock", "the child held the parent's seam"),
    ("CLAUDE_CODE_MESSAGING_TOKEN", "deadbeef", "the child held the parent's seam"),
)

@pytest.mark.parametrize(("name", "value", "consequence"), HAZARDS)
def test_every_measured_hazard_an_operators_shell_carries_is_blanked_before_the_cli_reads_it(
    name: str, value: str, consequence: str
) -> None:
    """The named cases, each with what it was measured doing when it got through.

    Parametrised over names rather than asserted as a set, because what is being claimed is one
    thing per row: that this name, with this value, does not reach the CLI. A single assertion over
    a set would pass with the set empty, and a set is also the wrong shape - the allowlist is not a
    list of these, it is the whole namespace less the dozen that carry a credential or an endpoint,
    so these rows are evidence that the general rule catches the specific cases rather than being
    the rule.
    """
    blanks = withheld({name: value})

    assert blanks.get(name) == "", (
        f"{name}={value!r} reaches the CLI: the mapping is {blanks!r}. Measured consequence when "
        f"it did: {consequence}"
    )

def test_the_blank_a_withheld_name_gets_is_what_the_cli_reads_as_no_level() -> None:
    """`""` and not `"unset"`, which is the whole reason a blank is the mechanism.

    Both look like "as if it had never been exported" and only one is. Measured through the bundled
    binary's own `get_settings`, which reports the resolver's output: with the level blank, a bare
    `opus` session applies `high`, the model's own default, exactly as it does with the name unset;
    with `unset` or `auto` it applies nothing at all, so a bare model's *sent* default
    becomes no parameter. This is asserted on the value rather than on the behaviour because the
    behaviour costs a CLI and the gate has none - `HAZARDS` above carries what the measurement was.
    """
    blanks = withheld({"CLAUDE_CODE_EFFORT_LEVEL": "low"})

    assert blanks == {"CLAUDE_CODE_EFFORT_LEVEL": ""}, (
        f"a withheld name is handed {blanks!r}. `unset` and `auto` are the values that look right "
        f"and suppress the effort parameter altogether, and `subprocess_cli` offers no third "
        f"option - it merges this over what it inherited and cannot take a key away"
    )

# The two `tests/conftest.py` exports at every test in this repository, spelled as a tuple and not
# as a mapping: a mapping keyed by one of these is the shape of a composed subprocess environment,
# which is what `scripts/check`'s paid-endpoint gate scans this tree for and rightly refuses. What
# is below is a pure function's argument and points nothing anywhere.
GUARDED_BY_CONFTEST: Final[tuple[str, ...]] = ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY")

def test_the_two_variables_the_paid_endpoint_guard_exports_reach_the_cli_a_test_starts() -> None:
    """The one that would fail silently and cost money, so it is asserted by name.

    `tests/conftest.py` exports a loopback base URL and a dummy key for every test in this
    repository, and its whole mechanism is that a `claude` a test spawns *inherits* them -
    `check_ready` above spawns one on every `scripts/check`. An allowlist that withheld either would
    defeat the guard while every existing test stayed green: the redirect tests read `os.environ`
    rather than the child's environment, and a run that reached the paid endpoint would answer
    correctly and pass. Withholding the key is the worse of the two, because the CLI then falls back
    to the operator's own OAuth bearer token and sends it to whatever is on the redirected port.
    """
    carried = dict.fromkeys(GUARDED_BY_CONFTEST, "whatever tests/conftest.py exported")

    assert withheld(carried) == {}, (
        f"the allowlist withholds {sorted(withheld(carried))} from a CLI a test starts. "
        f"`scripts/check`'s paid-endpoint gate proves a newly written test file inherits both, and "
        f"this is the other end of the same claim: that what it inherits is what the child gets"
    )

def test_no_name_outside_the_vendors_own_namespace_is_touched_by_this_allowlist() -> None:
    """The scope, and the reason no list here enumerates what a subprocess cannot run without.

    An agent runs the target repository's own build, so the environment it needs is the operator's
    machine: a toolchain root, a locale, a CA bundle, a package manager's cache. AGL could not
    enumerate that set and has no business deciding it - what it decides is the namespace that
    configures the *harness*, which is why `PATH` and `HOME` never had to be argued about.
    """
    machine = {
        "PATH": "/usr/bin",
        "HOME": "/Users/someone",
        "TMPDIR": "/var/folders/x/",
        "SHELL": "/bin/zsh",
        "LANG": "en_GB.UTF-8",
        "SSL_CERT_FILE": "/etc/ssl/cert.pem",
        "HTTPS_PROXY": "http://proxy:3128",
        "JAVA_HOME": "/opt/jdk",
    }

    assert withheld(machine) == {}, (
        f"the allowlist reaches {sorted(withheld(machine))}, which are the operator's machine and "
        f"not this vendor's configuration. A run that loses one of them is a run whose agent "
        f"cannot build the repository it was given"
    )

def test_the_three_names_the_sdk_writes_itself_are_left_for_the_sdk_to_write() -> None:
    """Not withheld and not passed through: absent from the mapping, because the SDK decides them.

    `subprocess_cli.connect` composes the child's environment as the inherited one with `CLAUDECODE`
    dropped, then `CLAUDE_CODE_ENTRYPOINT`, then `options.env`, then `CLAUDE_AGENT_SDK_VERSION`.
    `CLAUDE_CODE_ENTRYPOINT` is the one that bites: it is written *before* the merge, so a blank
    there replaces the SDK's own `sdk-py` with nothing and the CLI is told it was started by no
    entrypoint at all. The other two are harmless either way and are left out for one reason rather
    than two - a mapping AGL builds names what AGL decided.
    """
    theirs = {
        "CLAUDECODE": "1",
        "CLAUDE_CODE_ENTRYPOINT": "claude-desktop",
        "CLAUDE_AGENT_SDK_VERSION": "0.3.271",
    }

    assert withheld(theirs) == {}, (
        f"the mapping names {sorted(withheld(theirs))}, which `subprocess_cli` writes itself. "
        f"`CLAUDE_CODE_ENTRYPOINT` is merged over before `options.env` is, so a blank wins and the "
        f"session goes out with no entrypoint rather than with the SDK's"
    )

def test_a_vendor_name_the_shell_does_not_carry_is_not_invented_to_be_blanked() -> None:
    """An empty parent composes an empty mapping, which is what makes the blanking a response.

    Writing every hazard unconditionally would be a list of names again, kept by hand and stale on
    the next release. This reads what is there, so a name the vendor adds tomorrow is withheld the
    day an operator exports it and never before.
    """
    assert withheld({}) == {}, "the allowlist invented a name nothing exported"

# --- The version behind a model, read off the binary a session would actually start --------------

def _printing(root: Path, said: str, *, status: int = 0) -> Path:
    """A stand-in binary that prints `said` for any argument and exits, and starts no session."""
    binary = root / "claude-stub"
    binary.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdout.write({said!r})\nsys.exit({status})\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary

@pytest.mark.asyncio
async def test_a_configured_cli_path_is_the_binary_the_version_is_read_from(
    tmp_path: Path,
) -> None:
    """The case the whole of this probe's resolution exists for, and the one that is easy to lie in.

    The SDK bundles a binary and records its version in the package, so reading that record costs
    no process at all - and it describes the bundled binary whether or not the bundled binary is
    what runs. `cli_path` is exactly when it is not: `SubprocessCLITransport` takes the configured
    path outright and never resolves anything, so the bundled version would be a version reported
    for a binary this adapter will not start.

    This is the whole reason the version comes off a process rather than off `__cli_version__`: one
    spawn costs a tenth of a second, and a run that will spend a paid turn on `check_ready` a
    moment later is not the place to save it by reporting something that might be untrue.
    """
    binary = _printing(tmp_path, "9.9.9 (Claude Code)\n")

    reported = await ClaudeCodeRunner(binary).installation(Claude.HAIKU)

    assert reported.where == str(binary), (
        f"the version was read from {reported.where!r} and this adapter was configured with "
        f"{str(binary)!r}. A configured path is the binary, and no resolution runs at all"
    )
    assert reported.version == "9.9.9", (
        f"the version came back as {reported.version!r} from `9.9.9 (Claude Code)`. The product's "
        f"own name follows the number in parentheses and is no part of it"
    )
    assert reported.standing is Standing.ABOVE, (
        "a version above every one this adapter was exercised on stands above the range. There is "
        "nothing to refuse here - the run goes ahead - but there is something to say"
    )

@pytest.mark.asyncio
async def test_the_binary_nothing_configured_resolves_to_is_the_one_the_sdk_would_start(
    tmp_path: Path,
) -> None:
    """Resolution is the SDK's own, asked rather than copied, and this is what that buys.

    `_find_cli` prefers the binary the wheel bundles over a `claude` on `PATH`, and the two are
    routinely different versions on one machine - so a probe that reimplemented that order would
    report the wrong one the day the order changed, silently and in the direction of a warning
    nobody could act on. Compared against the resolver itself rather than against a path spelled
    out here, because a path spelled here is the copy this is written to avoid.

    The version is cross-checked against the SDK's own record of what it bundled, which is a second
    source for the same fact and the reason this clause is worth a process: a wheel whose recorded
    version and shipped binary disagree is invisible to either one alone.
    """
    resolved = SubprocessCLITransport(prompt="", options=ClaudeAgentOptions())._find_cli()

    reported = await ClaudeCodeRunner().installation(Claude.HAIKU)

    assert reported.where == resolved, (
        f"the version was read from {reported.where!r} and the SDK resolves {resolved!r}. These "
        f"are the same question, and a probe answering it differently reports a version for a "
        f"binary no session of this adapter's will ever start"
    )
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    if Path(resolved) != bundled:
        pytest.skip(
            f"the SDK resolved {resolved}, which is not the binary this wheel bundles, so there is "
            f"no second record of its version to compare against"
        )
    assert reported.version == __cli_version__, (
        f"the bundled binary printed {reported.version!r} and the SDK records {__cli_version__!r} "
        f"as what it bundled. One of the two is wrong about the file that is actually there"
    )

@pytest.mark.asyncio
async def test_a_binary_that_cannot_be_started_reports_no_version_and_still_names_it(
    tmp_path: Path,
) -> None:
    """The member that never raises, on the path where `check_ready` and `run` both do.

    `translate.py` turns a missing CLI into `UpstreamUnavailable` and preflight stops the run on
    it. This one is a warning's material and stops nothing: no version came back, the path it was
    looked for under is still reported, and the refusal is left to the member whose business it is.
    """
    missing = tmp_path / "no-such-binary"

    reported = await ClaudeCodeRunner(missing).installation(Claude.SONNET)

    assert reported.version is None
    assert reported.standing is Standing.UNREPORTED
    assert reported.where == str(missing)
    assert reported.tool, "a warning about a binary nobody found still has to name what it was"

@pytest.mark.parametrize(
    ("said", "status", "why"),
    [("", 0, "it printed nothing"), ("2.1.277 (Claude Code)\n", 3, "the binary failed")],
)
@pytest.mark.asyncio
async def test_a_binary_that_answers_oddly_reports_no_version_rather_than_a_guess(
    said: str, status: int, why: str, tmp_path: Path
) -> None:
    """An answer nobody measured is reported as unread, and a non-zero exit is not an answer."""
    binary = _printing(tmp_path, said, status=status)

    reported = await ClaudeCodeRunner(binary).installation(Claude.HAIKU)

    assert reported.version is None, f"{why}, and something was still reported as a version"

@pytest.mark.asyncio
async def test_this_adapter_reports_no_per_model_levels_because_it_asks_for_none(
    tmp_path: Path,
) -> None:
    """The asymmetry between the two backends, stated where it is decided rather than inferred.

    The other backend carries a listing a subcommand prints for free, so its half of a warning can
    name the level a task would be lowered to. This harness has one too, and reaching it costs a
    session rather than a flag - so this probe reports the version and nothing else, and the empty
    mapping is the port's own spelling of "the tool did not say".
    """
    reported = await ClaudeCodeRunner(_printing(tmp_path, "2.1.277 (Claude Code)\n")).installation(
        Claude.OPUS
    )

    assert reported.efforts == {}

def test_a_model_this_adapter_does_not_serve_is_refused_a_version_report_as_well() -> None:
    """The refusal the other two query members make, made here for the same reason.

    A runner that answered for a model it cannot run would put a warning about this harness in
    front of an operator whose role names a model some other backend serves.
    """
    with pytest.raises(InputError):
        asyncio.run(ClaudeCodeRunner().installation(OpenAI.SOL))
