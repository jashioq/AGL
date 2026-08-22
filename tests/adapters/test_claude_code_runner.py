"""`ClaudeCodeRunner` against the `AgentRunner` contract, plus the clauses that suite cannot see.

The first class is the port in full: `AgentContract` with its two fixtures overridden and nothing
else touched. That suite was written at stage 3, against the port's docstrings and before any
adapter existed (§1.9), which is why nothing below re-asserts any of it.

**Six of its eight tests start a real agent, and none of them runs - anywhere, on any machine.**
Every one of the six reads a *model's* conduct as its evidence: that it called a tool, that it
answered a question, that it ignored a repository's instructions. No free instrument can supply
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

That fixture was written here, at stage 7.1, and moved at 8.0a. A module-scoped autouse fixture
protects the file it is written in and no other, so a second adapter test file inherited nothing;
`harness` below is now an accessor onto the session's endpoint rather than a second listener. What
this file still owns is the assertion that the guard reached *it* - the endpoint the CLI is pointed
at being the same object these tests read their traffic off, which no repo-wide check can ask.

Two things follow, and both are wanted. `check_ready` is now exercised on the branch where it
**returns** - a success path this project had never observed, because the only machine that had ever
run it was logged out - and it costs nothing. And the four tests below that read a real session's
`init` now run a session **to completion**, where they used to wrap themselves in
`pytest.raises(UpstreamUnavailable)` and pass because a logged-out machine could not authenticate.
That is the failure `docs/agl-build-stages.md` records against this stage by name: "four tests were
green because the harness could not authenticate - they asserted the run would fail, and would have
passed with no harness installed at all." No test in this file passes because a run failed.

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
  * **That the workspace path never reaches a command line** (§3.5, and no gap of the suite's
    because the suite chooses no hostile path). Fired first as a control, then handed to the
    adapter, in the shape `tests/adapters/test_shell_verifier.py` established at stage 6.
  * **That a value which would parse as a flag is refused before anything starts** - the model, the
    CLI path, and a deny rule - which the suite cannot provoke because it supplies none of them.
  * **That every session this package opens is opened hermetically**, asserted by parsing the
    package rather than by running it, so a second session added later (a readiness probe, a
    version check) cannot quietly omit the two options whose SDK defaults are the leaky ones.
  * **That a tool call, a refusal, an activity line and a question round-trip work at all** (its
    gaps 7 and 12: most of that suite is behavioural and reads a model's conduct as evidence).
    Driven offline through a scripted `Transport`, which is the SDK's own injection point, so the
    real adapter, the real SDK message parsing and the real in-process MCP servers all run with no
    CLI and no model anywhere. **This is supplementary evidence and never acceptance**: a subagent's
    own test double is exactly what the stage-3 contract suites exist not to rely on, and every
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
from claude_agent_sdk import ClaudeAgentOptions, ProcessError
from claude_agent_sdk._internal.transport import Transport

from agl.adapters.claude_code import _session
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
from agl.ports.questions import Answer, Question
from agl.ports.run import JsonValue
from contracts._agent_hermeticity import CONFIGURATIONS, markers_in, plant
from contracts._agent_tasks import Notes, workspace
from contracts.agent import AgentContract
from instruments.loopback import DUMMY_KEY, REPLY, Loopback, wire_text

# The opt-in. It turns on the tests that spawn a real `claude` process against the loopback, and it
# does not turn on the six contract tests that read a model's conduct - nothing can, because no free
# instrument produces conduct. Two gates rather than one, because "the operator agreed to have
# processes started" and "there is a binary to start" are different facts with different fixes.
LIVE = "AGL_LIVE_AGENT"

# What a person is told when the six live tests do not run, which is always. Long on purpose: the
# whole point of this suite is that a green run means something, and a skip that reads like a pass
# is the failure `tests/contracts/agent.py` is written against.
_SKIPPED: Final = (
    "UNVERIFIED: this run did not start a real agent, so the ClaudeCodeRunner's entire run-path - "
    "the outcome, the refused tool call, the activity, both question clauses and the poisoned "
    "repository - is unverified by this run, and by every run. DEFERRED TO THE MANUAL QA PASS, "
    "with no switch here that changes it: each of these six reads a model's conduct as its "
    "evidence - that it called a tool, that it answered a question, that it ignored a poisoned "
    "repository - which no free instrument can supply, so running one costs a paid turn and no "
    "test in this build spends tokens. Run them by hand against an authenticated CLI, or do not "
    "believe them. What did run is everything below the contract subclass: a real CLI composing a "
    "real session against a loopback endpoint, so the options, the argv discipline, the registered "
    "tools and the request that left the machine are all asserted for real - plus the tool and "
    "question plumbing driven offline through a scripted transport. None of that covers a model "
    "deciding anything, and this skip is not a pass."
)

# The one extra sentence a machine carrying the opt-in gets. Appended rather than folded in, because
# it is true of one reader's environment and not of the deferral itself.
_OPTED_IN: Final = (
    f" ({LIVE}=1 is set here and it did turn on the live tests further down, which spawn a real "
    f"CLI against a loopback endpoint. It does not turn these six on and no variable can: what "
    f"they read is a model's conduct, and a loopback answers with whatever it was told to say.)"
)

# What a person is told when the CLI itself is missing. A different gate from the one above and kept
# separate on purpose: these tests need a process that starts, composes a session and prints its
# `init` message, which costs nothing and needs no authentication, so the only thing that can stop
# them is the binary not being there at all.
_NO_CLI: Final = (
    "UNVERIFIED: the Claude Code CLI is not on PATH, so nothing here could start it and read back "
    "the session it composed. The hermeticity options (§3.5), the argv discipline and the composed "
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
    f"options (§3.5), the argv discipline and the composed request are unverified by this run. "
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
    module-scoped autouse fixture right here, which protected this file and no other; stage 8 adds
    a second adapter test file, so it moved to `tests/conftest.py` where a module that has not been
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

    Unconditionally, because there is no condition worth writing: what the six tests behind it
    assert is a model's conduct, the only instrument that can answer is a paid one, and a test that
    spends money on a flag is still a test that spends money. They are deferred to the manual QA
    pass and the skip reason says so.
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

# How the model addresses AGL's asker: `mcp__<server>__<tool>`, and both halves of it are spelled in
# `_tools.py`. Written out here rather than imported because it is what a *model* sees, and the
# three tests using it check it against what the session advertises, what the composed request
# carries and what the prompt names - rather than against each other.
#
# Against a *list of names* this matches exactly; against prompt *text* it would be a substring, and
# a substring match is satisfied by any longer name beginning with this one - `_ASK` renamed to
# `ask_person` leaves `mcp__agl_ask__ask in prompt` green while naming a tool no session registers.
# `_MAY_ASK` renders the name inside backticks, so a prompt assertion matches `ASK_TOOL_NAMED`
# below: the closing delimiter is what makes it exact, and it needs no regex to be so.
ASK_TOOL: Final = "mcp__agl_ask__ask"
ASK_TOOL_NAMED: Final = f"`{ASK_TOOL}`"


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
    """§3.5 through the one window that needs no model: what the CLI says it registered.

    The contract suite's own hermeticity test can only see a leak an *agent acted on*, and says so
    about itself. This one sees the leak earlier and more certainly: a project subagent, a project
    slash command and a project MCP server planted in the workspace are all things the CLI reports
    by name on its `init` message, before a model exists to ignore them.

    The run **completes**, against the loopback, and the outcome is asserted before anything here is
    read. It used to end in `UpstreamUnavailable` and this test used to require that - which meant
    it passed on a machine with no session, and would have passed on a machine with no CLI.

    **The caveat, stated so that the next reader does not "tighten" this into a flaky test.**
    `init.agents`, `init.slash_commands` and `init.skills` all come back **non-empty**, and that is
    correct rather than a leak: what is in them is the *operator's own* machine-level configuration,
    which §3.11 puts out of scope for v1.1 in as many words - "v1.1 inherits the parent environment"
    - and some of it may not even be settings discovery, since this test process is itself running
    inside a Claude Code session and a spawned CLI inherits an environment. §3.5's claim is about
    **the target repository**, so what is asserted is that the three *planted* names are absent.
    `assert not announced["agents"]` would be asserting something §3.5 never said, against a value
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
        f"§3.5: the target repo contributes source code and nothing else - setting_sources=[] is "
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
    assert sorted(servers) == ["agl", "agl_ask"], (
        f"the session's MCP servers are {servers}, and AGL supplies exactly two: the workflow's "
        f"tools and the one that asks a person"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not _cli(), reason=_NO_CLI)
@pytest.mark.skipif(not _live(), reason=_NOT_OPTED_IN)
async def test_the_options_the_run_actually_built_are_the_hermetic_ones(
    tmp_path: Path, watched: Watched
) -> None:
    """The three §3.5 settings, and the four values deliberately left off the command line.

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
        "the harness's own asker is left available beside AGL's, so a model may pick the one that "
        "talks to nobody - which is a question waiting on an answer that cannot arrive"
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
    assert ASK_TOOL in registered, "AGL's asking tool is what MID_RUN_QUESTIONS rests on"
    assert "Read" in registered, "nothing denies Read, so a session missing it registered nothing"
    for gone in ("Bash", "WebFetch", "WebSearch", "AskUserQuestion"):
        assert gone not in registered, (
            f"{gone} is registered for a task declaring NO_SHELL and NO_NETWORK, and the harness's "
            f"own asker is denied for every task: {registered}"
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
async def test_the_composed_request_carries_the_asking_tool_with_a_usable_schema(
    tmp_path: Path, harness: Loopback
) -> None:
    """§3.7's asking tool, in the request that actually left the machine.

    **Why this and `test_the_asking_tool_is_advertised_with_a_schema_a_model_could_call`, which
    looks like the same assertion.** That one drives a scripted transport and reads a `tools/list`
    answered by AGL's own in-process MCP server: it proves `_tools.py` advertises the right thing to
    whoever asks. This one reads what the CLI composed and sent, which is a different fact with a
    whole harness in between - the MCP server has to be started, connected, enumerated, and its
    tools folded into the request under the API's own `input_schema` spelling rather than MCP's
    `inputSchema`. Any of that could go wrong with `_tools.py` perfectly correct, and the offline
    test would still be green. Two tests, because there are two claims.

    The properties are `Question`'s three fields, asserted by shape rather than by comparing the
    whole schema, so that a reworded description stays a rewording.
    """
    await spawn(task_in(workspace(tmp_path)))

    composed = harness.composed()
    offered = {
        entry.get("name"): entry
        for entry in composed.get("tools", [])
        if isinstance(entry, dict)
    }
    assert ASK_TOOL in offered, (
        f"the request that left the machine offers {sorted(name for name in offered if name)} and "
        f"{ASK_TOOL} is not among them. `capabilities()` answers MID_RUN_QUESTIONS unconditionally "
        f"for every task on every machine, and this is the request that has to make that true"
    )

    schema = offered[ASK_TOOL]["input_schema"]
    assert schema.get("type") == "object" and "question" in schema.get("required", []), (
        f"the asking tool reached the model as {schema!r}. `question` has to be required: it is "
        f"the whole of what a person is shown, and a call that omits it is one `Asking` can only "
        f"refuse back into the conversation after the turn has been spent"
    )
    properties = schema.get("properties", {})
    assert properties.get("question", {}).get("type") == "string", (
        f"`question` reached the model as {properties.get('question')!r} and `Question.prompt` is "
        f"text. A model handed any other type here would send something no view can render"
    )
    assert properties.get("options", {}).get("items", {}).get("type") == "string", (
        f"`options` reached the model as {properties.get('options')!r}. Without an array of "
        f"strings a model has no way to offer choices, so every question arrives as free text and "
        f"`Choice` "
        f"components have nothing to render"
    )
    assert properties.get("allow_free_text", {}).get("type") == "boolean", (
        f"`allow_free_text` reached the model as {properties.get('allow_free_text')!r}. It is the "
        f"third of `Question`'s three fields and the only way a model can say it is asking for a "
        f"choice among the options rather than for an opinion"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not _cli(), reason=_NO_CLI)
@pytest.mark.skipif(not _live(), reason=_NOT_OPTED_IN)
async def test_the_composed_request_names_the_asking_tool_when_somebody_can_answer(
    tmp_path: Path, harness: Loopback
) -> None:
    """§3.7's "agents are instructed to use it", asserted against what actually leaves.

    This is the measurement `_MAY_ASK` exists because of. Before it, `agl_ask` occurred **exactly
    once** in the whole 140 KB request - inside the tool's own definition - and running the same
    task with `on_question` supplied produced a byte-identical prompt. So the framework supplied the
    tool and instructed nobody: a workflow's `on_question` would be called only if a model went
    looking through its tool list for something it had never been told existed.

    Both halves, on one task run twice, because each is the other's control - the same shape as the
    offline `test_the_prompt_names_the_asking_tool_exactly_when_somebody_can_answer`, and a
    different claim: that one reads the string the adapter composed, this one reads the request the
    CLI assembled out of it. A harness that dropped the prompt on the way would fail here alone.

    The count is asserted on the run with no handler, not just the absence of the instruction: one
    occurrence is the tool definition, and pinning it is what keeps this test honest if `_MAY_ASK`
    is ever reworded into something that no longer contains the tool's name.
    """
    repo = workspace(tmp_path)
    task = task_in(repo)

    async def answer(question: Question) -> Answer:
        raise AssertionError("this run never asks; the handler is here to be counted, not called")

    await spawn(task, on_question=answer)
    told = wire_text(harness.composed())

    harness.clear()
    await spawn(task)
    untold = wire_text(harness.composed())

    assert runner_module._MAY_ASK in told, (
        f"a run carrying a question handler sent {len(told)} bytes to the model and none of them "
        f"said it could ask. §3.7 has the framework supplying the asking tool *and* the agent "
        f"instructed to use it, and an agent that never learns the tool is there is a workflow "
        f"whose on_question is never called"
    )
    assert runner_module._MAY_ASK not in untold and untold.count("agl_ask") == 1, (
        f"a run with no question handler mentioned agl_ask {untold.count('agl_ask')} time(s). "
        f"Exactly one is right and it is the tool's own definition: the tool is registered either "
        f"way, and an agent told to ask when nobody is listening spends a turn to be told that no "
        f"answer is available"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not _cli(), reason=_NO_CLI)
@pytest.mark.skipif(not _live(), reason=_NOT_OPTED_IN)
async def test_nothing_the_repository_wrote_reaches_the_model_in_the_request_that_leaves(
    tmp_path: Path, harness: Loopback
) -> None:
    """The measurement that settled §3.5's `CLAUDE.md` question, run again on every build.

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
        f"by the contract suite's own fixture. §3.5: the target repo contributes source code and "
        f"nothing else, and there are {len(CONFIGURATIONS)} rows in that table which are none of "
        f"AGL's to forward"
    )
    assert "claudeMd" not in sent, (
        "the request carries a `# claudeMd` block, which is how Claude Code injects a repository's "
        "CLAUDE.md into a session - the exact shape `setting_sources=[]` was measured to suppress. "
        "A marker-free block would be this leak with nothing planted in it to notice"
    )


# --- §3.5: the workspace path is a directory and never program text ------------------------------

MARKER: Final = "AGL-A-SHELL-EVALUATED-THE-PATH"

# One path component that is a whole command line: a substitution that leaves a file behind, a
# semicolon, a pipeline, quotes, spaces - and `--output=x`, which is the shape stage 5 found making
# a read-only git port write a file. `/` and NUL are the only bytes a filename cannot hold.
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
    """§3.5's argv rule, on the one value the composition root supplies.

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


def test_every_session_this_package_opens_is_opened_hermetically() -> None:
    """A structural assertion, so that a session added later cannot quietly omit §3.5's settings.

    Two of the three hermeticity options have a *leaky* SDK default, so omitting them is not a
    session that fails to start - it is a session that reads the target repository and works. The
    tests above cover the one `ClaudeAgentOptions` that `run` builds; this one covers every
    `ClaudeAgentOptions` in the package, including `check_ready`'s and whatever a later stage adds,
    and it does it by parsing the source rather than by running anything.

    `tests/adapters/test_shell_verifier.py` established the shape at stage 6, for the same kind of
    clause: a promise about how a module is written is worth more as a fact about the code than as
    a paragraph in a docstring.
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
            given = {keyword.arg for keyword in node.keywords}
            assert {"setting_sources", "strict_mcp_config"} <= given, (
                f"{source.name} opens a session without naming both of §3.5's settings: it passes "
                f"{sorted(name for name in given if name)}. The SDK's defaults for the two missing "
                f"here are None and False, and both of those read the target repository"
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
async def test_activity_is_the_tools_own_name_and_one_line_of_its_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3.7's line, formed by `translate.activity` and passed through untouched.

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
async def test_the_asking_tool_is_advertised_with_a_schema_a_model_could_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3.7's asking tool, read off the wire: one tool, and a schema that describes a question.

    `capabilities()` answers `MID_RUN_QUESTIONS` unconditionally, on every machine and for every
    task, and this is what that answer rests on - so it is asserted where the model would see it,
    on the `tools/list` the session's own MCP server answers, rather than on the dict `_tools.py`
    holds. The run carries **no** handler on purpose: the tool is registered either way, which is
    the fact that makes the prompt's instruction conditional and the tool's registration not.

    The three properties are `Question`'s three fields and nothing more - prompt text, the options
    offered, whether free text is allowed - which §3.7 calls the lowest common denominator across
    vendors. A property missing here is a field `Asking` can never be handed, however well the
    mapping below it is written. Asserted by shape rather than by comparing the whole schema, so
    that a reworded description stays a rewording.

    `test_the_composed_request_carries_the_asking_tool_with_a_usable_schema` asserts what looks like
    the same thing against a real CLI, and its docstring says why both are here: this one covers
    what `_tools.py` advertises to whoever asks, and that one covers what survives a whole harness
    on the way out. Neither subsumes the other, and this one runs on a machine with no CLI at all.
    """
    repo = workspace(tmp_path)
    seen: list[dict[str, Any]] = []

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        seen.extend(await cli.listed("agl_ask"))
        await cli.say(ends(result="done", terminal_reason="completed"))

    await offline(play, task_in(repo), monkeypatch)

    advertised = {entry["name"]: entry for entry in seen}
    assert list(advertised) == ["ask"], (
        f"the asking server advertises {sorted(advertised)}. It holds exactly one tool, addressed "
        f"as {ASK_TOOL}: a second one there is a second way to ask, and the whole reason the "
        f"harness's own asker is denied by name is that there should be exactly one"
    )
    assert advertised["ask"]["description"].strip(), (
        "the asking tool has no description, which is what a model reads to decide whether this "
        "is the tool for what it wants"
    )

    schema = advertised["ask"]["inputSchema"]
    assert schema.get("type") == "object" and "question" in schema.get("required", []), (
        f"the asking tool's advertised schema is {schema!r}. `question` has to be required: it is "
        f"the whole of what a person is shown, and a call that omits it is one `Asking` can only "
        f"refuse back into the conversation after the turn has been spent"
    )
    properties = schema.get("properties", {})
    assert properties.get("question", {}).get("type") == "string", (
        f"`question` is advertised as {properties.get('question')!r} and `Question.prompt` is "
        f"text. A model handed any other type here would send something no view can render"
    )
    assert properties.get("options", {}).get("type") == "array", (
        f"`options` is advertised as {properties.get('options')!r}. Without it a model has no way "
        f"to offer choices, so every question reaches the workflow as free text and `Choice` "
        f"components have nothing to render"
    )
    assert properties["options"].get("items", {}).get("type") == "string", (
        f"`options` does not say its items are strings: {properties['options']!r}. An option is "
        f"the exact text that comes back as the answer, and `_tools.py` drops anything that is not "
        f"a non-empty string - silently, because by then the turn is already spent"
    )
    assert properties.get("allow_free_text", {}).get("type") == "boolean", (
        f"`allow_free_text` is advertised as {properties.get('allow_free_text')!r}. It is the "
        f"third of `Question`'s three fields and the only way a model can say it is asking for a "
        f"choice among the options rather than for an opinion"
    )


@pytest.mark.asyncio
async def test_two_questions_and_two_answers_inside_one_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3.7: the answer is serialised back into the same session, so a negotiation is rounds.

    One `run`, one transport, one session, two `tools/call` round-trips - which is the clause in
    the smallest form that can hold it. The `Question` handed to the handler is checked field by
    field, which the contract suite cannot do because it does not know what payload a backend
    produced.
    """
    repo = workspace(tmp_path)
    asked: list[Question] = []

    async def answer(question: Question) -> Answer:
        asked.append(question)
        return Answer(text=f"answer-{len(asked)}")

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        first = await cli.call(
            "agl_ask",
            "ask",
            {"question": "Which path?", "options": ["left", "right"], "allow_free_text": False},
        )
        assert first["content"][0]["text"] == "answer-1"
        second = await cli.call("agl_ask", "ask", {"question": "And after that?"})
        assert second["content"][0]["text"] == "answer-2"
        await cli.say(ends(result="answer-1 answer-2", terminal_reason="completed"))

    outcome = await offline(play, task_in(repo), monkeypatch, on_question=answer)

    assert [question.prompt for question in asked] == ["Which path?", "And after that?"]
    assert asked[0].options == ("left", "right") and asked[0].allow_free_text is False
    assert asked[1].options == () and asked[1].allow_free_text is True, (
        "a question with no choices in it leaves free text allowed, which is the port's own "
        "instruction and the difference between an open question and one nobody could answer"
    )
    assert outcome.text == "answer-1 answer-2"


@pytest.mark.asyncio
async def test_a_question_with_no_handler_is_answered_at_once_and_never_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The port's second edge case, seen from inside: the tool answers rather than blocking.

    The contract suite asserts this from outside, through a deadline, and a deadline cannot tell a
    run that answered quickly from one that answered at all. Here the tool result itself is read:
    it says no answer is available, in words, and it is not an error - nothing went wrong.
    """
    repo = workspace(tmp_path)

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        answered = await asyncio.wait_for(
            cli.call("agl_ask", "ask", {"question": "Which path?"}), timeout=10
        )
        assert answered["isError"] is False, "nobody listening is not a failure"
        assert "No answer is available" in answered["content"][0]["text"]
        await cli.say(ends(result="done", terminal_reason="completed"))

    outcome = await offline(play, task_in(repo), monkeypatch)
    assert outcome.text == "done"


@pytest.mark.asyncio
async def test_a_question_asking_nothing_is_refused_back_into_the_conversation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Question` refuses an empty prompt, so the model is told rather than the run being killed.

    §3.3's mechanism applied to the adapter's own tool: there is a session in flight holding the
    reasoning that produced the call, and the cheap fix is for the model to ask again properly.
    """
    repo = workspace(tmp_path)
    asked: list[Question] = []

    async def answer(question: Question) -> Answer:
        asked.append(question)
        return Answer(text="never")

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        refused = await cli.call("agl_ask", "ask", {"question": "   "})
        assert refused["isError"] is True
        assert "asked nothing" in refused["content"][0]["text"]
        await cli.say(ends(result="done", terminal_reason="completed"))

    await offline(play, task_in(repo), monkeypatch, on_question=answer)
    assert asked == [], "a question with no prompt reached the handler, and no view could show it"


@pytest.mark.asyncio
async def test_a_question_handler_that_raises_ends_the_run_with_its_own_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A headless terminal raising on a view that needs an answer is a real path, not a hypothesis.

    §3.7: a terminal that cannot take input raises `UpstreamUnavailable` on any `Screen[T]`, and a
    workflow's handler may raise `Stop`. The SDK turns an exception out of a tool handler into an
    error result and carries on, which would spend an hour of agent time on a run whose asker has
    already failed - so it is kept, the model is told an answer is not available so that it does
    not block either, and the run ends on the exception as soon as the next message arrives.
    """
    repo = workspace(tmp_path)
    refused = UpstreamUnavailable("this terminal cannot take input")

    async def answer(question: Question) -> Answer:
        raise refused

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        told = await cli.call("agl_ask", "ask", {"question": "Which path?"})
        assert "No answer is available" in told["content"][0]["text"]
        await cli.say(says("carrying on"))
        await cli.say(ends(result="done", terminal_reason="completed"))

    with pytest.raises(UpstreamUnavailable) as raised:
        await offline(play, task_in(repo), monkeypatch, on_question=answer)
    assert raised.value is refused, (
        f"the run ended with {raised.value!r} rather than with the handler's own exception, so a "
        f"workflow's Stop or a headless terminal's refusal would be reported as something else"
    )


@pytest.mark.asyncio
async def test_a_subagents_last_words_are_not_the_runs_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`text` is the agent's closing message, and a nested conversation's last line is not it.

    `parent_tool_use_id` is what tells them apart. Activity is the other way round and covered
    above: a subagent grepping a file is as much "what is happening right now" as the parent doing
    it, and §3.7 gives the router no licence to interpret either string.
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
    """§3.1: the adapter translates what its backend throws, at its own boundary, and nothing above
    an adapter sees a vendor exception.

    The contract suite's gap 7 says in as many words that it cannot provoke one - "nothing here can
    make a backend fail on demand ... so no test provokes a translation" - and this is the case a
    person actually meets: a session that is not authenticated. What is asserted is that the CLI's
    own words survive into the message, because that is the whole of what makes the error
    actionable, and that the class is the one §3.2's preflight and every workflow catch.
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
    prompt the adapter handed the SDK, which is also where §3.5's argv argument lands - none of
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
async def test_the_prompt_names_the_asking_tool_exactly_when_somebody_can_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3.7: "The framework supplies the asking tool (agents are instructed to use it)".

    The instructing is the half that lives in `runner.py`. Supplying it is `_tools.py`'s and is
    asserted above; a tool's own `description` field is what a model reads once it is already
    considering that tool, so on its own it cannot be what makes the tool considered.

    Both halves here, on one task run twice, because each is the other's control. A run with a
    handler is told; a run without one is told nothing at all, since the tool is registered either
    way and an agent that asks with nobody listening spends a turn to be told no answer is
    available. That second half is also what keeps
    `test_a_prompt_with_nothing_standing_around_it_is_the_instructions_verbatim` a statement about
    ordinary tasks rather than about tasks that happen to have no handler.

    The name is checked against the one the session actually advertises and not only against a
    string in this file. `mcp__<server>__<tool>` is composed from two names `_tools.py` owns, and
    nothing in `runner.py` would notice either of them being renamed - a prompt naming a tool the
    model cannot call is worse than a prompt naming none.

    `test_the_composed_request_names_the_asking_tool_when_somebody_can_answer` makes the same pair
    of assertions one layer out, against what a real CLI actually sent. This one stops at the string
    `run` handed the SDK, and is the half that runs on a machine with no CLI.
    """
    repo = workspace(tmp_path)
    seen: list[str] = []
    advertised: set[str] = set()

    async def play(cli: Scripted) -> None:
        await cli.say(init(repo))
        advertised.update(f"mcp__agl_ask__{tool['name']}" for tool in await cli.listed("agl_ask"))
        await cli.say(ends(result="done", terminal_reason="completed"))

    def capture(*, prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
        from claude_agent_sdk import query

        seen.append(prompt)
        return query(prompt=prompt, options=options, transport=Scripted(play))

    async def answer(question: Question) -> Answer:
        raise AssertionError("this script never asks; the handler is here to be counted, not run")

    bare = AgentTask(
        instructions="Work out what to do about the failing build, and do it.",
        workspace=repo,
        model=Claude.HAIKU,
        restrictions=frozenset(),
        tools=(),
    )
    monkeypatch.setattr(_session, "query", capture)
    await ClaudeCodeRunner().run(bare, on_question=answer)
    await ClaudeCodeRunner().run(bare)
    told, untold = seen

    assert ASK_TOOL_NAMED in told, (
        f"a run carrying a question handler was told nothing about how to ask: {told!r}. §3.7 has "
        f"the framework supplying the asking tool *and* the agent instructed to use it, and an "
        f"agent that never learns the tool is there is a workflow whose on_question is never called"
    )
    assert ASK_TOOL in advertised, (
        f"the prompt names {ASK_TOOL} and the session advertises {sorted(advertised)}: the agent "
        f"was instructed to call a tool that is not registered, which costs it a turn and AGL the "
        f"answer it was waiting for"
    )
    assert told.endswith(bare.instructions), (
        f"the instructions are no longer last in the composed prompt: {told!r}. Everything AGL "
        f"adds stands above what the workflow author wrote"
    )
    assert ASK_TOOL not in untold and "agl_ask" not in untold, (
        f"a run with no question handler was told to ask anyway: {untold!r}. Nobody is listening, "
        f"so the whole of what that turn buys is being told that no answer is available - and this "
        f"is also what keeps a bare task's prompt the instructions byte for byte"
    )


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
    compares equal to them today. The four are all of them: Claude Code edits files, runs a shell,
    calls tools, and - because this adapter registers an asker of its own rather than depending on
    the harness's - asks mid-run on every build, which is why `MID_RUN_QUESTIONS` is not conditional
    on a feature flag that varies between machines.
    """
    assert asyncio.run(ClaudeCodeRunner().capabilities(Claude.OPUS)) == frozenset(Capability), (
        "this adapter reports every capability the port has a member for, and a member added to "
        "the port is a question about this backend that somebody has to answer here"
    )


def test_a_model_this_adapter_does_not_serve_is_refused_by_both_query_members() -> None:
    """§3.2: "An adapter handed a `ModelId` it does not serve raises `InputError`."

    The contract suite can only ever name a model the adapter serves - it has one `model` fixture -
    so the refusal is invisible to it. Both members are asserted because a `capabilities` that
    ignored its argument would answer "I can do all four" for a model this runner would then refuse
    to run, which is a preflight that admits a run and kills it at second one.
    """
    with pytest.raises(InputError):
        asyncio.run(ClaudeCodeRunner().capabilities(OpenAI.SOL))
    with pytest.raises(InputError):
        asyncio.run(ClaudeCodeRunner().check_ready(OpenAI.SOL))
