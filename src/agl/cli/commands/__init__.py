"""One module per agl subcommand - run, resume, clear, init, workflows - and the type they share.

`Registered` is that type, and it lives here from 16.2 because 16.2 is the deliverable that gave it
a second consumer. `cli/commands/run.py` wrote it down at 10.4 and said where it would move and
why: "When 16.2 and 16.3 add commands taking the same callable, `cli/commands/__init__.py` is where
it moves: both import through it already, and the move changes a name and no type."

It is a name and no type. `Callable[[], tuple[ProjectName, Services]]` is spelled once, in the
package every command already goes through, and the two commands that take one plus the module that
produces one all annotate against this line. Written on `run.py` it would now be `resume.py`
importing a sibling command in order to name a parameter neither of them owns, and `clear.py` - the
third consumer, which 16.3 added - would be doing it too. A `TYPE_CHECKING` block would be the other
way to break that, and there is not one anywhere in this codebase.

The direction of the imports is what made `run.py` the right place at 10.4 and this the right place
now. `cli/main.py` imports each command module in order to declare its subcommand, so no command may
import `main` back, and one of the two sides has to spell the callable out. A package `__init__` is
below both: `main` reaches it through the modules it already imports, and each command reaches it
without naming any other command.
"""

from collections.abc import Callable

from agl.ports.ids import ProjectName
from agl.sdk._engine.services import Services

__all__ = ["Registered"]


type Registered = Callable[[], tuple[ProjectName, Services]]
"""A registered repository, asked for rather than received: the project this invocation addresses
and the ports built for it.

§3.10's per-command composition, as a type. `cli/main.py` produces one - `Invocation.registered` -
and the three commands addressed to a repository call it. `init` and `workflows` take no parameter
of this type at all, which is 16.4 making the other half structural rather than remembered: `init`
writes the very project file this would look for, and `workflows` looks for nothing. Deferred rather
than resolved, so that a command supplies one bit, whether it needs a repository, and learns nothing
about what the answer is made of.

It answers with a `ProjectName` and not a `config.schema.Project`, because that is the whole of what
`api` takes and `api.py` says why: the rest of a `Project` has already been spent by the container
in constructing the ports handed back beside it."""
