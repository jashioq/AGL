"""What `agl get` reads off its command line, and the one reading the rest of AGL works from.

Five guarantees here are ones later code leans on and nothing downstream checks again. Every
owner, repository and ref accepted goes into a download address unencoded - an owner and a
repository as one path segment each, a ref as segments its `/` separates, none of them empty, `.`
or `..` - which is asked of `urllib.parse.quote` one field at a time over the corpus `_corpus.py`
builds, rather than of a list. Within its alphabet a ref is accepted exactly where
`git check-ref-format` accepts one, so no rule of git's is missing and none is made up. Every
workflow the types accept spells itself back as an argument that reads as the same workflow, which
is what lets a record on disk be read back as the workflow it records. The last segment of a path
is held to `WorkflowName` and to no rule of this module's own: over the same corpus, a directory's
name is refused exactly where `agl new` would refuse it as a name, and with that type's own
message. And no two workflows one command asks for can land in one workspace directory, compared
through `collision_key` because a macOS volume folds case.

Two decisions are pinned as behaviour, so that changing either fails here rather than passing
review. An `@` means one thing, where the ref starts, and the ref runs to the end of the argument,
the way a workflow's `uses:` writes `release/1.2` - so a directory holding an `@` cannot be asked
for at all, and a ref holding one only by its commit's sha. And requests are grouped into fetches
with the owner and the repository matched in any case, because GitHub answers to every spelling of
both, while two refs that differ only in case stay two fetches, because git keeps them apart.

The shape a refusal names and the alphabet a ref is held to are written out below rather than
imported from the module, so that the test states the grammar instead of echoing it.
"""

import random
import string
import urllib.parse
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from typing import Final
import pytest
from _corpus import CORPUS, STRUCTURED, git_rejects, imported_modules, impurities
from agl.ports import get_request
from agl.ports.errors import InputError, InternalError
from agl.ports.get_request import Fetch, GetRequest, RepositoryAtRef, RequestedWorkflow
from agl.ports.ids import WorkflowName

_SHAPE: Final = "owner/repo/path/to/workflow[,sibling...][@ref]"

_REF_ALPHABET: Final = frozenset(string.ascii_letters + string.digits + "._-+/")

_BRIEF: Final = "jashioq/myrepo/workflows/mine/implement_and_review"

_SHA: Final = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"

# RFC 3986's `pchar`, less the unreserved characters `quote` never touches: what a path segment may
# carry as itself. Anything else in an address has to be escaped, or ends the path where it stands.
_PATH_CHARACTERS: Final = "!$&'()*+,;=:@"

_SEED: Final = 20260911

# Refs as they are written - branches, tags, semver's build metadata, a full ref name - and then one
# either side of every turn git's rules for the shape of a ref take.
_REFS: Final = [
    "main", "HEAD", "v1.2.0", "release/1.0", "feature/whatever", "releases/v6", "refs/heads/main",
    "v1.0.0+build.5", "jtreg-8.3+1", "-a", "a/-b", "a./b", "a/b.LOCK", "lock", "a.locka",
    "a.lock.b", ".a", "a/.b", "a.lock", "a/b.lock", "a.lock/b", "a..b", "a/..", "a/./b", "a//b",
    "/a", "a/", "a.", "a/b.", ".", "..", "@actions/core@1.1.0", "v1,b", "v1#x", "v1%2Fx",
]  # fmt: skip

def _ref_fuzz(count: int) -> list[str]:
    """Pseudo-random refs drawn from the alphabet alone, so git's rules of shape decide each one."""
    rng = random.Random(_SEED)
    return ["".join(rng.choices([*"abzAZ09._-+/"], k=rng.randint(1, 12))) for _ in range(count)]

_REF_FUZZ: Final = _ref_fuzz(200)

# Every value a property of refs runs over: the shared corpus for its characters, then the shapes.
_REF_CANDIDATES: Final = list(dict.fromkeys([*_REFS, *CORPUS, *_REF_FUZZ]))

# The values git is asked about, a process each: the shapes, and the corpus's stated-coverage half,
# kept to the alphabet - inside which no character decides anything and the shape decides it all.
_GIT_SAMPLE: Final = [
    ref for ref in dict.fromkeys([*_REFS, *STRUCTURED, *_REF_FUZZ]) if set(ref) <= _REF_ALPHABET
]

def _refusal(specs: list[str]) -> str:
    """The message one refused request carries, asserted to be a refusal of the caller's input."""
    with pytest.raises(InputError) as caught:
        GetRequest.parsed(specs)
    return str(caught.value)

def _ref_accepted(ref: str) -> bool:
    """Whether the type takes `ref`, asked directly so that no check of the parser's comes first."""
    try:
        RepositoryAtRef("o", "r", ref)
    except InputError:
        return False
    return True

def _owned_by(owner: str) -> RepositoryAtRef:
    return RepositoryAtRef(owner, "r", None)

def _named(repo: str) -> RepositoryAtRef:
    return RepositoryAtRef("o", repo, None)

# --- Reading an argument ------------------------------------------------------------------------

def test_one_argument_reads_as_an_owner_a_repository_a_directory_and_a_name() -> None:
    """The first form the command takes, every field spelled out rather than recomposed."""
    (workflow,) = GetRequest.parsed([_BRIEF]).workflows
    assert workflow.repository == RepositoryAtRef("jashioq", "myrepo", None)
    assert workflow.directory == "workflows/mine/implement_and_review"
    assert workflow.name == WorkflowName("implement_and_review")
    assert workflow.spec == _BRIEF

def test_a_ref_written_after_the_workflow_is_kept_exactly_as_it_was_written() -> None:
    """Not resolved and not normalised: what a ref names is the far side's to say."""
    (workflow,) = GetRequest.parsed(["jashioq/myrepo/workflows/mine/a@v1.2.0"]).workflows
    assert workflow.repository == RepositoryAtRef("jashioq", "myrepo", "v1.2.0")
    assert workflow.directory == "workflows/mine/a"

def test_no_ref_is_held_as_none_while_a_written_head_stays_a_ref() -> None:
    """None is the default branch, whatever it is called when the fetch happens.

    `@HEAD` names the same commit today and is still kept as what was written: a request is
    recorded as asked, and two spellings of one request are two fetches rather than a guess.
    """
    default, head = GetRequest.parsed(["o/r/wf/a", "o/r/wf/b@HEAD"]).fetches
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

def test_every_sibling_in_a_comma_list_shares_the_one_ref_written_after_it() -> None:
    """The siblings come before the `@`, like everything else they share."""
    request = GetRequest.parsed(["o/r/wf/a,b,c@release/1.0"])
    assert [one.directory for one in request.workflows] == ["wf/a", "wf/b", "wf/c"]
    assert {one.repository for one in request.workflows} == {
        RepositoryAtRef("o", "r", "release/1.0")
    }

def test_a_workflow_directory_at_the_repository_root_needs_no_path_above_it() -> None:
    request = GetRequest.parsed(["o/r/a", "o/r/b,c@v1"])
    assert [one.directory for one in request.workflows] == ["a", "b", "c"]

def test_a_comma_above_the_last_segment_is_part_of_a_directory_name() -> None:
    """Only the last segment is a list, so a comma further up is a character like any other."""
    (workflow,) = GetRequest.parsed(["o/r/x,y/a"]).workflows
    assert workflow.directory == "x,y/a"

def test_directories_above_the_workflow_need_not_be_names_a_workflow_could_take() -> None:
    """They are directories in somebody else's repository, and only the last one is placed."""
    (workflow,) = GetRequest.parsed(["o/r/My Workflows/v1.0/caf\xe9/-x/#y%z/a"]).workflows
    assert workflow.directory == "My Workflows/v1.0/caf\xe9/-x/#y%z/a"

def test_several_arguments_are_read_in_the_order_written_and_each_keeps_its_own_text() -> None:
    """Several arguments are what shell brace expansion hands over, so order is the operator's."""
    request = GetRequest.parsed(["o/r/x/a", "p/s/y/b,c@v2", "o/r/z/d"])
    assert [str(one.name) for one in request.workflows] == ["a", "b", "c", "d"]
    assert [one.spec for one in request.workflows] == [
        "o/r/x/a", "p/s/y/b,c@v2", "p/s/y/b,c@v2", "o/r/z/d",
    ]  # fmt: skip

def test_everything_after_the_at_sign_is_the_ref_its_slashes_included() -> None:
    """`release/1.2` is a legal git ref, and written last it cannot be mistaken for a path.

    However many `/` a ref holds, the one `@` an argument has is where it starts, which is how a
    workflow's `uses:` writes it too.
    """
    (workflow,) = GetRequest.parsed(["o/r/wf/a@release/1.2"]).workflows
    (named,) = GetRequest.parsed(["o/r/wf/b@refs/heads/feature/x"]).workflows
    assert (workflow.directory, workflow.repository.ref) == ("wf/a", "release/1.2")
    assert (named.directory, named.repository.ref) == ("wf/b", "refs/heads/feature/x")

def test_an_at_sign_only_ever_starts_the_ref_so_no_directory_may_hold_one() -> None:
    """Pinned as behaviour: `@` has one meaning, so a directory holding one is out of reach.

    `o/r/tools@v2/triage` has the one reading - the ref `v2/triage` of a workflow `tools` - and
    never the other, a path through a directory `tools@v2`. The type refuses such a directory
    itself, because a record holding one would spell itself back as an argument asking for
    something else.
    """
    (workflow,) = GetRequest.parsed(["o/r/tools@v2/triage"]).workflows
    assert (workflow.directory, workflow.repository.ref) == ("tools", "v2/triage")
    with pytest.raises(InputError, match="its segment 'tools@v2' contains '@' at position 5"):
        RequestedWorkflow(RepositoryAtRef("o", "r", None), "tools@v2/triage", "spec")

@pytest.mark.parametrize(
    "spec",
    [
        "o/.github/a", "my-org/repo.name/a", "o_o/r_r/a@v1.0-rc_1", f"O/R/a@{_SHA}",
        "actions/checkout/a@releases/v6", "openjdk/jtreg/a@jtreg-8.3+1",
        "pypa/gh-action-pypi-publish/a@release/v1",
    ],
)  # fmt: skip
def test_every_owner_repository_and_ref_github_hands_out_is_accepted(spec: str) -> None:
    """`.github` is a repository GitHub gives special meaning to, so a leading `.` stays legal.

    The refs are real ones: `releases/v6` a branch of `actions/checkout`, `jtreg-8.3+1` a tag of
    `openjdk/jtreg`, and `release/v1` what this repository's own publishing workflow uses.
    """
    (workflow,) = GetRequest.parsed([spec]).workflows
    assert str(workflow) == spec

@pytest.mark.parametrize(
    "spec", [_BRIEF, "jashioq/myrepo/wf/a,b,c@v1.2.0", "O/R/x/y,z/w@release/1.0"]
)
def test_each_workflow_spells_itself_back_as_an_argument_that_reads_the_same(spec: str) -> None:
    """`str` is the one place the grammar is written the other way, so each checks the other."""
    for workflow in GetRequest.parsed([spec]).workflows:
        (again,) = GetRequest.parsed([str(workflow)]).workflows
        assert again == replace(workflow, spec=str(workflow))

def test_any_workflow_the_types_accept_reads_back_from_the_argument_it_spells() -> None:
    """Over the corpus, as a directory above the workflow and as a ref: `str` parses back to it.

    `config/provenance.py` rebuilds a workflow from its record and spells it with `str`, so a
    value the types take and the grammar reads another way is a record that reads back as another
    workflow. An `@` in a directory is the value that would, which is why the type refuses one.
    """
    spelled = 0
    for value in _REF_CANDIDATES:
        for ref, directory in ((None, f"{value}/a"), ("v1", f"{value}/a"), (value, "wf/a")):
            try:
                workflow = RequestedWorkflow(RepositoryAtRef("o", "r", ref), directory, "")
            except InputError:
                continue
            spelled += 1
            (again,) = GetRequest.parsed([str(workflow)]).workflows
            assert again == replace(workflow, spec=str(workflow)), str(workflow)
    assert 3000 < spelled < 3 * len(_REF_CANDIDATES) - 2000, f"{spelled} spelled back"

# --- Refusals -----------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("spec", "problem"),
    [
        ("", "is empty"), ("/o/r/a", "starts with '/'"), ("@v1", "starts with '@'"),
        ("o/r/a/", "ends with '/'"), ("o/r/wf/@v1", "has '/' right before its '@'"),
        ("o//r/a", "holds '//'"), ("o/r//a", "holds '//'"), ("o/r//a@v1", "holds '//'"),
        ("jashioq", "names an owner and no repository"),
        ("jashioq/myrepo", "names a repository and no directory inside it"),
        ("o/r/wf/a@", "'@' with no ref after it"),
        ("o/r/wf/a@v1@v2", "holds a second '@'"), ("o/r/tools@v2/triage@v1", "holds a second '@'"),
        ("o/r/wf/a,,b", "empty entry in its comma list 'a,,b'"),
        ("o/r/wf/a,", "empty entry in its comma list 'a,'"),
        ("o/r/wf/,a", "empty entry in its comma list ',a'"), ("o/r/,", "empty entry"),
        ("o/r/wf/a,@v1", "empty entry in its comma list 'a,'"),
        ("o/r/wf/a@v1,b", "has ',' after its '@'"),
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
    "spec",
    ["jashioq/myrepo@v1.2.0/workflows/mine/a,b", "o/r@release/1.2/wf/a", "jashioq/myrepo@v1.2.0",
     "o@v1/r/a", "o/r@/wf/a"],
)  # fmt: skip
def test_a_ref_written_ahead_of_the_path_is_refused_saying_a_ref_is_written_last(
    spec: str,
) -> None:
    """Refused, and never read as something else: before its `@` stands no workflow at all."""
    message = _refusal([spec])
    assert message.startswith(repr(spec)), message
    assert "a ref is written last, after the workflow's own directory" in message, message

def test_an_argument_with_its_ref_on_the_repository_never_reads_as_a_workflow() -> None:
    """`owner/repo@ref/path` over every ref the type takes: each one refused the same way.

    Before the `@` stand an owner and a repository and nothing else, and no ref holds an `@` of
    its own for a second reading to start from - so there is no ref this spelling reaches.
    """
    refs = [ref for ref in _REF_CANDIDATES if _ref_accepted(ref)]
    for ref in refs:
        for path in ("wf/a", "a,b"):
            assert "a ref is written last" in _refusal([f"o/r@{ref}/{path}"]), ref
    assert len(refs) > 300, f"{len(refs)} refs"

@pytest.mark.parametrize(
    ("spec", "part", "problem"),
    [
        ("a b/r/x", "owner 'a b'", "' ' at position 1"),
        ("./r/a", "owner '.'", "path traversal"), ("o/../a", "repository '..'", "path traversal"),
        ("o/r?x/a", "repository 'r?x'", "'?'"), ("o/r#x/a", "repository 'r#x'", "'#'"),
        ("o/r%2e/a", "repository 'r%2e'", "'%'"), ("o/r+x/a", "repository 'r+x'", "'+'"),
        ("o/caf\xe9/a", "repository 'caf\xe9'", "'\xe9'"),
        ("o/r/a@v1#x", "ref 'v1#x'", "'#'"), ("o/r/a@v1%2Fx", "ref 'v1%2Fx'", "'%'"),
        ("o/r/a@v 1", "ref 'v 1'", "' '"), ("o/r/a@v1~1", "ref 'v1~1'", "'~'"),
        ("o/r/a@caf\xe9", "ref 'caf\xe9'", "'\xe9'"),
    ],
)  # fmt: skip
def test_an_unusable_owner_repository_or_ref_is_refused_naming_the_part_and_its_problem(
    spec: str, part: str, problem: str
) -> None:
    message = _refusal([spec])
    assert message.startswith(f"in {spec!r}, {part} cannot be used: "), message
    assert problem in message, message

@pytest.mark.parametrize(
    ("ref", "problem"),
    [
        ("release/../main", "contains '..'"), ("..", "contains '..'"), ("v1.", "ends with '.'"),
        (".", "ends with '.'"), ("release//1.0", "empty component"), ("/v1", "empty component"),
        ("v1/", "empty component"), ("a/.b", "component '.b' starts with '.'"),
        (".github", "component '.github' starts with '.'"),
        ("v1/b.lock", "component 'b.lock' ends with '.lock'"),
        ("a.lock/b", "component 'a.lock' ends with '.lock'"),
    ],
)  # fmt: skip
def test_a_ref_git_would_never_hold_is_refused_naming_the_rule_it_breaks(
    ref: str, problem: str
) -> None:
    """Refused off the command line, where the alternative is a 404 that could not say why."""
    spec = f"o/r/wf/a@{ref}"
    message = _refusal([spec])
    assert message.startswith(f"in {spec!r}, ref {ref!r} cannot be used: "), message
    assert problem in message, message

def test_within_its_alphabet_a_ref_is_accepted_exactly_where_git_would_hold_it() -> None:
    """Over every shape above and the corpus's own: git's verdict inside the alphabet, no outside.

    Asked of `git check-ref-format` as `refs/heads/<ref>`, the full name a branch has, because it
    wants a `/` in the name it is handed. Outside the alphabet everything is refused whatever git
    would say - `#`, `%`, `,`, `@` and non-ASCII are all legal in a git ref.
    """
    rejected = set(git_rejects([f"refs/heads/{ref}" for ref in _GIT_SAMPLE]))
    disagreed = [
        ref for ref in _GIT_SAMPLE if _ref_accepted(ref) is (f"refs/heads/{ref}" in rejected)
    ]
    outside = [ref for ref in _REF_CANDIDATES if not set(ref) <= _REF_ALPHABET]
    assert not disagreed, f"git and the type disagree over {disagreed[:10]}"
    assert not [ref for ref in outside if _ref_accepted(ref)]
    assert 50 < len(rejected) < len(_GIT_SAMPLE) - 150, f"{len(rejected)} of {len(_GIT_SAMPLE)}"
    assert len(outside) > 1500, f"{len(outside)} outside the alphabet"

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

def test_the_last_segment_is_held_to_workflow_name_and_to_no_rule_of_this_module() -> None:
    """Over the whole corpus: refused exactly where `WorkflowName` refuses, and in its words.

    A second validator would show up here as a value one of the two refuses and the other takes.
    `/`, `,` and `@` are left out because the grammar spends them, and the empty string because the
    grammar refuses it before any name is read.
    """
    candidates = [value for value in CORPUS if value and not {"/", ",", "@"} & set(value)]
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

@pytest.mark.parametrize("built", [_owned_by, _named])
def test_every_owner_and_every_repository_accepted_is_one_address_segment_unencoded(
    built: Callable[[str], RepositoryAtRef],
) -> None:
    """One path segment that nothing resolves: no character `quote` would touch, and no `.`/`..`.

    That is what lets a download address be written by formatting these into it. Asked of each
    field on its own, so that one refusing a value first leaves no character of the other's
    unexamined.
    """
    accepted = 0
    for value in CORPUS:
        try:
            built(value)
        except InputError:
            continue
        accepted += 1
        assert urllib.parse.quote(value, safe="") == value, value
        assert value not in {".", ".."}, value
    assert 300 < accepted < len(CORPUS) - 1000, f"{accepted} of {len(CORPUS)} accepted"

def test_every_ref_accepted_goes_into_an_address_unencoded_with_no_segment_to_resolve() -> None:
    """As the segments its `/` separates, none empty, `.` or `..`, and nothing in them escaped.

    RFC 3986 lets a path carry each of its characters as itself, so formatting a ref into a
    download address sends what was written; an empty, `.` or `..` segment is one a server may
    resolve or collapse into another path, and so into another ref.
    """
    accepted = [ref for ref in _REF_CANDIDATES if _ref_accepted(ref)]
    for ref in accepted:
        assert urllib.parse.quote(ref, safe=_PATH_CHARACTERS + "/") == ref, ref
        assert not {"", ".", ".."} & set(ref.split("/")), ref
    assert 300 < len(accepted) < len(_REF_CANDIDATES) - 1000, f"{len(accepted)} accepted"
    assert sum("/" in ref for ref in accepted) > 20, "no ref holding '/' was accepted"
    assert sum("+" in ref for ref in accepted) > 20, "no ref holding '+' was accepted"

@pytest.mark.parametrize(
    ("specs", "problem"),
    [
        (["o/r/wf/a,b,a"], "'o/r/wf/a' is asked for twice"),
        (["o/r/wf/a", "o/r/wf/a"], "'o/r/wf/a' is asked for twice"),
        (["o/r/x/a", "p/s/y/a"], "'o/r/x/a' and 'p/s/y/a' are both workflow 'a'"),
        (["O/R/wf/a", "o/r/wf/a"], "'O/R/wf/a' and 'o/r/wf/a' are both workflow 'a'"),
        (["o/r/wf/a,A"], "'o/r/wf/a' and 'o/r/wf/A' are workflows 'a' and 'A'"),
        (["o/r/x/Triage", "p/s/y/triage@v1"], "differ only in case"),
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
    (fetch,) = GetRequest.parsed(["o/r/wf/a,b@v1", "o/r/other/c@v1", "o/r/d@v1"]).fetches
    assert fetch.repository == RepositoryAtRef("o", "r", "v1")
    assert [one.directory for one in fetch.workflows] == ["wf/a", "wf/b", "other/c", "d"]

def test_each_repository_and_each_of_its_refs_is_a_fetch_of_its_own() -> None:
    """In the order each was first asked for, which is the order the downloads are reported in."""
    fetches = GetRequest.parsed(["o/r/wf/a", "o/r/wf/b@v1", "p/r/wf/c", "o/r/wf/d"]).fetches
    assert [str(one.repository) for one in fetches] == ["o/r", "o/r@v1", "p/r"]
    assert [[str(w.name) for w in one.workflows] for one in fetches] == [["a", "d"], ["b"], ["c"]]

def test_an_owner_and_repository_spelled_in_another_case_join_the_first_spellings_fetch() -> None:
    """One fetch, under the spelling asked for first; each workflow keeps the one it came with."""
    (fetch,) = GetRequest.parsed(["Jashioq/MyRepo/wf/a", "jashioq/myrepo/wf/b"]).fetches
    assert str(fetch.repository) == "Jashioq/MyRepo"
    assert [str(one.repository) for one in fetch.workflows] == ["Jashioq/MyRepo", "jashioq/myrepo"]

def test_two_refs_differing_only_in_case_stay_two_fetches_because_git_keeps_them_apart() -> None:
    fetches = GetRequest.parsed(["o/r/wf/a@Main", "o/r/wf/b@main"]).fetches
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
    with pytest.raises(InputError, match="ref 'a//b' cannot be used: it has an empty component"):
        RepositoryAtRef("o", "r", "a//b")
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
