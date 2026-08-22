"""`adapters/openai/translate.py` - the four translations, tested one at a time.

There is no contract suite here and there should not be: `AgentContract` is written against
`AgentRunner`, and this module implements no port. It is the vendor boundary underneath one - pure
functions over plain values - so what is asserted below is what those functions produce, and the
suite that asserts what an `AgentRunner` owes runs against `runner.py` and `fake.py` at 8.2 and
8.3. Everything here is in-process: no subprocess, no CLI, no socket, no clock. The repo-wide
paid-endpoint guard in `tests/conftest.py` applies anyway, as it does to every file under `tests/`,
and nothing here needs it.

**What these tests can and cannot be.** The restriction half of the module is a claim about another
program's behaviour, and no test in this repository can settle it: asserting that `read-only`
appears in a field proves the string was produced, not that a sandbox refuses a write when the
harness is handed it. That verification is a set of free probes against the installed binary,
recorded in the module docstring with what each covered and what it could not - `codex sandbox` for
the filesystem and network rows, `codex debug prompt-input` for the policy handed to the model,
`codex features list` for the feature registry, and the argument parser itself for the exit status
that means "this command line was refused".

So the tests below assert what a test *can* settle, and one thing more that is worth naming
because it is the reason the file is worth having. Three of the four translations are decisions
rather than computations, and the way each of them fails is silently: a mode that is one value too
permissive, a restriction that renders nothing, a slug that would be read as a flag. Each of those
compiles, passes a type checker and produces a plausible-looking string. The assertions are
therefore about *properties* - totality over every subset, both halves present for every member,
no slug that begins with a dash - rather than golden copies of the tables, because a test holding
a second copy of a table agrees with the first only because one person edited both.

Named `test_openai_translate.py`: `tests/` carries no `__init__.py` (see `tests/conftest.py` for
why it must not), so pytest's module names are the bare filenames and two files of one name under
different directories would collide at import.
"""

import re
from collections.abc import Iterator
from itertools import combinations
from pathlib import Path
from typing import Final

import pytest

from agl.adapters.openai.translate import (
    APPROVAL,
    Sandbox,
    activity,
    failure,
    launch_failure,
    model_slug,
    sandbox,
    unreadable,
    unready,
)
from agl.ports.agent import Claude, ModelId, OpenAI, Restriction
from agl.ports.errors import (
    AglError,
    InputError,
    UpstreamUnavailable,
    UpstreamUnexpected,
)
from agl.ports.run import JsonValue

_WORKSPACE: Final = Path("/trees/proj/agl-fix-auth")

# The three values `--sandbox` accepts, read off the CLI's own `[possible values]`. A mode outside
# this set is refused by the argument parser at exit 2, before anything runs - which is a run that
# dies for a reason no workflow author can see in their own declaration.
_SANDBOX_MODES: Final = frozenset({"read-only", "workspace-write", "danger-full-access"})

# `approval_policy` advertises five variants and only four load. `untrusted` is refused outright -
# `approval_policy = "untrusted" is no longer supported; remove this setting` - and it is refused at
# configuration-load time, so emitting it would be a run that never starts.
_REFUSED_APPROVAL: Final = "untrusted"


def _subsets() -> Iterator[frozenset[Restriction]]:
    """Every one of the sixteen subsets of `Restriction`, built from the port's own members.

    Generated rather than listed, so a fifth member added to the port doubles this to thirty-two on
    the same commit rather than leaving half the space untested under a list somebody has to
    remember to extend.
    """
    members = list(Restriction)
    for size in range(len(members) + 1):
        for chosen in combinations(members, size):
            yield frozenset(chosen)


def _ids(subset: frozenset[Restriction]) -> str:
    """A stable pytest id for a subset, since a `frozenset`'s own repr order is not stable."""
    return "+".join(member.value for member in Restriction if member in subset) or "none"


_ALL_SUBSETS: Final = list(_subsets())


class TestTheSetCollapsesOntoOneScalar:
    """(a) Sixteen subsets, one mode each, and a reader can see which."""

    @pytest.mark.parametrize("restrictions", _ALL_SUBSETS, ids=_ids)
    def test_every_subset_produces_exactly_one_legal_mode(
        self, restrictions: frozenset[Restriction]
    ) -> None:
        """Totality, asserted over the whole space rather than over the cases somebody thought of.

        `Restriction` is a set and `sandbox_mode` is a scalar, so the adapter has to collapse one
        onto the other. The failure mode of a collapse is a subset nobody considered falling
        through to whatever the last branch happened to leave in the variable, and the only way to
        rule that out is to ask all sixteen.

        The mode is also asserted to be one the CLI accepts: a value outside `[possible values]` is
        refused by the argument parser at exit 2, and a run that dies there dies for a reason its
        workflow author cannot see in their own declaration.
        """
        rendered = sandbox(restrictions)
        assert rendered.mode in _SANDBOX_MODES, (
            f"{_ids(restrictions)} rendered mode {rendered.mode!r}, which is not one of the three "
            f"values the CLI accepts - the argument parser refuses it before anything runs"
        )

    @pytest.mark.parametrize("restrictions", _ALL_SUBSETS, ids=_ids)
    def test_the_collapse_is_a_function_of_the_set_and_of_nothing_else(
        self, restrictions: frozenset[Restriction]
    ) -> None:
        """The same set, built two different ways, renders identically.

        A `frozenset` of strings iterates in an order that depends on hash randomisation, so
        anything derived from the set's own order would move between processes - and a command line
        that moved between two runs would show up as a difference in every log and every comparison
        of two of them. Building the same set forwards and backwards is what catches it.
        """
        forwards = sandbox(frozenset(member for member in Restriction if member in restrictions))
        backwards = sandbox(
            frozenset(member for member in reversed(list(Restriction)) if member in restrictions)
        )
        assert forwards == backwards

    @pytest.mark.parametrize("restrictions", _ALL_SUBSETS, ids=_ids)
    def test_no_subset_ever_reaches_for_the_mode_that_switches_the_sandbox_off(
        self, restrictions: frozenset[Restriction]
    ) -> None:
        """`danger-full-access` is never produced, including for the empty set.

        The sandbox *is* this adapter's restriction mechanism, so the mode that turns it off could
        only ever serve a role that declared nothing - and answering "nothing forbidden" with "no
        sandbox at all" would make an unrestricted role strictly more dangerous on this backend
        than on the other one, which is a difference no workflow author declared and none can see.
        """
        assert sandbox(restrictions).mode != "danger-full-access"

    @pytest.mark.parametrize("restrictions", _ALL_SUBSETS, ids=_ids)
    def test_no_file_writes_is_the_only_thing_that_decides_the_mode(
        self, restrictions: frozenset[Restriction]
    ) -> None:
        """The three-row table in the module docstring, asserted as the one branch it claims to be.

        This is the assertion that keeps the collapse *legible*: a reader is told that one
        membership test decides the mode, and a second condition creeping in - a mode that also
        depended on `NO_SHELL`, say - would make the docstring's table a description of something
        that no longer happens.
        """
        expected = "read-only" if Restriction.NO_FILE_WRITES in restrictions else "workspace-write"
        assert sandbox(restrictions).mode == expected

    def test_the_over_restriction_is_where_the_module_says_it_is(self) -> None:
        """`{NO_FILE_WRITES}` alone comes back read-only, which also removes the network.

        The one case where this adapter enforces more than it was asked for. It is asserted rather
        than merely documented so that a later change which "fixed" it by dropping `NO_FILE_WRITES`
        to `workspace-write` fails here - dropping a declared restriction is the thing
        `Restriction`'s docstring rules out, and over-restricting is the direction the module chose
        deliberately. There is no override in the result, because a `network_access` key under
        `read-only` is accepted and provably does nothing, and a key that does nothing reads like
        enforcement to the next person.
        """
        rendered = sandbox(frozenset({Restriction.NO_FILE_WRITES}))
        assert rendered.mode == "read-only"
        assert not any("network_access" in token for token in rendered.options)

    @pytest.mark.parametrize(
        ("restrictions", "expected"),
        [
            (frozenset(), "true"),
            (frozenset({Restriction.NO_NETWORK}), "false"),
            (frozenset({Restriction.NO_VCS_WRITES}), "true"),
            (frozenset({Restriction.NO_SHELL, Restriction.NO_NETWORK}), "false"),
        ],
    )
    def test_the_network_switch_is_stated_in_both_directions(
        self, restrictions: frozenset[Restriction], expected: str
    ) -> None:
        """Under `workspace-write` the network key is always emitted, and says which way.

        Both positions are declared by a role - `NO_NETWORK` is a member of the port - so the
        adapter states both rather than leaning on the packaged default for one of them. A default
        can move between releases, and a run should not depend on one it never stated.
        """
        options = sandbox(restrictions).options
        assert f"sandbox_workspace_write.network_access={expected}" in options

    def test_no_vcs_writes_is_enforced_by_adding_nothing(self) -> None:
        """The mechanism is the harness's own default, so the rendering carries no extra override.

        Under `workspace-write` the `.git`, `.codex` and `.agents` paths inside the working root
        are read-only unless something opts them back in. This asserts the two halves of that: the
        restriction changes the mode not at all, and it never widens `writable_roots` - which is
        also asserted for the case where the restriction is *absent*, since the tempting reading of
        "restrictions are a set and not a level" is that a role which did not forbid committing
        should be given the ability. The module declines, and this is where that decision is held.
        """
        with_it = sandbox(frozenset({Restriction.NO_VCS_WRITES}))
        without_it = sandbox(frozenset())
        assert (with_it.mode, with_it.options) == (without_it.mode, without_it.options)
        assert with_it.in_words and not without_it.in_words, (
            "the two renderings differ in exactly one place, and it is the sentence. The mechanism "
            "is the harness's default either way; what the restriction adds is what the agent is "
            "told, which is the half that survives a managed policy substituting the mode"
        )
        for rendered in (with_it, without_it):
            assert not any("writable_roots" in token for token in rendered.options), (
                "the adapter widened writable_roots. Absence of a restriction is not a grant, and "
                "a worktree's .git is a pointer into the parent repository's own administrative "
                "directory - state shared with every other concurrent run"
            )

    def test_no_shell_reaches_for_both_routes_and_not_only_the_obvious_one(self) -> None:
        """`shell_tool` and `unified_exec`, because either alone is half a switch.

        Both are real feature names on this build and both are `stable` and on by default. Neither
        is verified to remove the tool from what the model is offered, which is why the sentence
        goes with them - but a harness whose working model is running commands plausibly has a
        second route, and disabling only the first would be a restriction half-applied.
        """
        options = sandbox(frozenset({Restriction.NO_SHELL})).options
        assert "features.shell_tool=false" in options
        assert "features.unified_exec=false" in options

    @pytest.mark.parametrize("restrictions", _ALL_SUBSETS, ids=_ids)
    def test_nothing_a_caller_supplied_is_ever_interpolated_into_an_option(
        self, restrictions: frozenset[Restriction]
    ) -> None:
        """§3.5: every value reaching a command line is hostile regardless of where it came from.

        This function takes no path, no name and no caller string, and every token it produces is a
        literal from the module - which is what keeps that rule from having any work to do here. It
        is asserted rather than assumed because the one override this module deliberately does not
        emit, `writable_roots`, is exactly the one that would have interpolated a workspace path.
        """
        for token in sandbox(restrictions).options:
            assert token == "-c" or re.fullmatch(r"[a-z_.]+=[a-z]+", token), (
                f"{token!r} is not a literal key=value override. A token built out of something a "
                f"caller supplied is the shape §3.5 is about"
            )


class TestEveryRestrictionAlsoReachesTheAgentInWords:
    """(a) The port's second honest move, produced for every member and never for none."""

    @pytest.mark.parametrize("member", list(Restriction))
    def test_every_member_renders_a_sentence(self, member: Restriction) -> None:
        """A member missing from the table would render as silence, which is the forbidden move.

        `Restriction`'s docstring: "A backend with no way to enforce one has two honest moves and
        no third: put it to the agent as an instruction, or refuse the task. Silently dropping it
        is neither." Parametrised over `Restriction` itself rather than over a list written here,
        so a member added to the port arrives in this test on the same commit and fails until it is
        rendered.
        """
        rendered = sandbox(frozenset({member}))
        assert rendered.in_words.strip(), (
            f"{member} rendered no instruction. The sandbox is exact for three of the four and "
            f"approximate for the fourth, but a denial reaches the agent as a command that failed "
            f"- and an agent that does not know why retries, works around, or spends its turn "
            f"discovering the wall"
        )
        assert member.value not in rendered.in_words, (
            f"{member} rendered its own enum value into the prompt. The agent is told what it may "
            f"not do, in words it can act on, not handed AGL's identifier for the rule"
        )

    def test_no_restrictions_render_no_words_at_all(self) -> None:
        """An unrestricted role gets no paragraph, not a preamble introducing an empty list."""
        rendered = sandbox(frozenset())
        assert rendered.in_words == ""

    def test_the_sentences_come_out_in_the_ports_order_and_not_the_sets(self) -> None:
        """Declaration order is the only ordering in this module that does not move.

        Asserted through the rendered prose rather than through an internal list, because the
        prompt is the artefact whose stability matters: a paragraph whose bullets reordered between
        two runs is a diff in every log for no reason anybody caused.
        """
        rendered = sandbox(frozenset(Restriction)).in_words
        positions = [
            rendered.index(phrase)
            for phrase in ("version control", "Change nothing on disk", "run commands", "network")
        ]
        assert positions == sorted(positions)

    def test_every_subset_speaks_for_exactly_the_members_it_holds(self) -> None:
        """One bullet per declared restriction: none missing, and none invented.

        The two failures this rules out are opposites and both are silent. A missing bullet is a
        restriction the agent was never told about; an extra one is the adapter telling an agent it
        may not do something no role forbade, which quietly narrows a task nobody narrowed.
        """
        for restrictions in _ALL_SUBSETS:
            bullets = [
                line for line in sandbox(restrictions).in_words.splitlines() if line.startswith("-")
            ]
            assert len(bullets) == len(restrictions), (
                f"{_ids(restrictions)} rendered {len(bullets)} sentences for "
                f"{len(restrictions)} restrictions"
            )

    def test_the_preamble_says_the_limits_outrank_what_the_sandbox_appears_to_allow(self) -> None:
        """The one thing the paragraph has to do beyond listing the sentences.

        Codex tells the model what its sandbox permits, in the harness's own prose. AGL's sentences
        are a different statement - what this *role* is forbidden - and on a machine where a
        managed policy substituted a wider sandbox mode they are the only part of the restriction
        still standing. A preamble that read as a description of the sandbox would invite the agent
        to resolve the two against each other rather than to obey both.
        """
        rendered = sandbox(frozenset({Restriction.NO_NETWORK})).in_words
        assert "sandbox" in rendered
        assert rendered.startswith("AGL")


class TestModelSlugs:
    """(b) A pinned slug for a model this adapter serves, and a refusal for anything else."""

    @pytest.mark.parametrize("model", list(OpenAI))
    def test_every_openai_model_maps_to_a_slug(self, model: ModelId) -> None:
        """Exhaustiveness, asked in the only place that can hold the question.

        `ModelId` is deliberately open to subclassing so the per-provider enums can extend it,
        which means no type checker can be asked whether the table is complete. Parametrising over
        `OpenAI` is that question: a member added to the port fails here until `translate.py` says
        what to run for it, rather than failing at second zero of the first run that names it.
        """
        slug = model_slug(model)
        assert slug, f"{model} mapped to an empty string, which the CLI reads as no model at all"

    @pytest.mark.parametrize("model", list(OpenAI))
    def test_the_slug_is_a_pin_and_carries_its_version(self, model: ModelId) -> None:
        """A dated slug, not a bare tier - the mirror image of the Claude adapter's choice.

        The port's `OpenAI` docstring drops the version from the enum deliberately, so that "this
        provider's adapter needs an edit on a release where the Claude one does not", and that
        sentence is only true if the table here is pinned. A slug that had lost its digits would be
        a tier resolving somewhere else - probably to whatever sits at priority 1 today - and one
        `ModelId` would then name different models on different days under a step fingerprint that
        says nothing changed.
        """
        slug = model_slug(model)
        assert re.search(r"\d", slug), (
            f"{model} maps to {slug!r}, which carries no version. This adapter pins: a tier that "
            f"resolved at run time would move the model under a fingerprint that says it did not"
        )

    @pytest.mark.parametrize("model", list(OpenAI))
    def test_no_slug_could_ever_be_read_as_a_flag(self, model: ModelId) -> None:
        """§3.5's rule about a value's position, kept where it can actually be kept.

        Every value reaching a command line is hostile regardless of provenance, and this one is
        handed to `-m`. A runtime guard in `translate.py` would be a branch no input can reach,
        because the values come from a closed table in that file - so the guarantee lives here,
        where it fails on the commit that adds a bad slug rather than on the run that sends it.
        """
        assert not model_slug(model).startswith("-")

    @pytest.mark.parametrize("model", list(Claude))
    def test_a_model_this_adapter_does_not_serve_is_refused(self, model: ModelId) -> None:
        """§3.2: refuse, and never substitute.

        `adapters/routing.py` dispatches on `task.model.provider` and should never send one of
        these here, so arriving is already a bug - but the honest answer to it is a refusal naming
        what this adapter does serve, not a quiet run of Terra in place of Opus. The message is
        checked for the model's own spelling because a refusal that does not name what it refused
        sends the reader to the wrong declaration.
        """
        with pytest.raises(InputError) as refused:
            model_slug(model)
        assert str(model) in str(refused.value)

    def test_the_refusal_says_what_is_served(self) -> None:
        """A person reading exit 2 needs the alternatives, not only the rejection."""
        with pytest.raises(InputError) as refused:
            model_slug(Claude.SONNET)
        message = str(refused.value)
        for served in OpenAI:
            assert str(served) in message


class TestTheApprovalSettingIsAdapterLocalAndConstant:
    """The R2 checkpoint, in the shape the module gives it: a constant, not a translation."""

    def test_the_approval_setting_does_not_depend_on_the_restrictions(self) -> None:
        """`sandbox()` never emits an approval policy, which is what makes the separation visible.

        The load-bearing mapping is `Restriction` -> `sandbox_mode`: what a role is forbidden is
        decided there and nowhere else, measured over fifteen renderings of the policy handed to
        the model, three distinct values, one per sandbox mode and none per approval policy. If the
        approval setting ever became a function of the restrictions, that measurement would have
        stopped being the reason this decision is safe to keep inside the adapter.
        """
        for restrictions in _ALL_SUBSETS:
            assert not any("approval" in token for token in sandbox(restrictions).options)

    def test_the_approval_policy_is_one_the_loader_accepts(self) -> None:
        """Four of the five advertised variants load, and this is not the fifth.

        `untrusted` is in the binary's own enum and in older documentation, and the loader refuses
        it outright - so emitting it would be a run that never starts, for a reason that appears
        nowhere in any workflow. Measured against the loader itself.
        """
        assert _REFUSED_APPROVAL not in " ".join(APPROVAL)
        assert 'approval_policy="never"' in APPROVAL

    def test_the_setting_travels_as_a_configuration_override_and_not_as_a_flag(self) -> None:
        """`codex exec` on this build has no `-a/--ask-for-approval`; the parser rejects it.

        The findings' flag table says otherwise and its recommended composition ends `-a never`,
        which would have exited 2 on every run. `-a` exists on the *top-level* interactive command,
        which is where that reading came from. This is the assertion that stops the flag form being
        copied back in from the document.
        """
        assert APPROVAL[0] == "-c"
        assert "-a" not in APPROVAL
        assert not any(token.startswith("--") for token in APPROVAL)


class TestFailuresBecomeAglErrors:
    """(c) Every way this backend can fail to answer, in `errors.py`'s vocabulary."""

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (FileNotFoundError(2, "No such file or directory", "codex"), UpstreamUnavailable),
            (PermissionError(13, "Permission denied", "codex"), UpstreamUnavailable),
            (OSError(8, "Exec format error", "codex"), UpstreamUnavailable),
        ],
    )
    def test_a_binary_that_will_not_start_is_unavailable(
        self, error: OSError, expected: type[AglError]
    ) -> None:
        """Missing, not on `PATH`, not executable, or unrunnable - all the same answer.

        Nothing was attempted and nothing reached a model, which is `UpstreamUnavailable`'s exact
        promise: "the same call may well succeed later". `PermissionError` is a subclass of
        `OSError` and is listed separately because a translation written in the wrong order would
        answer for the parent and lose the sentence that told a reader to look at the file mode.
        """
        translated = launch_failure(error)
        assert type(translated) is expected
        assert str(translated).strip()

    def test_a_missing_binary_says_which_binary_and_what_to_do(self) -> None:
        """The port asks `check_ready` for "a reason a person can act on"; so does a run.

        A message that says only "could not start" sends a reader to the wrong place. This one has
        to name the harness and say that installing it is the fix, because "not installed" and "the
        model refused" are the two readings of a failed run and only one of them is actionable in
        ten seconds.
        """
        message = str(launch_failure(FileNotFoundError(2, "No such file or directory", "codex")))
        assert "PATH" in message
        assert "install" in message.lower()

    def test_a_readiness_probe_always_answers_unavailable(self) -> None:
        """`check_ready`'s one refusal, whatever the probe found.

        The contract suite fails an adapter whose `check_ready` raises anything else, because
        §3.2's first preflight check catches `UpstreamUnavailable` and nothing else - anything else
        reaches the top of the CLI as exit 70 and tells the reader to file a bug about their own
        logged-out session. Every input is the same answer here, *not now*, and only the reason
        varies.
        """
        for status, output in ((1, "Not logged in"), (1, ""), (70, "something nobody has seen")):
            refusal = unready(status, output)
            assert isinstance(refusal, UpstreamUnavailable)
            assert str(refusal).strip()

    def test_a_probe_that_said_nothing_still_carries_a_message(self) -> None:
        """An `UpstreamUnavailable()` carrying nothing is the same dead end as no message at all."""
        assert "nothing" in str(unready(1, "   ")).lower()

    @pytest.mark.parametrize(
        ("reported", "exit_code", "stderr", "expected"),
        [
            ("model refused the request", 1, "", UpstreamUnavailable),
            ("You've hit your usage limit.", 1, "", UpstreamUnavailable),
            (None, 2, "error: unexpected argument '--nope' found", UpstreamUnexpected),
            (None, 2, "error: invalid value 'x' for '--sandbox'", UpstreamUnexpected),
            (None, 1, "Error: failed to load configuration", UpstreamUnavailable),
            (None, 1, "", UpstreamUnavailable),
            ("   ", 2, "error: unexpected argument", UpstreamUnexpected),
        ],
    )
    def test_each_failure_maps_to_its_meaning(
        self, reported: str | None, exit_code: int, stderr: str, expected: type[AglError]
    ) -> None:
        """The mapping §3.1 asks for, by what a reader of the exit code should do.

        The last row is the one worth reading twice: a `reported` that is only whitespace is
        treated as no report at all, so a `turn.failed` carrying an empty message falls through to
        the status rather than producing an error whose reason is a blank.

        Exit 2 is the one status that was established for free - the argument parser refusing the
        command line before anything runs - and it is `UpstreamUnexpected` because the binary works
        and this adapter's idea of its command line does not. Exit 1 is overloaded and cannot be
        read as anything, so it takes the fallback.
        """
        translated = failure(reported=reported, exit_code=exit_code, stderr=stderr)
        assert type(translated) is expected, (
            f"reported={reported!r} exit={exit_code} became {type(translated).__name__}, "
            f"not {expected.__name__}"
        )
        assert str(translated).strip()

    def test_what_the_stream_said_outranks_the_exit_status(self) -> None:
        """The ordering the whole of (c) rests on, asserted rather than left to the docstring.

        Codex's exit codes are undocumented and 1 spans "the configuration would not load" and "a
        turn ran and failed" - opposite answers to the only question a caller has. So a message
        from the stream wins, and it wins even against the one status this module *can* read: a run
        that explained itself is explained, whatever number the process exited with.
        """
        explained = failure(reported="the sandbox denied a write", exit_code=2, stderr="ignored")
        assert "the sandbox denied a write" in str(explained)
        assert "ignored" not in str(explained)

    def test_no_exit_status_is_ever_presented_as_a_meaning(self) -> None:
        """"Nothing above an adapter ever sees a raw exit code" - including in the prose.

        The number goes into the message because a person debugging wants it, and it is framed as a
        number rather than as a diagnosis, because on this harness it has none that was written
        down. A message that said "exit 1: not authenticated" would be inventing the table the
        module docstring declines to invent.
        """
        message = str(failure(reported=None, exit_code=1, stderr="boom"))
        assert "exited 1" in message
        assert "no meaning" in message

    @pytest.mark.parametrize(
        ("line", "reason"),
        [
            ("{not json", "Expecting property name enclosed in double quotes"),
            ("", "no content"),
            ("x" * 500, "Expecting value: line 1 column 1"),
        ],
    )
    def test_output_that_will_not_decode_is_unexpected_rather_than_unavailable(
        self, line: str, reason: str
    ) -> None:
        """`errors.py`: the far side is working and our understanding of it is what failed.

        Retrying the same call unchanged answers the same way, which is exactly what
        `UpstreamUnexpected` promises and exactly what `UpstreamUnavailable` does not. The long
        line is here because the message quotes what could not be read, and an error message is not
        a place to paste five hundred characters.
        """
        translated = unreadable(line, reason)
        assert isinstance(translated, UpstreamUnexpected)
        assert reason in str(translated)
        assert len(str(translated)) < 600


class TestActivityStrings:
    """(d) One line per frame kind, formatted from the field that kind is about."""

    @pytest.mark.parametrize(
        ("item", "expected"),
        [
            (
                {"type": "command_execution", "command": "./gradlew build", "exit_code": 0},
                "Running: ./gradlew build",
            ),
            (
                {
                    "type": "file_change",
                    "changes": [
                        {"path": "/trees/proj/agl-fix-auth/domain/usecase.kt", "kind": "update"}
                    ],
                },
                "Changing: domain/usecase.kt",
            ),
            (
                {"type": "mcp_tool_call", "server": "agl", "tool": "ask", "arguments": {}},
                "Calling: agl/ask",
            ),
            (
                {"type": "web_search", "query": "seatbelt deny file-write", "action": "search"},
                "Searching: seatbelt deny file-write",
            ),
        ],
    )
    def test_each_frame_kind_formats_its_own_field(
        self, item: dict[str, JsonValue], expected: str
    ) -> None:
        """Four kinds, four fields, and no tool named anywhere.

        This is what makes the rule a match on *frame kind* rather than the per-tool table §3.7
        forbids: the stream is typed, so the field carrying the interesting value is the field that
        kind is about, and the adapter never learns that a command came from a tool called `Bash`.
        Each payload here carries a second field too, so a rule that took whatever came first would
        be caught rather than accidentally agreeing.
        """
        assert activity(item, _WORKSPACE) == expected

    @pytest.mark.parametrize(
        "item",
        [
            {"type": "agent_message", "text": "I have finished."},
            {"type": "reasoning", "text": "Considering the options."},
            {"type": "todo_list", "items": [{"text": "one", "completed": False}]},
            {"type": "error", "message": "something went wrong"},
        ],
    )
    def test_content_and_run_business_are_not_activity(self, item: dict[str, JsonValue]) -> None:
        """`None`, because a dashboard cell showing what the model is *thinking* is not activity.

        `agent_message` and `reasoning` are the run's content and belong to `AgentOutcome`;
        `todo_list` and `error` are the run's business. All four say the same thing to the caller -
        nothing to show - which is why the return type does not distinguish them.
        """
        assert activity(item, _WORKSPACE) is None

    @pytest.mark.parametrize(
        "item",
        [
            {"type": "collab_tool_call", "tool": "spawn", "prompt": "go"},
            {"type": "something_invented_in_a_later_release", "value": "x"},
            {"type": 7},
            {},
        ],
    )
    def test_an_unrecognised_frame_is_silence_and_never_an_exception(
        self, item: dict[str, JsonValue]
    ) -> None:
        """The load-bearing one, and the reason it is load-bearing is in the first row.

        `collab_tool_call` is a real item kind in the harness's own source and appears in neither
        its published documentation nor this build's string pool - so it is a frame that may arrive
        tomorrow from a feature AGL never asked for. An adapter that raised on an unknown tag would
        turn that release into an outage; one that returns `None` shows one fewer dashboard line.
        """
        assert activity(item, _WORKSPACE) is None

    @pytest.mark.parametrize(
        "item",
        [
            {"type": "command_execution", "command": 7},
            {"type": "command_execution"},
            {"type": "file_change", "changes": "not a list"},
            {"type": "file_change", "changes": [{"path": None}, "not an object"]},
            {"type": "file_change"},
            {"type": "web_search", "query": {"nested": "object"}},
            {"type": "mcp_tool_call"},
        ],
    )
    def test_a_field_of_the_wrong_shape_costs_the_subject_and_not_the_run(
        self, item: dict[str, JsonValue]
    ) -> None:
        """A known kind whose payload cannot be read renders the bare label, and raises nothing.

        These values were produced by a model and serialised by a harness, so neither the presence
        of a field nor its JSON type is a promise. Losing the subject is the right price; raising
        would end a run over a dashboard line. The bare label is still true - a command *is*
        running - which is why it is the answer rather than `None`.
        """
        rendered = activity(item, _WORKSPACE)
        assert rendered in {"Running", "Changing", "Calling", "Searching"}

    def test_several_changed_paths_are_listed_and_none_is_invented(self) -> None:
        """A `file_change` may carry more than one path, and each is a path the model named."""
        item: dict[str, JsonValue] = {
            "type": "file_change",
            "changes": [
                {"path": "/trees/proj/agl-fix-auth/a.kt", "kind": "add"},
                {"path": "/trees/proj/agl-fix-auth/b.kt", "kind": "delete"},
            ],
        }
        assert activity(item, _WORKSPACE) == "Changing: a.kt, b.kt"

    def test_the_verb_is_true_of_a_delete_as_well_as_an_edit(self) -> None:
        """One word per kind, chosen to cover every case the kind covers.

        `file_change.kind` is `add`, `delete` or `update`, and rendering three different verbs
        would put a per-value table where the module says there is only a per-kind one. `Changing`
        is true of all three, and `Editing` would have been false for a delete.
        """
        deleted: dict[str, JsonValue] = {
            "type": "file_change",
            "changes": [{"path": "gone.kt", "kind": "delete"}],
        }
        assert activity(deleted, _WORKSPACE) == "Changing: gone.kt"

    def test_a_path_outside_the_workspace_is_left_whole(self) -> None:
        """Only a prefix is removed, and only when it is there. Nothing is resolved or guessed."""
        item: dict[str, JsonValue] = {
            "type": "file_change",
            "changes": [{"path": "/etc/hosts", "kind": "update"}],
        }
        assert activity(item, _WORKSPACE) == "Changing: /etc/hosts"

    def test_a_multi_line_command_becomes_one_marked_line(self) -> None:
        """A heredoc is a legal command; a dashboard row is one line.

        The ellipsis is the point: without it the first line of a heredoc reads as the whole
        command, and a reader watching a build believes the agent ran something it did not.
        """
        item: dict[str, JsonValue] = {
            "type": "command_execution",
            "command": "cat > f.txt <<'EOF'\nhello\nEOF",
        }
        assert activity(item, _WORKSPACE) == "Running: cat > f.txt <<'EOF'..."

    def test_a_long_value_is_capped_and_marked(self) -> None:
        """Capped from the end, where a long command's arguments are, and marked as cut."""
        item: dict[str, JsonValue] = {"type": "command_execution", "command": "echo " + "x" * 500}
        rendered = activity(item, _WORKSPACE)
        assert rendered is not None
        assert rendered.endswith("...")
        assert len(rendered) <= len("Running: ") + 120 + len("...")

    def test_runs_of_whitespace_are_closed_up(self) -> None:
        """One line means one line: tabs and doubled spaces would otherwise reach the terminal."""
        item: dict[str, JsonValue] = {"type": "command_execution", "command": "npm\t\trun    build"}
        assert activity(item, _WORKSPACE) == "Running: npm run build"

    def test_an_mcp_call_naming_only_a_server_still_says_something(self) -> None:
        """The two fields are joined by what is there, not by a fixed shape with a hole in it."""
        item: dict[str, JsonValue] = {"type": "mcp_tool_call", "server": "agl"}
        assert activity(item, _WORKSPACE) == "Calling: agl"

    def test_the_line_is_not_the_other_adapters_shape(self) -> None:
        """§3.7's cosmetic inconsistency, asserted so that nobody later "fixes" it into agreement.

        The Claude adapter renders `Bash: ./gradlew build` because its harness's unit is a named
        tool. Codex's unit is a typed event, and there is no tool name in the frame to put there.
        Forcing this into the other vendor's shape would mean inventing one, which is the first
        entry in the table §3.7 exists to prevent.
        """
        rendered = activity(
            {"type": "command_execution", "command": "./gradlew build"},
            _WORKSPACE,
        )
        assert rendered == "Running: ./gradlew build"
        assert not rendered.startswith("Bash")


class TestTheSandboxValueIsAValueAndNotAFlag:
    """The shape of what `sandbox()` hands back, which is part of what (a) claims."""

    def test_the_mode_is_the_bare_scalar(self) -> None:
        """Not `("--sandbox", "read-only")`.

        The collapse is the interesting thing about that field - sixteen possible restriction sets,
        one value out of two - and a reader should be able to see the value rather than a
        two-element tuple. `runner.py` pairs it with the flag.
        """
        rendered = sandbox(frozenset({Restriction.NO_FILE_WRITES}))
        assert rendered.mode == "read-only"
        assert not rendered.mode.startswith("-")

    def test_the_result_is_frozen_and_comparable(self) -> None:
        """Two renderings of the same set are equal, which is what the stability tests rest on."""
        one = sandbox(frozenset({Restriction.NO_NETWORK}))
        two = sandbox(frozenset({Restriction.NO_NETWORK}))
        assert one == two
        with pytest.raises(AttributeError):
            one.mode = "danger-full-access"  # type: ignore[misc]

    def test_all_three_halves_are_produced_for_a_restricted_role(self) -> None:
        """`Sandbox` is never a subset of itself: a caller gets the mechanism and the words.

        A caller that received only the mechanism would be enforcing a boundary whose shape the
        agent cannot see - and on a machine where a managed policy substituted the sandbox mode, it
        might be enforcing nothing at all.
        """
        rendered = sandbox(frozenset({Restriction.NO_SHELL}))
        assert isinstance(rendered, Sandbox)
        assert rendered.mode
        assert rendered.options
        assert rendered.in_words
