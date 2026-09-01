from collections.abc import Callable
from dataclasses import dataclass
from agl.ports.errors import ConflictError
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace

__all__ = ["Worktrees"]

class Worktrees[R]:
    def __init__(self) -> None:
        self._taken: dict[str, _Taken[R]] = {}

    def open(
        self, namespace: str, *, scope: RunScope, base: str, build: Callable[[RunScope, str], R]
    ) -> R:
        wanted = Namespace(namespace)
        key = wanted.collision_key
        taken = self._taken.get(key)
        if taken is not None:
            if taken.scope == scope and taken.namespace == wanted:
                return taken.child
            raise ConflictError(_collision(wanted, scope, taken.namespace, taken.scope))
        child = build(scope.inside(wanted), base)
        self._taken[key] = _Taken(wanted, scope, child)
        return child

@dataclass(frozen=True, slots=True)
class _Taken[R]:
    namespace: Namespace

    scope: RunScope

    child: R

def _collision(namespace: Namespace, scope: RunScope, held: Namespace, holder: RunScope) -> str:
    return (
        f"namespace {str(namespace)!r}, asked for by {_where(scope)}, is already taken in run "
        f"{str(holder.label)!r}: {_where(holder)} holds it as {str(held)!r}. Namespace names are "
        f"unique run-wide and not merely among siblings, compared case-insensitively, "
        f"because the trees root is flat - both of these are one checkout directory in this run, "
        f"and whichever opened second would be handed the other's working tree. Nothing was "
        f"changed: pick another name"
    )

def _where(scope: RunScope) -> str:
    if not scope.namespaces:
        return "the run itself"
    return "the worktree " + " -> ".join(str(name) for name in scope.namespaces)
