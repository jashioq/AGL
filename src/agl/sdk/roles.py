import sys
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from functools import update_wrapper
from pathlib import Path
from typing import Protocol
from agl.ports.agent import (
    ActivityReporter,
    Capability,
    Claude,
    ClaudeEffort,
    ModelChoice,
    ModelId,
    OpenAI,
    OpenAIEffort,
    Restriction,
    Tool,
)
from agl.ports.errors import InputError, UpstreamUnexpected
from agl.ports.ids import StepName
from agl.sdk._declarations import named
from agl.sdk._engine.prompts import check_placeholders
from agl.sdk.tools import ReportingTool

__all__ = [
    "ActivityReporter",
    "Capability",
    "Claude",
    "ClaudeEffort",
    "ModelId",
    "OpenAI",
    "OpenAIEffort",
    "Restriction",
    "Role",
    "RoleFactory",
    "RoleIncompleteError",
    "prompt_file",
    "role",
]

@dataclass(frozen=True, slots=True, kw_only=True)
class Role[P = None]:
    """An agent a step runs, with its instructions and tools."""

    name: str
    """The name this role's steps run under. Two roles' names should differ by more than case."""

    instructions: str
    """What the agent is asked to do. Each `{{TypeName}}` in it is filled with that input."""

    _model: ModelChoice | None = None

    _accepts: tuple[type[object], ...] = ()

    restrictions: AbstractSet[Restriction] = frozenset()
    """The [`Restriction`][agl.sdk.Restriction] members this role's agent works under."""

    tools: Sequence[Tool | ReportingTool[P]] = ()
    """The tools the agent is offered, with unique names and at most one reporting tool."""

    requires: AbstractSet[Capability] = frozenset()
    """The [`Capability`][agl.sdk.Capability] members the backend has to offer."""

    on_activity: ActivityReporter | None = None
    """Called with each line of progress the agent reports as it works."""

    def __post_init__(self) -> None:
        StepName(self.name)
        if not self.instructions.strip():
            raise InputError(
                f'Role "{self.name}" has no instructions. Write what its agent is asked to do.'
            )
        tools = tuple(self.tools)
        reporting = [declared.name for declared in tools if isinstance(declared, ReportingTool)]
        if len(reporting) > 1:
            raise InputError(
                f'Role "{self.name}" has more than one reporting tool: {_quoted(reporting)}. '
                "Keep one."
            )
        names = [declared.name for declared in tools]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise InputError(
                f'Role "{self.name}" has tools that share a name: {_quoted(duplicates)}. Give '
                "each tool its own name."
            )
        requires = frozenset(self.requires)
        if tools:
            requires |= {Capability.TOOL_CALLING}
        object.__setattr__(self, "restrictions", frozenset(self.restrictions))
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "requires", requires)

    @property
    def model(self) -> ModelChoice:
        """The model this role runs on.

        Returns:
            The model set with `@role(model=...)`.

        Raises:
            InputError: This role was built with `Role(...)`, not by a `@role` function.
        """
        if self._model is None:
            raise InputError(
                f'Role "{self.name}" was built with `Role(...)`, so it has no model. Return it '
                "from a function decorated with `@role(model=...)`, and call that function."
            )
        return self._model

    @property
    def accepts(self) -> tuple[type[object], ...]:
        """The input types a step can pass this role.

        Returns:
            The types set with `@role(accepts=...)`, or none.
        """
        return self._accepts

class RoleFactory[**P, R]:
    """A `@role` function, which builds a [`Role`][agl.sdk.Role] when called."""

    __name__: str
    __qualname__: str

    name: str
    """The decorated function's own name, which a refusal about this factory is reported under."""

    model: ModelChoice
    """The model given to `@role`, readable without calling the factory."""

    accepts: tuple[type[object], ...]
    """The classes given to `@role`, in the order they were written."""

    def __init__(
        self,
        declaration: Callable[P, Role[R]],
        model: ModelChoice,
        accepts: tuple[type[object], ...],
    ) -> None:
        # Here and not beside the `check_placeholders` call below: `accepts=` is the decorator's
        # own argument and is answerable at the decoration, where a prompt is not - the text is
        # what the declaration returns, so nothing has read one until it has been called.
        _check_accepted_types(declaration.__name__, accepts)
        update_wrapper(self, declaration)
        self._declaration = declaration
        self.name = declaration.__name__
        self.model = model
        self.accepts = accepts

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Role[R]:
        """Builds the [`Role`][agl.sdk.Role], passing everything through to the function.

        Args:
            args: The positional arguments the decorated function takes.
            kwargs: The keyword arguments the decorated function takes.

        Returns:
            The `Role` the function returned, carrying this factory's model and accepted types.

        Raises:
            InputError: The prompt and `accepts=` don't name the same set of types, or the
                `Role` the function returned is refused.
        """
        built = replace(
            self._declaration(*args, **kwargs), _model=self.model, _accepts=self.accepts
        )
        # Here and not in `Role.__post_init__`: the `Role` a declaration returns carries no
        # `_accepts` yet - the `replace` above is what stamps it - so a check there would refuse
        # every role a factory is part-way through building. This is the first moment a prompt and
        # the declaration that fills it are on one object.
        check_placeholders(self.name, built.name, built.instructions, self.accepts)
        return built

class _RoleDecorator(Protocol):
    def __call__[**P, R](self, declaration: Callable[P, Role[R]], /) -> RoleFactory[P, R]: ...

def role(*, model: ModelChoice, accepts: Sequence[type[object]] = ()) -> _RoleDecorator:
    """Declares a function that builds a [`Role`][agl.sdk.Role].

    Args:
        model: The model the role runs on, bare or called with an effort. A bare model reasons
            at whatever its own tool does by default.
        accepts: The classes the role takes as inputs, each named in its prompt as
            `{{TypeName}}`. If omitted, the role takes no inputs.

    Returns:
        The decorator to write above the function, which turns it into a role factory.

    Raises:
        InputError: An `accepts=` entry that is not a class, one `isinstance` refuses, or two
            that share a name.
    """

    def decorate[**P, R](declaration: Callable[P, Role[R]]) -> RoleFactory[P, R]:
        return RoleFactory(declaration, model, tuple(accepts))

    return decorate

def prompt_file(path: str | Path) -> str:
    """Reads a role's prompt out of a file.

    Args:
        path: The file to read. A relative path is resolved against the directory of the module
            that called this, never against the directory `agl` was started in.

    Returns:
        The file's text, decoded as UTF-8.

    Raises:
        InputError: There is no such file, it is a directory, it cannot be read, it is not
            UTF-8, or it is empty.
    """
    asked = Path(path)
    # `sys._getframe(1)` is the caller of *this* function, so the lookup happens here and not in the
    # helper below: a frame index is a fact about where the line is written.
    where = asked if asked.is_absolute() else _beside_the_caller(sys._getframe(1).f_globals, asked)
    try:
        text = where.read_text(encoding="utf-8")
    except FileNotFoundError as missing:
        raise InputError(
            f"There is no prompt file at {where}. Write a relative path from the directory of the "
            f"module that calls `prompt_file`."
        ) from missing
    except IsADirectoryError as directory:
        raise InputError(
            f"The prompt file {where} is a directory. Name the file inside it that holds the "
            f"prompt."
        ) from directory
    except UnicodeDecodeError as undecodable:
        raise InputError(
            f"The prompt file {where} is not UTF-8 at byte offset {undecodable.start}. Save it as "
            f"UTF-8."
        ) from undecodable
    except OSError as unreadable:
        raise InputError(
            f"The prompt file {where} can't be read: {unreadable.strerror or unreadable}."
        ) from unreadable
    if not text.strip():
        raise InputError(
            f"The prompt file {where} is empty. Write what the role's agent is asked to do."
        )
    return text

class RoleIncompleteError(UpstreamUnexpected):
    """The agent stopped without reporting a result."""

def _check_accepted_types(factory: str, accepts: tuple[type[object], ...]) -> None:
    # A parameterised generic and a union are not instances of `type` in CPython, so `list[str]`
    # and `int | str` are refused by this one test alongside a string, an instance and `None`.
    unusable = sorted(named(entry) for entry in accepts if not isinstance(entry, type))
    if unusable:
        raise InputError(
            f'Role factory "{factory}" has entries in `accepts=` that are not classes: '
            f"{', '.join(unusable)}. Write each as the class itself, as in `accepts=(Ticket,)`."
        )
    # `typing.Any` and a `Protocol` written without `@runtime_checkable` are instances of `type`,
    # so the test above takes both, and CPython's `isinstance` then refuses either as its second
    # argument whatever the first one is. Nothing on the class marks it and `mypy --strict` passes
    # either at the call site, so calling `isinstance` is the only test there is.
    unmatchable = sorted(named(entry) for entry in accepts if not _matchable(entry))
    if unmatchable:
        raise InputError(
            f'Role factory "{factory}" has entries in `accepts=` that `isinstance` refuses: '
            f"{', '.join(unmatchable)}. Declare the class an input really is, or write "
            f"`@runtime_checkable` above the protocol."
        )
    names = [kind.__qualname__ for kind in accepts]
    collided = sorted({name for name in names if names.count(name) > 1})
    if collided:
        raise InputError(
            f'Role factory "{factory}" has entries in `accepts=` that share a name: '
            f"{_quoted(collided)}. Give each class its own name, and declare each one once."
        )

def _quoted(names: Sequence[str]) -> str:
    return ", ".join(f'"{name}"' for name in names)

def _matchable(entry: type[object]) -> bool:
    try:
        isinstance(object(), entry)
    except TypeError:
        return False
    return True

def _beside_the_caller(caller: Mapping[str, object], asked: Path) -> Path:
    declared = caller.get("__file__")
    if not isinstance(declared, str):
        raise InputError(
            f"The prompt path {asked} is relative, and `prompt_file` was called from code with no "
            f"`__file__`, such as a REPL. Pass an absolute path."
        )
    return Path(declared).resolve().parent / asked
