"""What `agl get` reads off its command line, and the one reading the rest of AGL works from.

Three guarantees here are ones later code leans on and nothing downstream checks again. Every
owner, repository and ref accepted goes into a download address as one path segment and unencoded,
which is asked of `urllib.parse.quote` over the corpus `_corpus.py` builds rather than of a list.
The last segment of a path is held to `WorkflowName` and to no rule of this module's own: over the
same corpus, a directory's name is refused exactly where `agl new` would refuse it as a name, and
with that type's own message. And no two workflows one command asks for can land in one workspace
directory, compared through `collision_key` because a macOS volume folds case.

Two decisions are pinned as behaviour, so that changing either fails here rather than passing
review. A ref holding `/` cannot be written - `release/1.2` is a legal git ref, and the first `/`
after the `@` ends it here, the rest being read as the path. And requests are grouped into fetches
with the owner and the repository matched in any case, because GitHub answers to every spelling of
both, while two refs that differ only in case stay two fetches, because git keeps them apart.

The shape a refusal names is written out below rather than imported from the module, so that the
test states the grammar instead of echoing it.
"""

import urllib.parse
from dataclasses import FrozenInstanceError, replace
from typing import Final
import pytest
from _corpus import CORPUS, imported_modules, impurities
from agl.ports import get_request
from agl.ports.errors import InputError, InternalError
from agl.ports.get_request import Fetch, GetRequest, RepositoryAtRef, RequestedWorkflow
from agl.ports.ids import WorkflowName

_SHAPE: Final = "owner/repo[@ref]/path/to/workflow[,sibling...]"

_BRIEF: Final = "jashioq/myrepo/workflows/mine/implement_and_review"

_SHA: Final = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"

def _refusal(specs: list[str]) -> str:
    """The message one refused request carries, asserted to be a refusal of the caller's input."""
    with pytest.raises(InputError) as caught:
        GetRequest.parsed(specs)
    return str(caught.value)

# --- Reading an argument ------------------------------------------------------------------------

def test_one_argument_reads_as_an_owner_a_repository_a_directory_and_a_name() -> None:
    """The first form the command takes, every field spelled out rather than recomposed."""
    (workflow,) = GetRequest.parsed([_BRIEF]).workflows
    assert workflow.repository == RepositoryAtRef("jashioq", "myrepo", None)
    assert workflow.directory == "workflows/mine/implement_and_review"
    assert workflow.name == WorkflowName("implement_and_review")
    assert workflow.spec == _BRIEF

def test_a_ref_written_after_the_repository_is_kept_exactly_as_it_was_written() -> None:
    """Not resolved and not normalised: what a ref names is the far side's to say."""
    (workflow,) = GetRequest.parsed(["jashioq/myrepo@v1.2.0/workflows/mine/a"]).workflows
    assert workflow.repository == RepositoryAtRef("jashioq", "myrepo", "v1.2.0")
    assert workflow.directory == "workflows/mine/a"

def test_no_ref_is_held_as_none_while_a_written_head_stays_a_ref() -> None:
    """None is the default branch, whatever it is called when the fetch happens.

    `@HEAD` names the same commit today and is still kept as what was written: a request is
    recorded as asked, and two spellings of one request are two fetches rather than a guess.
    """
    default, head = GetRequest.parsed(["o/r/wf/a", "o/r@HEAD/wf/b"]).fetches
    assert default.repository.ref is None
    assert head.repository.ref == "HEAD"
    assert (str(default.repository), str(head.repository)) == ("o/r", "o/r@HEAD")

def test_a_comma_list_asks_for_siblings_that_share_every_directory_above_them() -> None:
    request = GetRequest.parsed(["jashioq/myrepo/workflows/mine/a,b,c"])
    assert [one.directory for one in request.workflows] == [
        "workflows/mine/a", "workflows/mine/b", "workflows/mine/c",
    ]  # fmt: skip
    assert [str(one.name) for one in request.workflows] == ["a", "b", "c"]
    assert {one.spec for one in request.workflows} == {"jashioq/myrepo/workflows/mine/a,b,c"}
    assert {one.repository for one in request.workflows} == {
        RepositoryAtRef("jashioq", "myrepo", None)
    }

def test_a_workflow_directory_at_the_repository_root_needs_no_path_above_it() -> None:
    request = GetRequest.parsed(["o/r/a", "o/r@v1/b,c"])
    assert [one.directory for one in request.workflows] == ["a", "b", "c"]

def test_a_comma_above_the_last_segment_is_part_of_a_directory_name() -> None:
    """Only the last segment is a list, so a comma further up is a character like any other."""
    (workflow,) = GetRequest.parsed(["o/r/x,y/a"]).workflows
    assert workflow.directory == "x,y/a"

def test_directories_above_the_workflow_need_not_be_names_a_workflow_could_take() -> None:
    """They are directories in somebody else's repository, and only the last one is placed."""
    (workflow,) = GetRequest.parsed(["o/r/My Workflows/v1.0/caf\xe9/-x/@y/a"]).workflows
    assert workflow.directory == "My Workflows/v1.0/caf\xe9/-x/@y/a"

def test_several_arguments_are_read_in_the_order_written_and_each_keeps_its_own_text() -> None:
    """Several arguments are what shell brace expansion hands over, so order is the operator's."""
    request = GetRequest.parsed(["o/r/x/a", "p/s@v2/y/b,c", "o/r/z/d"])
    assert [str(one.name) for one in request.workflows] == ["a", "b", "c", "d"]
    assert [one.spec for one in request.workflows] == [
        "o/r/x/a", "p/s@v2/y/b,c", "p/s@v2/y/b,c", "o/r/z/d",
    ]  # fmt: skip

def test_the_first_slash_after_the_at_sign_ends_the_ref_and_starts_the_path() -> None:
    """`release/1.2` is a legal git ref, and this grammar reads it as the ref `release` and a path.

    Pinned as behaviour and not refused, because nothing here can tell a slashed ref from a ref
    followed by a directory. What such a request meets instead is a ref or a directory the
    download does not find, and the fetch is where that has to be said.
    """
    (workflow,) = GetRequest.parsed(["o/r@release/1.2/wf/a"]).workflows
    assert workflow.repository.ref == "release"
    assert workflow.directory == "1.2/wf/a"

@pytest.mark.parametrize(
    "spec", ["o/.github/a", "my-org/repo.name/a", "o_o/r_r@v1.0-rc_1/a", f"O/R@{_SHA}/a"]
)
def test_every_owner_repository_and_ref_github_hands_out_is_accepted(spec: str) -> None:
    """`.github` is a repository GitHub gives special meaning to, so a leading `.` stays legal."""
    (workflow,) = GetRequest.parsed([spec]).workflows
    assert str(workflow) == spec

@pytest.mark.parametrize("spec", [_BRIEF, "jashioq/myrepo@v1.2.0/wf/a,b,c", "O/R@x/y,z/w"])
def test_each_workflow_spells_itself_back_as_an_argument_that_reads_the_same(spec: str) -> None:
    """`str` is the one place the grammar is written the other way, so each checks the other."""
    for workflow in GetRequest.parsed([spec]).workflows:
        (again,) = GetRequest.parsed([str(workflow)]).workflows
        assert again == replace(workflow, spec=str(workflow))

# --- Refusals -----------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("spec", "problem"),
    [
        ("", "is empty"), ("/o/r/a", "starts with '/'"), ("o/r/a/", "ends with '/'"),
        ("o//r/a", "holds '//'"), ("o/r//a", "holds '//'"),
        ("jashioq", "names an owner and no repository"),
        ("jashioq/myrepo", "names a repository and no directory inside it"),
        ("jashioq/myrepo@v1.2.0", "names a repository and no directory inside it"),
        ("o/r@/wf/a", "'@' with no ref after it"), ("o/@/wf/a", "'@' with no ref after it"),
        ("o/r/wf/a,,b", "empty entry in its comma list 'a,,b'"),
        ("o/r/wf/a,", "empty entry in its comma list 'a,'"),
        ("o/r/wf/,a", "empty entry in its comma list ',a'"), ("o/r/,", "empty entry"),
    ],
)  # fmt: skip
def test_a_malformed_argument_is_refused_naming_itself_the_problem_and_the_expected_shape(
    spec: str, problem: str
) -> None:
    message = _refusal([spec])
    assert message.startswith(repr(spec)), message
    assert problem in message, message
    assert message.endswith(f"expected {_SHAPE}"), message

@pytest.mark.parametrize(
    ("spec", "part", "problem"),
    [
        ("a b/r/x", "owner 'a b'", "' ' at position 1"), ("o@v1/r/a", "owner 'o@v1'", "'@'"),
        ("./r/a", "owner '.'", "path traversal"), ("o/../a", "repository '..'", "path traversal"),
        ("o/@v1/wf/a", "repository ''", "empty"), ("o/r?x/a", "repository 'r?x'", "'?'"),
        ("o/r#x/a", "repository 'r#x'", "'#'"), ("o/r%2e/a", "repository 'r%2e'", "'%'"),
        ("o/caf\xe9/a", "repository 'caf\xe9'", "'\xe9'"), ("o/r@v1+b/a", "ref 'v1+b'", "'+'"),
        ("o/r@v1@x/a", "ref 'v1@x'", "'@'"), ("o/r@../a", "ref '..'", "path traversal"),
    ],
)  # fmt: skip
def test_an_unusable_owner_repository_or_ref_is_refused_naming_the_part_and_its_problem(
    spec: str, part: str, problem: str
) -> None:
    message = _refusal([spec])
    assert message.startswith(f"in {spec!r}, {part} cannot be used: "), message
    assert problem in message, message

@pytest.mark.parametrize(
    ("spec", "segment", "problem"),
    [
        ("o/r/../a", "'..'", "path traversal"), ("o/r/x/./a", "'.'", "path traversal"),
        ("o/r/x\\y/a", "'x\\\\y'", "separator on Windows"), ("o/r/x\ty/a", "'x\\ty'", "control"),
        ("o/r/x\x00/a", "'x\\x00'", "control"), ("o/r/\u200b/a", "'\\u200b'", "invisible"),
        (f"o/r/x{chr(0xDC80)}/a", "'x\\udc80'", "invisible"),
    ],
)  # fmt: skip
def test_an_unusable_directory_above_the_workflow_is_refused_naming_its_segment(
    spec: str, segment: str, problem: str
) -> None:
    """A surrogate is what `surrogateescape` makes of bytes on argv that are not UTF-8."""
    message = _refusal([spec])
    assert message.startswith(f"in {spec!r}, directory "), message
    assert f"its segment {segment}" in message and problem in message, message

@pytest.mark.parametrize(
    ("spec", "refused"),
    [("o/r/wf/class", "class"), ("o/r/wf/con", "con"), ("o/r/wf/my-flow", "my-flow"),
     ("o/r/wf/2fast", "2fast"), ("o/r/wf/a,Nul", "Nul")],
)  # fmt: skip
def test_a_directory_name_workflow_name_refuses_is_refused_with_that_types_own_message(
    spec: str, refused: str
) -> None:
    """`agl new` validates with `WorkflowName`, and a downloaded directory is placed by its name.

    A comma is not among these, and cannot be: every comma in the last segment is read as a
    separator, so none ever reaches `WorkflowName`, which would refuse it.
    """
    with pytest.raises(InputError) as expected:
        WorkflowName(refused)
    message = _refusal([spec])
    assert message.startswith(f"in {spec!r}, directory "), message
    assert str(expected.value) in message, message

def test_the_last_segment_is_held_to_workflow_name_and_to_no_rule_of_this_module() -> None:
    """Over the whole corpus: refused exactly where `WorkflowName` refuses, and in its words.

    A second validator would show up here as a value one of the two refuses and the other takes.
    `/` and `,` are left out because the grammar spends them, and the empty string because the
    grammar refuses it before any name is read.
    """
    candidates = [value for value in CORPUS if value and "/" not in value and "," not in value]
    refused = 0
    for value in candidates:
        spec = f"o/r/wf/{value}"
        try:
            name = WorkflowName(value)
        except InputError as expected:
            refused += 1
            assert str(expected) in _refusal([spec]), value
        else:
            (workflow,) = GetRequest.parsed([spec]).workflows
            assert workflow.name == name, value
    assert 1000 < refused < len(candidates) - 100, f"{refused} of {len(candidates)} refused"

def test_every_owner_repository_and_ref_accepted_goes_into_an_address_unencoded() -> None:
    """One path segment that nothing resolves: no character `quote` would touch, and no `.`/`..`.

    That is what lets a download address be written by formatting these three into it.
    """
    accepted = 0
    for value in CORPUS:
        try:
            RepositoryAtRef(value, value, value)
        except InputError:
            continue
        accepted += 1
        assert urllib.parse.quote(value, safe="") == value, value
        assert value not in {".", ".."}, value
    assert 300 < accepted < len(CORPUS) - 1000, f"{accepted} of {len(CORPUS)} accepted"

@pytest.mark.parametrize(
    ("specs", "problem"),
    [
        (["o/r/wf/a,b,a"], "'o/r/wf/a' is asked for twice"),
        (["o/r/wf/a", "o/r/wf/a"], "'o/r/wf/a' is asked for twice"),
        (["o/r/x/a", "p/s/y/a"], "'o/r/x/a' and 'p/s/y/a' are both workflow 'a'"),
        (["O/R/wf/a", "o/r/wf/a"], "'O/R/wf/a' and 'o/r/wf/a' are both workflow 'a'"),
        (["o/r/wf/a,A"], "'o/r/wf/a' and 'o/r/wf/A' are workflows 'a' and 'A'"),
        (["o/r/x/Triage", "p/s@v1/y/triage"], "differ only in case"),
    ],
)  # fmt: skip
def test_two_workflows_that_would_share_one_workspace_directory_refuse_the_whole_request(
    specs: list[str], problem: str
) -> None:
    """Refused as a request, so the answer arrives before anything can have been fetched."""
    assert problem in _refusal(specs)

def test_a_request_for_no_workflow_at_all_is_refused_rather_than_doing_nothing() -> None:
    assert _refusal([]) == f"no workflow was asked for - expected at least one {_SHAPE}"

def test_one_string_handed_over_where_a_sequence_belongs_is_refused_as_agls_own_bug() -> None:
    """A `str` is a `Sequence[str]` to `mypy`, and each character would be read as an argument."""
    with pytest.raises(InternalError, match="one string"):
        GetRequest.parsed(_BRIEF)

# --- Fetches ------------------------------------------------------------------------------------

def test_four_workflows_from_one_repository_at_one_ref_are_one_fetch_and_not_four() -> None:
    """One tarball per repository, however the arguments that asked for it were split up."""
    (fetch,) = GetRequest.parsed(["o/r@v1/wf/a,b", "o/r@v1/other/c", "o/r@v1/d"]).fetches
    assert fetch.repository == RepositoryAtRef("o", "r", "v1")
    assert [one.directory for one in fetch.workflows] == ["wf/a", "wf/b", "other/c", "d"]

def test_each_repository_and_each_of_its_refs_is_a_fetch_of_its_own() -> None:
    """In the order each was first asked for, which is the order the downloads are reported in."""
    fetches = GetRequest.parsed(["o/r/wf/a", "o/r@v1/wf/b", "p/r/wf/c", "o/r/wf/d"]).fetches
    assert [str(one.repository) for one in fetches] == ["o/r", "o/r@v1", "p/r"]
    assert [[str(w.name) for w in one.workflows] for one in fetches] == [["a", "d"], ["b"], ["c"]]

def test_an_owner_and_repository_spelled_in_another_case_join_the_first_spellings_fetch() -> None:
    """One fetch, under the spelling asked for first; each workflow keeps the one it came with."""
    (fetch,) = GetRequest.parsed(["Jashioq/MyRepo/wf/a", "jashioq/myrepo/wf/b"]).fetches
    assert str(fetch.repository) == "Jashioq/MyRepo"
    assert [str(one.repository) for one in fetch.workflows] == ["Jashioq/MyRepo", "jashioq/myrepo"]

def test_two_refs_differing_only_in_case_stay_two_fetches_because_git_keeps_them_apart() -> None:
    fetches = GetRequest.parsed(["o/r@Main/wf/a", "o/r@main/wf/b"]).fetches
    assert [str(one.repository) for one in fetches] == ["o/r@Main", "o/r@main"]

def test_a_fetch_refuses_to_hold_a_workflow_from_any_repository_but_its_own() -> None:
    """Extracting a directory out of the wrong download finds the wrong files, or none at all."""
    (workflow,) = GetRequest.parsed(["o/r/wf/a"]).workflows
    assert Fetch(RepositoryAtRef("O", "R", None), (workflow,)).workflows == (workflow,)
    with pytest.raises(InternalError, match="does not hold"):
        Fetch(RepositoryAtRef("o", "r", "v1"), (workflow,))
    with pytest.raises(InternalError, match="no workflow at all"):
        Fetch(RepositoryAtRef("o", "r", None), ())

# --- The types themselves -----------------------------------------------------------------------

def test_the_types_refuse_bad_values_themselves_and_not_only_through_the_parser() -> None:
    """A request may be rebuilt from a record on disk as well as read off a command line."""
    with pytest.raises(InputError, match="owner '..' cannot be used"):
        RepositoryAtRef("..", "r", None)
    with pytest.raises(InputError, match="ref '' cannot be used: it is empty"):
        RepositoryAtRef("o", "r", "")
    repository = RepositoryAtRef("o", "r", None)
    with pytest.raises(InputError, match="empty segment"):
        RequestedWorkflow(repository, "/wf/a", "spec")
    with pytest.raises(InputError, match="workflow name '' cannot be used"):
        RequestedWorkflow(repository, "wf/", "spec")
    twice = (RequestedWorkflow(repository, "a", "x"), RequestedWorkflow(repository, "b/A", "y"))
    with pytest.raises(InputError, match="differ only in case"):
        GetRequest(twice)

def test_every_value_here_is_frozen_so_nothing_edits_one_past_its_validation() -> None:
    (workflow,) = GetRequest.parsed(["o/r/wf/a"]).workflows
    with pytest.raises(FrozenInstanceError):
        workflow.directory = "../escape"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        workflow.repository.owner = ".."  # type: ignore[misc]

def test_the_module_is_pure_computation_and_imports_nothing_that_could_make_it_otherwise() -> None:
    """No I/O and no network: reading an argument is string work, whatever the download does."""
    allowed = {"collections.abc", "dataclasses", "string", "typing", "unicodedata"}
    allowed |= {"agl.ports.errors", "agl.ports.ids"}
    assert impurities(get_request) == set()
    assert imported_modules(get_request) <= allowed
