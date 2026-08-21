"""Claude Code's own vocabulary, spoken here and nowhere above it.

`adapters/claude_code/` is AGL's `AgentRunner` over Claude Code, and this module is the whole of
the vendor boundary inside it: four translations, in both directions, with no I/O, no session, no
subprocess and nothing to await. `runner.py` drives the harness; everything it has to *say* in
Claude Code's language and everything it has to *read* in Claude Code's language is a call in
here, and every value that leaves is plain Python or an `agl.ports` type.

The reason it is one module rather than four is §1.1, which records what happens when a vendor's
vocabulary is not confined to one place. A tuple of strings in Claude Code's permission language
had reached two layers up into a workflow (`GIT_WRITES = ("Bash(git commit:*)", ...)`); an approval
mode was crossing the port as an unvalidated string; the port's model enum was a list of one
vendor's product names. All three now stop at this file. Somebody asking "does anything outside
`agl.adapters.claude_code` know what Claude Code calls things?" has one file to read, and
`.importlinter`'s contract 3 keeps the SDK import in the same package.

## Why this is over the project's 300-line convention

`scripts/check`'s size gate is a warning that asks whether a module still holds one idea. This one
does - it is the translation table between two vocabularies, and the four entries are four
crossings of the same boundary. Split, `Restriction` rendering would sit in one file and exception
translation in another, and the next reader looking for "what does AGL say to Claude Code, and
what does it make of what comes back" would have to find both halves and hope there were only two.

Most of the length is argument, not code. Three of the four translations are a *decision* no type
can check - a deny pattern Claude Code does not honour compiles perfectly and silently enforces
nothing - so what a reader needs from this file is the reasoning and the evidence that produced
the strings, which is what the next four sections are.

## (a) `Restriction` -> deny patterns: how the syntax was verified

Nothing below was written from memory. Four sources, in increasing order of how much they settle:

1. **`claude --help`** (CLI 2.1.220). `--disallowedTools <tools...>`: "Comma or space-separated
   list of tool names to deny (e.g. "Bash(git *) Edit")". That fixes the shape - `Tool`, or
   `Tool(specifier)` - and nothing else.
2. **The published permission reference** (`code.claude.com/docs/en/permissions`). Rules resolve
   deny, then ask, then allow, first match wins, and "a deny rule can't carry allowlist
   exceptions". A bare tool name in a deny rule "removes the tool from Claude's context entirely,
   so Claude never sees it". A trailing ` *` "enforces a word boundary, requiring the prefix to be
   followed by a space or end-of-string" - so `Bash(git commit *)` matches the bare `git commit`
   too, which a rule that only matched `git commit <something>` would not. Deny rules are matched
   against each subcommand of a compound command independently, and match past a leading
   environment assignment (`FOO=bar rm -rf tmp/`). A fixed wrapper list - `timeout`, `time`,
   `nice`, `nohup`, `stdbuf`, `command`, `builtin`, `noglob`, bare `xargs` - is stripped before
   matching, and `watch`, `setsid`, `flock`, `npx`, `docker exec` and `find -exec` are not.
3. **The shipped binary's own validator and matcher.** The macOS build is a JavaScript bundle, so
   `strings` over it reads the rule classifier (`/^(.+):\\*$/` -> a *prefix* rule; an unescaped `*`
   elsewhere -> a *wildcard* rule; otherwise *exact*), the glob compiler, and the branch that
   applies each. This is where the spelling was decided - see the next section.
4. **A live probe through `claude_agent_sdk` 0.2.140 against the installed CLI**, reading the tool
   list off the `init` message, which arrives before any model call and so costs nothing. With no
   deny rules the session registered `Bash, Edit, EnterWorktree, ExitWorktree, Monitor,
   NotebookEdit, Read, WebFetch, WebSearch, Write` among others. Denying ten bare names removed
   the eight of them that were registered - `Bash`, `Edit`, `EnterWorktree`, `Monitor`,
   `NotebookEdit`, `WebFetch`, `WebSearch`, `Write` - from the list, while `ExitWorktree`, which
   was not denied, stayed: the control that makes it the rules doing it rather than the session
   being different. The two names that were denied and did not appear either way, `PowerShell` and
   `MultiEdit`, are not registered in this build - see `_DENIALS` for why they are denied anyway.
   This is the documented "removes the tool from Claude's context" claim observed rather than
   believed, and it is why the tool-shaped rules below are the ones this module leans on.

**What could not be verified, and so is not claimed.** The end-to-end experiment - deny
`Bash(git commit *)`, ask the agent to commit, watch the call be refused - did not run: the CLI on
the machine this was written on answers `Failed to authenticate: OAuth session expired and could
not be refreshed`, which is itself the case `unready` exists to report. So the patterns are
verified as syntax Claude Code parses, classifies and matches in a way this module has read, and
as tool names that provably disappear from a session; they are not verified as a refusal observed
end to end.

## Why every Bash rule is spelled `Bash(git commit *)` and not `Bash(git commit:*)`

§1.1 quotes the old constant as `Bash(git commit:*)`, and the reference calls the two forms
equivalent: "The `:*` suffix is an equivalent way to write a trailing wildcard". They are not
quite equivalent, and the gap is in the direction that matters.

In the shipped matcher a rule ending `:*` is a **prefix** rule, compared literally: lower-case the
command, then `command == prefix or command.startswith(prefix + " ")`. A rule holding an unescaped
`*` and not ending `:*` is a **wildcard** rule, compiled to a regular expression and matched
against the command *with runs of spaces and tabs collapsed on both sides*, with a single trailing
` *` rewritten into an optional `( .*)?` group. Two consequences, both favouring the wildcard form:

  * `git  commit -m x`, with two spaces, matches `Bash(git commit *)` and does **not** match
    `Bash(git commit:*)`. The reference's own warning about fragile Bash patterns lists "Extra
    spaces" as a way a rule fails to match; in a deny rule a failure to match is a restriction
    silently dropped, which is the one outcome this module exists to prevent.
  * A `*` inside a `:*` prefix is a literal asterisk, so that form could not be extended to reach
    `git -C … commit` even in principle. The wildcard form could.

The CLI's own validator also prints the colon form labelled "prefix matching (legacy)" when it
rejects a misplaced one, offering the space form beside it. So the plan's literal is deliberately
not reproduced, and every rule goes through `_bash()` so the choice is one line if it ever moves.

## Why an instruction is produced for every restriction, always

`Restriction`'s docstring settles what a backend owes a limit it cannot enforce: "A backend with no
way to enforce one has two honest moves and no third: put it to the agent as an instruction, or
refuse the task. Silently dropping it is neither." Deny patterns are half of the first move, and
they are demonstrably not the whole of it:

  * **`NO_FILE_WRITES`.** Denying `Edit`, `Write` and `NotebookEdit` takes the file tools out of
    the session, and `Edit(//**)` is what a shell output redirect's target is checked against - the
    reference says a redirect target such as `>` or `>>` is "checked ... as a file write" covering
    "your `Edit` allow and deny rules". Neither reaches a program that opens a file itself: "Read
    and Edit deny rules ... don't apply to arbitrary subprocesses that read or write files
    indirectly, like a Python or Node script that opens files itself."
  * **`NO_NETWORK`.** The reference is blunt: "using WebFetch alone doesn't prevent network access.
    If Bash is allowed, Claude can still use `curl`, `wget`, or other tools to reach any URL."
  * **`NO_VCS_WRITES`.** The subcommand list below is matched against text beginning `git `, so
    `/usr/bin/git commit`, `sh -c 'git commit'`, a `git` alias, and any wrapper outside the built-in
    strip list all walk past it.
  * **`NO_SHELL`.** The bare-name denials are the strongest thing here and the probe shows the
    tools vanish - but the set of tools that can run a command is Claude Code's to grow, and this
    file names the ones that existed at 2.1.220. `Monitor` is in the list only because the
    PowerShell tool's own refusal message says so ("Monitor runs bash"); nothing announced it.

**Rejected: producing the instruction only where a gap is known.** It is the tempting design and it
would have made `NO_SHELL` silent, since bare-name denial removes the tool rather than pattern-
matching an argument. It was rejected because the condition is a claim of completeness that this
file cannot keep: a tool registry grows between releases, a subagent's inheritance of session deny
rules was not verified here, and a conditional would put the honesty of one restriction inside a
judgement made in this file about a vendor's roadmap. Saying it in words as well costs one line of
prompt - measured against a restriction that quietly stopped applying, that is not a cost. It also
means the caller can never be handed a partial deny list that looks whole: it gets both, always.

**Why `git` is enumerated and `curl` is not.** Both enumerations are incomplete, so the difference
has to be a principle rather than an appetite. It is this: `git` is one program with a fixed,
documented subcommand vocabulary, and what `NO_VCS_WRITES` forbids is that program's writing half -
there is no second `git`, so the enumeration is closed on the axis that matters even though its
spelling is not. "Writes a file" and "reaches the network" are capabilities of *every program on
the machine* - `python`, `perl`, `node`, `awk`, `ed` - so a list that stopped at `curl`, `wget`,
`tee` and `rm` would enumerate nothing in particular while reading, to the next person, like a
boundary. Where no list can be finished, this module denies the *tools* and says the rest in words.

## (b) `ModelId` -> model string: an alias, not a dated id

`Claude.OPUS` becomes `"opus"`, not `"claude-opus-5"`. The reference: "Aliases point to the
recommended version for your provider and update over time. To pin to a specific version, use the
full model name, for example `claude-opus-5`." A pin is exactly what AGL must not express here. The
port's members are a *tier* - a workflow author writing `model=Claude.OPUS` beside a prompt is
saying "this role needs deep judgement" (§3.2), not naming a checkpoint - so the honest rendering
is the alias that tracks the tier. A dated id would need an edit in this file on every model
release, and a retired one is a run that dies at second zero for a reason its workflow author
cannot fix from the workflow.

The second half of the argument is that nothing is lost by moving: this string is not a stored
format. A step's fingerprint (§3.6) is canonical JSON over the role, which holds `Claude.OPUS`, the
port's own value; the string below never reaches it. So the alias is free to resolve differently
next month without invalidating a single recorded step - unlike the `StrEnum` values in
`ports/agent.py`, which are pinned for exactly that reason.

Known and accepted: an alias resolves to different versions on different providers (the reference
tabulates Anthropic API, Bedrock, Vertex and Foundry separately), and AGL inherits whichever the
operator's harness authenticates against (§3.2.1). That is the same inheritance as billing, and it
belongs to the harness rather than to this file.

An unknown or unserved `ModelId` - including every `OpenAI` member, which this adapter does not
serve and `adapters/routing.py` should never have sent here - is an `InputError` and never a
substitution (§3.2). Substituting would answer a question about Opus with a run of something else.

## (c) Vendor exceptions -> `AglError`

§3.1: "Adapters translate vendor exceptions at their boundary; nothing above an adapter sees one."
The mapping is by what the reader of an exit code should do, which is `errors.py`'s own rule:

  * **Nothing started, or the far side never got to answer** -> `UpstreamUnavailable` (6), whose
    promise is that "the same call may well succeed later". The CLI missing from `PATH`, a
    connection that could not be made, a process that exited reporting a terminal error - a
    logged-out session arrives here, as this module's author found out.
  * **It answered and the answer cannot be read** -> `UpstreamUnexpected` (6), where "our
    understanding of it is what failed" and retrying unchanged gets the same answer. Undecodable
    JSON on the CLI's stream is this exactly.

`ClaudeSDKError` itself - an SDK error on a branch this file does not name - is
`UpstreamUnexpected`, and the choice is deliberate: `UpstreamUnavailable` carries a *promise* about
retrying, and a promise made about an exception nobody here has read is worse than declining to
make one. The class name goes into the message so a person can act on it anyway.

**`MessageParseError` is covered and deliberately not named.** The SDK defines it in `_errors` and
does not export it from the package, and importing a private module to catch it would trade a
correct answer for an import that a patch release can delete. It is a parse failure, so the base
branch already answers `UpstreamUnexpected` - the class it would be given if it were named -
and `tests/adapters/test_claude_code_translate.py` reaches into `_errors` to prove that, which is
a nosy test rather than a fragile import.

## (d) Tool calls -> activity strings: one generic rule, no table

§3.7: "Each adapter formats its own activity line from the tool calls it sees ... No shared verb
taxonomy, no `Activity` type, no framework lookup table." What that forbids is a mapping from a
tool's name to an English verb ("Running...", "Editing...") and a per-tool table of which payload
key is the interesting one. Both would be this adapter accumulating an opinion about a vendor's
tool set that the next vendor's adapter would then have to mirror.

So the tool's own name passes through verbatim, and the payload is summarised by one rule that
names no tool: **the first string value in the payload, in the order it arrived.** JSON objects
keep their order through the SDK, and a tool's arguments arrive in its schema's order, which puts
the argument the tool is *about* first - `command` for Bash, `file_path` for Edit and Read,
`pattern` for Grep, `url` for WebFetch, `description` for a subagent call. That reproduces §3.7's
three examples (`Bash: ./gradlew build`, `Edit: domain/usecase.kt`,
`Read: connectors/api/backend.ts`) without this file having heard of any of those tools.

Two further rules, both about the *value* and neither about the tool: a value beginning with the
task's workspace is shown relative to it, because an absolute worktree path is eighty characters of
noise in a dashboard cell that has room for one line; and the result is collapsed to one line and
capped, because a heredoc is a legal `command`. A payload with no string value at all renders as
the bare tool name, which is the honest thing to say about a call there is nothing to add about.

Known cost, and it is cosmetic by §3.7's own account: a tool whose schema happens to lead with a
large field renders that field's first line. Nothing branches on this string - the port passes it
through untouched, it is never persisted, and a replayed step correctly has none at all.

## What this module deliberately does not do

**No `ClaudeAgentOptions`.** Building the options object is `runner.py`'s, because it also carries
the hermeticity settings (§3.5), the workspace and the tool server - none of which is a
translation. This module produces the values that object's fields take and holds no SDK type.

**No permission mode, and no reading of `plan_only`.** `plan_only` is a *task* field, and choosing
a harness mechanism for it is a decision about how to run one, which is `runner.py`'s. §1.1's
charge was an approval mode crossing the port; a mode invented in this file would at least be on
the right side of it, but it would still be a run-shaping decision inside a pure translation.

**No `Question` mapping.** §3.7's mid-run question path needs the SDK's tool machinery and a live
session to answer back into, which is a session concern rather than a translation.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from claude_agent_sdk import (
    ClaudeSDKError,
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    ProcessError,
    ResultError,
    ToolUseBlock,
)

from agl.ports.agent import Claude, ModelId, Restriction
from agl.ports.errors import AglError, InputError, UpstreamUnavailable, UpstreamUnexpected

__all__ = [
    "Restraint",
    "activity",
    "model_name",
    "restraint",
    "translated",
    "unready",
]


def _bash(*commands: str) -> tuple[str, ...]:
    """Deny rules for command lines beginning with each of `commands`.

    The one place the permission language's wildcard is spelled, so that the module docstring's
    argument for the space form over `:*` is a single edit rather than forty. A trailing ` *`
    enforces a word boundary and admits the bare command, so `_bash("git commit")` covers both
    `git commit` and `git commit -m ...` while leaving `git commitfoo` alone.
    """
    return tuple(f"Bash({command} *)" for command in commands)


# The git subcommands that change something: the working tree, the index, the object store, a ref,
# a remote, a worktree, or git's own configuration. Grouped by what they change rather than by
# porcelain and plumbing, because the reason each one is here is what it writes.
#
# `config` is in the list on §3.5's evidence, which is not theoretical: a user's git configuration
# changes what a merge means - `pull.twohead = ours` lands none of the child's work and exits 0 -
# so an agent editing it is an agent editing the meaning of AGL's own integration. It costs the
# read-only `git config --get`, which is the cheapest thing in the list to lose.
#
# What this cannot cover is in the module docstring: the rules match text beginning `git `, so any
# other spelling of the same program walks past. That is why the instruction is produced too.
_GIT_WRITES: Final = (
    # The working tree, the index, or the branch's history.
    "git add",
    "git am",
    "git apply",
    "git bisect",
    "git branch",
    "git checkout",
    "git cherry-pick",
    "git clean",
    "git commit",
    "git merge",
    "git mv",
    "git notes",
    "git rebase",
    "git reset",
    "git restore",
    "git revert",
    "git rm",
    "git stash",
    "git switch",
    "git tag",
    # What the repository is: its objects, its remotes, its config, its worktrees, its location.
    "git clone",
    "git config",
    "git fetch",
    "git filter-branch",
    "git gc",
    "git init",
    "git maintenance",
    "git prune",
    "git pull",
    "git push",
    "git reflog",
    "git remote",
    "git repack",
    "git replace",
    "git sparse-checkout",
    "git submodule",
    "git worktree",
    # Plumbing that writes an object or a ref without going through any of the above.
    "git commit-tree",
    "git fast-import",
    "git hash-object",
    "git mktag",
    "git mktree",
    "git symbolic-ref",
    "git update-index",
    "git update-ref",
    "git write-tree",
)


# What each restriction denies. Bare tool names come first in each tuple because they are the
# strong half - a denied bare name is removed from the session's tool list, which the live probe
# in the module docstring observed - and the pattern rules after them are the best this module can
# do about a shell, which is the weak half and is why `_IN_WORDS` exists.
_DENIALS: Final[Mapping[Restriction, tuple[str, ...]]] = MappingProxyType(
    {
        # `EnterWorktree`/`ExitWorktree` are Claude Code's own git-worktree management, and §3.9
        # gives worktrees to AGL: an agent that makes or lands one is writing to version control
        # through a tool rather than through `git`, which is exactly what the pattern rules cannot
        # see. Both are denied, not only the first, because leaving a session is as much a write
        # as entering one and denying half a pair reads like an oversight.
        Restriction.NO_VCS_WRITES: ("EnterWorktree", "ExitWorktree", *_bash(*_GIT_WRITES)),
        # `MultiEdit` was not registered in the probed session - the reference calls it "the
        # legacy MultiEdit tool" - and is denied anyway. A rule naming a tool that does not exist
        # costs a startup warning; a tool that exists and is not named costs the restriction. The
        # two are not the same size. `Edit(//**)` is the path rule: an output redirect's target is
        # checked as a file write against `Edit` rules, and `//` anchors at the filesystem root
        # rather than at the settings source, so it covers a target outside the workspace too.
        Restriction.NO_FILE_WRITES: ("Edit", "Write", "NotebookEdit", "MultiEdit", "Edit(//**)"),
        # `PowerShell` is opt-in outside Windows and was absent from the probed session; it is
        # named for the same reason as `MultiEdit`. `Monitor` is here because the PowerShell tool's
        # own refusal message says "Monitor runs bash" - nothing in the permission reference
        # mentions it, which is the module docstring's point about a tool set that grows.
        Restriction.NO_SHELL: ("Bash", "PowerShell", "Monitor"),
        # The two network tools, and nothing about the shell: see "Why `git` is enumerated and
        # `curl` is not". The reference says in as many words that denying these does not prevent
        # network access while Bash is available.
        Restriction.NO_NETWORK: ("WebFetch", "WebSearch"),
    }
)


# The same four limits in AGL's own words, for the half no pattern reaches. Each is one imperative
# sentence naming the *effect* rather than a mechanism - a model told "do not use the Edit tool"
# has been told about a tool it cannot see, and learns nothing about the shell redirect that is
# the actual hole.
_IN_WORDS: Final[Mapping[Restriction, str]] = MappingProxyType(
    {
        Restriction.NO_VCS_WRITES: (
            "Do not change version control in any way: no commits, no staging, no branches, "
            "tags, merges, rebases, resets, stashes, pushes, fetches, worktrees or changes to "
            "git configuration. Leave your work as edits in the working tree; AGL records it."
        ),
        Restriction.NO_FILE_WRITES: (
            "Do not create, modify, move or delete any file, by any route - not with an editing "
            "tool, not with a shell redirect, and not by running a program that writes one."
        ),
        Restriction.NO_SHELL: (
            "Do not run shell commands, by any route, including through another tool that runs "
            "one for you."
        ),
        Restriction.NO_NETWORK: (
            "Do not reach the network, by any route - no fetching pages, no downloads, no "
            "package installs, and no program that opens a connection for you."
        ),
    }
)


# What the sentences are introduced by. It says whose limits they are and that they are not the
# tool list's leftovers, because a model that can see it has no Bash tool and is then told not to
# run shell commands should read that as one statement rather than as a contradiction to resolve.
_PREAMBLE: Final = (
    "AGL places the following limits on this task. They hold whatever the tools available to you "
    "appear to allow, they are not negotiable, and working around one is a failed task rather "
    "than a solved one:"
)


# How much of a tool call's payload reaches an activity line. One dashboard cell, one line: long
# enough for a build command or a path from a repository root, short enough not to wrap. What is
# cut is cut from the end, where a long command's arguments are, rather than from the middle.
_ACTIVITY_LIMIT: Final = 120


# The model aliases, and the whole of what this adapter serves. An alias rather than a dated id -
# the module docstring argues it - and a mapping rather than a `match`, because `ModelId` is
# deliberately open to subclassing (`ports/agent.py`) so exhaustiveness is not a property any type
# checker could be asked about. `tests/adapters/test_claude_code_translate.py` asserts every
# `Claude` member has an entry, which is the same guarantee in the place that can hold it.
_MODEL_NAMES: Final[Mapping[ModelId, str]] = MappingProxyType(
    {
        Claude.OPUS: "opus",
        Claude.SONNET: "sonnet",
        Claude.HAIKU: "haiku",
    }
)


@dataclass(frozen=True, slots=True)
class Restraint:
    """A role's restrictions in the two forms Claude Code will take them, and both are produced.

    Never one or the other. `denied_tools` is what the harness enforces and `in_words` is what the
    agent is told, and the module docstring argues at length why a caller gets both for every
    restriction rather than whichever this file judged sufficient. A caller that used only the
    first would be enforcing a subset while believing it had a boundary, which is the failure
    `Restriction`'s own docstring rules out.
    """

    denied_tools: tuple[str, ...]
    """Straight into `ClaudeAgentOptions.disallowed_tools`, in a fixed order and without repeats.

    Ordered by `Restriction`'s declaration order rather than by the set's iteration order, because
    a `frozenset` of strings iterates in an order that changes between processes and a tuple that
    moved between two runs would show up as a difference in every log and every test that compared
    two of them."""

    in_words: str
    """The same limits as prose for the agent, or `""` when there were no restrictions at all.

    Where it goes is `runner.py`'s to decide - a system prompt, the head of the instructions,
    whatever the harness offers - because that is a question about how a session is composed. What
    is settled here is that it must reach the agent: a `Restraint` whose `in_words` is dropped is
    a partial deny list presented as a whole one."""


def restraint(restrictions: frozenset[Restriction]) -> Restraint:
    """Render a role's restrictions into deny patterns and the sentences that go with them.

    Total: every member of `Restriction` has an entry in both tables above, and an empty set is
    the honest `Restraint((), "")` rather than a preamble introducing nothing.

    Iteration is over `Restriction` and not over the argument, which is what makes the result
    stable: enum members iterate in declaration order, a `frozenset` does not. Duplicates are
    dropped while keeping first-seen order, because two restrictions may name one rule - a role
    with both `NO_VCS_WRITES` and `NO_NETWORK` names `git fetch` once from one of them - and a
    repeated deny rule is noise in a diff rather than a second refusal.
    """
    denied: list[str] = []
    spoken: list[str] = []
    for member in Restriction:
        if member not in restrictions:
            continue
        for rule in _DENIALS[member]:
            if rule not in denied:
                denied.append(rule)
        spoken.append(f"- {_IN_WORDS[member]}")
    if not spoken:
        return Restraint((), "")
    return Restraint(tuple(denied), "\n".join([_PREAMBLE, *spoken]))


def model_name(model: ModelId) -> str:
    """What Claude Code should be asked to run for `model`. Raises `InputError` for anything else.

    The refusal is the interesting half. §3.2: "An adapter handed a `ModelId` it does not serve
    raises `InputError`; it never silently substitutes." Every `OpenAI` member lands here, and so
    would a `Claude` member added to the port without a line in `_MODEL_NAMES` - which is the
    right failure for that mistake, since answering a request for a model AGL cannot serve with a
    run of a different one produces work nobody asked for and a result nobody can read.

    `InputError` rather than `NotFoundError` or `InternalError`, and the port settles it: a model
    is named by a workflow author declaring a role, nothing has been attempted when this refuses,
    and exit 2 sends the reader to the declaration rather than to a bug report against AGL.
    """
    name = _MODEL_NAMES.get(model)
    if name is None:
        served = sorted(str(member) for member in _MODEL_NAMES)
        raise InputError(
            f"the Claude Code adapter cannot run {str(model)!r}: it serves {served} and nothing "
            f"else. It will not stand in another model for this one - the model was named beside "
            f"the prompt because the choice was semantic, and substituting answers a different "
            f"question than the one the workflow asked"
        )
    return name


def translated(error: ClaudeSDKError) -> AglError:
    """What an SDK exception means in `errors.py`'s vocabulary. Returned, so call sites `raise`.

    Returned rather than raised for `_runner.py`'s reason: a call site reading
    `raise translated(error) from error` says which line failed, and chains the original so that
    the vendor exception survives in the traceback while never being what a caller catches.

    Ordered most specific first, because the SDK's classes nest - `CLINotFoundError` is a
    `CLIConnectionError`, `ResultError` is a `ProcessError` - and the broad branch would otherwise
    swallow the specific one along with the message that made it actionable.
    """
    if isinstance(error, CLINotFoundError):
        return UpstreamUnavailable(
            f"the Claude Code CLI is not installed or is not on PATH: {_said(error)}. Nothing "
            f"was attempted, so this is not a failed task - install Claude Code, or point AGL at "
            f"an existing installation, and the same call may well succeed"
        )
    if isinstance(error, CLIConnectionError):
        return UpstreamUnavailable(
            f"AGL could not open a session with the Claude Code CLI: {_said(error)}. Nothing "
            f"reached a model, so the same call may well succeed once the CLI can be started"
        )
    if isinstance(error, ResultError):
        return UpstreamUnavailable(
            f"the Claude Code CLI stopped and reported an error instead of a result: "
            f"{_said(error)}. A session that is not authenticated, an exhausted allowance and an "
            f"unusable request all arrive this way, so the message above is the part to act on"
        )
    if isinstance(error, ProcessError):
        return UpstreamUnavailable(
            f"the Claude Code CLI exited without answering: {_said(error)}. Nothing usable came "
            f"back from the far side, so the same call may well succeed once whatever stopped it "
            f"is fixed"
        )
    if isinstance(error, CLIJSONDecodeError):
        return UpstreamUnexpected(
            f"the Claude Code CLI answered with something AGL cannot read: {_said(error)}. The "
            f"CLI is working and this adapter's reading of it is not, so the same call will "
            f"answer the same way - this is a version mismatch or an AGL bug, not a busy backend"
        )
    return UpstreamUnexpected(
        f"the Claude Code SDK raised {type(error).__name__}, which this adapter has no specific "
        f"reading of: {_said(error)}. It is reported as an answer AGL could not act on rather "
        f"than as a backend that was unreachable, because promising that a retry may help is a "
        f"promise nothing here can keep for an error it has not seen before"
    )


def unready(error: ClaudeSDKError) -> UpstreamUnavailable:
    """What an SDK exception means when it was raised by a readiness probe. Always unavailable.

    `AgentRunner.check_ready` has one refusal - "Raise `UpstreamUnavailable` with a reason a person
    can act on" - and `tests/contracts/_agent_preflight.py` fails an adapter that raises anything
    else, because §3.2's first preflight check catches that class and nothing else: any other
    exception reaches the top of the CLI as exit 70 and tells the reader to file a bug about their
    own logged-out session.

    So this is not `translated` with a different name. A probe attempts nothing and asks only
    whether the harness could serve a run; every way of failing that question is the same answer -
    not now - including the ones `translated` would call `UpstreamUnexpected`, since a CLI whose
    output this adapter cannot parse is a CLI this adapter cannot run against either. What varies
    is the reason, which is why the message is `translated`'s and only the class is fixed.
    """
    reported = translated(error)
    if isinstance(reported, UpstreamUnavailable):
        return reported
    return UpstreamUnavailable(
        f"the Claude Code CLI is installed but did not answer a readiness check in a way AGL "
        f"could use: {reported}"
    )


def activity(call: ToolUseBlock, workspace: Path) -> str:
    """What to show while `call` is running: the tool's own name, and one line about the payload.

    `Bash: ./gradlew build`, `Edit: domain/usecase.kt`, `TodoWrite`. The name passes through
    verbatim, including an MCP tool's `mcp__server__name` - §3.7 gives the router no licence to
    interpret this string, so neither does the adapter that makes it - and the payload goes
    through the one generic rule the module docstring argues for, which names no tool.

    `workspace` is the task's, and is used only to shorten a value that starts with it. Passing it
    is what keeps the shortening a rule about a path prefix rather than a rule about which tools
    take paths, which would be the lookup table §3.7 forbids wearing a different hat.
    """
    subject = _subject(call.input, workspace)
    return f"{call.name}: {subject}" if subject else call.name


def _subject(payload: Mapping[str, Any], workspace: Path) -> str:
    """The first string value in `payload`, shortened for one line. `""` when there is none.

    In arrival order, which is a tool's schema order, which puts the argument the call is about
    first. A payload of numbers, lists or objects and no string at all - a batch of todos, a set
    of coordinates - has nothing worth a line, and says so by returning nothing rather than by
    rendering a repr of a structure.
    """
    for value in payload.values():
        if isinstance(value, str) and value.strip():
            return _shortened(_relative(value.strip(), workspace))
    return ""


def _relative(text: str, workspace: Path) -> str:
    """`text` without the workspace it sits in, when it begins with one. Otherwise unchanged.

    A prefix test and nothing more: no `Path` is built, nothing is resolved, and no filesystem is
    touched, because this runs on a value an agent chose and a value an agent chose is not a
    promise that anything is there. §3.7's examples are relative because a run's worktree lives
    under a trees root under a home directory, and an eighty-character prefix repeated down a
    dashboard column is the same eighty characters in every row.
    """
    prefix = f"{workspace}{os.sep}"
    return text[len(prefix) :] if text.startswith(prefix) and len(text) > len(prefix) else text


def _shortened(text: str) -> str:
    """One line of `text`, with runs of whitespace closed up, capped, and marked when it was cut.

    A `command` can be a heredoc and a `prompt` can be a paragraph, so the first line is taken and
    the rest is represented by the ellipsis rather than dropped silently: a reader seeing
    `Bash: cat > file.txt <<'EOF'...` knows there was more, where the same line without the mark
    would read as the whole command.
    """
    first, newline, _ = text.partition("\n")
    line = " ".join(first.split())
    cut = bool(newline)
    if len(line) > _ACTIVITY_LIMIT:
        line, cut = line[:_ACTIVITY_LIMIT].rstrip(), True
    return f"{line}..." if cut else line


def _said(error: ClaudeSDKError) -> str:
    """Whatever the SDK put in the exception, as something a message can hold. Never empty.

    `tests/contracts/_agent_preflight.py` asserts `check_ready`'s refusal carries a message, and
    "an `UpstreamUnavailable()` carrying nothing is the same dead end as no message at all". Some
    of these classes are constructed with no arguments at all, so the class name is the fallback:
    it is thin, and it is the difference between a reader who knows what to search for and one
    with a blank line.

    Nothing here reaches for the structured fields beside the message. `CLINotFoundError` folds the
    path it looked at into its own text, and `ProcessError` folds in the exit status and the
    standard error - so re-reading `cli_path` and `exit_code` would print each of them twice, and
    would be this module depending on two more pieces of a surface it depends on quite enough of.
    """
    said = str(error).strip()
    return said or f"{type(error).__name__}, with nothing said about why"
