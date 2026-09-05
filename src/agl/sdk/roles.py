import sys
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from functools import update_wrapper
from pathlib import Path
from typing import Protocol
from agl.ports.agent import (
    Capability,
    Claude,
    ModelId,
    OpenAI,
    Restriction,
    Tool,
)
from agl.ports.errors import InputError, UpstreamUnexpected
from agl.ports.ids import StepName
from agl.sdk.tools import ReportingTool

__all__ = [
    "Capability",
    "Claude",
    "ModelId",
    "OpenAI",
    "Restriction",
    "Role",
    "RoleFactory",
    "RoleIncompleteError",
    "prompt_file",
    "role",
]

@dataclass(frozen=True, slots=True, kw_only=True)
class Role[P = None]:
    name: str

    instructions: str

    _model: ModelId | None = None

    restrictions: AbstractSet[Restriction] = frozenset()

    tools: Sequence[Tool | ReportingTool[P]] = ()

    requires: AbstractSet[Capability] = frozenset()

    def __post_init__(self) -> None:
        StepName(self.name)
        if not self.instructions.strip():
            raise InputError(
                f"a role's instructions are the whole of what its agent is asked to do, and this "
                f"one was declared with {self.instructions!r}. `AgentTask` refuses an empty prompt "
                f"too, at the dispatch - refused here, the line that needs fixing is on screen"
            )
        tools = tuple(self.tools)
        reporting = [declared.name for declared in tools if isinstance(declared, ReportingTool)]
        if len(reporting) > 1:
            raise InputError(
                f"this role declares more than one reporting tool: {reporting}. A reporting step's "
                f"result is that tool's payload, singular - with two, `run.step` would have "
                f"to pick one, and whichever it picked would be a rule living in the framework "
                f"about a decision the workflow made. A role reports through one tool or none"
            )
        names = [declared.name for declared in tools]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise InputError(
                f"this role declares these tools more than once: {duplicates}. A model names the "
                f"tool it is calling, so a duplicate is a call no backend can resolve to one "
                f"handler - `AgentTask` refuses it too, one layer down and one run later"
            )
        requires = frozenset(self.requires)
        if tools:
            requires |= {Capability.TOOL_CALLING}
        object.__setattr__(self, "restrictions", frozenset(self.restrictions))
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "requires", requires)

    @property
    def model(self) -> ModelId:
        """Which model runs this role, bound by its factory rather than written on the `Role`.

        :return: the model, which is a fingerprint term and decides the provider; never `None`
        :raises InputError: this `Role` came from a bare `Role(...)` no factory bound a model to
        """
        if self._model is None:
            raise InputError(
                f"the role named {self.name!r} has no model, so nothing can say which provider "
                f"runs it, fingerprint it or check what its backend can do. A role's model is "
                f"declared on its factory - `@role(model=Claude.OPUS)` above the function that "
                f"returns this `Role` - and is deliberately not a field of `Role` "
                f"itself, so that preflight can read it without calling the factory. This value "
                f"came from a bare `Role(...)`, which builds one nothing has bound a model to"
            )
        return self._model

class RoleFactory[**P, R]:
    __name__: str
    __qualname__: str

    name: str

    model: ModelId

    def __init__(self, declaration: Callable[P, Role[R]], model: ModelId) -> None:
        update_wrapper(self, declaration)
        self._declaration = declaration
        self.name = declaration.__name__
        self.model = model

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Role[R]:
        return replace(self._declaration(*args, **kwargs), _model=self.model)

class _RoleDecorator(Protocol):
    def __call__[**P, R](self, declaration: Callable[P, Role[R]], /) -> RoleFactory[P, R]: ...

def role(*, model: ModelId) -> _RoleDecorator:
    """Declare a role factory, naming the model here so preflight can read it without calling it.

    :param model: fingerprinted into every step this role runs, and asked about before step one
    :return: a decorator binding the model onto each `Role` its function returns
    """

    def decorate[**P, R](declaration: Callable[P, Role[R]]) -> RoleFactory[P, R]:
        return RoleFactory(declaration, model)

    return decorate

def prompt_file(path: str | Path) -> str:
    """Read a prompt now, at the declaration, so the text and not the filename is fingerprinted.

    :param path: relative resolves against the calling module's directory, not the current one
    :return: the text exactly as read, untrimmed, because its whitespace is inside the fingerprint
    :raises InputError: no such file, a directory, unreadable, not UTF-8, or blank once stripped
    """
    asked = Path(path)
    # `sys._getframe(1)` is the caller of *this* function, so the lookup happens here and not in the
    # helper below: a frame index is a fact about where the line is written.
    where = asked if asked.is_absolute() else _beside_the_caller(sys._getframe(1).f_globals, asked)
    try:
        text = where.read_text(encoding="utf-8")
    except FileNotFoundError as missing:
        raise InputError(
            f"there is no prompt file at {where}, so the role declared with it would have nothing "
            f"to ask its agent. A relative path is resolved against the directory of the module "
            f"that called `prompt_file` - never against the current directory - so this is the "
            f"path {asked!r} names from where it was written"
        ) from missing
    except IsADirectoryError as directory:
        raise InputError(
            f"{where} is a directory, and a role's instructions are one prompt. Name the file "
            f"inside it that this role is asking its agent to read"
        ) from directory
    except UnicodeDecodeError as undecodable:
        raise InputError(
            f"{where} is not UTF-8 text: {undecodable}. A prompt is read as UTF-8 and nothing "
            f"here repairs one - a prompt read with replacement characters in it is a prompt "
            f"nobody wrote, fingerprinted as though somebody had, and handed to a model that "
            f"would answer it anyway"
        ) from undecodable
    except OSError as unreadable:
        raise InputError(
            f"{where} could not be read: {unreadable}. The prompt is read where the role is "
            f"declared, so this is the role's factory failing rather than the step it was for"
        ) from unreadable
    if not text.strip():
        raise InputError(
            f"the prompt file {where} is empty, and a role's instructions are the whole of what "
            f"its agent is asked to do. `Role` refuses an empty prompt too, one line later, and "
            f"`AgentTask` refuses it again at the dispatch"
        )
    return text

class RoleIncompleteError(UpstreamUnexpected):
    ...

def _beside_the_caller(caller: Mapping[str, object], asked: Path) -> Path:
    declared = caller.get("__file__")
    if not isinstance(declared, str):
        raise InputError(
            f"`prompt_file({str(asked)!r})` was called from something with no `__file__` - a REPL, "
            f"an `exec`, or a frozen import - so there is no module directory for a relative path "
            f"to be relative to. Pass an absolute path. AGL will not fall back to the current "
            f"directory: a workflow's prompts sit beside its code, in the workspace directory it "
            f"was read from, and the directory `agl` was started in is the repository being "
            f"worked on - the one place those prompts are certainly not"
        )
    return Path(declared).resolve().parent / asked
