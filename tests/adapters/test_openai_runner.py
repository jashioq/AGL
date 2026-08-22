"""`OpenAiRunner` against the `AgentRunner` contract, plus the clauses that suite cannot see.

The first class is the port in full: `AgentContract` with its two fixtures overridden and nothing
else touched. That suite was written at stage 3, against the port's docstrings and before any
adapter existed (§1.9), which is why nothing below re-asserts any of it.

**Six of its eight tests start a real agent, and none of them runs - anywhere, on any machine.**
Every one of the six reads a *model's* conduct as its evidence: that it called a tool, that it
answered a question, that it ignored a repository's instructions. No free instrument can supply
that, and on this backend the only instrument that could is a paid turn, so they are deferred to
the manual QA pass. The gate is delivered by the `runner` fixture handing back a runner whose `run`
skips: the criterion is "does this test start an agent", which is a fact about the *port member*
rather than about a test's name, so no list here goes stale when a test in that suite is renamed.
`capabilities` and `check_ready` are the real thing in both cases and run unconditionally.

**No test in this file runs the harness's agent command.** That is the stage's rule and it is
structural here rather than promised: the two things this module starts are a *stub* CLI it writes
itself, and the real binary's model-free subcommands. `tests/conftest.py` additionally points
`CODEX_HOME` at an empty directory for every test in the repository, so a real binary any test
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
model-visible prompt as JSON and contacts nothing, which makes §3.5 assertable without a model:
the adapter's own configuration overrides are lifted off the command line it composed and handed to
it in a poisoned repository, with a control run proving the poison was there to find.

Both are gated on the binary being installed and on nothing else. There is deliberately no opt-in
switch: neither subcommand reaches a model, both are named in the stage's own list of free
instruments, and gating a free measurement behind a variable is how a measurement stops being made.

## What follows the contract subclass, in rough order

  * **The command line it composes** - the hermeticity overrides, the sandbox mode, the model, the
    servers, the prompt's absence from it, and the workspace's absence from it.
  * **§3.5, three ways**: the composed prompt carries nothing the repository wrote; every override
    the adapter emits loads; and a poisoned repository reaches the model with none of its markers,
    including a `.codex/skills` row the contract suite's own table does not carry.
  * **The argv guards**, which the suite cannot provoke because it supplies neither value.
  * **The stream**, frame by frame, including the outcomes the suite lists as beyond it (gap 10:
    it cannot make a run reach a limit and has no second source for the fact).
  * **The tools and the questions**, driven against the adapter's own MCP server with no CLI - the
    round trip, the refusal, both question edge cases, and a handler that raises.

Named `test_openai_runner.py`, for the module it covers: `tests/` carries no `__init__.py` (see
`tests/conftest.py` for why it must not), so pytest's module names are the bare filenames and two
files of one name under different directories would collide at import.
"""

import ast
import asyncio
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, NoReturn

import pytest

from agl.adapters.openai import runner as runner_module
from agl.adapters.openai.runner import OpenAiRunner
from agl.ports.agent import (
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
from agl.ports.errors import InputError, UpstreamUnavailable, UpstreamUnexpected
from agl.ports.questions import Answer, Question
from agl.ports.run import JsonValue
from contracts._agent_hermeticity import CONFIGURATIONS, markers_in, plant
from contracts._agent_tasks import Notes, workspace
from contracts.agent import AgentContract

# What a person is told when the six live tests do not run, which is always. Long on purpose: the
# whole point of this suite is that a green run means something, and a skip that reads like a pass
# is the failure `tests/contracts/agent.py` is written against.
_SKIPPED: Final = (
    "UNVERIFIED: this run did not start a real agent, so the OpenAiRunner's entire run-path - the "
    "outcome, the refused tool call, the activity, both question clauses and the poisoned "
    "repository - is unverified by this run, and by every run. DEFERRED TO THE MANUAL QA PASS, "
    "with no switch here that changes it: each of these six reads a model's conduct as its "
    "evidence - that it called a tool, that it answered a question, that it ignored a poisoned "
    "repository - and on this backend the only instrument that produces conduct is a paid turn. "
    "No test in this build spends tokens. Run them by hand against an authenticated CLI (see "
    "docs/manual-qa.md entries 8 and 9), or do not believe them. What did run is everything below "
    "the contract subclass: the composed command line, the composed prompt, the whole stream "
    "reading, and every tool and question round trip driven against this adapter's own MCP server "
    "over real HTTP - plus, where the binary is installed, the hermeticity overrides checked "
    "against a poisoned repository with the harness's own free prompt renderer. None of that "
    "covers a model deciding anything, and this skip is not a pass."
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

# The stub, written to disk and handed to the adapter as its CLI. It is deliberately small and
# deliberately *not* a harness: it records, it plays back, and it can call an MCP tool.
_STUB: Final = '''#!{python}
"""A stand-in for the harness, written by tests/adapters/test_openai_runner.py."""

import json
import os
import pathlib
import sys
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


def main():
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    record = {{"argv": sys.argv[1:], "cwd": os.getcwd(), "stdin": None, "answers": []}}
    written = pathlib.Path(plan["record"])
    try:
        if sys.argv[1:2] == ["login"]:
            login = plan["login"]
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


def task_in(repo: Path, *, tools: tuple[Tool, ...] = (), **fields: Any) -> AgentTask:
    """One ordinary task in `repo`, with restrictions so the sandbox overrides are on the wire."""
    return AgentTask(
        instructions="Read README.md and say in one sentence what this project does.",
        workspace=repo,
        model=OpenAI.LUNA,
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

    Unconditionally, because there is no condition worth writing: what the six tests behind it
    assert is a model's conduct, the only instrument that can answer is a paid one, and a test that
    spends money on a flag is still a test that spends money.
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
    four §3.5 overrides are asserted by value because each of them has a default that reads the
    target repository.
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
async def test_the_workspace_is_the_working_directory_and_is_not_on_the_command_line(
    tmp_path: Path,
) -> None:
    """§3.5: the one caller-supplied path this adapter handles never reaches an argument list.

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
async def test_both_mcp_servers_are_injected_with_a_timeout_a_person_can_answer_inside(
    tmp_path: Path,
) -> None:
    """The tool channel, as it reaches the harness: two servers, and the number that matters.

    `tool_timeout_sec` defaults to sixty seconds and AGL's asking tool waits on a person. That
    default is the specific way `MID_RUN_QUESTIONS` dies quietly - the call fails, the agent is
    told the tool errored, and it carries on guessing - so the override is asserted by value rather
    than by presence, and asserted to be longer than any person's thinking time rather than merely
    different from sixty.
    """
    stub = Stub(tmp_path, steps=[{"say": started()}])

    await drive(stub, task_in(workspace(tmp_path)))
    supplied = [token for token in stub.argv() if token.startswith("mcp_servers.")]

    assert len(supplied) == 2, (
        f"the command line declares {len(supplied)} MCP server(s): {supplied}. Two are supplied - "
        f"the workflow's own tools and the one that asks a person - on separate servers so that a "
        f"workflow calling a tool `ask` cannot collide with AGL's asker"
    )
    names = sorted(token.split("=", 1)[0].removeprefix("mcp_servers.") for token in supplied)
    assert names == ["agl", "agl_ask"], f"the servers are named {names}"
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
            f"a tool call may take {seconds}s. The harness's own default is 60, an asking tool "
            f"waits on a person, and a capability that survives only while nobody thinks for a "
            f"minute is not a capability preflight can admit a role on"
        )


@pytest.mark.asyncio
async def test_a_prompt_with_nothing_standing_around_it_is_the_instructions_verbatim(
    tmp_path: Path,
) -> None:
    """A workflow author's prompt is the whole of what they wrote, and reaches the agent unedited.

    The other half is asserted with it: standing context, the restrictions in words and `plan_only`
    all reach the agent, above the instructions, with the instructions still last. Read off the
    stub's standard input, which is also where §3.5's argument lands - none of this text is on a
    command line, because the prompt travels on the child's standard input.
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


@pytest.mark.asyncio
async def test_the_prompt_names_the_asking_tool_exactly_when_somebody_can_answer(
    tmp_path: Path,
) -> None:
    """§3.7: "The framework supplies the asking tool (agents are instructed to use it)".

    Both halves, on one task run twice, because each is the other's control. A run with a handler
    is told what to call; a run without one is told nothing, since the tool is registered either
    way and an agent that asks with nobody listening spends a turn to be told no answer is
    available. That second half is also what keeps a bare task's prompt the instructions byte for
    byte.

    The name is checked against the one the server actually advertises rather than only against a
    string in this file: `mcp__<server>__<tool>` is composed from two names `_tools.py` owns, and a
    prompt naming a tool no session registers is worse than a prompt naming none.
    """
    repo = workspace(tmp_path)
    listing = {"server": "agl_ask", "list": True}
    told = Stub(tmp_path / "told", steps=[{"call": listing}, {"say": started()}])
    untold = Stub(tmp_path / "untold", steps=[{"say": started()}])

    async def answer(question: Question) -> Answer:
        raise AssertionError("this run never asks; the handler is here to be counted, not called")

    await drive(told, task_in(repo), on_question=answer)
    await drive(untold, task_in(repo))

    advertised = told.seen()["answers"][0]["result"]["tools"]
    assert [tool["name"] for tool in advertised] == ["ask"], (
        f"the asking server advertises {[tool['name'] for tool in advertised]}. It holds exactly "
        f"one tool: a second one there is a second way to ask"
    )
    assert f"`mcp__agl_ask__{advertised[0]['name']}`" in told.seen()["stdin"], (
        f"a run carrying a question handler was told nothing about how to ask: "
        f"{told.seen()['stdin']!r}. §3.7 has the framework supplying the asking tool *and* the "
        f"agent instructed to use it, and an agent that never learns the tool is there is a "
        f"workflow whose on_question is never called"
    )
    assert "agl_ask" not in untold.seen()["stdin"], (
        f"a run with no question handler was told to ask anyway: {untold.seen()['stdin']!r}. "
        f"Nobody is listening, so the whole of what that turn buys is being told so"
    )


# --- §3.5: what the repository contributes, which is source code and nothing else ----------------


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
    """§3.5 through the one window this harness opens for free: what it would put in front of a
    model, rendered without a model.

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
    `$CODEX_HOME/AGENTS.md`. That is the second channel §3.5 names and §3.11 defers, and it is
    absent here only because `tests/conftest.py` empties that directory for a different reason.
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
        f"workspace. §3.5: the target repo contributes source code and nothing else, and these "
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


def test_every_child_this_package_starts_is_started_somewhere_this_adapter_chose() -> None:
    """A structural assertion, so that a process added later cannot inherit AGL's own directory.

    Both of this package's children are started with an explicit working directory and neither is
    an accident: a run's is the workspace, and the readiness probe's is a temporary directory of
    its own. The failure this catches is silent - a child with no `cwd=` runs wherever the operator
    started `agl`, which for this harness means resolving a project root, and every `AGENTS.md`
    above it, out of somebody else's repository.

    Asserted by parsing the package rather than by running it, so that a third child added at a
    later stage is covered the moment it exists. `tests/adapters/test_shell_verifier.py`
    established the shape at stage 6, for the same kind of clause.
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
            given = {keyword.arg for keyword in node.keywords}
            assert "cwd" in given, (
                f"{source.name}:{node.lineno} starts a child without saying where: it passes "
                f"{sorted(name for name in given if name)}. A child with no working directory of "
                f"its own inherits AGL's, and this harness reads instructions out of the directory "
                f"it is standing in"
            )
    assert spawns >= 2, (
        f"only {spawns} child process start(s) were found in {package}, and there are at least "
        f"two - the run and the readiness probe. This test found nothing to check, which means it "
        f"is no longer checking anything"
    )


# --- §3.5: a value that would parse as a flag -----------------------------------------------------

MARKER: Final = "AGL-A-SHELL-EVALUATED-THE-PATH"

# One path component that is a whole command line: a substitution that leaves a file behind, a
# semicolon, a pipeline, quotes, spaces - and `--output=x`, which is the shape stage 5 found making
# a read-only git port write a file. `/` and NUL are the only bytes a filename cannot hold.
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
    """§3.5's argv rule on the one value the composition root supplies.

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
    """§3.1: the adapter translates at its own boundary, and the CLI's words survive into it.

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
    """An error the stream announced is a failure whatever the status says.

    Nothing establishes that this harness exits non-zero for every error it reports, and the
    consequence of guessing wrong is the damaging direction: an error message returned in the one
    field a workflow reads as the agent's answer.
    """
    stub = Stub(tmp_path, steps=[{"say": {"type": "error", "message": "the sky fell in"}}], exit=0)

    with pytest.raises(UpstreamUnavailable) as raised:
        await drive(stub, task_in(workspace(tmp_path)))
    assert "the sky fell in" in str(raised.value)


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
    §3.6 then records it under a fingerprint saying nothing was amiss.
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
    """§3.7's line, formed by `translate.activity` and passed through untouched.

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


# --- Tools and questions, against the adapter's own server, with no harness anywhere -------------


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
    """Three malformed calls, and none of them ends the run or reaches a handler.

    §3.3 decides the shape: by the time a call is wrong there is a session in flight holding all
    the reasoning that produced it, and a protocol error is the one answer that gives the model
    nothing to correct. So each of these comes back as a *refused result*, in words, and the run
    carries on to its ordinary ending.

    The third is the one check this server owes. Nothing here validates a payload against its
    schema - the port says the schema is data and the handler decides what is acceptable, and AGL
    has no validator - but the port also declares a handler's parameter to be a mapping, so a
    client that sent an array must not be the thing that discovers otherwise.
    """
    notes = Notes()
    stub = Stub(
        tmp_path,
        steps=[
            {"call": {"server": "agl", "tool": "no_such_tool", "arguments": {}}},
            {"call": {"server": "agl_ask", "tool": "ask", "arguments": {"question": "  "}}},
            {"call": {"server": "agl", "tool": "record_note", "arguments": ["not", "object"]}},
            {"say": started()},
        ],
    )

    outcome = await drive(stub, task_in(workspace(tmp_path), tools=(notes.tool,)))
    unknown, empty, wrong = (answer["result"] for answer in stub.seen()["answers"])

    assert unknown["isError"] is True and "no tool called" in unknown["content"][0]["text"]
    assert empty["isError"] is True and "asked nothing" in empty["content"][0]["text"]
    assert wrong["isError"] is True and "JSON object" in wrong["content"][0]["text"]
    assert notes.received == [], f"a malformed call reached a handler: {notes.received}"
    assert outcome.stop_reason is StopReason.COMPLETED, "and the run itself ended normally"


@pytest.mark.asyncio
async def test_two_questions_and_two_answers_inside_one_run(tmp_path: Path) -> None:
    """§3.7: the answer is serialised back into the same session, so a negotiation is rounds.

    One `run`, one child, two tool round trips - which is the clause in the smallest form that can
    hold it. The `Question` handed to the handler is checked field by field, which the contract
    suite cannot do because it does not know what payload a backend produced.
    """
    asked: list[Question] = []

    async def answer(question: Question) -> Answer:
        asked.append(question)
        return Answer(text=f"answer-{len(asked)}")

    ask = {"server": "agl_ask", "tool": "ask"}
    stub = Stub(
        tmp_path,
        steps=[
            {
                "call": {
                    **ask,
                    "arguments": {
                        "question": "Which path?",
                        "options": ["left", "right"],
                        "allow_free_text": False,
                    },
                }
            },
            {"call": {**ask, "arguments": {"question": "And after that?"}}},
            {"say": said("answer-1 answer-2")},
            {"say": started()},
        ],
    )

    outcome = await drive(stub, task_in(workspace(tmp_path)), on_question=answer)
    first, second = (answer_["result"] for answer_ in stub.seen()["answers"])

    assert [question.prompt for question in asked] == ["Which path?", "And after that?"]
    assert asked[0].options == ("left", "right") and asked[0].allow_free_text is False
    assert asked[1].options == () and asked[1].allow_free_text is True, (
        "a question with no choices in it leaves free text allowed, which is the port's own "
        "instruction and the difference between an open question and one nobody could answer"
    )
    assert first["content"][0]["text"] == "answer-1"
    assert second["content"][0]["text"] == "answer-2"
    assert outcome.text == "answer-1 answer-2"


@pytest.mark.asyncio
async def test_a_question_with_no_handler_is_answered_at_once_and_never_waits(
    tmp_path: Path,
) -> None:
    """The port's second edge case, seen from inside: the tool answers rather than blocking.

    The contract suite asserts this from outside, through a deadline, and a deadline cannot tell a
    run that answered quickly from one that answered at all. Here the tool result itself is read:
    it says no answer is available, in words, and it is not an error - nothing went wrong.
    """
    stub = Stub(
        tmp_path,
        steps=[
            {"call": {"server": "agl_ask", "tool": "ask", "arguments": {"question": "Which?"}}},
            {"say": said("done")},
            {"say": started()},
        ],
    )

    outcome = await drive(stub, task_in(workspace(tmp_path)))
    told = stub.seen()["answers"][0]["result"]

    assert told["isError"] is False, "nobody listening is not a failure"
    assert "No answer is available" in told["content"][0]["text"]
    assert outcome.text == "done"


@pytest.mark.asyncio
async def test_a_question_handler_that_raises_ends_the_run_with_its_own_exception(
    tmp_path: Path,
) -> None:
    """A headless terminal raising on a view that needs an answer is a real path, not a hypothesis.

    §3.7: a terminal that cannot take input raises `UpstreamUnavailable` on any screen, and a
    workflow's handler may raise `Stop`. The model is told an answer is not available so that it
    does not block either, and the run then ends on the handler's own exception as soon as the next
    frame arrives - rather than spending an hour of agent time on a run whose asker has failed.
    """
    refused = UpstreamUnavailable("this terminal cannot take input")

    async def answer(question: Question) -> Answer:
        raise refused

    stub = Stub(
        tmp_path,
        steps=[
            {"call": {"server": "agl_ask", "tool": "ask", "arguments": {"question": "Which?"}}},
            {"say": item("item.started", "reasoning", text="carrying on")},
            {"say": said("done")},
            {"say": started()},
        ],
    )

    with pytest.raises(UpstreamUnavailable) as raised:
        await drive(stub, task_in(workspace(tmp_path)), on_question=answer)

    assert raised.value is refused, (
        f"the run ended with {raised.value!r} rather than with the handler's own exception, so a "
        f"workflow's Stop or a headless terminal's refusal would be reported as something else"
    )


@pytest.mark.asyncio
async def test_a_tool_handler_that_raises_is_told_to_the_model_and_does_not_end_the_run(
    tmp_path: Path,
) -> None:
    """A workflow tool that throws behaves the same way on both backends, which is the point.

    The other adapter gets this from its vendor's SDK, which turns an exception out of a tool
    handler into an error result and carries on. AGL owns the server here, so the behaviour has to
    be written - and writing it differently would mean one workflow tool behaving two ways
    depending on which adapter happened to serve the step.
    """

    async def explode(payload: Mapping[str, JsonValue]) -> ToolResult:
        raise RuntimeError("the note store is on fire")

    tool = Tool(
        name="record_note",
        description="Write down one note.",
        payload_schema={"type": "object", "properties": {"note": {"type": "string"}}},
        handler=explode,
    )
    stub = Stub(
        tmp_path,
        steps=[
            {"call": {"server": "agl", "tool": "record_note", "arguments": {"note": "x"}}},
            {"say": started()},
        ],
    )

    outcome = await drive(stub, task_in(workspace(tmp_path), tools=(tool,)))
    told = stub.seen()["answers"][0]["result"]

    assert told["isError"] is True and "on fire" in told["content"][0]["text"]
    assert outcome.stop_reason is StopReason.COMPLETED


@pytest.mark.asyncio
async def test_a_tools_schema_reaches_the_model_as_the_workflow_declared_it(
    tmp_path: Path,
) -> None:
    """What a client reads off the server, which is what decides whether a model can call anything.

    Two claims. A workflow's own schema is advertised whole, so a model producing an argument
    against it produces one the handler will accept. And the asking tool's three properties are
    `Question`'s three fields - the prompt, the options offered, whether free text is allowed -
    since a property missing here is a field `Asking` can never be handed, however well the mapping
    below it is written.
    """
    notes = Notes()
    stub = Stub(
        tmp_path,
        steps=[
            {"call": {"server": "agl", "list": True}},
            {"call": {"server": "agl_ask", "list": True}},
            {"say": started()},
        ],
    )

    await drive(stub, task_in(workspace(tmp_path), tools=(notes.tool,)))
    supplied, asking = (answer["result"]["tools"] for answer in stub.seen()["answers"])

    declared = next(entry for entry in supplied if entry["name"] == "record_note")
    assert declared["inputSchema"] == dict(notes.tool.payload_schema), (
        f"the workflow's tool reached the model as {declared['inputSchema']!r}, and it declared "
        f"{dict(notes.tool.payload_schema)!r}. Nothing here is entitled to rewrite it"
    )
    assert declared["description"] == notes.tool.description

    schema = next(entry for entry in asking if entry["name"] == "ask")["inputSchema"]
    assert schema["type"] == "object" and "question" in schema["required"], (
        f"the asking tool's advertised schema is {schema!r}. `question` has to be required: it is "
        f"the whole of what a person is shown"
    )
    properties = schema["properties"]
    assert properties["question"]["type"] == "string"
    assert properties["options"]["items"]["type"] == "string", (
        f"`options` is advertised as {properties['options']!r}. An option is the exact text that "
        f"comes back as the answer, and anything that is not a non-empty string is dropped"
    )
    assert properties["allow_free_text"]["type"] == "boolean"


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


# --- The two members preflight asks --------------------------------------------------------------


def test_capabilities_are_the_ports_own_members_and_not_equivalent_strings() -> None:
    """The suite asserts this too; what it cannot assert is *which* four, and why they are static.

    `Capability` is a `StrEnum`, so this is a statement about the members and not about a set that
    compares equal to them today. The four are all of them: this harness edits files, runs
    commands, calls tools over MCP, and - because this adapter runs an asking tool of its own
    rather than depending on the harness's, which this mode refuses by name - asks mid-run on every
    build, which is why `MID_RUN_QUESTIONS` is not conditional on a flag that varies by machine.
    """
    assert asyncio.run(OpenAiRunner().capabilities(OpenAI.SOL)) == frozenset(Capability), (
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

    `tests/contracts/_agent_preflight.py` fails any other exception by name, because §3.2's first
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
    ready, which is the one distinction §3.2's preflight is built on.
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
