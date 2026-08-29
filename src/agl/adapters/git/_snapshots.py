
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from agl.ports.errors import NotFoundError

__all__ = ["FakeRepository", "Hold", "Tree"]


type Tree = Mapping[str, bytes]

_BRANCH_REF: Final = "refs/heads/"

_INITIAL: Final = "the state this repository starts at"

_ENCODING: Final = "utf-8"
_SURROGATES: Final = "surrogatepass"


@dataclass(frozen=True, slots=True)
class _State:

    tree: Tree
    parents: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class Hold:

    source: str

    target: str

    combined: Tree

    collisions: tuple[str, ...]

    message: str

    touched: frozenset[str]


class FakeRepository:

    def __init__(
        self, files: Mapping[str, bytes] | None = None, default_branch: str = "main"
    ) -> None:
        self._states: dict[str, _State] = {}
        self._branches: dict[str, str] = {}
        self._checkouts: dict[Path, str] = {}
        self._holds: dict[Path, Hold] = {}
        self._depths: dict[str, int] = {}
        self._default = default_branch
        self._branches[default_branch] = self.record(dict(files or {}), (), _INITIAL)


    @property
    def default_ref(self) -> str:
        return f"{_BRANCH_REF}{self._default}"

    def record(self, tree: Mapping[str, bytes], parents: tuple[str, ...], message: str) -> str:
        held = MappingProxyType(dict(tree))
        identity = _identity(held, parents, message)
        self._states.setdefault(identity, _State(held, parents, message))
        return identity

    def resolve(self, ref: str) -> str:
        if ref in self._states:
            return ref
        short = ref[len(_BRANCH_REF) :] if ref.startswith(_BRANCH_REF) else ref
        tip = self._branches.get(short)
        if tip is None:
            raise NotFoundError(
                f"{ref!r} names no state in this repository. It is well-formed, so either nothing "
                f"has recorded it yet or it is spelled differently here"
            )
        return tip

    def tree_of(self, state: str) -> Tree:
        return self._states[state].tree

    def message_of(self, state: str) -> str:
        return self._states[state].message.rstrip()

    def contains(self, ancestor: str, descendant: str) -> bool:
        return ancestor in self._reachable(descendant)

    def merge_base(self, left: str, right: str) -> str | None:
        common = self._reachable(left) & self._reachable(right)
        if not common:
            return None
        return max(common, key=lambda state: (self._depth(state), state))


    def tip(self, branch: str) -> str | None:
        return self._branches.get(branch)

    def move(self, branch: str, state: str) -> None:
        self._branches[branch] = state

    def drop(self, branch: str) -> None:
        self._branches.pop(branch, None)


    def checked_out_at(self, path: Path) -> str | None:
        return self._checkouts.get(path.resolve())

    def checkout_of(self, branch: str) -> Path | None:
        self.prune()
        for path, held in self._checkouts.items():
            if held == branch:
                return path
        return None

    def attach(self, path: Path, branch: str, state: str) -> None:
        self._checkouts[path.resolve()] = branch
        self._branches.setdefault(branch, state)

    def detach(self, path: Path) -> None:
        at = path.resolve()
        self._checkouts.pop(at, None)
        self._holds.pop(at, None)

    def prune(self) -> None:
        for path in [path for path in self._checkouts if not path.is_dir()]:
            self.detach(path)


    def held(self, path: Path) -> Hold | None:
        return self._holds.get(path.resolve())

    def hold(self, path: Path, pending: Hold) -> None:
        self._holds[path.resolve()] = pending

    def release(self, path: Path) -> None:
        self._holds.pop(path.resolve(), None)


    def _reachable(self, state: str) -> frozenset[str]:
        seen = {state}
        pending = [state]
        while pending:
            for parent in self._states[pending.pop()].parents:
                if parent not in seen:
                    seen.add(parent)
                    pending.append(parent)
        return frozenset(seen)

    def _depth(self, state: str) -> int:
        known = self._depths
        pending = [state]
        while pending:
            at = pending[-1]
            if at in known:
                pending.pop()
                continue
            parents = self._states[at].parents
            missing = [parent for parent in parents if parent not in known]
            if missing:
                pending.extend(missing)
                continue
            known[at] = 1 + max((known[parent] for parent in parents), default=-1)
            pending.pop()
        return known[state]


def _identity(tree: Tree, parents: tuple[str, ...], message: str) -> str:
    digest = hashlib.sha256()
    for parent in parents:
        digest.update(f"parent {parent}\n".encode())
    for path in sorted(tree):
        content = tree[path]
        name = path.encode(_ENCODING, _SURROGATES)
        digest.update(f"file {len(name)} {len(content)}\n".encode())
        digest.update(name)
        digest.update(content)
    said = message.encode(_ENCODING, _SURROGATES)
    digest.update(f"message {len(said)}\n".encode())
    digest.update(said)
    return digest.hexdigest()
