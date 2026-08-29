
import asyncio
import signal
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from agl.adapters.openai._session import _halted, _signal, outcome_of
from agl.adapters.openai._tools import ASKING_TOOL, Asking, Supply
from agl.adapters.openai.translate import (
    APPROVAL,
    Sandbox,
    launch_failure,
    model_slug,
    sandbox,
    unanswered,
    unready,
)
from agl.ports.agent import (
    ActivityReporter,
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Capability,
    ModelId,
    QuestionHandler,
)
from agl.ports.errors import InputError

__all__ = ["OpenAiRunner"]

_CLI: Final = "codex"

_CAPABILITIES: Final = frozenset(
    {
        Capability.FILE_EDIT,
        Capability.SHELL,
        Capability.MID_RUN_QUESTIONS,
        Capability.TOOL_CALLING,
    }
)

_READY: Final = ("login", "status")
_READY_SECONDS: Final = 30.0

_EXEC: Final = "exec"
_FROM_STDIN: Final = "-"

_ALWAYS: Final[tuple[str, ...]] = (
    "--json",
    "--color",
    "never",
    "--skip-git-repo-check",
    "--ignore-rules",
    "--ignore-user-config",
    "-c",
    "project_doc_max_bytes=0",
    "-c",
    "skills.include_instructions=false",
    *APPROVAL,
)

_TOOL_SECONDS: Final = 86_400
_STARTUP_SECONDS: Final = 30

_PLAN_ONLY: Final = (
    "AGL is asking you to examine and propose, and to change nothing: work out what should be "
    "done and report it, rather than doing it. This is what is being asked of you, not a "
    "restriction placed on you - anything you are actually forbidden to do is listed separately."
)

_MAY_ASK: Final = (
    "There is a person running this task and you can put a question to them and wait for their "
    f"answer: call the tool `{ASKING_TOOL}`. It will wait as long as they take. Use it when a "
    "decision is genuinely theirs to make rather than guessing at what they would want."
)

_CONTEXT_HEADING: Final = "AGL is running this task with the following standing context:"


class OpenAiRunner(AgentRunner):

    def __init__(self, cli_path: Path | None = None) -> None:
        self._cli = _CLI if cli_path is None else _not_a_flag(str(cli_path), "cli_path")

    async def capabilities(self, model: ModelId) -> frozenset[Capability]:
        model_slug(model)
        return _CAPABILITIES

    async def check_ready(self, model: ModelId) -> None:
        model_slug(model)
        with tempfile.TemporaryDirectory(prefix="agl-ready-") as elsewhere:
            try:
                child = await asyncio.create_subprocess_exec(
                    self._cli,
                    *_READY,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=elsewhere,
                    start_new_session=True,
                )
            except OSError as error:
                raise launch_failure(error) from error
            try:
                async with asyncio.timeout(_READY_SECONDS):
                    said, _ = await child.communicate()
            except TimeoutError:
                await _halted(child)
                await child.wait()
                raise unanswered(_READY_SECONDS) from None
            except BaseException:
                _signal(child, signal.SIGTERM)
                raise
            status = await child.wait()
        if status != 0:
            raise unready(status, said.decode("utf-8", errors="replace").strip())

    async def run(
        self,
        task: AgentTask,
        *,
        on_question: QuestionHandler | None = None,
        on_activity: ActivityReporter | None = None,
    ) -> AgentOutcome:
        slug = _not_a_flag(model_slug(task.model), "model")
        limits = sandbox(task.restrictions)
        asking = Asking(on_question)
        async with Supply(task.tools, asking) as supply:
            return await outcome_of(
                _argv(self._cli, slug, limits, supply.urls),
                prompt=_prompt(task, limits, may_ask=on_question is not None),
                workspace=task.workspace,
                asking=asking,
                on_activity=on_activity,
            )


def _argv(cli: str, slug: str, limits: Sandbox, urls: Mapping[str, str]) -> list[str]:
    return [
        cli,
        _EXEC,
        *_ALWAYS,
        "-s",
        limits.mode,
        *limits.options,
        "-m",
        slug,
        *_supplied(urls),
        _FROM_STDIN,
    ]


def _supplied(urls: Mapping[str, str]) -> list[str]:
    return [
        token
        for name in sorted(urls)
        for token in (
            "-c",
            f"mcp_servers.{name}={{"
            f'url="{urls[name]}",'
            f"tool_timeout_sec={_TOOL_SECONDS},"
            f"startup_timeout_sec={_STARTUP_SECONDS},"
            f'default_tools_approval_mode="auto"'
            f"}}",
        )
    ]


def _prompt(task: AgentTask, limits: Sandbox, *, may_ask: bool) -> str:
    standing = [
        f"{_CONTEXT_HEADING}\n\n{task.context}" if task.context else "",
        limits.in_words,
        _MAY_ASK if may_ask else "",
        _PLAN_ONLY if task.plan_only else "",
    ]
    return "\n\n".join([*(part for part in standing if part), task.instructions])


def _not_a_flag(value: str, what: str) -> str:
    if value.startswith("-"):
        raise InputError(
            f"the OpenAI adapter will not use {value!r} as its {what}: it begins with '-', and "
            f"this value reaches the CLI as its own argument, where a leading dash makes it a flag "
            f"rather than a value. Every value reaching a command line is hostile regardless "
            f"of where it came from"
        )
    return value
