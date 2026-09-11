from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from agl.config.inspection import Member, PlaceableWorkflow, StandingEntry, folded, listed
from agl.config.placement import Got
from agl.config.provenance import Provenance, placed_hash, read_provenance
from agl.config.questions import GainedDependencies, LocalChanges, Question
from agl.config.removal import entries_named
from agl.ports.errors import AglError, ConflictError, InputError, NotFoundError
from agl.ports.fetch import Fetcher, Resolution, ResolvedRef, UnresolvedRef
from agl.ports.get_request import Fetch, RepositoryAtRef, RequestedWorkflow
from agl.ports.home_layout import PROVENANCE_FILE, AglHome, workflows_dir

__all__ = [
    "Comparison",
    "DownloadedWorkflow",
    "MovedWorkflow",
    "ReplaceableWorkflow",
    "Replacements",
    "UncheckedWorkflow",
    "UnreplaceableWorkflow",
    "Updated",
    "compared",
    "replacements",
]

_HIDDEN: Final = "."

# A git object id: sha1 is 40 characters of lowercase hexadecimal, sha256 is 64.
_SHA_CHARACTERS: Final = frozenset("0123456789abcdef")
_SHA_LENGTHS: Final = frozenset({40, 64})

@dataclass(frozen=True, slots=True)
class DownloadedWorkflow:
    """A workflow `agl get` placed: the entry it stands in, and what its provenance file records."""

    entry: Path
    """Where the provenance was read, whose name need not be the one the workflow was placed as."""

    provenance: Provenance

@dataclass(frozen=True, slots=True)
class MovedWorkflow:
    """A downloaded workflow whose ref names another commit now: the workflow, and that commit."""

    entry: Path

    provenance: Provenance

    commit: str
    """What its recorded ref names now: a download asks for that ref, and never for this commit."""

@dataclass(frozen=True, slots=True)
class UncheckedWorkflow:
    """An entry whose commit could not be compared, and the error saying why - never raised."""

    entry: Path

    provenance: Provenance | None
    """`None` where the provenance file itself is what could not be read."""

    refusal: AglError

@dataclass(frozen=True, slots=True)
class Comparison:
    """Every downloaded workflow, by whether its ref still names the commit it was placed from."""

    current: tuple[DownloadedWorkflow, ...]

    moved: tuple[MovedWorkflow, ...]

    refused: tuple[UncheckedWorkflow, ...]

@dataclass(frozen=True, slots=True)
class ReplaceableWorkflow:
    """A moved workflow an update may replace, measured where it stands before anything is asked."""

    entry: Path

    provenance: Provenance

    changed: bool
    """Whether it measures other than its provenance records, which any change in it makes it do."""

    declared: tuple[str, ...]
    """Its `[project] dependencies` as written on disk, none where its project file reads none."""

@dataclass(frozen=True, slots=True)
class UnreplaceableWorkflow:
    """A moved workflow an update will not replace, and the error saying why - never raised."""

    entry: Path

    provenance: Provenance

    refusal: AglError

@dataclass(frozen=True, slots=True)
class Replacements:
    """Every moved workflow, by whether an update may replace it where it stands."""

    replaceable: tuple[ReplaceableWorkflow, ...]

    unreplaceable: tuple[UnreplaceableWorkflow, ...]

    # At the ref each was placed from and never at the commit the check resolved: the provenance an
    # update writes keeps the ref its download was asked at, so a download at that commit would pin
    # the workflow there for good. And not through `GetRequest`, which refuses two workflows placed
    # in one directory - two copies of one, differing in case, are inspection's to refuse.
    @property
    def fetches(self) -> tuple[Fetch, ...]:
        """One download per repository at a recorded ref, each workflow in it asked for once."""
        grouped: dict[_Asked, list[RequestedWorkflow]] = {}
        for one in self.replaceable:
            workflow = one.provenance.workflow
            wanted = grouped.setdefault(_asked(workflow.repository), [])
            if workflow not in wanted:
                wanted.append(workflow)
        return tuple(Fetch(wanted[0].repository, tuple(wanted)) for wanted in grouped.values())

    # A dependency is compared as it is written, so a line the copy does not write the same way - a
    # new name, a changed bound, a URL repointed under an old name - is one uv has not installed for
    # it, and asked about. One the update drops installs nothing, and is not.
    def questions(self, placeable: PlaceableWorkflow) -> tuple[Question, ...]:
        """What an update asks before it replaces a copy, in order: its changes, then additions."""
        standing = next(
            one for one in self.replaceable if one.provenance.workflow == placeable.workflow
        )
        asked: list[Question] = []
        if standing.changed:
            asked.append(LocalChanges(standing.entry, standing.provenance.commit, placeable.commit))
        gained = tuple(one for one in placeable.dependencies if one not in standing.declared)
        if gained:
            asked.append(
                GainedDependencies(placeable.workflow, placeable.commit, standing.entry, gained)
            )
        return tuple(asked)

@dataclass(frozen=True, slots=True)
class Updated:
    """What one `agl update` made of every workflow `agl get` placed, by what became of each."""

    comparison: Comparison

    replacements: Replacements

    got: Got
    """Every replaceable workflow once downloaded, sorted as `agl get` sorts what it asked for."""

    @property
    def refusals(self) -> tuple[AglError, ...]:
        """Every refusal, whichever phase made it: what the command's exit status is read from."""
        return (
            *(one.refusal for one in self.comparison.refused),
            *(one.refusal for one in self.replacements.unreplaceable),
            *(one.refusal for one in self.got.refused),
        )

type _Found = DownloadedWorkflow | UncheckedWorkflow | None

type _Asked = tuple[str, str, str | None]

async def compared(fetcher: Fetcher, home: AglHome, name: str | None) -> Comparison:
    """Every downloaded workflow's recorded commit set beside its ref's, or `name`'s alone."""
    entries = [entry for entry in listed(home) if not entry.path.name.startswith(_HIDDEN)]
    found = {entry.path: _downloaded(entry.path) for entry in entries}
    if name is not None:
        chosen = _checked_entry(entries, name, found, workflows_dir(home))
        found = {chosen.path: found[chosen.path]}
    downloads = [one for one in found.values() if isinstance(one, DownloadedWorkflow)]
    resolutions = await _resolutions(fetcher, downloads)
    current: list[DownloadedWorkflow] = []
    moved: list[MovedWorkflow] = []
    refused = [one for one in found.values() if isinstance(one, UncheckedWorkflow)]
    for one in downloads:
        resolution = resolutions[_asked(one.provenance.workflow.repository)]
        if isinstance(resolution, UnresolvedRef):
            refused.append(UncheckedWorkflow(one.entry, one.provenance, resolution.refusal))
        elif resolution.commit == one.provenance.commit:
            current.append(one)
        else:
            moved.append(MovedWorkflow(one.entry, one.provenance, resolution.commit))
    return Comparison(tuple(current), tuple(moved), tuple(refused))

def _downloaded(entry: Path) -> _Found:
    if not entry.is_dir():
        return None
    try:
        provenance = read_provenance(entry)
    except InputError as unreadable:
        return UncheckedWorkflow(entry, None, unreadable)
    return None if provenance is None else DownloadedWorkflow(entry, provenance)

def _checked_entry(
    entries: Sequence[StandingEntry], name: str, found: Mapping[Path, _Found], directory: Path
) -> StandingEntry:
    spellings = entries_named(entries, name)
    if len(spellings) > 1:
        raise ConflictError(_ambiguous(name, spellings))
    if not spellings:
        raise NotFoundError(_unlisted(name, entries, found, directory))
    if found[spellings[0].path] is None:
        raise NotFoundError(_undownloaded(spellings[0].path))
    return spellings[0]

async def _resolutions(
    fetcher: Fetcher, downloads: Iterable[DownloadedWorkflow]
) -> dict[_Asked, Resolution]:
    resolutions: dict[_Asked, Resolution] = {}
    for one in downloads:
        repository = one.provenance.workflow.repository
        if _asked(repository) not in resolutions:
            resolutions[_asked(repository)] = await _resolution(fetcher, repository)
    return resolutions

# GitHub answers to an owner and a repository in any case, while git keeps two refs differing only
# in case apart - the unit `GetRequest.fetches` downloads in, so one question is asked per download.
def _asked(repository: RepositoryAtRef) -> _Asked:
    return repository.owner.casefold(), repository.repo.casefold(), repository.ref

# A full object id names one commit for good, so asking what it names now would spend one of the
# sixty requests an hour GitHub allows an address on an answer already in hand.
async def _resolution(fetcher: Fetcher, repository: RepositoryAtRef) -> Resolution:
    ref = repository.ref
    if ref is not None and len(ref) in _SHA_LENGTHS and _SHA_CHARACTERS.issuperset(ref):
        return ResolvedRef(repository, ref)
    return await fetcher.resolve(repository)

def replacements(home: AglHome, moved: Sequence[MovedWorkflow]) -> Replacements:
    """Each moved workflow measured where it stands, or refused where no update may replace it."""
    members = {entry.path: entry.member for entry in listed(home)}
    measured = [_replacement(one, members.get(one.entry)) for one in moved]
    return Replacements(
        tuple(one for one in measured if isinstance(one, ReplaceableWorkflow)),
        tuple(one for one in measured if isinstance(one, UnreplaceableWorkflow)),
    )

# A package imports by its own directory's name, so `triage`'s files placed at `triage_old` would
# import as a package their own declarations never name - and placed at `triage` instead, they would
# stand beside a renamed or copied workflow declaring every name they declare.
def _replacement(
    moved: MovedWorkflow, member: Member | None
) -> ReplaceableWorkflow | UnreplaceableWorkflow:
    entry, provenance = moved.entry, moved.provenance
    if folded(entry.name) != provenance.workflow.name.collision_key:
        misplaced = ConflictError(_misplaced(entry, provenance))
        return UnreplaceableWorkflow(entry, provenance, misplaced)
    if entry.is_symlink():
        return UnreplaceableWorkflow(entry, provenance, ConflictError(_linked(entry, provenance)))
    try:
        changed = placed_hash(entry) != provenance.content_hash
    except InputError as unmeasured:
        return UnreplaceableWorkflow(entry, provenance, InputError(_unmeasured(entry, unmeasured)))
    declared = () if member is None else member.dependencies
    return ReplaceableWorkflow(entry, provenance, changed, declared)

def _ambiguous(name: str, spellings: Sequence[StandingEntry]) -> str:
    return (
        f"{name!r} is not the name of any entry as it is spelled, and {len(spellings)} entries "
        f"differ from it only in case: {', '.join(str(entry.path) for entry in spellings)}. AGL "
        f"will not choose which of them to check - ask for one by its name exactly as it is spelled"
    )

def _unlisted(
    name: str, entries: Sequence[StandingEntry], found: Mapping[Path, _Found], directory: Path
) -> str:
    declaring = [
        entry.path.name
        for entry in entries
        if entry.member is not None and name in entry.member.declared
    ]
    if declaring:
        return (
            f"nothing in {directory} is named {name!r}, which is a workflow declared in "
            f"{_quoted(declaring)}. `agl update` takes the name of the entry a declaration is "
            f"written in rather than the name it declares"
        )
    downloaded = [path.name for path, one in found.items() if one is not None]
    if not downloaded:
        return (
            f"nothing in {directory} is named {name!r}, and nothing there was placed by `agl get`, "
            f"which is all `agl update` checks"
        )
    return (
        f"nothing in {directory} is named {name!r}. What `agl get` placed there: "
        f"{_quoted(downloaded)}. `agl update` takes one of those - an entry's own name, which need "
        f"not be any name `agl run` takes"
    )

def _undownloaded(entry: Path) -> str:
    if not entry.is_dir():
        return (
            f"{entry} is not a directory, and `agl update` checks only a workflow's directory that "
            f"`agl get` placed"
        )
    return (
        f"{entry} holds no {PROVENANCE_FILE}, so nothing records a repository it came from: `agl "
        f"get` writes that file into each workflow it places, and a workflow written by hand or by "
        f"`agl new` has none. It is yours to change, and `agl update` leaves it as it is"
    )

def _misplaced(entry: Path, provenance: Provenance) -> str:
    placed_as = str(provenance.workflow.name)
    return (
        f"{entry} holds the provenance of {provenance.workflow}, which `agl get` placed as "
        f"{placed_as!r}, so it was renamed or copied since - and an update replaces a workflow "
        f"only under the name it was placed as, the one its package imports as. Nothing is "
        f"replaced: rename it back to {placed_as!r} to update it, or delete its {PROVENANCE_FILE} "
        f"to keep it as a workflow of your own, which `agl update` passes over"
    )

def _linked(entry: Path, provenance: Provenance) -> str:
    return (
        f"{entry} is a link, and an update replaces a workflow's own directory: the download "
        f"would stand in the link's place, and what the link names would silently stop being the "
        f"workflow `agl run` runs. Nothing is replaced - update what the link names yourself, or "
        f"`agl remove {entry.name}` and `agl get {provenance.workflow}` to put a download there"
    )

def _unmeasured(entry: Path, refused: InputError) -> str:
    return (
        f"{entry} cannot be measured against the hash its provenance records, so nothing tells "
        f"whether it changed since it was placed, and an update replaces nothing it cannot tell "
        f"that of: {refused}"
    )

def _quoted(names: Sequence[str]) -> str:
    return ", ".join(repr(name) for name in names)
