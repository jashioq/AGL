"""`OpenAiRunner` against the `AgentRunner` contract, plus the clauses that suite cannot see.

The first class is the port in full: `AgentContract` with its two fixtures overridden and nothing
else touched. That suite was written against the port's docstrings and before any adapter
existed, which is the inversion `tests/contracts/` rests on and why nothing below re-asserts it.

**Six of its eight tests start a real agent, and none of them runs - anywhere, on any machine.**
Five of the six read a *model's* conduct as their evidence: that it called a tool, that it
corrected a refused call, that it ignored a repository's instructions. No free instrument can supply
that, and on this backend the only instrument that could is a paid turn, so they are deferred to
the manual QA pass. The sixth - what a run does when its activity reporter raises - reads no
conduct at all and is deferred for a different reason: the contract suite's one knob is the runner,
so it has no way to hand a real `OpenAiRunner` a stub to report from. That clause is asserted for
real further down this file, against the same adapter, driven by the stub CLI. The gate is
delivered by the `runner` fixture handing back a runner whose `run` skips: the criterion is "does
this test start an agent", which is a fact about the *port member* rather than about a test's name,
so no list here goes stale when a test in that suite is renamed. `capabilities` and `check_ready`
are the real thing in both cases and run unconditionally.

**No test in this file runs the harness's agent command.** No test in this repository spends
tokens, and here that is structural rather than promised: the two things this module starts are a
*stub* CLI it writes itself, and the real binary's model-free subcommands. `tests/conftest.py`
additionally points `CODEX_HOME` at an empty directory for every test in the repository, so a real
binary any test
starts has no credential to spend - asserted below rather than believed.

## What is asserted for real, and with what

**A stub CLI, written per test, standing where the harness would be.** It records the argument list
it was given, the directory it was started in and the prompt it was handed on standard input; it
plays a scripted event stream back on standard output; and it can act as an **MCP client** against
the servers the adapter started, because their addresses are in the argument list it was just
handed. So the real `OpenAiRunner`, the real argv composition, the real stream reading, the real
HTTP listener, the real MCP dispatch and the real tool handlers all run - what is fake is one
harness and one model.

That is this file's counterpart to the other adapter's scripted transport, and it carries the same
caveat: **it is supplementary evidence and never acceptance.** `tests/contracts/agent.py` exists
because a subagent that writes its own tests writes tests that pass, and a test double written in
the same hour as the code it exercises is that risk exactly. Its value is that a regression is
caught in a second on a laptop with no session.

**The real binary, for the two questions it answers for free.** `login status` decides
`check_ready` locally out of its own credential store, so this file exercises the refusing branch
against the credential-free home `tests/conftest.py` installs. And `debug prompt-input` renders the
model-visible prompt as JSON and contacts nothing, which makes hermeticity assertable with no
model:
the adapter's own configuration overrides are lifted off the command line it composed and handed to
it in a poisoned repository, with a control run proving the poison was there to find.

Both are gated on the binary being installed and on nothing else. There is deliberately no opt-in
switch: neither subcommand reaches a model, both are free instruments, and gating a free
measurement behind a variable is how a measurement stops being made.

## What follows the contract subclass, in rough order

  * **The command line it composes** - the hermeticity overrides, the sandbox mode, the model, the
    servers, the prompt's absence from it, and the workspace's absence from it.
  * **Hermeticity, three ways**: the composed prompt carries nothing the repository wrote; every
    override
    the adapter emits loads; and a poisoned repository reaches the model with none of its markers,
    including a `.codex/skills` row the contract suite's own table does not carry.
  * **The argv guards**, which the suite cannot provoke because it supplies neither value.
  * **The stream**, frame by frame, including the outcomes the suite lists as beyond it (gap 10:
    it cannot make a run reach a limit and has no second source for the fact).
  * **The tools**, driven against the adapter's own MCP server with no CLI - the round trip, the
    refusal, a malformed call the server itself has to turn away, and a handler that raises. A
    workflow's asking tool is one of these and nothing more: AGL registers no asking tool of its
    own, so there is no second server here and no question the port has heard of.
  * **The two members preflight asks**, ending with a probe that never answers: its deadline, the
    one exception class preflight catches, and whether the group it started is still running.

Named `test_openai_runner.py`, for the module it covers: `tests/` carries no `__init__.py` (see
`tests/conftest.py` for why it must not), so pytest's module names are the bare filenames and two
files of one name under different directories would collide at import.
"""

import ast
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Awaitable, Iterable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, Final, NoReturn
import pytest
from agl.adapters.openai import _tools, _version
from agl.adapters.openai import runner as runner_module
from agl.adapters.openai.runner import OpenAiRunner
from agl.ports.agent import (
    AgentRunner,
    AgentTask,
    Capability,
    Claude,
    ClaudeEffort,
    ModelChoice,
    ModelEfforts,
    ModelId,
    OpenAI,
    OpenAIEffort,
    Restriction,
    Standing,
    StopReason,
    Tool,
    ToolResult,
)
from agl.ports.errors import InputError, UpstreamUnavailable, UpstreamUnexpected
from agl.ports.run import JsonValue
from contracts._agent_hermeticity import CONFIGURATIONS, markers_in, plant
from contracts._agent_tasks import Activity, Notes, ReporterFailed, workspace
from contracts.agent import AgentContract

# What a person is told when the six deferred contract tests do not run, which is always. Long on
# purpose: the whole point of this suite is that a green run means something, and a skip that reads
# like a pass is the failure `tests/contracts/agent.py` is written against.
_SKIPPED: Final = (
    "UNVERIFIED: this run did not start a real agent, so the OpenAiRunner's entire run-path - the "
    "outcome, the refused tool call, the tool handler that raised, the activity, the activity "
    "reporter that raised and the poisoned repository - is unverified by this run, and by every "
    "run. DEFERRED TO THE MANUAL QA PASS, with no switch here that changes it: five of the six "
    "read a model's conduct as their evidence - that it called a tool, that it corrected a refused "
    "call, that it ignored a poisoned repository - and on this backend the only "
    "instrument that produces conduct is a paid turn. The sixth, the activity reporter that "
    "raised, needs no conduct; it is deferred only because the contract suite's one knob is the "
    "runner and a real OpenAiRunner reports nothing without a harness to read, and it is asserted "
    "for real against the stub CLI further down this file. No test in this build spends tokens. "
    "Run the other five by hand against an authenticated CLI, or do not believe them. What did "
    "run is everything below the contract subclass: the "
    "composed command line, the composed prompt, the whole stream reading, and every tool "
    "round trip driven against this adapter's own MCP server over real HTTP - plus, where "
    "the binary is installed, the hermeticity overrides checked against a poisoned repository with "
    "the harness's own free prompt renderer. None of that covers a model deciding anything, and "
    "this skip is not a pass."
)

# What a person is told when the binary is missing. A different gate and kept separate: these need
# a process that starts and answers a model-free subcommand, which costs nothing and needs no
# authentication, so the only thing that can stop them is the binary not being there at all.
_NO_CLI: Final = (
    "UNVERIFIED: the Codex CLI is not on PATH, so nothing here could ask it what a repository "
    "contributes to a prompt or whether it is logged in. Both are free - `debug prompt-input` "
    "renders the model-visible prompt and contacts nothing, `login status` reads a credential "
    "store - so installing the CLI makes these run again on any machine, logged in or not."
)

# The one marker this file plants itself. The contract suite's Codex row lists AGENTS.md and
# .codex/config.toml; a repository's `.codex/skills/*/SKILL.md` is a third instruction channel that
# reaches the model - measured, and suppressed by one of the adapter's overrides - and it is not in
# that row. `tests/contracts/` may not be edited from here, so the row grows in this file instead.
SKILL_MARKER: Final = "AGL-LEAK-SKILL-9f2c41"

# What the stub CLI is asked to be, per test: a JSON plan beside a JSON record of what it saw.
_PLAN: Final = "plan.json"
_RECORD: Final = "record.json"

# The two answers the harness gives about itself, spelled as the installed 0.155.1 spells them: the
# version line has the tool's own name in front of it, and a level sits under `effort` inside an
# object beside the description the harness shows in its own menu. It is the release
# `_version.TESTED` names, which is what makes the standing below `WITHIN` rather than a warning.
_SPELLED_VERSION: Final = "codex-cli 0.155.1\n"

def _listed(slug: str, levels: tuple[str, ...], fallback: str) -> dict[str, Any]:
    """One model as the harness's own listing writes it, down to the shape of a level."""
    return {
        "slug": slug,
        "supported_reasoning_levels": [
            {"effort": level, "description": f"{level} reasoning"} for level in levels
        ],
        "default_reasoning_level": fallback,
    }

# The stub, written to disk and handed to the adapter as its CLI. It is deliberately small and
# deliberately *not* a harness: it records, it plays back, and it can call an MCP tool.
#
# It can also *wedge*, which is the one thing here that is not a stand-in for the harness doing its
# job but a stand-in for it failing to. `login status` reads a credential store, and a credential
# store can block - a keychain prompt with nobody at the machine, an authentication agent that has
# stopped answering - so a probe that hangs is a real state of a real machine and not a hypothesis.
# The wedged branch starts a grandchild before it sleeps and writes both pids down, because the
# question a deadline has to answer is not only "did the call come back" but "is anything still
# running", and a grandchild is what tells a process signal from a group one.

_STUB: Final = '''#!{python}
"""A stand-in for the harness, written by tests/adapters/test_openai_runner.py."""

import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

PLAN = pathlib.Path({plan!r})


def address(name, argv):
    """The URL the adapter told the harness this server is on, read off its own command line."""
    prefix = "mcp_servers." + name + "="
    for token in argv:
        if token.startswith(prefix):
            start = token.index('url="') + 5
            return token[start : token.index('"', start)]
    raise SystemExit("the command line carries no server called " + name)


def post(url, message):
    body = json.dumps(message).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={{
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }},
    )
    with urllib.request.urlopen(request) as answered:
        raw = answered.read()
    return json.loads(raw) if raw else None


def speak(call, argv):
    url = address(call["server"], argv)
    post(url, {{
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {{
            "protocolVersion": "2025-06-18",
            "capabilities": {{}},
            "clientInfo": {{"name": "agl-stub", "version": "1"}},
        }},
    }})
    post(url, {{"jsonrpc": "2.0", "method": "notifications/initialized"}})
    if call.get("list"):
        return post(url, {{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {{}}}})
    return post(url, {{
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {{"name": call["tool"], "arguments": call.get("arguments", {{}})}},
    }})


def probe(plan, record):
    """Answer one of the two questions the version probe puts, into a record of its own."""
    key = "version" if record["argv"][:1] == ["--version"] else "catalogue"
    record["home"] = os.environ.get("CODEX_HOME")
    record.update(surroundings())
    pathlib.Path(plan["record"] + "." + key).write_text(json.dumps(record), encoding="utf-8")
    sys.stdout.write(plan[key])
    return plan.get(key + "_exit", 0)


def surroundings():
    """The names this child was handed, in two groups and with no value recorded for any of them.

    Names only, deliberately: an operator's real environment carries tokens, and a record written
    into a temporary directory is no place for one. What the tests need is which names arrived.
    """
    return {{
        "vendor": sorted(n for n in os.environ if n.startswith(("CODEX", "OPENAI"))),
        "machine": sorted(n for n in ("PATH", "HOME", "TMPDIR", "SHELL") if n in os.environ),
    }}


def main():
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    record = {{"argv": sys.argv[1:], "cwd": os.getcwd(), "stdin": None, "answers": []}}
    record["state_home"] = os.environ.get("CODEX_SQLITE_HOME")
    record["state_home_exists"] = os.path.isdir(record["state_home"] or "")
    record.update(surroundings())
    if sys.argv[1:2] == ["--version"] or sys.argv[1:3] == ["debug", "models"]:
        return probe(plan, record)
    written = pathlib.Path(plan["record"])
    try:
        if sys.argv[1:2] == ["login"]:
            login = plan["login"]
            if login.get("wedge"):
                held = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(" + str(login["sleep"]) + ")"]
                )
                pathlib.Path(login["wedge"]).write_text(
                    json.dumps([os.getpid(), held.pid]), encoding="utf-8"
                )
                time.sleep(login["sleep"])
            print(login["say"])
            return login["exit"]
        record["stdin"] = sys.stdin.read()
        for step in plan.get("steps", []):
            if "say" in step:
                print(json.dumps(step["say"]), flush=True)
            elif "raw" in step:
                print(step["raw"], flush=True)
            elif "err" in step:
                print(step["err"], file=sys.stderr, flush=True)
            elif "call" in step:
                record["answers"].append(speak(step["call"], sys.argv[1:]))
        return plan.get("exit", 0)
    finally:
        written.write_text(json.dumps(record), encoding="utf-8")


sys.exit(main())
'''

class Stub:
    """One scripted stand-in for the harness: what it will do, and what it saw.

    Built per test into that test's own temporary directory, so two tests can never read each
    other's record and no state survives a run.
    """

    def __init__(self, root: Path, **plan: Any) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.record = root / _RECORD
        plan.setdefault("login", {"say": "Logged in using ChatGPT", "exit": 0})
        plan.setdefault("version", _SPELLED_VERSION)
        plan.setdefault("catalogue", json.dumps({"models": []}))
        plan["record"] = str(self.record)
        (root / _PLAN).write_text(json.dumps(plan), encoding="utf-8")
        self.path = root / "codex-stub.py"
        self.path.write_text(
            _STUB.format(python=sys.executable, plan=str(root / _PLAN)), encoding="utf-8"
        )
        self.path.chmod(0o755)

    def seen(self) -> Mapping[str, Any]:
        """What the stub recorded, or a failed assertion saying it never ran."""
        assert self.record.is_file(), (
            f"the stub CLI at {self.path} left no record, so it was never started. Everything "
            f"this test asserts afterwards is about a command line that was composed and handed "
            f"over; a run that did not get that far is a failure to report"
        )
        seen = json.loads(self.record.read_text(encoding="utf-8"))
        assert isinstance(seen, dict)
        return seen

    def argv(self) -> list[str]:
        """The argument list the adapter composed, without the program name."""
        given = self.seen()["argv"]
        assert isinstance(given, list)
        return [str(token) for token in given]

    def probed(self, which: str) -> Mapping[str, Any]:
        """What the stub saw for one of the two questions the version probe puts to it."""
        written = self.record.with_name(f"{self.record.name}.{which}")
        assert written.is_file(), (
            f"the stub CLI at {self.path} left no {which} record, so it was never asked that "
            f"question. Both are put on every probe, and one that was not asked is a version or a "
            f"catalogue reported from nothing at all"
        )
        seen = json.loads(written.read_text(encoding="utf-8"))
        assert isinstance(seen, dict)
        return seen

def started(**fields: Any) -> dict[str, Any]:
    """A `turn.completed`-shaped stream: the ordinary ending, with whatever else is asked for."""
    return {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}, **fields}

def item(kind: str, of: str, **fields: Any) -> dict[str, Any]:
    """One item frame of `kind` carrying an item of type `of`."""
    return {"type": kind, "item": {"id": "i1", "type": of, "status": "completed", **fields}}

def said(text: str) -> dict[str, Any]:
    """The frame the agent's closing message arrives on."""
    return item("item.completed", "agent_message", text=text)

async def drive(stub: Stub, task: AgentTask, **kwargs: Any) -> Any:
    """Run `task` through the real adapter against the stub, and hand back what `run` returns."""
    return await OpenAiRunner(stub.path).run(task, **kwargs)

def task_in(
    repo: Path, *, tools: tuple[Tool, ...] = (), model: ModelChoice = OpenAI.LUNA, **fields: Any
) -> AgentTask:
    """One ordinary task in `repo`, with restrictions so the sandbox overrides are on the wire."""
    return AgentTask(
        instructions="Read README.md and say in one sentence what this project does.",
        workspace=repo,
        model=model,
        restrictions=frozenset({Restriction.NO_NETWORK}),
        tools=tools,
        **fields,
    )

def _cli() -> bool:
    """Whether there is a binary to ask the two free questions of."""
    return shutil.which("codex") is not None

# --- The guard this file rests on ---------------------------------------------------------------

def test_no_test_in_this_module_can_spend_the_operators_credential() -> None:
    """The Codex half of the repo-wide guard, asserted rather than promised.

    This module starts the real binary, and the only thing standing between that and the
    operator's own subscription is `tests/conftest.py` pointing `CODEX_HOME` at a directory with no
    credential in it. A docstring saying "these tests are free" is worth nothing on the day that
    fixture is renamed or lost in a reshuffle, and the failure would be silent - a test that spends
    money looks exactly like one that does not until the bill arrives.

    `scripts/check`'s paid-endpoint gate asks the wider question, whether a module added today
    inherits anything at all. This one asks whether the guard reached *this* file, which no
    repo-wide check can ask, and it is the assertion that matters here because the commands below
    are the ones that would use a credential if there were one.
    """
    home = os.environ.get("CODEX_HOME", "")
    assert home, (
        "CODEX_HOME is unset, so every process this file starts reads the operator's own "
        "credential store. The guard in tests/conftest.py points it at an empty directory for "
        "every test in the repository, and this file spawns a real CLI"
    )
    assert not (Path(home) / "auth.json").is_file(), (
        f"CODEX_HOME is {home!r} and there is a credential in it. The CLI reads both its "
        f"configuration and its authentication out of that directory, so a test that reached a "
        f"model would do it with the operator's own subscription and their own allowance"
    )

# --- The port in full -----------------------------------------------------------------------

class _NeverRuns(OpenAiRunner):
    """The runner the contract suite gets: real, except that `run` skips and always skips.

    Subclassed rather than mocked, so `capabilities` and `check_ready` are the adapter's own and
    the two tests that ask them are testing the real thing. `run` skips, loudly, which puts the
    gate on the *port member that starts an agent* instead of on a list of test names - the suite's
    tests can be renamed, split or added to and this keeps deciding correctly.

    Unconditionally, because there is no condition worth writing: five of the six tests behind
    it assert a model's conduct, the only instrument that can answer is a paid one, and a test that
    spends money on a flag is still a test that spends money.

    The sixth is `test_an_activity_reporter_that_raises_ends_the_run_with_its_own_exception`, and
    it is the one clause here a free instrument could reach: it asks the agent for nothing. What
    stops it is the shape of the contract suite rather than the price of a turn - its one knob is
    the runner, and an `OpenAiRunner` pointed at this file's stub CLI is not something the suite
    has a way to build. Marking that one test by name would put a list of test names in this file
    after all, for a clause this file already asserts against the same adapter in
    `test_an_activity_reporter_that_raises_comes_out_of_this_adapters_run`.
    """

    async def run(self, *args: object, **kwargs: object) -> NoReturn:
        pytest.skip(_SKIPPED)

class TestOpenAiRunner(AgentContract):
    """The port in full, against the real adapter: two of its eight tests today, and six deferred.

    Two overrides and nothing else, which is what the suite asks for. The gate lives inside the
    `runner` fixture because that is one of the two, and because the alternative - marking
    individual tests - would mean this file naming tests that belong to a suite it does not own.
    """

    @pytest.fixture
    def runner(self) -> AgentRunner:
        """The adapter, resolving the CLI from `PATH`, with `run` skipping.

        Nothing else is configured, because there is nothing else: the model, the workspace, the
        tools and the restrictions all arrive per call, and the hermeticity settings are not
        settings but obligations the adapter carries whoever built it.
        """
        return _NeverRuns()

    @pytest.fixture
    def model(self) -> ModelId:
        """The cheapest tier this adapter serves, since every deferred test is a one-shot errand."""
        return OpenAI.LUNA

# --- The command line it composes ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_command_line_carries_every_setting_that_makes_a_session_agls(
    tmp_path: Path,
) -> None:
    """One composed command line, read off the process that was actually started.

    Read off what `run` handed over rather than off a reconstruction in this file: rebuilding the
    argument list here and asserting on the rebuild would assert that this file can build a list,
    which nobody doubts. Every token below closes something `runner.py`'s docstring names, and the
    four hermeticity overrides are asserted by value because each of them has a default that
    reads the target repository.
    """
    stub = Stub(tmp_path, steps=[{"say": said("done")}, {"say": started()}])
    repo = workspace(tmp_path)

    await drive(stub, task_in(repo))
    argv = stub.argv()

    assert argv[0] == "exec", (
        f"the first argument is {argv[0]!r}. This adapter drives the non-interactive command and "
        f"only that one: the interactive one has a different flag set and no event stream, and "
        f"the app-server one has a different lifecycle and no sandbox flag at all"
    )
    for expected in (
        "--json",
        "--ignore-rules",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "project_doc_max_bytes=0",
        "skills.include_instructions=false",
        'approval_policy="never"',
    ):
        assert expected in argv, (
            f"{expected!r} is not on the command line: {argv}. Every one of these closes a channel "
            f"that was measured open - a repository's AGENTS.md at any depth, its skills, its "
            f"execpolicy rules, the operator's own configuration file, and an approval setting "
            f"that would otherwise teach the agent to ask a mode that refuses by protocol error"
        )
    assert argv[argv.index("--color") + 1] == "never", "nothing here parses terminal escapes"
    assert argv[argv.index("-s") + 1] == "workspace-write", (
        f"the sandbox mode is {argv[argv.index('-s') + 1]!r} for a task declaring NO_NETWORK "
        f"alone: the network is taken by an override, and read-only would also take file writes"
    )
    assert "sandbox_workspace_write.network_access=false" in argv, (
        f"NO_NETWORK reached the harness as nothing: {argv}"
    )
    assert argv[argv.index("-m") + 1] == "gpt-5.6-luna", "the model is the slug, not the tier"
    assert argv[-1] == "-", (
        f"the last argument is {argv[-1]!r}. It is what tells the harness to read the instructions "
        f"from standard input, which is where the largest untrusted string in the system belongs"
    )
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv, "the sandbox is the mechanism"
    assert "--approve-for-me" not in argv, "that widens the sandbox that is the whole mechanism"

@pytest.mark.asyncio
async def test_every_command_line_refuses_the_rollout_and_the_plugin_clone_the_harness_would_write(
    tmp_path: Path,
) -> None:
    """The two overrides that are about the operator's home rather than about the prompt.

    Every other token on this command line closes a channel *into* the model. These two close what
    the harness writes on its way to starting one, and neither is reachable from the sandbox: the
    sandbox constrains commands the model runs, and both of these happen before it has run any.
    Measured on a fresh home against 0.155.1, with the run failing at a loopback endpoint so that
    only the startup is in the number: 3,467,981 bytes with AGL's overrides as they were, 376,571
    with these two and the state home below, and four attempted connections off the machine -
    `github.com`, `api.github.com` and `chatgpt.com` twice - reduced to none by the second one
    alone. Asserted by value rather than by consequence because the consequence is a directory
    this suite must never write to: `tests/conftest.py` points the home at a scratch directory
    precisely so that no test can measure what a run does to the operator's own.
    """
    stub = Stub(tmp_path, steps=[{"say": started()}])

    await drive(stub, task_in(workspace(tmp_path)))
    argv = stub.argv()

    assert "--ephemeral" in argv, (
        f"nothing on {argv} stops the harness persisting its session. The rollout it writes "
        f"carries the instructions, the standing context and every tool call, it is 28 KB for a "
        f"run that never reached a model, and AGL reads it back nowhere: a resume is served by "
        f"AGL's own journal"
    )
    assert "features.plugins=false" in argv, (
        f"nothing on {argv} switches the plugin feature off. On a home that has not seen it that "
        f"feature clones the plugin marketplace - a 90 MB git working tree - over the network, "
        f"before the first token and whatever the sandbox says"
    )

@pytest.mark.asyncio
async def test_the_workspace_is_the_working_directory_and_is_not_on_the_command_line(
    tmp_path: Path,
) -> None:
    """The one caller-supplied path this adapter handles never reaches an argument list.

    The harness offers a flag for it and this adapter uses the process's working directory
    instead - a `chdir` between fork and exec, which is never a string anything parses. Both halves
    are asserted, because either alone is satisfiable by an adapter that got it wrong: the
    directory arrived whole, and no token on the command line is it.
    """
    stub = Stub(tmp_path, steps=[{"say": started()}])
    repo = workspace(tmp_path)

    await drive(stub, task_in(repo))

    assert Path(stub.seen()["cwd"]).resolve() == repo.resolve(), (
        f"the harness was started in {stub.seen()['cwd']!r} and the workspace is {str(repo)!r}. A "
        f"run happening somewhere else is a run in somebody else's repository"
    )
    assert not [token for token in stub.argv() if str(repo) in token], (
        f"the workspace is on the command line: {stub.argv()}. It is passed as the child's working "
        f"directory precisely so that it cannot be, and the flag that would put it there has the "
        f"working directory as its own default, so nothing is bought by using it"
    )

@pytest.mark.asyncio
async def test_the_mcp_server_is_injected_with_a_timeout_a_person_can_answer_inside(
    tmp_path: Path,
) -> None:
    """The tool channel, as it reaches the harness: one server, and the number that matters.

    `tool_timeout_sec` defaults to sixty seconds and a workflow's asking tool waits on a person.
    That default is the specific way an approval gate dies quietly - the call fails, the agent is
    told the tool errored, and it carries on guessing - so the override is asserted by value rather
    than by presence, and asserted to be longer than any person's thinking time rather than merely
    different from sixty. AGL cannot know which of a role's tools blocks on a person, and would not
    want to: the ceiling is per server and this one carries whatever the workflow declared.

    There were two servers while AGL registered an asking tool of its own, on a name of its own so
    that a workflow calling a tool `ask` could not collide with it. A question is an ordinary tool
    now, so there is one server and the collision cannot arise - two tools of one name are refused
    at the `Role`, one layer up and one run earlier.
    """
    stub = Stub(tmp_path, steps=[{"say": started()}])

    await drive(stub, task_in(workspace(tmp_path)))
    supplied = [token for token in stub.argv() if token.startswith("mcp_servers.")]

    assert len(supplied) == 1, (
        f"the command line declares {len(supplied)} MCP server(s): {supplied}. One is supplied, "
        f"and it carries the workflow's own tools"
    )
    names = sorted(token.split("=", 1)[0].removeprefix("mcp_servers.") for token in supplied)
    assert names == ["agl"], f"the servers are named {names}"
    for token in supplied:
        assert "url=\"http://127.0.0.1:" in token, (
            f"a server was declared at {token!r}. It has to be a loopback literal: a hostname "
            f"resolves through whatever the machine says it means, and anything else is an address "
            f"reachable from off the machine"
        )
        assert 'default_tools_approval_mode="auto"' in token, (
            f"{token!r} leaves the server's approval mode at its default. In this mode no approval "
            f"can ever be granted, so a server that asks is a tool call waiting on nobody"
        )
        seconds = int(token.split("tool_timeout_sec=", 1)[1].split(",", 1)[0])
        assert seconds >= 3600, (
            f"a tool call may take {seconds}s. The harness's own default is 60, a workflow's "
            f"asking tool waits on a person, and an approval gate that survives only while nobody "
            f"thinks for a minute is not a gate anybody should be relying on"
        )

_EFFORT_KEY: Final = "model_reasoning_effort"

@pytest.mark.asyncio
@pytest.mark.parametrize("effort", list(OpenAIEffort))
async def test_a_model_chosen_at_an_effort_carries_one_override_directly_after_the_model(
    effort: OpenAIEffort, tmp_path: Path
) -> None:
    """The level travels as one `-c` pair, once, beside the `-m` it qualifies and before `-`.

    `codex exec` has no effort flag of its own, so the override is the only route and a second one
    would leave which of two levels wins to the harness's loader. The slug is asserted beside it
    because a table keyed by the bare member and looked up with the whole choice type-checks and
    misses: `model_slug` would refuse the run, so `gpt-5.6-luna` on the command line is the
    evidence that the lookup was made with `model_of`.
    """
    stub = Stub(tmp_path, steps=[{"say": said("done")}, {"say": started()}])

    await drive(stub, task_in(workspace(tmp_path), model=OpenAI.LUNA(effort=effort)))
    argv = stub.argv()

    model_at = argv.index("-m")
    assert argv[model_at + 1] == "gpt-5.6-luna", "the model is the slug of the bare member"
    assert argv[model_at + 2 : model_at + 4] == ["-c", f'{_EFFORT_KEY}="{effort.value}"'], (
        f"the override for {effort!r} is not directly after the model: {argv}"
    )
    assert len([token for token in argv if _EFFORT_KEY in token]) == 1, (
        f"the command line carries the effort more than once: {argv}"
    )
    assert argv[-1] == "-", "the prompt still arrives on standard input, after every override"

@pytest.mark.asyncio
@pytest.mark.parametrize("model", list(OpenAI))
async def test_a_bare_model_carries_no_effort_override_and_leaves_the_catalog_default(
    model: OpenAI, tmp_path: Path
) -> None:
    """A member written without an effort runs at the harness's own default, exactly as before.

    The absence is asserted over every token rather than at a position, since what leaves the
    default in place is that the key is nowhere on the command line - the MCP server's override is
    what follows the model here, and it names no effort.
    """
    stub = Stub(tmp_path, steps=[{"say": said("done")}, {"say": started()}])

    await drive(stub, task_in(workspace(tmp_path), model=model))
    argv = stub.argv()

    assert not [token for token in argv if _EFFORT_KEY in token], (
        f"a bare {model!r} was sent an effort: {argv}"
    )

@pytest.mark.asyncio
@pytest.mark.parametrize("model", list(Claude))
async def test_a_model_of_the_other_provider_at_an_effort_is_refused_before_anything_starts(
    model: Claude, tmp_path: Path
) -> None:
    """An effort does not make a Claude model one this adapter serves, and no child is started."""
    stub = Stub(tmp_path, steps=[{"say": started()}])

    with pytest.raises(InputError) as refused:
        await drive(stub, task_in(workspace(tmp_path), model=model(effort=ClaudeEffort.HIGH)))
    assert str(model) in str(refused.value)
    assert not stub.record.exists(), "the refusal came after the harness had been started"

@pytest.mark.asyncio
async def test_a_prompt_with_nothing_standing_around_it_is_the_instructions_verbatim(
    tmp_path: Path,
) -> None:
    """A workflow author's prompt is the whole of what they wrote, and reaches the agent unedited.

    The other half is asserted with it: standing context, the restrictions in words and `plan_only`
    all reach the agent, above the instructions, with the instructions still last. Read off the
    stub's standard input, which is where a hostile value would land too - none of this text is
    on a command line, because the prompt travels on the child's standard input.
    """
    repo = workspace(tmp_path)
    bare = Stub(tmp_path / "bare", steps=[{"say": started()}])

    await drive(
        bare,
        AgentTask(
            instructions="Read README.md and say what this is.",
            workspace=repo,
            model=OpenAI.LUNA,
            restrictions=frozenset(),
            tools=(),
        ),
    )
    assert bare.seen()["stdin"] == "Read README.md and say what this is.", (
        f"a task with no context, no restrictions and no plan_only was rewritten: "
        f"{bare.seen()['stdin']!r}"
    )

    dressed = Stub(tmp_path / "dressed", steps=[{"say": started()}])
    await drive(
        dressed,
        AgentTask(
            instructions="Read README.md and say what this is.",
            workspace=repo,
            model=OpenAI.LUNA,
            restrictions=frozenset({Restriction.NO_SHELL}),
            tools=(),
            context="This repository is a teaching example.",
            plan_only=True,
        ),
    )
    composed = dressed.seen()["stdin"]
    assert composed.endswith("Read README.md and say what this is."), (
        f"the instructions are not last in the composed prompt: {composed!r}"
    )
    assert "This repository is a teaching example." in composed, "the standing context is dropped"
    assert "Do not run commands." in composed, (
        "the restrictions in words did not reach the agent. NO_SHELL has no exact mechanism on "
        "this harness, so the sentence is not belt-and-braces - it is the enforcement"
    )
    assert "examine and propose" in composed, "plan_only reached the agent as nothing at all"

# --- What the repository contributes, which is source code and nothing else ----------------------

def poisoned(root: Path) -> Path:
    """The contract suite's poisoned repository, plus the row its Codex configuration is missing.

    `plant` is imported rather than reproduced: the rows in `CONFIGURATIONS` are the fixture, this
    file has no business owning a second copy of them, and a row added there arrives here for free.
    What is added is a repository skill, which is a repo-contributed instruction channel outside
    `AGENTS.md` that this harness genuinely reads and that the suite's Codex row does not carry.
    """
    repo, _ = plant(root)
    skill = repo / ".codex" / "skills" / "agl-leak"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: agl-leak\ndescription: {SKILL_MARKER}\n---\nLeak.\n", encoding="utf-8"
    )
    return repo

@pytest.mark.asyncio
async def test_no_marker_from_a_poisoned_repository_is_in_what_this_adapter_tells_the_agent(
    tmp_path: Path,
) -> None:
    """The composed prompt carries the workflow's words and nothing the repository wrote.

    This is the adapter's own half, and it needs no binary at all. It would fail an adapter that
    read an `AGENTS.md` and helpfully prepended it, which is a thing an adapter could do with every
    harness option perfectly set. The harness's own half is the test below.
    """
    repo = poisoned(tmp_path)
    stub = Stub(tmp_path / "stub", steps=[{"say": started()}])

    await drive(stub, task_in(repo))
    composed = stub.seen()["stdin"]

    assert not markers_in(composed) and SKILL_MARKER not in composed, (
        f"the prompt this adapter composed carries {markers_in(composed)}, planted in the "
        f"workspace by the contract suite's own fixture. There are {len(CONFIGURATIONS)} rows in "
        f"that table and none of them is AGL's to read"
    )

@pytest.mark.skipif(not _cli(), reason=_NO_CLI)
@pytest.mark.asyncio
async def test_the_overrides_this_adapter_emits_load_and_silence_a_poisoned_repository(
    tmp_path: Path,
) -> None:
    """Hermeticity through the one window this harness opens for free: what it would put in
    front of a model, rendered without a model.

    `debug prompt-input` prints the model-visible prompt as JSON and contacts nothing, and it takes
    the same configuration overrides a run does - so the overrides are lifted straight off the
    command line the adapter composed a moment ago and handed to it in the poisoned repository.
    Two things are asserted at once and both matter:

      * **They all load.** An override this harness's loader rejects makes it exit before anything
        runs, so a green here is also the statement that the whole composed configuration is
        acceptable to this version - which is the half of "the command line is right" that no stub
        can check.
      * **The repository contributes nothing.** Not its `AGENTS.md`, at any depth, and not its
        `.codex/skills/*/SKILL.md`, which is a channel the contract suite's Codex row does not
        carry and which reaches the model when nothing suppresses it.

    **The control fires first and it is what makes a green readable.** Without the overrides the
    same repository puts its markers in front of the model; with them it does not. Without that,
    "no marker" and "no marker to find" are the same observation - and this test's failure mode,
    like the contract suite's, is to pass.

    What survives all of this, on a machine where it exists, is the *operator's* own
    `$CODEX_HOME/AGENTS.md`. Silencing an operator's own machine configuration was deliberately
    not built - it is theirs, not the repository's - and it is absent here only because
    `tests/conftest.py` empties that directory for a different reason.
    """
    repo = poisoned(tmp_path)
    stub = Stub(tmp_path / "stub", steps=[{"say": started()}])
    await drive(stub, task_in(repo))
    argv = stub.argv()
    pairs = zip(argv, argv[1:], strict=False)
    overrides = [token for pair in pairs if pair[0] == "-c" for token in pair]

    loose = _rendered(repo, [])
    assert markers_in(loose) or SKILL_MARKER in loose, (
        f"a repository carrying {len(CONFIGURATIONS)} poisoned configurations and a poisoned skill "
        f"contributed nothing to the prompt even with no overrides at all, so this test would "
        f"report a clean prompt whether or not anything is being kept out of it"
    )

    hermetic = _rendered(repo, overrides)
    leaked = [*markers_in(hermetic), *([SKILL_MARKER] if SKILL_MARKER in hermetic else [])]
    assert not leaked, (
        f"the prompt the harness would put in front of a model carries {leaked}, planted in the "
        f"workspace. The target repo contributes source code and nothing else, and these "
        f"overrides are the whole of what stands between a checkout and the agent"
    )

def _rendered(repo: Path, overrides: Sequence[str]) -> str:
    """The model-visible prompt the harness would compose in `repo`, as text. Free: no model.

    A non-zero exit is a failed assertion rather than an empty string, because the interesting way
    for this to go wrong is an override the loader refuses - which would otherwise look exactly
    like a repository that contributed nothing.
    """
    done = subprocess.run(
        ["codex", "debug", "prompt-input", *overrides, "X"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, (
        f"the harness refused to render a prompt under {list(overrides)}: {done.stderr.strip()}. "
        f"An override its loader rejects stops a run before anything starts, so this is the "
        f"composed configuration failing rather than a test-fixture problem"
    )
    return done.stdout

# Every directory this package may stand a child in, spelled as the source text `ast.unparse`
# produces, with what each one is. The **value** and not merely the keyword's presence, for
# `test_claude_code_runner.py`'s reason on its own siblings: the name is satisfied by the leak.
# `cwd=None` names the option and is exactly the inheritance an explicit directory exists to
# displace - `create_subprocess_exec` reads it as "wherever the parent happens to be standing" - so
# a test that asked only whether the keyword appeared would pass against the bug it is written for.
#
# A literal path would fail here too, and should: a directory written into the source is one chosen
# when the file was written rather than one chosen per call, and a run's workspace is not knowable
# then. So what is permitted is a small table of *names bound in the calling function*, and a fourth
# child spelling its directory some other way fails until somebody comes here and says which
# directory it is. That line is the point. It is weaker evidence than the Claude sibling's `[]` and
# `True`, and unavoidably so - hermeticity has one right value and a working directory has one right
# *property* - but it is the strongest thing readable at the call site, which is the same standard.
CHOSEN: Final[Mapping[str, str]] = {
    "workspace": "the run's own workspace, provisioned by WorkspaceProvider",
    "elsewhere": "a temporary directory of the probe's own, readiness probe or version probe",
}

def test_every_child_this_package_starts_is_started_somewhere_this_adapter_chose() -> None:
    """A structural assertion, so that a process added later cannot inherit AGL's own directory.

    Every one of this package's children is started with an explicit working directory and none of
    them by accident: a run's is the workspace, and each probe's - the readiness one and the
    version one - is a temporary directory of its own. The failure this catches is silent - a child
    with no `cwd=` runs wherever the operator started `agl`, which for this harness means resolving
    a project root, and every `AGENTS.md` above it, out of somebody else's repository.

    **The directory each child is given, and not only that the keyword was there.** This test began
    asserting presence alone, which reads as a check and is not one: `cwd=None` is what
    `create_subprocess_exec` means by "inherit", so the one spelling that reproduces the bug in full
    satisfied it. What is compared now is the source text of the argument against `CHOSEN` above -
    the same instrument its Claude sibling uses on `setting_sources` and `strict_mcp_config`, and
    the same deliberate strictness: a value assembled elsewhere, a literal path, or `None` all fail,
    because a working directory a reviewer cannot see at the call site is one nobody checked.

    Asserted by parsing the package rather than by running it, so that a third child added later
    is covered the moment it exists. `tests/adapters/test_shell_verifier.py` established the
    shape, for the same kind of clause;
    `test_claude_code_runner.py::test_every_session_this_package_opens_is_opened_hermetically` is
    this test's sibling over the hermeticity options that package's sessions carry.
    """
    package = Path(runner_module.__file__).parent
    spawns = 0
    for source in sorted(package.glob("*.py")):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", None) != "create_subprocess_exec":
                continue
            spawns += 1
            given = {keyword.arg: keyword.value for keyword in node.keywords}
            assert "cwd" in given, (
                f"{source.name}:{node.lineno} starts a child without saying where: it passes "
                f"{sorted(name for name in given if name)}. A child with no working directory of "
                f"its own inherits AGL's, and this harness reads instructions out of the directory "
                f"it is standing in"
            )
            written = ast.unparse(given["cwd"])
            assert written in CHOSEN, (
                f"{source.name}:{node.lineno} starts a child with `cwd={written}`, which is not "
                f"one of the directories this adapter chooses: "
                f"{', '.join(f'{name} ({what})' for name, what in sorted(CHOSEN.items()))}. "
                f"`cwd=None` is the spelling this catches and it is the whole failure - the child "
                f"then runs wherever the operator started `agl`, and this harness resolves a "
                f"project root and every AGENTS.md above it out of the directory it is standing "
                f"in. If this child genuinely stands somewhere new, say where in CHOSEN above; a "
                f"directory that lives in another module is one this test cannot read and a "
                f"reviewer cannot see here"
            )
    assert spawns >= 3, (
        f"only {spawns} child process start(s) were found in {package}, and there are at least "
        f"three - the run, the readiness probe and the version probe. This test found nothing to "
        f"check, which means it is no longer checking anything"
    )

# --- A value that would parse as a flag -----------------------------------------------------------

MARKER: Final = "AGL-A-SHELL-EVALUATED-THE-PATH"

# One path component that is a whole command line: a substitution that leaves a file behind, a
# semicolon, a pipeline, quotes, spaces - and `--output=x`, which is the shape that was found
# making a read-only git port write a file. `/` and NUL are the only bytes a filename cannot hold.
LOADED_NAME: Final = f"agl $(touch {MARKER}); echo leaked | cat & 'q' \"d\" --output=x tree"

@pytest.mark.asyncio
async def test_a_workspace_whose_name_would_run_a_command_never_runs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The workspace reaches the child as its working directory and as nothing else.

    The control fires first, because a green result has to be readable: "nothing interpolated this
    path" and "this path had nothing in it to interpolate" are the same observation otherwise. So
    the directory name is pasted into a real command line, the marker file it creates is proved to
    exist, the marker is removed, and only then is the adapter asked to work in that directory.

    Two witnesses afterwards. No marker file anywhere under the temporary directory, which is what
    a substitution reaching any shell would leave; and the child echoing the directory back
    **whole**, which is what tells a `chdir` from a path that was split on spaces, truncated at the
    semicolon, or quietly ignored.
    """
    monkeypatch.chdir(tmp_path)
    repo = workspace(tmp_path / LOADED_NAME)
    stub = Stub(tmp_path / "stub", steps=[{"say": started()}])

    subprocess.run(f"cd {repo}", shell=True, cwd=tmp_path, capture_output=True, check=False)
    fired = sorted(tmp_path.rglob(MARKER))
    assert fired, (
        f"the control did not fire: pasting this directory name into a command line was supposed "
        f"to run `touch {MARKER}`, and no such file appeared. A fixture that is not dangerous "
        f"disarms this test silently, which is the failure it exists to avoid"
    )
    for stray in fired:
        stray.unlink()

    await drive(stub, task_in(repo))

    assert not sorted(tmp_path.rglob(MARKER)), (
        f"a run whose workspace holds `$(touch {MARKER})` in its name left the file behind, so "
        f"the path reached a shell as text. It is passed as the child's working directory "
        f"precisely so that it cannot: an argument list is not program text, and a directory is "
        f"not an argument"
    )
    assert Path(stub.seen()["cwd"]).resolve() == repo.resolve(), (
        f"the child says it is standing in {stub.seen()['cwd']!r}. The workspace was "
        f"{str(repo)!r}, whole, including the spaces and the `--output=x`"
    )

def test_a_cli_path_that_would_parse_as_a_flag_is_refused_at_construction() -> None:
    """The argv rule on the one value the composition root supplies.

    `cli_path` reaches the command line as its own token, so a value beginning with `-` is a flag
    rather than a value - and this particular one names the flag that would switch off the sandbox
    that is the entire restriction mechanism.
    """
    with pytest.raises(InputError) as refused:
        OpenAiRunner(Path("--dangerously-bypass-approvals-and-sandbox"))
    assert "cli_path" in str(refused.value), (
        f"the refusal does not name which value was refused: {refused.value}"
    )

@pytest.mark.asyncio
async def test_a_model_that_would_parse_as_a_flag_is_refused_before_anything_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same rule on the value that is *rendered* rather than supplied.

    `translate.model_slug` answers out of a closed table today, so no `ModelId` can produce this -
    which is exactly why the guard is worth a test, and why `translate.py` said in as many words
    that the guarantee belongs where the value reaches a command line rather than in a branch of
    its own that no input can reach. Substituting the renderer is how the guard is reached at all.

    What is asserted is that the refusal happens **before a process exists**: the stub leaves a
    record whenever it is started, and there is none.
    """
    monkeypatch.setattr(runner_module, "model_slug", lambda model: "--add-dir")
    stub = Stub(tmp_path / "stub", steps=[{"say": started()}])

    with pytest.raises(InputError) as refused:
        await drive(stub, task_in(workspace(tmp_path)))

    assert "model" in str(refused.value), f"the refusal does not say what it refused: {refused}"
    assert not stub.record.is_file(), (
        "a child was started with a model that parses as a flag. The refusal has to happen before "
        "anything runs, or it is not a refusal - it is a harness reporting a bad argument after "
        "AGL has already spent whatever starting it costs"
    )

# --- The stream: every outcome this adapter can reach ---------------------------------------------

@pytest.mark.asyncio
async def test_a_completed_turn_is_the_outcome_and_the_last_thing_the_agent_said(
    tmp_path: Path,
) -> None:
    """The ordinary ending, and the two fields the port answers with.

    The agent's text is taken from the last message frame that carried any, which is why two are
    played: an item is updated and then completed, and reporting the first would answer with a
    prefix of the sentence the agent finished writing.
    """
    stub = Stub(
        tmp_path,
        steps=[
            {"say": item("item.updated", "agent_message", text="One Pyth")},
            {"say": said("One Python module that greets a name.")},
            {"say": started()},
        ],
    )

    outcome = await drive(stub, task_in(workspace(tmp_path)))

    assert outcome.stop_reason is StopReason.COMPLETED
    assert outcome.text == "One Python module that greets a name."

@pytest.mark.asyncio
async def test_a_stream_that_never_says_how_it_ended_answers_with_no_stop_reason(
    tmp_path: Path,
) -> None:
    """`None` is the port's spelling for "this backend did not say", and here it is reachable.

    This harness carries no machine-readable stop reason at all - a turn either completes or fails,
    and neither says why - so `COMPLETED` is the one thing that can be read and everything else is
    honestly nothing. Inventing `COMPLETED` for a stream that ended without saying so would tell a
    workflow the agent finished when it may have been cut off, which is the one genuinely damaging
    answer here.
    """
    stub = Stub(tmp_path, steps=[{"say": said("as far as I got")}])

    outcome = await drive(stub, task_in(workspace(tmp_path)))

    assert outcome.stop_reason is None, (
        f"a stream with no terminal event was read as {outcome.stop_reason!r}. The port made None "
        f"legal precisely so that "
        f"'this backend did not say' has a spelling that is not a lie"
    )
    assert outcome.text == "as far as I got"

@pytest.mark.asyncio
async def test_an_agent_that_said_nothing_answers_with_the_empty_string(tmp_path: Path) -> None:
    """`""` and never `None`: the port's only content channel gets no second way to be empty."""
    stub = Stub(tmp_path, steps=[{"say": started()}])

    assert (await drive(stub, task_in(workspace(tmp_path)))).text == ""

@pytest.mark.asyncio
async def test_a_failed_turn_is_raised_with_the_harnesss_own_words(tmp_path: Path) -> None:
    """The adapter translates at its own boundary, and the CLI's words survive into it.

    The contract suite's gap 7 says in as many words that it cannot provoke one - "nothing here can
    make a backend fail on demand" - and this is a case a person actually meets. It is also where
    the stream-first ordering earns its keep: the exit status here is 1, which on this harness
    spans "the configuration would not load" and "a turn ran and failed", and only the frame says
    which.
    """
    reason = "You've hit your usage limit."
    stub = Stub(
        tmp_path,
        steps=[{"say": {"type": "turn.failed", "error": {"message": reason}}}],
        exit=1,
    )

    with pytest.raises(UpstreamUnavailable) as raised:
        await drive(stub, task_in(workspace(tmp_path)))

    assert reason in str(raised.value), (
        f"the refusal does not carry what the harness said: {raised.value}. An UpstreamUnavailable "
        f"whose message does not name the cause is the same dead end as no message at all"
    )

@pytest.mark.asyncio
async def test_a_top_level_error_event_is_raised_even_when_the_process_exits_cleanly(
    tmp_path: Path,
) -> None:
    """An error the stream announced and never finished past is a failure whatever the status says.

    Nothing establishes that this harness exits non-zero for every error it reports, and the
    consequence of guessing wrong is the damaging direction: an error message returned in the one
    field a workflow reads as the agent's answer. What a turn does finish past is the retry notice
    in `test_a_reconnect_notice_before_a_completed_turn_leaves_the_run_finished_and_answered`;
    nothing here ends the turn at all, so the message stands as the only account of the run.
    """
    stub = Stub(tmp_path, steps=[{"say": {"type": "error", "message": "the sky fell in"}}], exit=0)

    with pytest.raises(UpstreamUnavailable) as raised:
        await drive(stub, task_in(workspace(tmp_path)))
    assert "the sky fell in" in str(raised.value)

# A dropped stream is announced as a top-level `error` whose text opens `Reconnecting... n/m`, the
# parenthetical naming however the connection ended; measured on codex-cli 0.155.1 driven at an
# endpoint on 127.0.0.1 that cut the stream. The opening is the stable part and the tag is the
# only one the retry carries.
_RECONNECT: Final = (
    "Reconnecting... 1/5 (stream disconnected before completion: stream closed before "
    "response.completed)"
)

@pytest.mark.asyncio
async def test_a_reconnect_notice_before_a_completed_turn_leaves_the_run_finished_and_answered(
    tmp_path: Path,
) -> None:
    """A dropped stream that reconnected and finished, replayed frame for frame as it arrives.

    The harness announces a lost connection as a top-level `error` event, retries behind it, and
    then completes the turn and exits 0. So an `error` frame is not on its own a statement that the
    run failed, and reading it as one throws away a turn that finished along with everything the
    agent did in it - the operator is told to act on the least informative line in the stream while
    the work it describes is already done. `turn.completed` beside a clean exit is what says the
    turn got past it, and it is the only thing here that does.
    """
    stub = Stub(
        tmp_path,
        steps=[
            {"say": {"type": "turn.started"}},
            {"say": {"type": "error", "message": _RECONNECT}},
            {"say": said("I finished the task successfully.")},
            {"say": started()},
        ],
        exit=0,
    )

    outcome = await drive(stub, task_in(workspace(tmp_path)))

    assert outcome.stop_reason is StopReason.COMPLETED, (
        f"a turn that completed after its stream reconnected answered {outcome.stop_reason!r}. A "
        f"retry the harness recovered from is not an outcome, and a run destroyed by one is a step "
        f"re-run for nothing"
    )
    assert outcome.text == "I finished the task successfully."

@pytest.mark.asyncio
async def test_a_terminal_error_after_a_reconnect_notice_is_the_message_the_refusal_carries(
    tmp_path: Path,
) -> None:
    """Which of two announced errors an operator is sent to act on, when a run really does fail.

    A retry can precede a genuine failure, so keeping the first message means handing over
    `Reconnecting...` and discarding the cause. A refusal naming the wrong thing is worse than the
    dead end of naming nothing: it sends somebody to fix a network that was fine, and the sentence
    that would have told them their allowance is gone was read and thrown away.
    """
    terminal = "You've hit your usage limit."
    stub = Stub(
        tmp_path,
        steps=[
            {"say": {"type": "turn.started"}},
            {"say": {"type": "error", "message": _RECONNECT}},
            {"say": {"type": "error", "message": terminal}},
            {"say": {"type": "turn.failed", "error": {"message": terminal}}},
        ],
        exit=1,
    )

    with pytest.raises(UpstreamUnavailable) as raised:
        await drive(stub, task_in(workspace(tmp_path)))

    assert terminal in str(raised.value), (
        f"the refusal does not carry the error the turn failed on: {raised.value}"
    )
    assert "Reconnecting" not in str(raised.value), (
        f"the refusal quotes the retry that preceded the failure: {raised.value}. That is the "
        f"message latched first rather than the one saying why the run stopped"
    )

@pytest.mark.asyncio
async def test_a_rejected_command_line_is_our_bug_and_not_a_backend_that_was_busy(
    tmp_path: Path,
) -> None:
    """Exit 2 is the argument parser refusing to start, so no retry can change it.

    `UpstreamUnexpected` rather than `UpstreamUnavailable`, and the distinction is what a reader is
    supposed to do next: the binary works and this adapter's idea of its command line does not.
    """
    stub = Stub(tmp_path, steps=[{"err": "error: unexpected argument '--nope' found"}], exit=2)

    with pytest.raises(UpstreamUnexpected) as raised:
        await drive(stub, task_in(workspace(tmp_path)))
    assert "unexpected argument" in str(raised.value), (
        f"the refusal drops the parser's own complaint: {raised.value}"
    )

@pytest.mark.asyncio
async def test_a_non_zero_exit_with_nothing_on_the_stream_falls_back_to_standard_error(
    tmp_path: Path,
) -> None:
    """The fallback, and the reason standard error is drained rather than inherited.

    A run that failed with no frame to explain it leaves the harness's last words as the only
    evidence there is, so they have to have been read - which is also what stops a child from
    blocking forever on a pipe nobody is emptying.
    """
    stub = Stub(tmp_path, steps=[{"err": "codex: CODEX_HOME does not exist"}], exit=1)

    with pytest.raises(UpstreamUnavailable) as raised:
        await drive(stub, task_in(workspace(tmp_path)))
    assert "CODEX_HOME does not exist" in str(raised.value)

@pytest.mark.asyncio
async def test_a_completed_turn_that_exits_non_zero_is_still_a_failure(tmp_path: Path) -> None:
    """Which question the exit status answers, and which one it does not.

    The *message* comes from the stream first, because 1 is overloaded and a frame carries words.
    Whether the run failed at all is decided the other way: a non-zero exit is a failure even when
    the stream looked healthy, because the two ways of being wrong are not symmetrical. A run
    reported as failed when it merely exited oddly costs a step a person can see and re-run; a
    truncated answer returned as `COMPLETED` is a wrong result that looks like a right one, and
    the ledger then records it under a fingerprint saying nothing was amiss.
    """
    stub = Stub(tmp_path, steps=[{"say": said("half an ans")}, {"say": started()}], exit=1)

    with pytest.raises(UpstreamUnavailable):
        await drive(stub, task_in(workspace(tmp_path)))

@pytest.mark.asyncio
async def test_a_line_that_is_not_json_is_unreadable_and_a_frame_from_the_future_is_not(
    tmp_path: Path,
) -> None:
    """The distinction the whole reading half turns on, asserted in both directions.

    A line this adapter cannot parse is the harness having said something we cannot read, which is
    `UpstreamUnexpected` - the far side is working and our understanding of it is what failed. An
    **unknown frame kind** is not that: an item kind exists in this harness's own source that
    appears in neither its documentation nor this build, so a tag from the future is a certainty,
    and an adapter that raised on one would turn a harness release into an outage.
    """
    broken = Stub(tmp_path / "broken", steps=[{"raw": '{"type": "turn.compl'}], exit=0)
    with pytest.raises(UpstreamUnexpected) as raised:
        await drive(broken, task_in(workspace(tmp_path)))
    assert "turn.compl" in str(raised.value), f"the refusal does not quote the line: {raised.value}"

    ahead = Stub(
        tmp_path / "ahead",
        steps=[
            {"say": {"type": "thread.started", "thread_id": "01997"}},
            {"say": {"type": "turn.negotiated", "whatever": True}},
            {"say": item("item.started", "collab_tool_call", tool="delegate")},
            {"say": said("done")},
            {"say": started()},
        ],
    )
    outcome = await drive(ahead, task_in(workspace(tmp_path)))
    assert outcome.stop_reason is StopReason.COMPLETED and outcome.text == "done", (
        f"a stream carrying three frames this adapter has no reading for answered {outcome!r}. "
        f"Consume what you recognise, ignore what you do not, and never treat an unknown tag as "
        f"an error"
    )

@pytest.mark.asyncio
async def test_an_event_larger_than_the_read_buffer_is_read_and_one_larger_than_memory_is_not(
    tmp_path: Path,
) -> None:
    """One frame can carry a whole command's output, and this is what that does to the reader.

    Two behaviours, on one run, because each is the other's control. A frame larger than the read
    buffer is **recovered and read**: the stream's own `readuntil` refuses a line longer than its
    buffer, and letting that surface would mean an agent whose build printed two megabytes ended
    the run with an error about a limit nobody chose. A frame larger than what this adapter will
    hold is **skipped**, silently, and the run carries on - a cap is what stops an agent's console
    output from exhausting this process, and raising on one would put an outage where a lost
    dashboard line belongs.

    The second is asserted through what the outcome does *not* say, which is the only way a silent
    skip is visible: the closing text is the last message small enough to read, and the run still
    ends normally.
    """
    recovered = "x" * (3 << 20)
    stub = Stub(
        tmp_path,
        steps=[
            {"say": said(recovered)},
            {"say": said("y" * (9 << 20))},
            {"say": started()},
        ],
    )

    outcome = await drive(stub, task_in(workspace(tmp_path)))

    assert outcome.text == recovered, (
        f"a {len(recovered)}-byte event was read as {len(outcome.text)} bytes. Anything other than "
        f"the whole of it means the recovery joined the pieces wrongly, and anything raised means "
        f"a buffer size decided whether a run succeeded"
    )
    assert outcome.stop_reason is StopReason.COMPLETED, (
        "a frame too large to hold ended the run. It is skipped instead, because what is lost is "
        "one line of a dashboard and what would be lost otherwise is the whole step"
    )

@pytest.mark.asyncio
async def test_activity_is_the_frames_own_kind_and_the_field_that_kind_is_about(
    tmp_path: Path,
) -> None:
    """The activity line, formed by `translate.activity` and passed through untouched.

    The contract suite can only assert that whatever arrives is a `str`, because it cannot know
    what the adapter meant to say. This one knows: a command renders as the command, a file change
    renders relative to the workspace, and a tool call renders as the server and tool.

    Two rules about *when* are asserted with it, and both are `_session.py`'s. An item that has
    completed is not activity - a dashboard cell still reading `Running:` after the command
    finished is telling a person something untrue - and the same line twice running is reported
    once, because an item updated while a command's output grows renders to the same sentence
    every time.
    """
    repo = workspace(tmp_path)
    lines: list[str] = []
    stub = Stub(
        tmp_path,
        steps=[
            {"say": item("item.started", "command_execution", command="./gradlew build")},
            {"say": item("item.updated", "command_execution", command="./gradlew build")},
            {"say": item("item.completed", "command_execution", command="./gradlew build")},
            {"say": item("item.started", "file_change", changes=[{"path": f"{repo}/src/g.py"}])},
            {"say": item("item.started", "mcp_tool_call", server="agl", tool="record_note")},
            {"say": item("item.started", "reasoning", text="thinking")},
            {"say": item("item.completed", "web_search", query="never reported")},
            {"say": started()},
        ],
    )

    await drive(stub, task_in(repo), on_activity=lines.append)

    assert lines == [
        "Running: ./gradlew build",
        "Changing: src/g.py",
        "Calling: agl/record_note",
    ], f"the activity lines were {lines}"

@pytest.mark.asyncio
async def test_an_activity_reporter_that_raises_comes_out_of_this_adapters_run(
    tmp_path: Path,
) -> None:
    """The contract suite's activity-reporter clause, against the real adapter, for free.

    That clause is the one test of a `run` in `AgentContract` that reads no model conduct, which is
    what makes it reachable here: the reporter fails on whatever the stream reports, and the stub
    emits two started items without an agent deciding anything. Against `_NeverRuns` it skips with
    the other five, so this is where the real `OpenAiRunner` is actually held to it.

    What it forbids is a `try` around `_item`'s `on_activity(line)`. That is one line to add, it
    would look like defensive good manners, and every other test in this build would stay green
    while a broken reporter went unmentioned for the length of every run.
    """
    repo = workspace(tmp_path)
    failing = Activity(raise_first=1)
    stub = Stub(
        tmp_path,
        steps=[
            {"say": item("item.started", "command_execution", command="./gradlew build")},
            {"say": item("item.started", "mcp_tool_call", server="agl", tool="record_note")},
            {"say": started()},
        ],
    )

    with pytest.raises(ReporterFailed):
        await drive(stub, task_in(repo), on_activity=failing)

    assert len(failing.lines) == 1, (
        f"the reporter was called {len(failing.lines)} time(s) and it raised on the first, so the "
        f"stream reader caught the exception and went on reporting. `ports/agent.py` puts no `try` "
        f"around that call by design"
    )

# --- Tools, against the adapter's own server, with no harness anywhere ---------------------------

@pytest.mark.asyncio
async def test_a_tool_call_reaches_its_handler_as_a_mapping_and_its_text_goes_back(
    tmp_path: Path,
) -> None:
    """The port's uniform rule: invoke the handler, put its `text` back into the conversation.

    The contract suite asserts the same thing through a model's conduct and says so about itself.
    Here the call is made directly - over real HTTP, against the real MCP server this adapter runs,
    from a process that found the address on its own command line - so what is observed is the
    wiring: the payload arrives parsed, the handler's text comes back as the tool result, and
    nothing about which tool it is was read on the way.
    """
    notes = Notes()
    stub = Stub(
        tmp_path,
        steps=[
            {"call": {"server": "agl", "tool": "record_note", "arguments": {"note": "one module"}}},
            {"say": said("done")},
            {"say": started()},
        ],
    )

    await drive(stub, task_in(workspace(tmp_path), tools=(notes.tool,)))

    assert [dict(payload) for payload in notes.received] == [{"note": "one module"}], (  # type: ignore[call-overload]
        f"the handler was handed {notes.received}, and the port declares a Mapping"
    )
    assert isinstance(notes.received[0], Mapping), (
        "an adapter that passed on the raw text its backend produced would make every handler in "
        "the framework parse a payload the port says is already parsed"
    )
    answered = stub.seen()["answers"][0]["result"]
    assert answered["content"][0]["text"] == "Noted. Nothing else is needed from this tool."
    assert answered["isError"] is False

@pytest.mark.asyncio
async def test_a_refused_tool_result_carries_the_mechanisms_own_error_flag(
    tmp_path: Path,
) -> None:
    """`ToolResult.rejected` becomes MCP's error flag rather than prose in the text.

    The port lets an adapter render a refusal into the text when its backend has no error channel,
    and this one has one - so the assertion is that it is used. The contract suite deliberately
    cannot see this: it asserts the outcome (the handler called again) and never the mechanism.
    """
    notes = Notes(reject_first=1)
    call = {"server": "agl", "tool": "record_note", "arguments": {"note": "no file named"}}
    stub = Stub(
        tmp_path,
        steps=[
            {"call": call},
            {"call": {**call, "arguments": {"note": "README.md says so"}}},
            {"say": started()},
        ],
    )

    await drive(stub, task_in(workspace(tmp_path), tools=(notes.tool,)))
    refused, accepted = (answer["result"] for answer in stub.seen()["answers"])

    assert refused["isError"] is True and "not accepted" in refused["content"][0]["text"]
    assert accepted["isError"] is False
    assert len(notes.received) == 2, "both calls reached the handler inside one run"

@pytest.mark.asyncio
async def test_a_call_the_server_cannot_carry_is_refused_back_into_the_conversation(
    tmp_path: Path,
) -> None:
    """Two malformed calls, and neither ends the run or reaches a handler.

    There were three. The middle one was a blank question put to AGL's own asking tool, and it went
    with that tool: what refuses a blank question now is the *workflow's* handler, on this same
    path, so the assertion belongs to whichever workflow supplies one.

    The reject-back-to-the-agent rule decides the shape: by the time a call is wrong there is a
    session in flight holding all
    the reasoning that produced it, and a protocol error is the one answer that gives the model
    nothing to correct. So each of these comes back as a *refused result*, in words, and the run
    carries on to its ordinary ending.

    The second is the one check this server owes. Nothing here validates a payload against its
    schema - the port says the schema is data and the handler decides what is acceptable, and AGL
    has no validator - but the port also declares a handler's parameter to be a mapping, so a
    client that sent an array must not be the thing that discovers otherwise.
    """
    notes = Notes()
    stub = Stub(
        tmp_path,
        steps=[
            {"call": {"server": "agl", "tool": "no_such_tool", "arguments": {}}},
            {"call": {"server": "agl", "tool": "record_note", "arguments": ["not", "object"]}},
            {"say": started()},
        ],
    )

    outcome = await drive(stub, task_in(workspace(tmp_path), tools=(notes.tool,)))
    unknown, wrong = (answer["result"] for answer in stub.seen()["answers"])

    assert unknown["isError"] is True and "no tool called" in unknown["content"][0]["text"]
    assert wrong["isError"] is True and "JSON object" in wrong["content"][0]["text"]
    assert notes.received == [], f"a malformed call reached a handler: {notes.received}"
    assert outcome.stop_reason is StopReason.COMPLETED, "and the run itself ended normally"

# There were three tests here and there are none. Two were about the `agl_ask` MCP server AGL used
# to register on every task - a question answered with nobody listening, and a question handler that
# raised ending the run - and the third was the two-round negotiation through it. The server is
# gone: a question is an ordinary tool a workflow supplies, so it arrives on the `agl` server with
# everything else and every clause those tests made is made about a tool above. The round-trip claim
# is `test_a_refused_tool_result_carries_the_mechanisms_own_error_flag`, which drives two calls
# through one child and reads both results.

@pytest.mark.asyncio
async def test_a_tool_handler_that_raises_ends_the_run_with_its_own_exception(
    tmp_path: Path,
) -> None:
    """A workflow tool that throws behaves the same way on both backends, which is the point.

    AGL owns the MCP server here, so `_tools.Caller.handled` is where the exception is caught: it
    records it, answers the in-flight call with a result the model can read rather than leaving the
    harness waiting on a tool that never replied, and `_session.py` then breaks out of the stream
    at the next frame and raises it out of `run`. The other adapter's vendor SDK would have turned
    the same exception into an error result and carried on, which is exactly why that adapter
    catches at its own boundary too - a workflow's tool cannot behave two ways depending on which
    adapter happened to serve the step.

    **This test used to assert the opposite** - `..._is_told_to_the_model_and_does_not_end_the_
    run` - and `tests/contracts/agent.py` argues the inversion in full. The short of it: a handler
    that wants the agent to try again says so with `ToolResult(rejected=True)`, which is untouched,
    so a handler that *raises* is saying something else, and absorbing it is what leaves an
    unanswerable approval gate silently absent while the step records a result anyway.

    **Two arrangements, because the stub can only be read when it finishes on its own.** The first
    puts the call last, so the stub writes its record and exits before the adapter has anything to
    stop - which is what makes `stub.seen()` a fact rather than a race against a SIGTERM. The
    second puts two calls back to back before any frame, which is what a harness issuing parallel
    tool calls looks like, and asserts the second never reached the handler: once a caller's code
    has failed, no more of it runs.
    """
    calls: list[Mapping[str, JsonValue]] = []
    stopping = RuntimeError("the note store is on fire")

    async def explode(payload: Mapping[str, JsonValue]) -> ToolResult:
        calls.append(payload)
        raise stopping

    tool = Tool(
        name="record_note",
        description="Write down one note.",
        payload_schema={"type": "object", "properties": {"note": {"type": "string"}}},
        handler=explode,
    )
    stub = Stub(
        tmp_path / "told",
        steps=[
            {"say": started()},
            {"call": {"server": "agl", "tool": "record_note", "arguments": {"note": "x"}}},
        ],
    )

    with pytest.raises(RuntimeError) as raised:
        async with asyncio.timeout(30):
            await drive(stub, task_in(workspace(tmp_path), tools=(tool,)))

    assert raised.value is stopping, (
        f"the run ended with {raised.value!r} rather than with the handler's own exception, so a "
        f"workflow's Stop or a headless terminal's refusal would be reported as something else"
    )
    told = stub.seen()["answers"][0]["result"]
    assert told["isError"] is True and "on fire" in told["content"][0]["text"], (
        f"the model was handed {told}. The call it made is still answered - a harness waiting on a "
        f"tool result that never comes is a hang, and this adapter's tool timeout is a day - and "
        f"what it is told is that the task is being stopped"
    )

    calls.clear()
    twice = Stub(
        tmp_path / "twice",
        steps=[
            {"call": {"server": "agl", "tool": "record_note", "arguments": {"note": "x"}}},
            {"call": {"server": "agl", "tool": "record_note", "arguments": {"note": "y"}}},
            {"say": said("done")},
            {"say": started()},
        ],
    )
    with pytest.raises(RuntimeError):
        async with asyncio.timeout(30):
            await drive(twice, task_in(workspace(tmp_path), tools=(tool,)))

    assert len(calls) == 1, (
        f"the handler was called {len(calls)} time(s) against a harness that called the tool "
        f"twice before any frame arrived. A stream check cannot come between two calls made back "
        f"to back, so the second one is refused where the first was caught: once a caller's own "
        f"code has failed, no more of it runs"
    )

# --- and which of two failures is the one the run is stopped by -----------------------------------

_LATCH_BOUND: Final = 5.0
"""Seconds either half of the arrangement below is allowed to take.

Nothing here starts a process, opens a socket or writes a stub: two coroutines hand an
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
    guard before the first one raised. That is two tool calls in flight at once, and on this backend
    the transport produces them without any help from the harness: `_http.Listener` is an
    `asyncio.start_server` that spawns one task per connection, so two concurrent POSTs to the MCP
    server are two concurrent `Caller.handled`. The stub above reaches the same state a different
    way, issuing two calls back to back with no frame between them.

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
    classes are byte-identical copies, `tests/adapters/test_claude_code_runner.py` holds this same
    clause under this same name, and a workflow's tool cannot behave two ways depending on which
    adapter happened to serve the step.
    """
    caller = _tools.Caller()
    first = RuntimeError("the note store is on fire")
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
        f"harness waiting on a tool result that never comes is a hang - and each is told what its "
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
async def test_a_tools_schema_reaches_the_model_as_the_workflow_declared_it(
    tmp_path: Path,
) -> None:
    """What a client reads off the server, which is what decides whether a model can call anything.

    One claim, and it is now the only one there is: a workflow's own schema is advertised whole, so
    a model producing an argument against it produces one the handler will accept.

    There was a second, about the three properties of AGL's own asking tool. That tool is gone and
    the claim went with it in the only direction it could: what an asking tool advertises is now
    derived from a payload dataclass the *workflow* wrote, so it is that workflow's own suite that
    owes the assertion. What is left here is the crossing itself, which is this adapter's - and it
    carries a workflow's asking tool exactly as it carries any other.
    """
    notes = Notes()
    stub = Stub(
        tmp_path,
        steps=[
            {"call": {"server": "agl", "list": True}},
            {"say": started()},
        ],
    )

    await drive(stub, task_in(workspace(tmp_path), tools=(notes.tool,)))
    (supplied,) = (answer["result"]["tools"] for answer in stub.seen()["answers"])

    declared = next(entry for entry in supplied if entry["name"] == "record_note")
    assert declared["inputSchema"] == dict(notes.tool.payload_schema), (
        f"the workflow's tool reached the model as {declared['inputSchema']!r}, and it declared "
        f"{dict(notes.tool.payload_schema)!r}. Nothing here is entitled to rewrite it"
    )
    assert declared["description"] == notes.tool.description
    assert "title" in declared["inputSchema"], (
        "the fixture this test is pointed at no longer carries a `title`, so the assertion above "
        "no longer says anything about the annotation `sdk/tools.py::_object_schema` writes into "
        "every derived payload schema - see `_NOTE_SCHEMA`. `title` is a standard JSON Schema "
        "annotation keyword with no validating behaviour in any draft, which is why it was chosen "
        "over `$id` and `description` to carry a payload type's identity across the port"
    )

@pytest.mark.asyncio
async def test_a_schema_carrying_only_a_type_still_describes_an_object(tmp_path: Path) -> None:
    """`{"type": "object"}` is a legal `payload_schema` and has to survive the crossing.

    A client that requires a `properties` key would otherwise refuse a tool the port considers
    perfectly declared, and the failure would be a tool the model never calls with no error
    anywhere. What is added is the key the port's own words already imply, and nothing else.
    """

    async def here(payload: Mapping[str, JsonValue]) -> ToolResult:
        return ToolResult(text="here")

    bare = Tool(
        name="ping", description="Say that you are here.", payload_schema={}, handler=here
    )
    stub = Stub(
        tmp_path, steps=[{"call": {"server": "agl", "list": True}}, {"say": started()}]
    )

    await drive(stub, task_in(workspace(tmp_path), tools=(bare,)))
    advertised = stub.seen()["answers"][0]["result"]["tools"][0]

    assert advertised["inputSchema"] == {"type": "object", "properties": {}}

@pytest.mark.asyncio
async def test_every_advertised_tool_is_marked_neither_destructive_nor_open_world(
    tmp_path: Path,
) -> None:
    """Without these two the harness never calls an AGL tool at all, and says so only to the model.

    `runner.py` runs the harness under `approval_policy="never"`, which denies rather than allows
    anything needing approval, and MCP's own defaults make an unannotated tool both destructive and
    open-world. The two together mean a reporting tool is refused before its handler is reached, the
    step returns nothing, and the only record of why is a sentence in the agent's final message.

    Measured against codex-cli 0.149.0 and 0.152.0, which agree: `readOnlyHint` alone is also
    accepted, and either hint alone is not. `readOnlyHint` is the wrong claim to make here - a
    reporting tool is how a step's result is recorded, so it does modify something - which is why
    the pair is what `_tools.py` sends. Nothing in this suite can reach the harness to check that
    it still reads them, so what is asserted here is only that AGL sends them.
    """

    async def here(payload: Mapping[str, JsonValue]) -> ToolResult:
        return ToolResult(text="here")

    bare = Tool(
        name="ping", description="Say that you are here.", payload_schema={}, handler=here
    )
    stub = Stub(
        tmp_path, steps=[{"call": {"server": "agl", "list": True}}, {"say": started()}]
    )

    await drive(stub, task_in(workspace(tmp_path), tools=(bare,)))
    advertised = stub.seen()["answers"][0]["result"]["tools"][0]

    assert advertised["annotations"] == {"destructiveHint": False, "openWorldHint": False}, (
        f"the tool reached the harness annotated {advertised.get('annotations')!r}. Under "
        f"`approval_policy=\"never\"` anything short of both being false is denied, and the denial "
        f"surfaces as a step that reported nothing rather than as an error"
    )

# --- The three members preflight asks ------------------------------------------------------------

def test_capabilities_are_the_ports_own_members_and_not_equivalent_strings() -> None:
    """The suite asserts this too; what it cannot assert is *which* three, and why they are static.

    `Capability` is a `StrEnum`, so this is a statement about the members and not about a set that
    compares equal to them today. The three are all of them: this harness edits files, runs
    commands and calls tools over MCP, on every build and on every machine, so none of the three is
    conditional on a flag.

    There were four while `MID_RUN_QUESTIONS` existed, and this docstring used to argue that one at
    length - it was unconditional because AGL ran an asking tool of its own rather than depending on
    the harness's. The member went when a question became an ordinary tool: what a role needs of a
    backend in order to ask is `TOOL_CALLING`, which is already here.
    """
    assert asyncio.run(OpenAiRunner().capabilities(OpenAI.SOL)) == frozenset(Capability), (
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
        asyncio.run(OpenAiRunner().capabilities(Claude.OPUS))
    with pytest.raises(InputError):
        asyncio.run(OpenAiRunner().check_ready(Claude.OPUS))

@pytest.mark.asyncio
async def test_check_ready_returns_when_the_cli_says_it_is_logged_in(tmp_path: Path) -> None:
    """The branch where nothing is wrong, and the probe that has to have happened for it to mean
    anything.

    A `check_ready` that returned by doing nothing at all would satisfy `await` and nothing else,
    so the argument list is read back: it is the harness's own credential-store query, which is why
    this member costs nothing on this backend where the other adapter has to spend a turn.
    """
    stub = Stub(tmp_path, login={"say": "Logged in using ChatGPT", "exit": 0})

    await OpenAiRunner(stub.path).check_ready(OpenAI.TERRA)

    assert stub.argv() == ["login", "status"], (
        f"the readiness probe ran {stub.argv()}. It is meant to be the local credential query, "
        f"which reaches no model and no network - a probe that started a turn would make deciding "
        f"whether to spend money cost money"
    )

@pytest.mark.asyncio
async def test_check_ready_refuses_with_the_clis_own_reason_when_it_is_not_logged_in(
    tmp_path: Path,
) -> None:
    """The refusing branch, and the one exception this member is allowed.

    `tests/contracts/_agent_preflight.py` fails any other exception by name, because the first
    preflight check catches `UpstreamUnavailable` and nothing else - anything else reaches the top
    of the CLI as exit 70 and tells a person to file a bug about their own logged-out session.
    """
    stub = Stub(tmp_path, login={"say": "Not logged in", "exit": 1})

    with pytest.raises(UpstreamUnavailable) as raised:
        await OpenAiRunner(stub.path).check_ready(OpenAI.TERRA)
    assert "Not logged in" in str(raised.value), (
        f"the refusal does not carry the reason the CLI gave: {raised.value}"
    )

@pytest.mark.asyncio
async def test_check_ready_says_the_cli_is_missing_rather_than_raising_an_os_error(
    tmp_path: Path,
) -> None:
    """The other way this member is reached: there is no binary at all.

    An `OSError` out of here would escape as a framework bug rather than as a backend that is not
    ready, which is the one distinction preflight is built on.
    """
    with pytest.raises(UpstreamUnavailable) as raised:
        await OpenAiRunner(tmp_path / "no-such-binary").check_ready(OpenAI.TERRA)
    assert "not installed" in str(raised.value) or "PATH" in str(raised.value)

@pytest.mark.skipif(not _cli(), reason=_NO_CLI)
@pytest.mark.asyncio
async def test_check_ready_refuses_against_the_real_cli_with_no_credential() -> None:
    """The same member against the real binary, which is free on this backend and only on this one.

    `tests/conftest.py` points the credential directory at an empty one for every test in the
    repository, so the honest answer here is "not logged in" and this is the adapter reaching it
    through the real command rather than through a stub that was told to say so. It is also the
    measurement behind `check_ready` being free: no model is contacted, and none can be.
    """
    with pytest.raises(UpstreamUnavailable) as raised:
        await OpenAiRunner().check_ready(OpenAI.LUNA)
    assert str(raised.value), "the port asks for a reason a person can act on"

@pytest.mark.asyncio
async def test_the_version_probe_puts_both_of_the_harnesss_own_questions_and_reads_each_answer(
    tmp_path: Path,
) -> None:
    """Two subcommands, and each one is read for a different half of what a warning is built from.

    `--version` for the release and `debug models` for what each model reasons at. The second is
    the whole reason a warning on this backend can be specific where the Claude one cannot: the
    harness carries a listing, it costs no turn to read, and it is what lets a sentence name the
    levels a model does offer where the one a role asked for is not among them.

    The levels are asserted **in the harness's own order**, which is the half a set could not carry:
    `sdk/_engine/preflight.py`'s `_unlisted` names the last of them as the ceiling, so a reading
    that sorted or de-ordered them would put a level the tool never topped out at into a sentence.
    They are asserted as the harness's own strings and never against `OpenAIEffort`, which is the
    point of reporting them at all - the enum is the source and a listing that has come apart from
    it is exactly what there would be something to say about.
    """
    stub = Stub(
        tmp_path,
        catalogue=json.dumps(
            {
                "models": [
                    _listed("gpt-5.6-luna", ("low", "medium", "high", "xhigh", "max"), "medium"),
                    _listed("gpt-5.6-sol", ("low", "medium"), "low"),
                ]
            }
        ),
    )

    reported = await OpenAiRunner(stub.path).installation(OpenAI.LUNA)

    assert stub.probed("version")["argv"] == ["--version"]
    assert stub.probed("catalogue")["argv"] == ["debug", "models"]
    assert reported.version == "0.155.1", (
        f"the version came back as {reported.version!r} from {_SPELLED_VERSION!r}. The harness "
        f"prints its own name in front of the number, so a reading that keeps the whole line puts "
        f"`codex-cli 0.155.1` where an ordering expects dotted digits and every run is then warned "
        f"about a version nothing could place"
    )
    assert reported.standing is Standing.WITHIN
    assert reported.where == str(stub.path)
    assert reported.efforts[OpenAI.LUNA] == ModelEfforts(
        levels=("low", "medium", "high", "xhigh", "max"), default="medium"
    ), (
        f"{str(OpenAI.LUNA)!r} reported {reported.efforts.get(OpenAI.LUNA)}. A level sits under "
        f"`effort` inside an object beside a description, so a reading that took the objects "
        f"themselves reports levels no sentence could name"
    )
    assert reported.efforts[OpenAI.SOL] == ModelEfforts(
        levels=("low", "medium"), default="low"
    )

@pytest.mark.asyncio
async def test_neither_question_is_put_against_the_credential_home_this_process_carries(
    tmp_path: Path,
) -> None:
    """The one thing this feature does outside AGL, and it is a write rather than a read.

    Every invocation of this harness creates `$CODEX_HOME/tmp/arg0/…` before it answers anything,
    pruning the one before it - so a probe on every run churns a directory the operator owns, in
    order to ask a question that reads nothing from it. It reads nothing from it: against a home
    holding no credential and no configuration the version and the listing come back identical,
    over no connection, which is what makes redirecting it free rather than a trade.

    Asserted against the home *this process* carries rather than against the operator's own,
    because `tests/conftest.py` has already redirected that one for every test in the repository -
    so the comparison here is "the probe chose its own" and not "the suite was lucky".
    """
    stub = Stub(tmp_path)
    ambient = os.environ.get("CODEX_HOME")

    await OpenAiRunner(stub.path).installation(OpenAI.TERRA)

    homes = [stub.probed(which)["home"] for which in ("version", "catalogue")]
    assert homes[0] and homes[0] == homes[1], (
        f"the two questions were put against {homes}. One probe is one directory: two would be two "
        f"sets of aliases written and neither pruned by the other"
    )
    assert homes[0] != ambient, (
        f"both questions were put against {homes[0]!r}, which is the home this process carries. "
        f"The probe hands the child one of its own, because a question that only reads has no "
        f"business writing into a directory somebody else owns"
    )
    assert not Path(homes[0]).exists(), (
        f"{homes[0]!r} is still there after the probe returned. It is a temporary directory and "
        f"the aliases the harness wrote into it go with it; one that outlives the probe is the "
        f"churn moved rather than stopped"
    )

@pytest.mark.asyncio
async def test_a_listing_naming_a_model_this_adapter_does_not_serve_leaves_it_out(
    tmp_path: Path,
) -> None:
    """The listing describes every model the account reaches, and AGL maps three of them.

    Keyed by `ModelId` and not by slug, so a slug with no member behind it has no key to go under -
    and inventing one would put a name in a warning that no `@role(model=…)` could ever name.
    """
    stub = Stub(
        tmp_path,
        catalogue=json.dumps(
            {
                "models": [
                    _listed("gpt-5.6-luna", ("low",), "low"),
                    _listed("some-other-model", ("low", "high"), "high"),
                ]
            }
        ),
    )

    reported = await OpenAiRunner(stub.path).installation(OpenAI.LUNA)

    assert reported.efforts == {OpenAI.LUNA: ModelEfforts(levels=("low",), default="low")}

@pytest.mark.asyncio
async def test_the_levels_come_back_in_the_order_the_catalogue_listed_them_and_never_sorted(
    tmp_path: Path,
) -> None:
    """The order is the harness's answer too, and the reading preserves it rather than deriving one.

    Measured over 0.155.1's whole catalogue, each of its nine models lists an ascending prefix of
    `low, medium, high, xhigh, max, ultra`, so the last level a model lists is the most it reasons
    at - which is what `sdk/_engine/preflight.py`'s `_unlisted` names when a role asks for a level
    the model has not got. Nothing here checks that the order *is* ascending, because that is the
    tool's claim and not AGL's; what is checked is that AGL passes it through.

    The listing below is deliberately not ascending and not alphabetical, so a reading that sorted
    either way is caught, and it repeats a level so that a tuple cannot report the same one twice
    where the set this used to be could not have.
    """
    stub = Stub(
        tmp_path,
        catalogue=json.dumps(
            {"models": [_listed("gpt-5.6-luna", ("max", "low", "high", "max"), "low")]}
        ),
    )

    reported = await OpenAiRunner(stub.path).installation(OpenAI.LUNA)

    assert reported.efforts[OpenAI.LUNA].levels == ("max", "low", "high"), (
        f"{str(OpenAI.LUNA)!r} reported {reported.efforts[OpenAI.LUNA].levels}. A sentence names "
        f"the last of these as the ceiling, so an order of AGL's own naming a level the tool never "
        f"topped out at is the failure, and a repeat is a level named twice in one list"
    )

@pytest.mark.parametrize(
    ("catalogue", "why"),
    [
        ("not json at all", "unparseable"),
        ('{"models": "a string"}', "not a list of models"),
        ('{"models": [{"slug": "gpt-5.6-luna"}]}', "carrying no levels"),
    ],
)
@pytest.mark.asyncio
async def test_a_listing_that_cannot_be_read_costs_the_efforts_and_never_the_version(
    catalogue: str, why: str, tmp_path: Path
) -> None:
    """Two answers, read separately, so a harness that changed one of them still reports the other.

    The version is what a warning most needs and the listing is what makes one specific, so a
    listing this reading was not written for leaves a general warning standing rather than taking
    the whole report down with it. Nothing is refused on either path.
    """
    stub = Stub(tmp_path, catalogue=catalogue)

    reported = await OpenAiRunner(stub.path).installation(OpenAI.LUNA)

    assert reported.version == "0.155.1", f"a listing {why} took the version with it"
    assert reported.efforts == {}

@pytest.mark.parametrize(
    ("plan", "why"),
    [
        ({"version": _SPELLED_VERSION, "version_exit": 1}, "the subcommand failed"),
        ({"version": "codex-cli"}, "it printed only its own name"),
        ({"version": "codex-cli 0.155.1 (build 7)"}, "it printed a third word"),
    ],
)
@pytest.mark.asyncio
async def test_a_version_line_this_reading_was_not_written_for_reports_nothing_at_all(
    plan: dict[str, Any], why: str, tmp_path: Path
) -> None:
    """A spelling nobody measured is reported as unread, and never as whichever word looked right.

    The measured line is two words, so picking one out of three would be guessing which - and a
    guess reaches `Standing` looking exactly like a version somebody read. The first row is a
    perfectly well-formed line printed by a subcommand that then failed, which is the row that says
    the exit status is read at all: text on stdout is not an answer if the process disowned it.
    """
    stub = Stub(tmp_path, **plan)

    reported = await OpenAiRunner(stub.path).installation(OpenAI.LUNA)

    assert reported.version is None, f"{why}, and something was still reported as a version"
    assert reported.standing is Standing.UNREPORTED

@pytest.mark.asyncio
async def test_a_harness_that_is_not_installed_reports_no_version_and_refuses_nothing(
    tmp_path: Path,
) -> None:
    """The member that never raises, on the path where every other one does.

    `check_ready` answers a missing binary with `UpstreamUnavailable` and stops the run at second
    zero. This one is a warning's material: a backend nobody could reach has no version, the name
    it was looked for under is still reported, and the run carries on to be refused by the member
    whose business that is.
    """
    missing = tmp_path / "no-such-binary"

    reported = await OpenAiRunner(missing).installation(OpenAI.TERRA)

    assert reported.version is None
    assert reported.where == str(missing)
    assert reported.tool
    assert reported.efforts == {}

def test_a_model_this_adapter_does_not_serve_is_refused_a_version_report_as_well() -> None:
    """The same refusal the other two query members make, and for the same reason.

    A runner that answered for a model it cannot run would put a version warning about this harness
    in front of an operator whose role names a model some other backend serves.
    """
    with pytest.raises(InputError):
        asyncio.run(OpenAiRunner().installation(Claude.OPUS))

# --- The probe that never answers ----------------------------------------------------------------

# The three numbers this test turns on, and the gaps between them are the assertions.
#
# `PROBE_DEADLINE` is what the adapter's own `_READY_SECONDS` is replaced with. Thirty seconds is
# the shipped number and no test can afford to wait it out, so it is monkeypatched on the module the
# way `model_slug` is above - which is also the honest consequence of that number not being a
# constructor parameter, and the reason it does not need to be: nothing but a test has any use for
# a different one. A second rather than a tenth because the stub has to start an interpreter, fork a
# grandchild and write a file before it hangs, and a deadline that expired during Python's own
# start-up would test the adapter against a probe that had not begun.
#
# `PROBE_BOUND` is the test's own bound and it is the whole reason this test can be run at all. A
# `check_ready` with no deadline does not fail here - it *hangs*, and a hang reaches pytest's 60s
# backstop as `Timeout (>60.0s)` with a traceback into the event loop's selector, which names the
# wrong thing and stalls the run for a minute doing it. Fifteen seconds is fifteen times the
# deadline, a quarter of the backstop, and far under the sleep below.
#
# `WEDGED_SLEEP` is what the stub and its grandchild sleep for. Two orders of magnitude past the
# deadline, so that nothing asserted below can be satisfied by the probe simply finishing, and
# short enough that a mutation run which leaves them behind does not leave them behind for an hour.
PROBE_DEADLINE: Final = 1.0
PROBE_BOUND: Final = 15.0
WEDGED_SLEEP: Final = 120.0

# How long a signalled process is given to be gone. The same five seconds
# `tests/adapters/test_shell_verifier.py` allows the build it stops, and for the same reason:
# delivery is prompt, reaping is when the system gets to it.
GONE_WITHIN: Final = 5.0

@pytest.mark.asyncio
async def test_a_probe_that_never_answers_is_refused_at_its_deadline_with_nothing_left_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preflight is on the path of every run, so a readiness probe with no deadline hangs every run.

    This is the one member here that a person cannot work around. `run` is behind a workflow and a
    step; `check_ready` is asked before anything at all, once per run, against a local credential
    store - and a credential store blocks. A keychain prompt raised on a machine nobody is sitting
    at, an authentication agent that stopped answering, a mount that went away underneath one: none
    of these ends, and `communicate()` on a child that never writes and never exits does not either.
    The symptom is not a slow run or a failed one. It is `agl run` printing nothing, forever, with
    no exception, no exit code and no timeout anywhere between here and the person waiting.

    **Three claims, and each needs the others to mean anything.**

      * **It comes back.** Bounded by `PROBE_BOUND` rather than by pytest's backstop, because the
        failure this test is written for is a hang, and a hang that reaches the backstop is
        reported as `Timeout (>60.0s)` against the event loop - a sentence that names neither this
        member nor this clause. The bound is what turns the defect into a failure that says what
        broke, and it is also the deadline assertion: the probe cannot come back inside fifteen
        seconds against a hundred-and-twenty-second sleep unless a deadline stopped it.
      * **It comes back as the one exception preflight catches.** `sdk/_engine/preflight.py` catches
        `UpstreamUnavailable` and nothing else, and `tests/contracts/_agent_preflight.py` fails any
        other exception by name - so `pytest.raises` here is not a formality. A probe that timed out
        is `Unavailable` and not `Unexpected` on the repo's own reading of the two: nothing was
        misunderstood, nothing was misparsed, the far side simply did not answer, and the same call
        succeeds the moment the prompt is dismissed. `UpstreamUnexpected` would be the claim that
        retrying is pointless, which is the opposite of true here, and it would also escape
        preflight's own wrapping and reach a person as a bug report request about their own
        keychain.
      * **Nothing is left running.** A deadline that returns while the probe keeps its cores is half
        a fix and it is the half that shows up on the machine: this runs once per run, so the
        orphans accumulate one per invocation. Both pids are checked - the probe itself, and a
        grandchild it started before it hung. The grandchild is the load-bearing one. It is what
        separates the shape this adapter uses (a session of its own, and `_session.py`'s `_signal`
        against the whole group) from the shape `git/_runner.py` uses (no session, and a signal to
        the process alone), which would leave it behind. It is also why the session is not
        optional: `_signal` spells the group as `os.getpgid(child.pid)`, and a probe started
        without `start_new_session=True` is in *AGL's own* group, so the same two lines would send
        SIGTERM and then SIGKILL to the process running this test.

    The pids are read out of a file the stub writes rather than off its output, for
    `test_shell_verifier.py`'s reason on the same question: nothing here should depend on when a
    buffer was flushed, and the child is killed before it flushes anything.
    """
    wedge = tmp_path / "wedged.json"
    stub = Stub(
        tmp_path,
        login={"wedge": str(wedge), "sleep": WEDGED_SLEEP, "say": "never printed", "exit": 0},
    )
    monkeypatch.setattr(runner_module, "_READY_SECONDS", PROBE_DEADLINE)

    try:
        async with asyncio.timeout(PROBE_BOUND):
            with pytest.raises(UpstreamUnavailable) as raised:
                await OpenAiRunner(stub.path).check_ready(OpenAI.TERRA)
    except TimeoutError:
        _put_down(_wedged(wedge))
        pytest.fail(
            f"`check_ready` was still waiting {PROBE_BOUND:g}s after it was called, against a "
            f"probe wedged for {WEDGED_SLEEP:g}s and a {PROBE_DEADLINE:g}s deadline. That is the "
            f"defect exactly: preflight runs before every run, so a readiness probe with no "
            f"deadline is not a slow run - it is a run that never starts and never says why"
        )

    assert f"{PROBE_DEADLINE:g}s" in str(raised.value), (
        f"the refusal does not say how long it waited: {raised.value}. The whole of what a person "
        f"can act on here is that the probe was given a deadline and did not meet it; a message "
        f"that omits the number reads as the CLI having refused, which is a different thing to do "
        f"about it"
    )

    probe, grandchild = _wedged(wedge)
    try:
        for pid, what in ((probe, "the probe"), (grandchild, "a process the probe started")):
            assert not await _still_there(pid, GONE_WITHIN), (
                f"the deadline expired and {what} (pid {pid}) was still running {GONE_WITHIN:g}s "
                f"later. Preflight asks this once per run, so an orphan here is one more wedged "
                f"process per `agl run` on a machine whose credential store is already wedged - "
                f"and the grandchild is the one that says whether the whole process group was "
                f"signalled or only the child AGL happens to hold a handle to"
            )
    finally:
        _put_down((probe, grandchild))

def _wedged(where: Path) -> tuple[int, int]:
    """The two pids the wedged stub wrote down, or a failed assertion saying it never hung."""
    assert where.is_file(), (
        f"the wedged stub left no record at {where}, so it was stopped before it reached the point "
        f"of hanging - or never started at all. Everything after this asserts about processes that "
        f"were running when the deadline expired, and there is no evidence any of them were"
    )
    written = json.loads(where.read_text(encoding="utf-8"))
    probe, grandchild = written
    return int(probe), int(grandchild)

async def _still_there(pid: int, seconds: float) -> bool:
    """Is `pid` still running after up to `seconds`? Polls, and answers as soon as it knows.

    A poll rather than a sleep: a signal is delivered promptly and reaped when the system gets to
    it, so asserting on the first microsecond would be asserting about a scheduler.
    """
    deadline = time.monotonic() + seconds
    while _there(pid) and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    return _there(pid)

def _there(pid: int) -> bool:
    """Signal 0: the ordinary way to ask whether a process exists without disturbing it."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

def _put_down(pids: Iterable[int]) -> None:
    """Kill whatever is left, so a red run cannot leave a two-minute sleep behind it.

    Every assertion above has already been made by the time this runs, and on the failing paths
    there is nothing to preserve: a process this could still reach is one the adapter was supposed
    to have stopped.
    """
    for pid in pids:
        with suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)

# --- The environment: what the allowlist lets past, and what a shell no longer decides -----------

# Names an operator's shell may carry that steer this harness, and what each one does. `_HOME` is
# the pair's counterexample: it is on the allowlist, and `tests/conftest.py` points it at a
# credential-free directory for every test in this repository precisely so that it travels.
SHELL_CARRIED: Final[tuple[tuple[str, str], ...]] = (
    # What the harness sets on its *own* children to tell them they are confined. Inherited from
    # outside, it tells this child something about its confinement that AGL did not arrange.
    ("CODEX_SANDBOX", "the child was told it was already sandboxed"),
    ("CODEX_SANDBOX_NETWORK_DISABLED", "the child was told its network was already off"),
    # The credential route that is not `auth.json`. Left through deliberately - the binary names it
    # in the same sentence as the two others when it says no credentials were found - and here to
    # prove the pair below is asserting something.
    ("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "the harness reported itself as something else"),
    ("CODEX_NON_INTERACTIVE", "the harness took a different view of its own terminal"),
)

@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "consequence"), SHELL_CARRIED)
async def test_no_vendor_name_the_allowlist_refuses_reaches_the_harness_that_actually_ran(
    name: str, consequence: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read off the child's own environment rather than off the mapping that composed it.

    This adapter hands `create_subprocess_exec` the whole environment, which is the one thing the
    Claude adapter cannot do - so what is claimed here is *absence* and absence is worth measuring
    on the far side. The stub records the names it was given and no value for any of them, so a real
    process, started by the real adapter through the real spawn, is what answers.
    """
    monkeypatch.setenv(name, "whatever the operator exported")
    stub = Stub(tmp_path / "stub", steps=[{"say": started()}])

    await drive(stub, task_in(workspace(tmp_path)))

    assert name not in stub.seen()["vendor"], (
        f"{name} reached the harness: it was handed {stub.seen()['vendor']}. Measured consequence "
        f"when it did: {consequence}"
    )

@pytest.mark.asyncio
async def test_the_home_the_paid_endpoint_guard_exports_reaches_the_harness_a_test_starts(
    tmp_path: Path,
) -> None:
    """The one that would fail silently and cost money, so it is asserted against a real child.

    `tests/conftest.py` points this harness's home at a directory holding no `auth.json`, and its
    whole mechanism is that a `codex` a test spawns *inherits* it - `--ignore-user-config` says of
    itself that authentication still reads that directory. An allowlist that dropped the name would
    hand every test the operator's own ChatGPT tokens while the suite stayed green: the existing
    redirect tests read this process's environment, not the child's.

    The name is spelled as `_version._HOME` rather than written out, because `scripts/check`'s
    paid-endpoint gate scans this tree for a literal of it - correctly, since no scan keyed on a
    name can tell a scratch directory from the operator's own.
    """
    stub = Stub(tmp_path / "stub", steps=[{"say": started()}])

    await drive(stub, task_in(workspace(tmp_path)))

    assert _version._HOME in stub.seen()["vendor"], (
        f"{_version._HOME} did not reach the harness: it was handed {stub.seen()['vendor']}. That "
        f"name is the only thing between a test and this machine's real ChatGPT credentials, and "
        f"the guard cannot place it anywhere but the environment"
    )

@pytest.mark.asyncio
async def test_the_machine_outside_this_vendors_namespace_reaches_the_harness_untouched(
    tmp_path: Path,
) -> None:
    """The scope, measured on the far side: an agent runs the repository's own build.

    This adapter replaces the child's environment outright, so everything the child has is something
    the allowlist put there - which makes a missing `PATH` a real possibility here in a way it never
    is for the Claude adapter. What keeps it from happening is that nothing outside the two vendor
    prefixes is considered at all, and the child is the only witness to that.
    """
    stub = Stub(tmp_path / "stub", steps=[{"say": started()}])

    await drive(stub, task_in(workspace(tmp_path)))

    assert stub.seen()["machine"] == ["HOME", "PATH", "SHELL", "TMPDIR"], (
        f"the harness was handed {stub.seen()['machine']} of the four this test looks for. An "
        f"agent with no PATH runs no build, and one with no HOME or TMPDIR fails somewhere else "
        f"entirely - which is the failure that only shows up under load"
    )

@pytest.mark.asyncio
async def test_the_readiness_probe_asks_its_question_through_the_same_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third spawn in this package, which is the one a scan of the run path would miss.

    `check_ready` reads the credential store, so the home has to travel and the rest has to not -
    and it is a separate `create_subprocess_exec` from the run's, in a separate module, so nothing
    about the run's composition says anything about it. Asserted on the child rather than on the
    call, for the reason the run's own version gives: absence is worth measuring on the far side.
    """
    monkeypatch.setenv("CODEX_SANDBOX", "the operator's own")
    stub = Stub(tmp_path, login={"say": "Logged in using ChatGPT", "exit": 0})

    await OpenAiRunner(stub.path).check_ready(OpenAI.TERRA)

    assert stub.seen()["vendor"] == [_version._HOME], (
        f"the readiness probe was handed {stub.seen()['vendor']}. The home is what it reads the "
        f"credential store out of and the only vendor name it has any use for"
    )

@pytest.mark.asyncio
async def test_the_version_probe_is_asked_through_the_same_allowlist_with_its_own_home_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seam a later deliverable sets this harness's home through, asserted where it already is.

    `probed` is the one place in this adapter that sets a vendor name of its own - the home, to a
    fresh directory, for the reason `_version.py`'s `_HOME` comment gives, and
    `test_neither_question_is_put_against_the_credential_home_this_process_carries` is what holds
    *that*. What is new here is that it sets it by handing `composed` what it chose, so the choice
    wins over the shell while everything else still goes through the allowlist. A second name to
    set goes in beside it and needs no second mechanism.
    """
    monkeypatch.setenv("CODEX_SQLITE_HOME", "the operator's own")
    stub = Stub(tmp_path / "stub")

    await OpenAiRunner(stub.path).installation(OpenAI.LUNA)

    for which in ("version", "catalogue"):
        seen = stub.probed(which)
        assert "CODEX_SQLITE_HOME" not in seen["vendor"], (
            f"the {which} probe was handed {seen['vendor']}, so it is asked against whatever the "
            f"shell carried rather than through the allowlist the run itself goes through"
        )
        chosen = seen["home"] != os.environ.get(_version._HOME)
        assert _version._HOME in seen["vendor"] and chosen, (
            f"the {which} probe was asked with the home at {seen['home']!r}, which is the one this "
            f"process carries. What `probed` chose was dropped, so the seam a later deliverable "
            f"sets this harness's home through is not there"
        )

# --- Where the harness keeps its own state, which is the half the home cannot be moved for -------

@pytest.mark.asyncio
async def test_a_run_points_the_harness_state_at_a_directory_it_made_and_then_removed(
    tmp_path: Path,
) -> None:
    """The one write this adapter redirects rather than suppresses, and why it redirects it.

    The credential lives under the home, so the home stays the operator's and everything defaulted
    into it lands there. Six SQLite databases are defaulted into it - thread history, memories,
    goals, queue, logs and state - and the name below is the only lever that moves them. Volume is
    the smaller half: 2.4 MB of write-ahead log a run, measured against 0.155.1. The larger half is
    that AGL's turns would otherwise be rows in the history and the memories the operator's own
    interactive sessions read back.

    Both halves of the claim are asserted on the child, because either alone passes for an adapter
    that got it wrong: a name pointing at a directory that was not there is a redirect the harness
    falls back out of, and one pointing at a directory still standing afterwards is an adapter
    accumulating somewhere else instead of somewhere else per run.
    """
    stub = Stub(tmp_path, steps=[{"say": started()}])

    await drive(stub, task_in(workspace(tmp_path)))
    seen = stub.seen()

    assert seen["state_home_exists"], (
        f"the harness was started with its state home at {seen['state_home']!r}, which was not a "
        f"directory while it ran. A redirect at a path that is not there is one the harness falls "
        f"back out of, and it falls back to the home the credential is in"
    )
    assert not Path(str(seen["state_home"])).exists(), (
        f"{seen['state_home']!r} outlived the run. A directory per run is what keeps AGL's turns "
        f"out of the operator's own thread history; one that stays is the same accumulation under "
        f"a different name"
    )

@pytest.mark.asyncio
async def test_the_shells_own_state_redirect_loses_to_the_one_this_adapter_chose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The name is off the allowlist *and* set, which are two different guarantees.

    Off the allowlist alone would mean the operator's value is dropped and the harness falls back
    to the home. Set alone would mean AGL names a directory that whatever the shell carried could
    still be read instead of. `composed` resolves it in AGL's favour by construction, and this is
    the test that says so from the far side of a real spawn: the shell exports a path that is not
    even a directory, and what the child got is the one the run made.
    """
    monkeypatch.setenv("CODEX_SQLITE_HOME", str(tmp_path / "the-operators-own"))
    stub = Stub(tmp_path / "stub", steps=[{"say": started()}])

    await drive(stub, task_in(workspace(tmp_path)))
    seen = stub.seen()

    assert seen["state_home"] != str(tmp_path / "the-operators-own"), (
        f"the harness kept its state at {seen['state_home']!r}, which is what the shell said. An "
        f"operator's redirect deciding where a run of AGL's writes is the defect this name being "
        f"off the allowlist exists to stop"
    )
    assert seen["state_home_exists"], (
        f"the harness was started with its state home at {seen['state_home']!r}, so the shell's "
        f"value was dropped without one of AGL's own put there - which leaves the databases back "
        f"in the home the credential is in"
    )
