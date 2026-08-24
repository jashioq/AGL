"""Ring 2: what workflow authors build from - the public surface a workflow imports.

**One import line, and this is the door it comes through.**

    from agl.sdk import Claude, OpenAI, Role, Run, Screen, Text, arg, reporting_tool, workflow

Everything below is re-exported from a module in this package and from nowhere else, so the two
spellings are one surface: `from agl.sdk import Screen` and `from agl.sdk.terminal import Screen`
name the same object, and a workflow that prefers submodules loses nothing. What an author must
never have to write is `from agl.ports...`, and the list below is chosen against exactly that test.

## Why the full re-export, when 15.1 deliberately added none

`ARCHITECTURE.md` §5 and `ports/terminal.py` both say a workflow author writes `from agl.sdk import
Screen`, and until 16.5 that line raised `ImportError`. `sdk/terminal.py` and `sdk/questions.py`
each declined to make it true and each said why: re-exporting two modules at package level would
leave the SDK with one import style for terminal components and another for everything else, and
both concluded that the question is about the front door as a whole and belongs to a deliverable
that takes all of it at once.

That objection is an objection to a **partial** re-export, and a full one answers it rather than
overrides it. Three things carry the decision:

  * **It makes two documents true instead of rewording them around a gap.** Both sentences were
    written as statements of intent about the SDK's front door rather than as loose talk about
    which package a type lives in, and the cheaper repair - edit the docs to say
    `agl.sdk.terminal` - would have been the design following the implementation.
  * **R1 counts lines.** Measurable target #2 is "`fix` is ~8 lines", stage 17 is where that is
    measured, and a workflow that imports its params helper, its role vocabulary, its tool
    declaration, its components and its `Run` from five modules spends five lines before it has
    said anything. One `from agl.sdk import ...` is the difference between an authoring surface and
    a directory of modules.
  * **A name left out is a name imported from `agl.ports`**, which is what the facades exist to
    prevent (`sdk/terminal.py` argues it about its own nine names). That is the rule the list below
    is assembled by, and every omission is argued in the next section rather than left to be
    discovered by whoever needed it.

## What is on it, and what is not

**On it, by layer of the thing an author writes** (§3.3's four): the params helper `arg`; the role
vocabulary - `Role`, `prompt_file`, `RoleIncompleteError`, and the enums a role is declared out of,
`Claude`, `OpenAI`, `ModelId`, `Restriction`, `Capability`, `QuestionHandler`; the tool declarations
`reporting_tool`, `ReportingTool`, `Tool`, `ToolResult`; the nine terminal components and the
`Terminal` they are shown on; `Question` and `Answer`, which is what an `on_question` handler is
written against; and `workflow`, `Run`, `Workflow` and `Stop`.

`Claude` and `Restriction` are worth a sentence, because they are the names most obviously *not*
declared in this package. They are `ports/agent.py`'s, for the layering reason `Screen` is
`ports/terminal.py`'s - an `AgentRunner` speaks them - and an author writing `model=Claude.OPUS`
should no more reach into `ports` for that than for a `Screen`. So `sdk/roles.py` re-exports them
beside the `Role` they are fields of, and this module takes them from there: **everything here comes
from a module in this package**, which is what keeps the two import styles one surface.

**Not on it, each for its own reason:**

  * **`_engine` and everything in it.** `sdk/_engine/__init__.py` says it is "not part of the
    surface a workflow author imports", and that stays true: `Services`, `Journal`, `Steps`,
    `Worktrees`, `Leases`, `Fingerprints` and `Capabilities` are the plumbing under `run.step`,
    `run.worktree` and `run.integrate`, and a workflow that named one of them would be reaching
    past the six members §3.3 gives it. `api.py` imports three of them and is framework.
  * **The rest of `sdk/params.py`.** `parse`, `to_json`, `from_json`, `parser_for` and
    `RefusingParser` are what the *framework* does with a params class - `api.run` parses argv,
    `api.resume` rebuilds from the record, `agl workflows <name>` formats the parser. An author
    declares fields with `arg()` and reads `run.params`; the other five are on that module for
    `api.py` and for anyone inspecting a parser, and putting them here would advertise a parsing
    surface no workflow has any business calling.
  * **`sdk/testing.py`'s vocabulary.** `Agent`, `Reply` and `Call` are re-exported by
    `agl/testing.py` instead, beside the `harness` that is useless without them - one import for a
    test, as this is one import for a workflow. A name on two front doors is a name a reader has to
    choose between, and the test-facing half has a front door of its own.
  * **`ports/errors.py`'s hierarchy, except `Stop`.** That one is here because §3.1 makes it a
    workflow's own mechanism - "workflows subclass it under their own names" - and it arrives
    through `sdk/workflow.py`, which has re-exported it since stage 10. (`RoleIncompleteError` is
    on the door too and is not that module's: it is `sdk/roles.py`'s own class, because §3.3 makes
    it a fact about a `Role`.) The nine remaining classes are not the authoring surface:
    `ports/errors.py` holds "the one exception -> exit-code table in the codebase", every layer
    raises out of it and `cli/exit_codes.py` reads it, so it is what AGL raises *at* everyone rather
    than part of what a workflow is built *from*, and `EXIT_CODES` and `exit_code_for` beside them
    are the CLI's. **The omission is
    worth watching rather than settled**: `sdk/workflow.py` warns an author away from `except
    AglError:` around a step, and an author who takes that advice and catches `UpstreamError`
    instead is reaching into `agl.ports` for it. If `fix` or `split` catches an AGL class, that is
    the evidence this decision was wrong, and the repair is to re-export the hierarchy from a module
    in this package rather than to point authors at `ports`.
  * **`Integration`**, which `run.integrate()` returns. It is `sdk/_engine/integration.py`'s, for
    the reason `sdk/workflow.py` gives where it is annotated: `ports.IntegrationOutcome` carries no
    `retry` and no `abort`, so the object a workflow gets back has to be the engine's. An author
    reads `outcome.conflicted` and calls one of its two verbs on a value they were handed; nothing
    about that needs the name, and exporting it would put an `_engine` class on the front door.

## No `__getattr__`, and `__all__` is typed out

Every name below is a real import statement and `__all__` is a literal list, never assembled from
the submodules' own. `sdk/terminal.py` argues that at length for its nine and the argument is the
same one at nine times the size: a re-export computed at runtime is invisible to `ruff`, to `mypy`
and to anyone reading this file to find out what is here, and a lazy `__getattr__` would
additionally hide a typo until the line that made it ran. `tests/sdk/test_front_door.py` is what
asserts that this list and the submodules' have not drifted apart.

**No cycle, and it is worth saying why not.** Importing this package executes every import below, so
a module under `agl.sdk` that imported `agl.sdk` at package level would be a cycle. None does, none
may, and each imports the submodule it needs directly - `sdk/roles.py` writes `from agl.sdk.tools
import ReportingTool`, not `from agl.sdk import ReportingTool`. `tests/sdk/test_front_door.py` pins
that too, because the failure is an `ImportError` at a distance.

`scripts/check`'s package-root gate is about `src/agl/__init__.py` and not about this file. That one
holds no import statement at all, for the reason contract 5 cannot express - see `.importlinter`.
"""

from agl.sdk.params import arg
from agl.sdk.questions import Answer, Question
from agl.sdk.roles import (
    Capability,
    Claude,
    ModelId,
    OpenAI,
    QuestionHandler,
    Restriction,
    Role,
    RoleIncompleteError,
    prompt_file,
)
from agl.sdk.terminal import (
    Choice,
    Component,
    Response,
    Row,
    Rows,
    Screen,
    Terminal,
    Text,
    TextInput,
)
from agl.sdk.tools import ReportingTool, Tool, ToolResult, reporting_tool
from agl.sdk.workflow import Run, Stop, Workflow, workflow

# Listed and not computed - see the module docstring. Sorted, so that a name added to it is added
# where a reader looks for it rather than at the end.
__all__ = [
    "Answer",
    "Capability",
    "Choice",
    "Claude",
    "Component",
    "ModelId",
    "OpenAI",
    "Question",
    "QuestionHandler",
    "ReportingTool",
    "Response",
    "Restriction",
    "Role",
    "RoleIncompleteError",
    "Row",
    "Rows",
    "Run",
    "Screen",
    "Stop",
    "Terminal",
    "Text",
    "TextInput",
    "Tool",
    "ToolResult",
    "Workflow",
    "arg",
    "prompt_file",
    "reporting_tool",
    "workflow",
]
