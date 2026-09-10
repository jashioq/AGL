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
    ModelId,
    OpenAI,
    Restriction,
    Tool,
)
from agl.ports.errors import InputError, UpstreamUnexpected
from agl.ports.ids import StepName
from agl.sdk._engine.prompts import check_placeholders
from agl.sdk.tools import ReportingTool

__all__ = [
    "ActivityReporter",
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
    """What one step asks of one agent: a name, a prompt, tools, restrictions and a watcher."""

    name: str
    """The `steps/<name>/` directory its entries file under, matched with the case folded away."""

    instructions: str

    _model: ModelId | None = None

    _accepts: tuple[type[object], ...] = ()

    restrictions: AbstractSet[Restriction] = frozenset()

    tools: Sequence[Tool | ReportingTool[P]] = ()

    requires: AbstractSet[Capability] = frozenset()

    on_activity: ActivityReporter | None = None
    """Each line as the agent works, nothing when a step ends: the last stands until the next."""

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

        :return: the model and so the provider; a fingerprint term, so changing it replays nothing
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

    @property
    def accepts(self) -> tuple[type[object], ...]:
        """Which input types a step may pass it, bound by its factory rather than written here.

        :return: the declared types, matched by `isinstance`; empty for a role that takes no inputs
        """
        return self._accepts

class RoleFactory[**P, R]:
    """What `@role` returns: a declaration, plus the name, model and types read without calling."""

    __name__: str
    __qualname__: str

    name: str

    model: ModelId

    accepts: tuple[type[object], ...]

    def __init__(
        self, declaration: Callable[P, Role[R]], model: ModelId, accepts: tuple[type[object], ...]
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

def role(*, model: ModelId, accepts: Sequence[type[object]] = ()) -> _RoleDecorator:
    """Declare a role factory, naming the model and the inputs so both are readable uncalled.

    :param model: fingerprinted into every step this role runs, and asked about before step one
    :param accepts: classes with distinct names; the prompt names each `{{TypeName}}` and no other
    :return: a decorator binding the model and the accepted types onto each `Role` it returns
    """

    def decorate[**P, R](declaration: Callable[P, Role[R]]) -> RoleFactory[P, R]:
        return RoleFactory(declaration, model, tuple(accepts))

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
    """The agent produced no result: nothing was recorded, so the next attempt runs the step."""

def _check_accepted_types(factory: str, accepts: tuple[type[object], ...]) -> None:
    # A parameterised generic and a union are not instances of `type` in CPython, so `list[str]`
    # and `int | str` are refused by this one test alongside a string, an instance and `None`.
    unusable = sorted(repr(entry) for entry in accepts if not isinstance(entry, type))
    if unusable:
        raise InputError(
            f"the role factory {factory!r} declares {unusable} in `accepts=`, and every entry "
            f"there has to be a class. An input is matched to a declared type by `isinstance` and "
            f"recorded under that type's `__qualname__`, so an entry that is not a class can "
            f"neither match a value nor name the `{{{{TypeName}}}}` a match would fill. Write the "
            f"class itself - `accepts=(Ticket,)`, never `accepts=('Ticket',)` and never "
            f"`accepts=(Ticket(),)`"
        )
    # `typing.Any` and a `Protocol` written without `@runtime_checkable` are instances of `type`,
    # so the test above takes both, and CPython's `isinstance` then refuses either as its second
    # argument whatever the first one is. Nothing on the class marks it and `mypy --strict` passes
    # either at the call site, so calling `isinstance` is the only test there is.
    unmatchable = sorted(repr(entry) for entry in accepts if not _matchable(entry))
    if unmatchable:
        raise InputError(
            f"the role factory {factory!r} declares {unmatchable} in `accepts=`, and `isinstance` "
            f"refuses each of them as its second argument. An input is matched to a declared type "
            f"by `isinstance`, so an entry that call will not take matches no value at all - left "
            f"to the step it raises a bare `TypeError` from inside AGL at the first step that "
            f"passes one, with whatever ran before that step already paid for. `typing.Any` is one "
            f"of these and a `Protocol` declared without `@runtime_checkable` is the other: write "
            f"`@runtime_checkable` above the protocol, or declare the class an input really is"
        )
    names = [kind.__qualname__ for kind in accepts]
    collided = sorted({name for name in names if names.count(name) > 1})
    if collided:
        raise InputError(
            f"the role factory {factory!r} declares more than one `accepts=` entry under each of "
            f"{collided}. A step's inputs are recorded one per declared type, under that type's "
            f"`__qualname__`, and a prompt fills a `{{{{TypeName}}}}` from that one key - so two "
            f"entries sharing a name are one slot, only one of them can ever be filled, and the "
            f"scan comparing `accepts=` against the prompt reads one name where two were "
            f"declared. Two classes written in two modules, or in two functions, share a "
            f"`__qualname__`, so this is as often a collision as a repetition: declare one entry "
            f"per name, renaming a class where both of them are really wanted. A subclass needs "
            f"no entry of its own - it is matched under the base already declared - and one "
            f"declared beside its base is a different name and is not this"
        )

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
            f"`prompt_file({str(asked)!r})` was called from something with no `__file__` - a REPL, "
            f"an `exec`, or a frozen import - so there is no module directory for a relative path "
            f"to be relative to. Pass an absolute path. AGL will not fall back to the current "
            f"directory: a workflow's prompts sit beside its code, in the workspace directory it "
            f"was read from, and the directory `agl` was started in is the repository being "
            f"worked on - the one place those prompts are certainly not"
        )
    return Path(declared).resolve().parent / asked
