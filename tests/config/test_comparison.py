"""`config/comparison.py`: which workflows `agl get` placed, and whether each one's ref has moved.

Every case builds a workspace under `tmp_path` - workflow directories with the provenance file `agl
get` writes, and directories with none - and hands `compared` a `FakeFetcher` scripted with what
each repository's ref names now. The fake records every ref it was asked about, which is how the
questions are counted: GitHub allows an address nobody is signed in from sixty of them an hour.

**A download is a directory holding a provenance file**, and nothing else is this check's business.
A workflow written by hand or by `agl new` records no repository, so it is passed over in silence -
unless it is asked for by name, and then it is refused saying why. Dot-led entries, which are where
AGL stages what it places or removes, are never considered at all.

**One question per repository at a ref**, grouped the way `GetRequest.fetches` groups downloads -
owner and repository in any case, the ref exactly - and none for a ref that is a commit's full sha,
which names that commit for good. The ref asked is always the recorded one, never the commit a
workflow was placed from: asking at that commit would answer "unchanged" for ever.

**Every failure refuses what it touched and nothing else.** A provenance file that will not read
refuses its own workflow, and a ref that cannot be resolved refuses every workflow sharing it with
one refusal; every other workflow is still compared.

**What a later download will meet is kept intact rather than refused here.** A directory renamed
after it was placed is compared under the entry it stands in now, and one copied with its provenance
file is compared under each entry, with one question between them - the check reports where each
stands, and the provenance says what each was placed as.

**What an update may replace is decided next, before anything is downloaded.** `replacements`
refuses a moved copy standing under another name than it was placed as, one that is a link and one
that cannot be measured - each as a value, never raised - and measures the rest: the hash it stands
at, which says whether anything in it changed since it was placed and which placement holds it to as
it replaces it, and the dependencies it declares on disk, as written. Its downloads are one per
repository at a recorded ref, and its questions are `agl update`'s own.
"""

import os
from dataclasses import replace
from pathlib import Path
from typing import Final
import pytest
from agl.adapters.github.fake import FakeFetcher
from agl.config.comparison import (
    Comparison,
    DownloadedWorkflow,
    MovedWorkflow,
    ReplaceableWorkflow,
    Replacements,
    UncheckedWorkflow,
    compared,
    replacements,
)
from agl.config.inspection import PlaceableWorkflow
from agl.config.provenance import Provenance, placed_hash, read_provenance, rendered
from agl.config.questions import GainedDependencies, LocalChanges
from agl.config.registry import GROUP
from agl.ports.errors import ConflictError, InputError, NotFoundError, UpstreamUnavailable
from agl.ports.get_request import RepositoryAtRef, RequestedWorkflow
from agl.ports.home_layout import PROVENANCE_FILE, STAGING_PREFIX, AglHome, workflows_dir

pytestmark = pytest.mark.asyncio

_PLACED_FROM: Final = "0b496e91ec7ae4428c3ed2eeb4c3a40df431f2cc"
_NOW: Final = "f548e57e544e1ff5a4c46bf1e1b8685f8e4a348a"

_FLOWS: Final = RepositoryAtRef("octo", "flows", None)
_RELEASED: Final = RepositoryAtRef("octo", "flows", "release/1.0")
_OTHER: Final = RepositoryAtRef("octo", "other", "v2")

def _home(tmp_path: Path) -> AglHome:
    """An AGL_HOME nothing else can reach, built rather than resolved so no variable is read."""
    return AglHome(tmp_path / "home")

def _workflow(home: AglHome, directory: str) -> Path:
    """A workflow directory as `agl new` or a person writes one: a project file and a module."""
    entry = workflows_dir(home) / directory
    entry.mkdir(parents=True)
    (entry / "pyproject.toml").write_text(
        f'[project]\nname = "{directory}"\nversion = "0.1.0"\n\n'
        f'[project.entry-points."{GROUP}"]\n{directory} = "{directory}:{directory}"\n',
        encoding="utf-8",
    )
    (entry / "__init__.py").write_bytes(b"from agl.sdk import Run, workflow\n")
    return entry

def _placed(
    home: AglHome,
    directory: str,
    repository: RepositoryAtRef = _FLOWS,
    *,
    commit: str = _PLACED_FROM,
    path: str | None = None,
) -> Path:
    """A workflow directory as `agl get` leaves one: its files, and the provenance it wrote last."""
    entry = _workflow(home, directory)
    unspelled = RequestedWorkflow(repository, path or f"workflows/{directory}", "")
    workflow = replace(unspelled, spec=str(unspelled))
    provenance = Provenance(workflow, commit, placed_hash(entry))
    (entry / PROVENANCE_FILE).write_bytes(rendered(provenance))
    return entry

def _recorded(entry: Path) -> Provenance:
    """What the provenance in `entry` records, read the way the check reads it."""
    provenance = read_provenance(entry)
    assert provenance is not None, f"{entry} holds no provenance file"
    return provenance

def _serving(*repositories: RepositoryAtRef, commit: str = _PLACED_FROM) -> FakeFetcher:
    """A fetcher whose every repository's ref names `commit` now."""
    fetcher = FakeFetcher()
    for repository in repositories:
        fetcher.serves(repository, {}, commit=commit)
    return fetcher

# --- what moved, and what did not ---------------------------------------------------------------

async def test_workflows_whose_refs_still_name_the_commits_they_were_placed_from_are_current(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    triage = _placed(home, "triage")
    lint = _placed(home, "lint", _RELEASED)

    comparison = await compared(_serving(_FLOWS, _RELEASED), home, None)

    assert comparison == Comparison(
        current=(
            DownloadedWorkflow(lint, _recorded(lint)),
            DownloadedWorkflow(triage, _recorded(triage)),
        ),
        moved=(),
        refused=(),
    )

async def test_a_workflow_whose_ref_names_another_commit_now_has_moved_to_that_commit(
    tmp_path: Path,
) -> None:
    """Both commits carried: the one it was placed from in its provenance, the one now beside it."""
    home = _home(tmp_path)
    triage = _placed(home, "triage")
    lint = _placed(home, "lint", _RELEASED)
    fetcher = _serving(_RELEASED)
    fetcher.serves(_FLOWS, {}, commit=_NOW)

    comparison = await compared(fetcher, home, None)

    assert comparison.moved == (MovedWorkflow(triage, _recorded(triage), _NOW),)
    assert comparison.current == (DownloadedWorkflow(lint, _recorded(lint)),)
    assert comparison.refused == ()

# --- the questions asked ------------------------------------------------------------------------

async def test_one_question_is_asked_per_repository_and_ref_however_many_workflows_share_it(
    tmp_path: Path,
) -> None:
    """Four workflows, two refs: two questions, the owner and repository matched in any case.

    `beta` spells the repository as `Octo/Flows`, which GitHub answers to as `octo/flows`, so it
    shares `alpha`'s question - asked in `alpha`'s spelling, since it was listed first.
    """
    home = _home(tmp_path)
    _placed(home, "alpha")
    _placed(home, "beta", RepositoryAtRef("Octo", "Flows", None))
    _placed(home, "gamma")
    _placed(home, "delta", _RELEASED)
    fetcher = _serving(_FLOWS, _RELEASED)

    comparison = await compared(fetcher, home, None)

    assert fetcher.resolved == (_FLOWS, _RELEASED)
    assert len(comparison.current) == 4

async def test_two_refs_differing_only_in_case_are_two_questions_because_git_keeps_them_apart(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    _placed(home, "alpha", RepositoryAtRef("octo", "flows", "Release"))
    _placed(home, "beta", RepositoryAtRef("octo", "flows", "release"))
    fetcher = _serving(
        RepositoryAtRef("octo", "flows", "Release"), RepositoryAtRef("octo", "flows", "release")
    )

    await compared(fetcher, home, None)

    assert [repository.ref for repository in fetcher.resolved] == ["Release", "release"]

@pytest.mark.parametrize("length", [40, 64])
async def test_a_ref_that_is_a_full_sha_is_never_asked_about_because_it_cannot_move(
    tmp_path: Path, length: int
) -> None:
    """Placed from the sha it names, it is current with no question spent on it."""
    home = _home(tmp_path)
    sha = (_PLACED_FROM * 2)[:length]
    pinned = _placed(home, "pinned", RepositoryAtRef("octo", "flows", sha), commit=sha)
    fetcher = FakeFetcher()

    comparison = await compared(fetcher, home, None)

    assert fetcher.resolved == ()
    assert comparison.current == (DownloadedWorkflow(pinned, _recorded(pinned)),)

async def test_a_full_sha_ref_recording_some_other_commit_has_moved_to_the_sha_it_names(
    tmp_path: Path,
) -> None:
    """A provenance edited by hand to disagree with its own ref: the ref is what a download gets."""
    home = _home(tmp_path)
    pinned = _placed(home, "pinned", RepositoryAtRef("octo", "flows", _NOW))
    fetcher = FakeFetcher()

    comparison = await compared(fetcher, home, None)

    assert fetcher.resolved == ()
    assert comparison.moved == (MovedWorkflow(pinned, _recorded(pinned), _NOW),)

@pytest.mark.parametrize("ref", [_PLACED_FROM[:7], _PLACED_FROM.upper(), "main", "HEAD"])
async def test_an_abbreviated_or_respelled_sha_and_a_branch_are_asked_like_any_ref(
    tmp_path: Path, ref: str
) -> None:
    """Only the full sha in the form a commit is recorded in pins; GitHub resolves the rest."""
    home = _home(tmp_path)
    _placed(home, "triage", RepositoryAtRef("octo", "flows", ref))
    fetcher = _serving(RepositoryAtRef("octo", "flows", ref))

    await compared(fetcher, home, None)

    assert fetcher.resolved == (RepositoryAtRef("octo", "flows", ref),)

async def test_the_ref_asked_is_the_recorded_one_and_never_the_commit_it_was_placed_from(
    tmp_path: Path,
) -> None:
    """Asked at the commit, a branch would answer that commit whatever had landed on it since."""
    home = _home(tmp_path)
    _placed(home, "triage", _RELEASED)
    fetcher = _serving(_RELEASED, commit=_NOW)

    comparison = await compared(fetcher, home, None)

    assert fetcher.resolved == (_RELEASED,)
    assert [moved.commit for moved in comparison.moved] == [_NOW]
    assert fetcher.fetched == ()

# --- what is not a download ---------------------------------------------------------------------

async def test_nothing_that_is_not_a_download_is_compared_asked_about_or_mentioned(
    tmp_path: Path,
) -> None:
    """Hand-written, scaffolded, a plain file, a dangling link, and a dot-led staging leftover.

    The last holds a provenance file of its own - a crash can leave one in a staging directory - and
    is still never read, since nothing dot-led is a workflow anything reads.
    """
    home = _home(tmp_path)
    _workflow(home, "hand_written")
    (workflows_dir(home) / "notes.md").write_bytes(b"not a workflow\n")
    (workflows_dir(home) / "gone").symlink_to(tmp_path / "nowhere", target_is_directory=True)
    staged = workflows_dir(home) / f"{STAGING_PREFIX}1t3p5p_r"
    staged.mkdir()
    (staged / PROVENANCE_FILE).write_bytes(b"{not even json")
    fetcher = FakeFetcher()

    comparison = await compared(fetcher, home, None)

    assert comparison == Comparison((), (), ())
    assert fetcher.resolved == ()

async def test_a_workspace_with_no_workflows_directory_yet_holds_nothing_to_compare(
    tmp_path: Path,
) -> None:
    assert await compared(FakeFetcher(), _home(tmp_path), None) == Comparison((), (), ())

async def test_a_link_to_a_placed_workflow_is_compared_through_the_link_it_stands_as(
    tmp_path: Path,
) -> None:
    """The entry is the link, which is what a later download would replace, and never its target."""
    home = _home(tmp_path)
    target = _placed(AglHome(tmp_path / "elsewhere"), "triage")
    link = workflows_dir(home) / "triage"
    workflows_dir(home).mkdir(parents=True)
    link.symlink_to(target, target_is_directory=True)

    comparison = await compared(_serving(_FLOWS), home, None)

    assert [one.entry for one in comparison.current] == [link]

# --- every failure refuses what it touched and nothing else -------------------------------------

async def test_a_provenance_file_that_will_not_read_refuses_its_workflow_and_spares_the_rest(
    tmp_path: Path,
) -> None:
    """Refused as the reader refuses it, naming the file, and no question asked on its behalf."""
    home = _home(tmp_path)
    broken = _placed(home, "broken")
    (broken / PROVENANCE_FILE).write_bytes(b'{"owner": "octo"}\n')
    triage = _placed(home, "triage", _RELEASED)
    fetcher = _serving(_RELEASED)

    comparison = await compared(fetcher, home, None)

    (refused,) = comparison.refused
    assert (refused.entry, refused.provenance) == (broken, None)
    assert isinstance(refused.refusal, InputError)
    assert str(broken / PROVENANCE_FILE) in str(refused.refusal)
    assert comparison.current == (DownloadedWorkflow(triage, _recorded(triage)),)
    assert fetcher.resolved == (_RELEASED,)

async def test_a_ref_that_cannot_be_resolved_refuses_every_workflow_sharing_it_with_one_refusal(
    tmp_path: Path,
) -> None:
    """The very error the fetcher answered with, for each of them, and the other ref still asked."""
    home = _home(tmp_path)
    alpha = _placed(home, "alpha")
    beta = _placed(home, "beta")
    other = _placed(home, "other", _OTHER)
    throttled = UpstreamUnavailable("the commits endpoint is limiting this address, as scripted")
    fetcher = _serving(_OTHER)
    fetcher.refuses(_FLOWS, throttled)

    comparison = await compared(fetcher, home, None)

    assert comparison.refused == (
        UncheckedWorkflow(alpha, _recorded(alpha), throttled),
        UncheckedWorkflow(beta, _recorded(beta), throttled),
    )
    assert comparison.current == (DownloadedWorkflow(other, _recorded(other)),)
    assert comparison.refused[0].refusal is comparison.refused[1].refusal

# --- what a later download will meet, kept intact -----------------------------------------------

async def test_a_workflow_renamed_after_it_was_placed_is_compared_under_the_entry_it_stands_in(
    tmp_path: Path,
) -> None:
    """`triage_old` records `workflows/triage`: the entry is where it is, the record what it was."""
    home = _home(tmp_path)
    renamed = _placed(home, "triage_old", path="workflows/triage")

    comparison = await compared(_serving(_FLOWS, commit=_NOW), home, None)

    (moved,) = comparison.moved
    assert moved.entry == renamed
    assert str(moved.provenance.workflow.name) == "triage"

async def test_a_workflow_copied_with_its_provenance_is_compared_under_each_entry_with_one_question(
    tmp_path: Path,
) -> None:
    """Two records naming one workflow: neither refuses the other, and one question answers both."""
    home = _home(tmp_path)
    original = _placed(home, "triage")
    copy = _placed(home, "triage_copy", path="workflows/triage")
    fetcher = _serving(_FLOWS)

    comparison = await compared(fetcher, home, None)

    assert [one.entry for one in comparison.current] == [original, copy]
    assert fetcher.resolved == (_FLOWS,)

# --- one workflow, by name ----------------------------------------------------------------------

async def test_a_name_compares_that_entry_alone_and_asks_nothing_about_the_others(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    _placed(home, "triage")
    lint = _placed(home, "lint", _RELEASED)
    fetcher = _serving(_FLOWS, _RELEASED, commit=_NOW)

    comparison = await compared(fetcher, home, "lint")

    assert comparison == Comparison((), (MovedWorkflow(lint, _recorded(lint), _NOW),), ())
    assert fetcher.resolved == (_RELEASED,)

@pytest.mark.parametrize("spelled", ["Triage", "TRIAGE"])
async def test_a_name_matched_only_by_its_case_reaches_the_entry_as_it_is_spelled_on_disk(
    tmp_path: Path, spelled: str
) -> None:
    home = _home(tmp_path)
    standing = _placed(home, spelled, path="workflows/triage")

    comparison = await compared(_serving(_FLOWS), home, "triage")

    assert [one.entry for one in comparison.current] == [standing]

async def test_entries_differing_from_the_name_only_in_case_refuse_it_rather_than_choosing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two spellings side by side, as a case-sensitive volume holds them, and a third typed."""
    home = _home(tmp_path)
    first = _placed(home, "Triage", path="workflows/triage")
    container = workflows_dir(home)
    second = container / "TRIAGE"
    if second.exists():
        listing = Path.iterdir
        monkeypatch.setattr(
            Path,
            "iterdir",
            lambda path: iter([second, first]) if path == container else listing(path),
        )
    else:
        _placed(home, "TRIAGE", path="workflows/triage")
    fetcher = _serving(_FLOWS)

    with pytest.raises(ConflictError) as refused:
        await compared(fetcher, home, "triage")

    assert "Triage" in str(refused.value) and "TRIAGE" in str(refused.value)
    assert fetcher.resolved == ()

async def test_a_name_nothing_holds_is_not_found_naming_what_agl_get_placed_there(
    tmp_path: Path,
) -> None:
    """The workflows this command takes, and not the hand-written one beside them."""
    home = _home(tmp_path)
    _placed(home, "triage")
    _workflow(home, "hand_written")

    with pytest.raises(NotFoundError) as refused:
        await compared(FakeFetcher(), home, "lint")

    said = str(refused.value)
    assert "What `agl get` placed there: 'triage'." in said
    assert "hand_written" not in said

async def test_a_name_that_only_a_declaration_uses_is_not_found_naming_the_entry(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    triage = _placed(home, "triage_dir")
    (triage / "pyproject.toml").write_text(
        f'[project]\nname = "triage_dir"\nversion = "0.1.0"\n\n'
        f'[project.entry-points."{GROUP}"]\nsort-issues = "triage_dir:sort"\n',
        encoding="utf-8",
    )

    with pytest.raises(NotFoundError) as refused:
        await compared(FakeFetcher(), home, "sort-issues")

    assert "a workflow declared in 'triage_dir'" in str(refused.value)

async def test_a_name_in_a_workspace_nothing_was_downloaded_into_says_so(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _workflow(home, "hand_written")

    with pytest.raises(NotFoundError) as refused:
        await compared(FakeFetcher(), home, "triage")

    assert "nothing there was placed by `agl get`" in str(refused.value)

async def test_a_named_workflow_agl_get_never_placed_is_not_found_saying_why(
    tmp_path: Path,
) -> None:
    """Exit 3, before any question: nothing records a repository to ask about."""
    home = _home(tmp_path)
    hand_written = _workflow(home, "hand_written")
    fetcher = FakeFetcher()

    with pytest.raises(NotFoundError) as refused:
        await compared(fetcher, home, "hand_written")

    said = str(refused.value)
    assert said.startswith(f"{hand_written} holds no {PROVENANCE_FILE}")
    assert "`agl new`" in said
    assert fetcher.resolved == ()

async def test_a_named_entry_that_is_a_plain_file_is_not_found_as_no_workflow_directory(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    workflows_dir(home).mkdir(parents=True)
    (workflows_dir(home) / "notes").write_bytes(b"not a workflow\n")

    with pytest.raises(NotFoundError) as refused:
        await compared(FakeFetcher(), home, "notes")

    assert "is not a directory" in str(refused.value)

async def test_a_named_workflow_whose_provenance_will_not_read_is_refused_and_not_raised(
    tmp_path: Path,
) -> None:
    """One workflow checked is the whole check over one workflow: its refusal is an answer."""
    home = _home(tmp_path)
    broken = _placed(home, "broken")
    (broken / PROVENANCE_FILE).write_bytes(b"not json\n")

    comparison = await compared(FakeFetcher(), home, "broken")

    assert [(one.entry, type(one.refusal)) for one in comparison.refused] == [(broken, InputError)]

async def test_a_dot_led_name_is_never_reached_even_where_it_holds_a_provenance_file(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    _placed(home, "triage")
    staged = workflows_dir(home) / f"{STAGING_PREFIX}1t3p5p_r"
    staged.mkdir()
    (staged / PROVENANCE_FILE).write_bytes((_placed(home, "other") / PROVENANCE_FILE).read_bytes())
    fetcher = _serving(_FLOWS)

    with pytest.raises(NotFoundError):
        await compared(fetcher, home, staged.name)

    assert fetcher.resolved == ()

# --- what an update may replace, measured before anything is asked ------------------------------

async def _moved(home: AglHome) -> tuple[MovedWorkflow, ...]:
    """Every workflow in `home` whose ref names `_NOW`, as the check hands them on."""
    comparison = await compared(_serving(_FLOWS, _RELEASED, commit=_NOW), home, None)
    return comparison.moved

async def test_a_moved_copy_standing_as_it_was_placed_is_replaceable_and_measured_unchanged(
    tmp_path: Path,
) -> None:
    """Its dependencies are read off its project file as written, for the question about gains."""
    home = _home(tmp_path)
    entry = _placed(home, "triage")
    project = entry / "pyproject.toml"
    declaring = 'version = "0.1.0"\ndependencies = ["httpx>=0.27", "rich"]\n'
    project.write_text(
        project.read_text(encoding="utf-8").replace('version = "0.1.0"\n', declaring),
        encoding="utf-8",
    )
    (entry / PROVENANCE_FILE).write_bytes(
        rendered(replace(_recorded(entry), content_hash=placed_hash(entry)))
    )

    replacing = replacements(home, await _moved(home))

    measured = placed_hash(entry)
    assert replacing == Replacements(
        (ReplaceableWorkflow(entry, _recorded(entry), measured, ("httpx>=0.27", "rich")),), ()
    )
    assert not replacing.replaceable[0].changed

async def test_a_moved_copy_with_anything_in_it_changed_since_it_was_placed_measures_changed(
    tmp_path: Path,
) -> None:
    """A file added is a change as much as a line edited: the hash is over names and bytes alike."""
    home = _home(tmp_path)
    edited = _placed(home, "edited")
    (edited / "__init__.py").write_bytes(b"# the operator's own\n")
    added = _placed(home, "added")
    (added / "notes.md").write_bytes(b"# notes\n")

    replacing = replacements(home, await _moved(home))

    assert [(one.entry.name, one.changed) for one in replacing.replaceable] == [
        ("added", True),
        ("edited", True),
    ]

async def test_a_changed_copy_keeps_the_hash_it_measured_and_not_merely_that_it_changed(
    tmp_path: Path,
) -> None:
    """The hash of the copy as the operator left it, which is what the question put about it covers.

    Placement measures the copy again against this as it replaces it, so an edit saved while that
    question was on screen is one the answer never covered - which a bare "changed" cannot tell.
    """
    home = _home(tmp_path)
    entry = _placed(home, "triage")
    (entry / "__init__.py").write_bytes(b"# the operator's own\n")
    edited = placed_hash(entry)

    (one,) = replacements(home, await _moved(home)).replaceable

    assert one.measured == edited
    assert one.measured != one.provenance.content_hash
    assert one.changed

async def test_what_each_copy_measured_is_handed_on_under_the_workflow_downloaded_for_it(
    tmp_path: Path,
) -> None:
    """One entry per replaceable copy, changed or not, under the workflow its download asks for."""
    home = _home(tmp_path)
    triage = _placed(home, "triage")
    lint = _placed(home, "lint", _RELEASED)
    (lint / "notes.md").write_bytes(b"# notes\n")

    replacing = replacements(home, await _moved(home))

    assert replacing.measured == {
        _recorded(lint).workflow: placed_hash(lint),
        _recorded(triage).workflow: placed_hash(triage),
    }

async def test_a_moved_copy_under_another_name_than_it_was_placed_as_is_a_conflict(
    tmp_path: Path,
) -> None:
    """Renamed or copied since: refused naming the name it was placed as, and never measured."""
    home = _home(tmp_path)
    renamed = _placed(home, "triage_old", path="workflows/triage")

    replacing = replacements(home, await _moved(home))

    assert replacing.replaceable == ()
    (refused,) = replacing.unreplaceable
    assert (refused.entry, refused.provenance) == (renamed, _recorded(renamed))
    assert isinstance(refused.refusal, ConflictError)
    assert "which `agl get` placed as 'triage'" in str(refused.refusal)
    assert "rename it back to 'triage'" in str(refused.refusal)

async def test_a_moved_copy_spelled_in_another_case_than_it_was_placed_as_is_replaceable(
    tmp_path: Path,
) -> None:
    """The name folded as a case-insensitive volume folds it, which is how it was matched."""
    home = _home(tmp_path)
    entry = _placed(home, "Triage", path="workflows/triage")

    replacing = replacements(home, await _moved(home))

    assert [one.entry for one in replacing.replaceable] == [entry]

async def test_a_moved_copy_that_is_a_link_is_a_conflict_saying_how_to_put_a_download_there(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path)
    target = _placed(AglHome(tmp_path / "elsewhere"), "triage")
    workflows_dir(home).mkdir(parents=True)
    link = workflows_dir(home) / "triage"
    link.symlink_to(target, target_is_directory=True)

    replacing = replacements(home, await _moved(home))

    (refused,) = replacing.unreplaceable
    assert refused.entry == link
    assert isinstance(refused.refusal, ConflictError)
    assert "`agl remove triage` and `agl get octo/flows/workflows/triage`" in str(refused.refusal)

async def test_a_moved_copy_that_cannot_be_measured_is_refused_as_what_cannot_be_read(
    tmp_path: Path,
) -> None:
    """A directory in it that cannot be listed: whether it changed cannot be told either way."""
    home = _home(tmp_path)
    entry = _placed(home, "triage")
    closed = entry / "prompts"
    closed.mkdir()
    closed.chmod(0)
    try:
        if os.access(closed, os.R_OK):
            pytest.skip("this user lists a directory whatever its mode says, as root does")
        replacing = replacements(home, await _moved(home))
    finally:
        closed.chmod(0o755)

    (refused,) = replacing.unreplaceable
    assert isinstance(refused.refusal, InputError)
    assert str(refused.refusal).startswith(f"{entry} cannot be measured against the hash")
    assert f"{closed} cannot be listed" in str(refused.refusal)

async def test_a_moved_copy_whose_project_file_will_not_read_declares_no_dependency(
    tmp_path: Path,
) -> None:
    """Nothing it declares can be read, so every dependency the update declares is one it gains."""
    home = _home(tmp_path)
    entry = _placed(home, "triage")
    (entry / "pyproject.toml").write_bytes(b"[project\n")

    replacing = replacements(home, await _moved(home))

    assert [(one.changed, one.declared) for one in replacing.replaceable] == [(True, ())]

def _replaceable(
    name: str,
    repository: RepositoryAtRef = _FLOWS,
    *,
    changed: bool = False,
    declared: tuple[str, ...] = (),
) -> ReplaceableWorkflow:
    """A copy measured as `replacements` measures one, built rather than read off a disk."""
    unspelled = RequestedWorkflow(repository, f"workflows/{name}", "")
    workflow = replace(unspelled, spec=str(unspelled))
    provenance = Provenance(workflow, _PLACED_FROM, "0" * 64)
    measured = ("1" if changed else "0") * 64
    return ReplaceableWorkflow(Path("/nowhere") / name, provenance, measured, declared)

async def test_the_downloads_are_one_per_repository_at_a_recorded_ref_each_workflow_asked_once(
    tmp_path: Path,
) -> None:
    """Two copies of one workflow, differing in case where a volume keeps both, ask for it once.

    Asked at each ref as recorded, a `None` ref included, and never at a commit.
    """
    twice = _replaceable("triage")
    replacing = Replacements(
        (twice, replace(twice, entry=Path("/nowhere/Triage")), _replaceable("lint", _RELEASED)),
        (),
    )

    assert [(fetch.repository, fetch.workflows) for fetch in replacing.fetches] == [
        (_FLOWS, (twice.provenance.workflow,)),
        (_RELEASED, (_replaceable("lint", _RELEASED).provenance.workflow,)),
    ]

async def test_an_update_asks_about_changes_first_and_then_what_its_copy_does_not_declare(
    tmp_path: Path,
) -> None:
    """A dependency is compared as written: a changed bound is asked about, an unchanged one not."""
    standing = _replaceable("triage", changed=True, declared=("httpx>=0.27", "rich"))
    placeable = PlaceableWorkflow(
        standing.provenance.workflow, _NOW, {}, ("httpx>=0.28", "rich", "pydantic"), standing.entry
    )

    asked = Replacements((standing,), ()).questions(placeable)

    assert asked == (
        LocalChanges(standing.entry, _PLACED_FROM, _NOW),
        GainedDependencies(
            standing.provenance.workflow, _NOW, standing.entry, ("httpx>=0.28", "pydantic")
        ),
    )

async def test_an_unchanged_copy_gaining_nothing_is_asked_no_question_at_all(
    tmp_path: Path,
) -> None:
    standing = _replaceable("triage", declared=("rich",))
    placeable = PlaceableWorkflow(standing.provenance.workflow, _NOW, {}, ("rich",), standing.entry)

    assert Replacements((standing,), ()).questions(placeable) == ()
