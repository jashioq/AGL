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
sentence about pure re-export facades covers this module, `sdk/questions.py` and `sdk/errors.py`.
That third one arrived at 18.0, when a workflow's own test file was found reaching into
`agl.ports.errors` to say how a run had refused; it holds no logic on the same terms as these two,
and differs from them in one way that is worth knowing about here - it takes the `AglError`
hierarchy out of `ports/errors.py` and leaves that module's exit-code table to `cli/exit_codes.py`,
which is a seam its own port draws rather than a curation of the kind the next section forbids.

## The whole of `ports.terminal.__all__`, not a chosen subset

Deciding which of the nine names an author "really" needs would be the one kind of logic a facade
must not hold. A name left out is a name an author imports from `agl.ports` instead, which is
precisely what this module exists to prevent - and the omission would be discovered by whoever
needed it rather than by whoever made it. `Terminal` itself is re-exported for that reason, even
though `run.terminal` is how one is normally reached: a workflow that factors its asking into a
helper has to annotate the parameter, and `Component` and `Response` are what a helper returning
part of a screen is annotated with.

## The spelling is `from agl.sdk import Screen`, and 16.5 is what made it true

`ARCHITECTURE.md` §5 and `ports/terminal.py` both write that line, and until 16.5 it raised
`ImportError`: `src/agl/sdk/__init__.py` held no re-exports, and 15.1 deliberately added none. The
reason given then was that re-exporting *these two modules and no others* would leave one import
style for terminal components and a different one for everything else, and that making the shorter
spelling true is a decision about the SDK's front door - all of it, at once - rather than a decision
about terminal components.

16.5 took that decision, and it took it the other way: `sdk/__init__.py` now re-exports the whole
authoring surface, so there is one style rather than two and the objection above is answered rather
than overruled. Both spellings work and name the same objects, this module being where the nine are
re-exported from and the package root taking them from here. `from agl.sdk import Screen` is the one
an author writes; `from agl.sdk.terminal import Screen` is what a workflow that prefers submodules
writes, and it costs nothing.
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
