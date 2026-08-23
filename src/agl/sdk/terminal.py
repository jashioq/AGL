"""Re-export facade over `agl.ports.terminal`: the `Terminal` port and everything a view is built
out of, at the name a workflow author imports. **No logic, and that is the specification.**

`ARCHITECTURE.md` §5's reason is a layering one rather than a matter of taste. `Terminal.show` takes
a view function returning a `Screen[T]`, so `Screen` is part of the port's own signature and has to
live beside it; were the components declared here instead, `ports/terminal.py` would have to import
`agl.sdk` and `.importlinter`'s contract 1 - `workflows` -> {`sdk`, `adapters`} -> `ports` - would
invert on its lowest edge, which is a failing build and not a stylistic complaint. So the types stay
in `ports/`, and this module exists so that an author writing a view never reaches into a package
the layering put below them. `ports/terminal.py` makes the same argument from the other side.

## No logic, and the absence is what is being specified

No alias, no wrapper, no subclass, no convenience constructor, no `Screen` of our own. Every name
below **is** the object `agl.ports.terminal` defines - `is`-identical, not merely compatible - so a
view built through this module and an adapter's exhaustive `match` over `Component` are looking at
one set of classes. A facade that wrapped anything would be a second definition free to drift from
the first, and the drift would surface as a `Screen` an adapter could not draw.

`sdk/tools.py` is the module that is deliberately *not* this: it re-exports `ports.agent.Tool` and
carries the reporting-tool declaration besides, and its first paragraph says so, because §5's
sentence about pure re-export facades covers this module and `sdk/questions.py` and no third.

## The whole of `ports.terminal.__all__`, not a chosen subset

Deciding which of the nine names an author "really" needs would be the one kind of logic a facade
must not hold. A name left out is a name an author imports from `agl.ports` instead, which is
precisely what this module exists to prevent - and the omission would be discovered by whoever
needed it rather than by whoever made it. `Terminal` itself is re-exported for that reason, even
though `run.terminal` is how one is normally reached: a workflow that factors its asking into a
helper has to annotate the parameter, and `Component` and `Response` are what a helper returning
part of a screen is annotated with.

## The spelling is `from agl.sdk.terminal import Screen`

`ARCHITECTURE.md` §5 and `ports/terminal.py` both write `from agl.sdk import Screen`, and this
module does **not** make that true: `src/agl/sdk/__init__.py` holds no re-exports and 15.1
deliberately adds none. Every other member of the SDK is imported from its own submodule - `from
agl.sdk.params import arg`, `from agl.sdk.workflow import Run, Stop, workflow`, which is what
`workflows/noop/` writes - so re-exporting these two modules and no others at package level would
leave one import style for terminal components and a different one for everything else, and an
author would have to remember which names fall on which side.

Making the shorter spelling true is a decision about the SDK's front door - all of it, at once - and
not a decision about terminal components, so it is not taken here. The two sentences are read as
naming the package a type belongs to rather than the exact line to type.
"""

from agl.ports.terminal import (
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

# Listed rather than computed from `ports.terminal.__all__`: a re-export whose names are assembled
# at runtime is invisible to `ruff`, to `mypy` and to anyone reading the file to find out what is
# here. `tests/sdk/test_run_terminal.py` is what asserts the two lists have not drifted apart.
__all__ = [
    "Choice",
    "Component",
    "Response",
    "Row",
    "Rows",
    "Screen",
    "Terminal",
    "Text",
    "TextInput",
]
