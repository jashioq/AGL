"""`adapters/claude_code/translate.py` - the four translations, tested one at a time.

There is no contract suite here and there should not be: `AgentContract` is written against
`AgentRunner`, and this module implements no port. It is the vendor boundary underneath one - four
pure functions - so what is asserted below is what those functions produce, and the suite that
asserts what an `AgentRunner` owes runs against `runner.py` and `fake.py` at 7.2 and 7.3.

**What these tests can and cannot be.** The restriction half of the module is a claim about
another program's behaviour, and no test in this repository can settle it: asserting that
`Bash(git commit *)` appears in a tuple proves the string was produced, not that Claude Code
refuses a commit when it is handed one. That verification is a probe against the installed CLI,
recorded in the module docstring with what it covered and what it could not. So the tests below
assert two things it *can* settle - that every restriction renders something in both forms, and
that every rule obeys the permission language's own grammar as this repo understands it - and the
grammar half is deliberately written as rules rather than as a golden copy of the tuple: a test
holding an expected list of forty-five strings is a second copy of the data, and it agrees with
the first only because one person edited both.

Named `test_claude_code_translate.py`: `tests/` carries no `__init__.py` (see `tests/conftest.py`
for why it must not), so pytest's module names are the bare filenames and two files of one name
under different directories would collide at import.
"""

import re
from pathlib import Path
from typing import Any, Final

import pytest
from claude_agent_sdk import (
    ClaudeSDKError,
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    ProcessError,
    ResultError,
    ToolUseBlock,
)
from claude_agent_sdk._errors import MessageParseError

from agl.adapters.claude_code.translate import (
    Restraint,
    activity,
    model_name,
    restraint,
    translated,
    unready,
)
from agl.ports.agent import Claude, ModelId, OpenAI, Restriction
from agl.ports.errors import InputError, UpstreamUnavailable, UpstreamUnexpected

# A permission rule is `Tool` or `Tool(specifier)`, and the CLI's own validator refuses a tool
# name that does not begin with an upper-case letter unless it holds an underscore (the MCP form).
# Nothing here emits an MCP rule, so the stricter half is what is asserted.
_RULE: Final = re.compile(r"^[A-Z][A-Za-z0-9]*(\((?P<specifier>.*)\))?$")

# The tools whose *path* rules Claude Code accepts and then never consults, warning at startup:
# only `Edit(path)` and `Read(path)` are matched by the file permission checks. A bare tool name is
# a different thing - it is matched at the tool level everywhere and draws no warning - so the
# assertion below is about rules with a specifier, not about the names.
_UNCONSULTED_PATH_RULES: Final = ("Write", "NotebookEdit", "MultiEdit", "Glob")

_WORKSPACE: Final = Path("/trees/proj/agl-fix-auth")


def _call(name: str, payload: dict[str, Any]) -> ToolUseBlock:
    """One tool call, as the SDK delivers it. The id is never read and is here to satisfy it."""
    return ToolUseBlock(id="toolu_probe", name=name, input=payload)


class TestRestrictionsRender:
    """(a) Every restriction produces both halves, and the set they came from does not leak."""

    @pytest.mark.parametrize("member", list(Restriction))
    def test_every_member_renders_rules_and_words(self, member: Restriction) -> None:
        """The whole point of the module's "always both" rule, asserted per member.

        A member missing from either table would render as silence - no deny rule and no sentence -
        which is `Restriction`'s own forbidden third move, "silently dropping it". Parametrised
        over `Restriction` itself rather than over a list written here, so a member added to the
        port arrives in this test on the same commit and fails until it is rendered.
        """
        rendered = restraint(frozenset({member}))
        assert rendered.denied_tools, (
            f"{member} rendered no deny rules at all, so a Claude Code session carrying it is a "
            f"session that was never told anything about it"
        )
        assert rendered.in_words.strip(), (
            f"{member} rendered no instruction. Deny patterns do not reach every route - the "
            f"module docstring names the routes - so the sentence is the other half of the port's "
            f"'put it to the agent as an instruction', and a restriction with neither is dropped"
        )
        assert member.value not in rendered.in_words, (
            f"{member} rendered its own enum value into the prompt. The agent is told what it may "
            f"not do, in words it can act on, not handed AGL's identifier for the rule"
        )

    def test_no_restrictions_render_nothing(self) -> None:
        """An unrestricted role is `Restraint((), "")` and not a preamble introducing an empty list.

        `frozenset()` is the port's spelling of "nothing", and the honest rendering of nothing is
        nothing: an options object with an empty `disallowed_tools` and a prompt with no paragraph
        of limits in front of it.
        """
        assert restraint(frozenset()) == Restraint((), "")

    def test_all_four_together_render_every_rule_once(self) -> None:
        """The whole set, deduplicated, with each member's rules still present.

        Restrictions are "a set and not a level", so every combination has to work, and the one
        that exercises the deduplication is all of them at once.
        """
        every = restraint(frozenset(Restriction))
        assert len(every.denied_tools) == len(set(every.denied_tools)), (
            f"a deny rule was emitted twice: {sorted(every.denied_tools)}. Two restrictions may "
            f"name one rule, and a repeat is noise in a diff rather than a second refusal"
        )
        for member in Restriction:
            alone = restraint(frozenset({member}))
            assert set(alone.denied_tools) <= set(every.denied_tools), (
                f"{member} lost rules when it was combined with the others, so the combination "
                f"enforces less than one of its parts does"
            )
            assert alone.in_words.partition("\n")[2] in every.in_words

    def test_the_order_is_the_ports_and_not_the_sets(self) -> None:
        """Two equal sets built differently render identically, in `Restriction`'s own order.

        A `frozenset` of strings iterates in an order that depends on hash randomisation, so a
        result derived from the set's order would move between processes - and a `disallowed_tools`
        list that moved would show up as a difference in every log and every comparison of two
        runs. Building the same set from two orderings is what catches it.
        """
        forwards = restraint(frozenset(list(Restriction)))
        backwards = restraint(frozenset(reversed(list(Restriction))))
        assert forwards == backwards
        positions = [
            forwards.in_words.index(word)
            for word in ("version control", "delete any file", "shell commands", "the network")
        ]
        assert positions == sorted(positions), (
            "the sentences did not come out in Restriction's declaration order, which is the only "
            "ordering in this module that does not move between processes"
        )


class TestRestrictionsObeyThePermissionGrammar:
    """(a) Every rule is something Claude Code's own rule validator accepts and consults."""

    @pytest.mark.parametrize("member", list(Restriction))
    def test_every_rule_is_a_well_formed_permission_rule(self, member: Restriction) -> None:
        """`Tool` or `Tool(specifier)`, with a tool name the validator will not reject.

        The CLI's validator refuses a tool name that does not start upper-case, and a rule it
        refuses is a rule that enforces nothing. This is the cheapest half of "the deny list is
        real" and the only half a test in this repository can reach.
        """
        for rule in restraint(frozenset({member})).denied_tools:
            assert _RULE.match(rule), (
                f"{rule!r} is not of the form Tool or Tool(specifier). Claude Code's rule "
                f"validator rejects it, and a rejected deny rule is a restriction that renders "
                f"as text and enforces nothing"
            )

    def test_no_rule_uses_the_colon_star_form(self) -> None:
        """The module chose `Bash(x *)` over `Bash(x:*)`; this is what notices if one creeps back.

        They are documented as equivalent and are not: the colon form is matched as a literal
        prefix against the command, while the space form is matched with runs of whitespace
        collapsed - so `git  commit -m x`, with two spaces, defeats the first and not the second.
        The module docstring has the evidence. §1.1 quotes the colon form, which is exactly why a
        future reader copying the plan's literal into this module needs a test to stop them.
        """
        for rule in restraint(frozenset(Restriction)).denied_tools:
            assert ":*" not in rule, (
                f"{rule!r} uses the `:*` prefix form. It is matched literally, without the "
                f"whitespace collapsing the wildcard form gets, so a command spelled with two "
                f"spaces walks past it - see the module docstring"
            )

    def test_no_rule_is_a_path_rule_on_a_tool_that_ignores_them(self) -> None:
        """`Write(path)`, `NotebookEdit(path)`, `MultiEdit(path)` and `Glob(path)` are never sent.

        Claude Code accepts them, warns at startup, and never consults them: only `Edit(path)` and
        `Read(path)` are matched by the file permission checks. Those names may appear as *bare*
        rules - a bare name is matched at the tool level and draws no warning - so the assertion is
        about a specifier, which is the form that would silently do nothing.
        """
        for rule in restraint(frozenset(Restriction)).denied_tools:
            match = _RULE.match(rule)
            assert match is not None
            if match.group("specifier") is None:
                continue
            tool = rule.partition("(")[0]
            assert tool not in _UNCONSULTED_PATH_RULES, (
                f"{rule!r} is a path rule on {tool}, which Claude Code accepts, warns about, and "
                f"then never consults. Use Edit(...) for file writes and Read(...) for reads"
            )

    @pytest.mark.parametrize(
        ("member", "expected"),
        [
            (Restriction.NO_VCS_WRITES, "Bash(git commit *)"),
            (Restriction.NO_VCS_WRITES, "Bash(git push *)"),
            (Restriction.NO_FILE_WRITES, "Edit"),
            (Restriction.NO_FILE_WRITES, "Edit(//**)"),
            (Restriction.NO_SHELL, "Bash"),
            (Restriction.NO_NETWORK, "WebFetch"),
        ],
    )
    def test_the_load_bearing_rules_are_present(
        self, member: Restriction, expected: str
    ) -> None:
        """One rule per restriction that the whole thing is pointless without.

        Not a golden copy of the tuples - that would be the same list twice, agreeing because one
        person edited both. These are the specific rules the plan and the reference name:
        `Bash(git commit *)` is §1.1's constant in its new home, `Edit(//**)` is what an output
        redirect's target is checked against, and the bare names are the ones the live probe
        watched disappear from a session's tool list.
        """
        assert expected in restraint(frozenset({member})).denied_tools


class TestModelNames:
    """(b) The tier alias for a model this adapter serves, and a refusal for anything else."""

    @pytest.mark.parametrize("model", list(Claude))
    def test_every_claude_model_maps_to_an_alias(self, model: ModelId) -> None:
        """Exhaustiveness, in the only place that can hold it.

        `ModelId` is deliberately open to subclassing so the per-provider enums can extend it,
        which means no type checker can be asked whether the table below is complete. Parametrising
        over `Claude` is that question, asked here: a member added to the port fails this test
        until `translate.py` says what to run for it, rather than failing at second zero of the
        first run that names it.

        The alias is asserted to be one bare word - no dash, no digits, no date - because the
        module's argument for an alias over `claude-opus-5` is that the string tracks a tier
        rather than pinning a checkpoint, and a pinned id is what this would silently become.
        """
        name = model_name(model)
        assert name, f"{model} mapped to an empty string, which Claude Code reads as no model"
        assert re.fullmatch(r"[a-z]+", name), (
            f"{model} maps to {name!r}. The adapter sends a tier alias, not a pinned model id: an "
            f"alias tracks the recommended version for whatever provider the harness authenticates "
            f"against, and a dated id needs an edit here on every release and dies when retired"
        )

    @pytest.mark.parametrize("model", list(OpenAI))
    def test_a_model_this_adapter_does_not_serve_is_refused(self, model: ModelId) -> None:
        """§3.2: refuse, and never substitute.

        `adapters/routing.py` dispatches on `task.model.provider` and should never send one of
        these here, so arriving is already a bug - but the honest answer to it is a refusal naming
        what this adapter does serve, not a quiet run of Opus in place of Sol. The message is
        checked for the model's own spelling because a refusal that does not name what it refused
        sends the reader to the wrong declaration.
        """
        with pytest.raises(InputError) as refused:
            model_name(model)
        assert str(model) in str(refused.value)

    def test_the_refusal_says_what_is_served(self) -> None:
        """A person reading exit 2 needs the alternatives, not only the rejection."""
        with pytest.raises(InputError) as refused:
            model_name(OpenAI.SOL)
        message = str(refused.value)
        for served in Claude:
            assert str(served) in message


class TestVendorExceptions:
    """(c) Every member of the SDK's hierarchy, and the base, become an `AglError`."""

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (CLINotFoundError(), UpstreamUnavailable),
            (CLINotFoundError("not here", cli_path="/usr/local/bin/claude"), UpstreamUnavailable),
            (CLIConnectionError("could not connect"), UpstreamUnavailable),
            (ProcessError("exited badly", exit_code=2, stderr="boom"), UpstreamUnavailable),
            (ResultError("Failed to authenticate", exit_code=1), UpstreamUnavailable),
            (CLIJSONDecodeError("{not json", ValueError("line 1")), UpstreamUnexpected),
            (MessageParseError("unknown message type"), UpstreamUnexpected),
            (ClaudeSDKError("something new in a later SDK"), UpstreamUnexpected),
        ],
    )
    def test_each_class_maps_to_its_meaning(
        self, error: ClaudeSDKError, expected: type[Exception]
    ) -> None:
        """The mapping §3.1 asks for, by what a reader of the exit code should do.

        `MessageParseError` is in the list and is deliberately not named in `translate.py`: the SDK
        keeps it in `_errors` and does not export it, so the module leans on the base branch, which
        gives a parse failure the class it would have been given anyway. This test is what makes
        that a covered case rather than an untested assumption - and it reaches into the private
        module to do it, which a test may do and a shipped adapter may not.

        `ResultError` is a `ProcessError` and `CLINotFoundError` is a `CLIConnectionError`, so a
        translation written in the wrong order would answer for the parent and lose the message
        that made the child actionable. Both children are here for that reason.
        """
        translation = translated(error)
        assert type(translation) is expected, (
            f"{type(error).__name__} became {type(translation).__name__}, not {expected.__name__}"
        )

    @pytest.mark.parametrize(
        "error",
        [
            CLINotFoundError(),
            CLIConnectionError("could not connect"),
            ProcessError("exited badly", exit_code=2),
            ResultError("Failed to authenticate: OAuth session expired"),
            CLIJSONDecodeError("{not json", ValueError("line 1")),
            MessageParseError("unknown message type"),
            ClaudeSDKError(),
        ],
    )
    def test_every_translation_says_something_actionable(self, error: ClaudeSDKError) -> None:
        """A message, always, and one that names the thing that failed.

        `tests/contracts/_agent_preflight.py` asserts a non-empty refusal from `check_ready`, and
        the port asks for "a reason a person can act on". The bare `ClaudeSDKError()` is the case
        that would otherwise render as an empty string, so the fallback that puts the class name in
        is asserted rather than assumed.
        """
        message = str(translated(error))
        assert message.strip(), f"{type(error).__name__} translated to an error with no message"
        assert "Claude Code" in message or type(error).__name__ in message

    @pytest.mark.parametrize(
        "error",
        [
            CLINotFoundError(),
            CLIConnectionError("could not connect"),
            ProcessError("exited badly", exit_code=2),
            ResultError("Failed to authenticate: OAuth session expired"),
            CLIJSONDecodeError("{not json", ValueError("line 1")),
            MessageParseError("unknown message type"),
            ClaudeSDKError(),
        ],
    )
    def test_a_readiness_probe_always_answers_unavailable(self, error: ClaudeSDKError) -> None:
        """`check_ready`'s one refusal, for every way the SDK can fail a probe.

        The contract suite fails an adapter whose `check_ready` raises anything else, because §3.2's
        first preflight check catches `UpstreamUnavailable` and nothing else - anything else reaches
        the top of the CLI as exit 70 and tells the reader to file a bug about their own logged-out
        session. The two classes `translated` would call `UpstreamUnexpected` are in the list, since
        those are the ones a naive `unready = translated` would get wrong.
        """
        refusal = unready(error)
        assert isinstance(refusal, UpstreamUnavailable)
        assert str(refusal).strip()


class TestActivityStrings:
    """(d) The tool's own name, and one generic rule about the payload."""

    @pytest.mark.parametrize(
        ("name", "payload", "expected"),
        [
            (
                "Bash",
                {"command": "./gradlew build", "description": "Build"},
                "Bash: ./gradlew build",
            ),
            (
                "Read",
                {"file_path": "/trees/proj/agl-fix-auth/connectors/api/backend.ts"},
                "Read: connectors/api/backend.ts",
            ),
            ("Grep", {"pattern": "TODO", "path": "src"}, "Grep: TODO"),
            (
                "WebFetch",
                {"url": "https://example.test/a", "prompt": "what"},
                "WebFetch: https://example.test/a",
            ),
        ],
    )
    def test_the_first_string_in_the_payload_is_the_subject(
        self, name: str, payload: dict[str, Any], expected: str
    ) -> None:
        """§3.7's own examples, produced by a rule that has never heard of any of these tools.

        The rule is "the first string value, in arrival order", which is a tool's schema order,
        which puts the argument the call is about first. Four different tools with four differently
        named leading arguments, and one rule.
        """
        assert activity(_call(name, payload), _WORKSPACE) == expected

    def test_the_edit_example_from_the_plan(self) -> None:
        """`Edit: domain/usecase.kt` - the path shortened against the task's own workspace.

        The shortening is a rule about a prefix and not about which tools take paths: the value is
        chosen by arrival order, and then anything that begins with the workspace is shown relative
        to it. A worktree path is a trees root under a home directory, and repeating it down every
        row of a dashboard column spends the whole column on the part that never changes.
        """
        call = _call(
            "Edit",
            {
                "file_path": "/trees/proj/agl-fix-auth/domain/usecase.kt",
                "old_string": "a",
                "new_string": "b",
            },
        )
        assert activity(call, _WORKSPACE) == "Edit: domain/usecase.kt"

    def test_a_path_outside_the_workspace_is_left_whole(self) -> None:
        """Only a prefix is removed, and only when it is there. Nothing is resolved or guessed."""
        call = _call("Read", {"file_path": "/etc/hosts"})
        assert activity(call, _WORKSPACE) == "Read: /etc/hosts"

    def test_a_tool_this_module_has_never_heard_of_formats_anyway(self) -> None:
        """The proof that there is no table: an invented tool, an invented argument name.

        §3.7 forbids "a framework lookup table", and the adapter-level version of the same mistake
        is a table here. A name nobody could have listed, formatted correctly, is what says there
        is not one - and an MCP tool's `mcp__server__name` passes through verbatim for the same
        reason, since interpreting it would be the first entry in the table that must not exist.
        """
        assert activity(_call("Frobnicate", {"widget": "left"}), _WORKSPACE) == "Frobnicate: left"
        mcp = _call("mcp__agl__report_tickets", {"summary": "seven tickets"})
        assert activity(mcp, _WORKSPACE) == "mcp__agl__report_tickets: seven tickets"

    def test_a_payload_with_no_string_is_the_bare_tool_name(self) -> None:
        """Nothing to add is said by adding nothing, not by rendering a repr of a structure."""
        todos = _call("TodoWrite", {"todos": [{"content": "x"}]})
        assert activity(todos, _WORKSPACE) == "TodoWrite"
        assert activity(_call("Snapshot", {}), _WORKSPACE) == "Snapshot"
        assert activity(_call("Wait", {"seconds": 30}), _WORKSPACE) == "Wait"

    def test_an_empty_or_blank_string_is_skipped_rather_than_shown(self) -> None:
        """A blank leading argument would render `Bash: ` - a colon with nothing after it."""
        assert activity(_call("Bash", {"description": "   ", "command": "ls"}), _WORKSPACE) == (
            "Bash: ls"
        )

    def test_a_multi_line_value_becomes_one_marked_line(self) -> None:
        """A heredoc is a legal command; a dashboard row is one line.

        The ellipsis is the point: without it, the first line of a heredoc reads as the whole
        command, and a reader watching a build believes the agent ran something it did not.
        """
        call = _call("Bash", {"command": "cat > f.txt <<'EOF'\nhello\nEOF"})
        assert activity(call, _WORKSPACE) == "Bash: cat > f.txt <<'EOF'..."

    def test_a_long_value_is_capped_and_marked(self) -> None:
        """Capped from the end, where a long command's arguments are, and marked as cut."""
        rendered = activity(_call("Bash", {"command": "echo " + "x" * 500}), _WORKSPACE)
        assert rendered.endswith("...")
        assert len(rendered) <= len("Bash: ") + 120 + len("...")

    def test_runs_of_whitespace_are_closed_up(self) -> None:
        """One line means one line: tabs and doubled spaces would otherwise reach the terminal."""
        call = _call("Bash", {"command": "npm\t\trun    build"})
        assert activity(call, _WORKSPACE) == "Bash: npm run build"
