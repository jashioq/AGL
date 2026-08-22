"""The Codex CLI's own vocabulary, spoken here and nowhere above it.

`adapters/openai/` is AGL's `AgentRunner` over the Codex CLI, and this module is the whole of the
vendor boundary inside it: four translations, in both directions, with no I/O, no subprocess, no
stream and nothing to await. `runner.py` drives the binary; everything it has to *say* in Codex's
language and everything it has to *read* in Codex's language is a call on this module's surface,
and every value that leaves is plain Python or an `agl.ports` type. That the vocabulary is
confined at all is §1.1's requirement, and there is no import to contain here - the harness is a
binary, not a package - so `.importlinter` has nothing to say about this adapter and
`scripts/check`'s gate 5 stands in for it.

**The two translations that read are in `_reading.py`, and this module re-exports them**, so a
caller still has one import and one place to look. The split is by obligation rather than by line
count. What is *said* has to be total: every subset of `Restriction` renders to exactly one
sandbox mode, every served `ModelId` to exactly one slug, and anything else is refused rather than
guessed. What is *read* has the opposite duty - it must never raise on something it did not
expect, because an unfamiliar frame kind or a field of an unfamiliar JSON type is a harness
release rather than a failure. Two rules that strict and that opposed do not belong in one
reader's head at once, and the halves have no code in common.

**Every measurement cited below is free and none of it spent a token.** `codex exec` was never run.
The instruments are `--help`, the subcommands that provably reach no model (`debug prompt-input`,
`features list`, `mcp list`, `login status`), the shipped 0.149.0 binary's string pool, and
`docs/codex-cli-findings.md`. Where a claim rests on that document's *inference* rather than on a
measurement, the word "inferred" or "unverified" stands beside it.

## (a) `Restriction` -> a sandbox mode: a set collapsed onto a scalar, totally and visibly

`Restriction` is a set of four independent members; `sandbox_mode` is one value. The collapse is
this adapter's arithmetic - the findings record it as such (§9, pressure 9) so it is not later
blamed on the port - and it turns on exactly one membership test:

| `NO_FILE_WRITES` | `NO_NETWORK` | mode | network override |
|---|---|---|---|
| in the set | either | `read-only` | none: it would do nothing (measured) |
| absent | in the set | `workspace-write` | `network_access=false` |
| absent | absent | `workspace-write` | `network_access=true` |

Sixteen subsets, three rows, one branch. `NO_VCS_WRITES` and `NO_SHELL` never move the mode, for
reasons that are different from each other.

**`NO_FILE_WRITES` -> `read-only`. Exact, and it over-restricts.** That mode permits reading and
nothing else - and it also takes the network, with no knob that gives it back. Measured from two
directions: the findings ran `curl` under `codex sandbox` and watched
`sandbox_workspace_write.network_access=true` make no difference under `read-only`; and rendering
the model-visible prompt for this module with that override set and unset gives a byte-identical
`<permission_profile>` (`5d2937a4a5a7`) and the same sentence either way, *Network access is
restricted*. Under `workspace-write` the same override flips it to *Network access is enabled*.

So `{NO_FILE_WRITES}` without `NO_NETWORK` is enforced harder than it was declared, and **the port
has no way to say so.** `Restriction`'s docstring gives an adapter two honest moves for a limit it
cannot *enforce* - mechanism, or words - and says nothing about the opposite; there is nothing
useful to tell the agent either, since warning it about a wall it will not walk into is noise. So
the gap is recorded here and nowhere else. It is one gap, it costs a reviewing role its network and
nothing else (`read-only` leaves command execution alone - the findings settled that against an
earlier draft that had it the other way), and no restriction is ever dropped by it.

**`NO_VCS_WRITES` -> `workspace-write`, by adding nothing.** The best-established row in the
findings and the cheapest to implement, because it is the harness's own default: under
`workspace-write` the `.git`, `.codex` and `.agents` paths inside the working root stay read-only
unless something opts them back in. Measured three ways - `touch .git/x` refused with `Operation
not permitted`, `git commit` dying on `.git/index.lock`, and the `<permission_profile>` handed to
the model spelling the three exclusions out as `access="read"` entries. The mechanism here is *the
absence of an override*, which is an uncomfortable thing to leave as silence in code.

**And the converse, which 8.0 left for this deliverable: when `NO_VCS_WRITES` is absent the adapter
still does not widen `sandbox_workspace_write.writable_roots`.** The argument for widening is the
port's own sentence, that restrictions "are a set and not a level ... nothing here implies anything
else" - a role that did not forbid committing has not been forbidden it. Three reasons it is
declined, the first being the principle this module follows throughout:

  * **This adapter moves the switches the port names and leaves the ones it does not.**
    `network_access` is set in both directions because `NO_NETWORK` exists, so both of its
    positions are *declared* by a role - and an adapter that only ever narrowed it would make one
    of the port's four members mean nothing here. No member says "this role must be able to
    commit", so opening `.git` would be inventing a permission out of the absence of a prohibition.
    Absence of a restriction is not a grant.
  * **What it would open is not the agent's repository.** §3.9 gives AGL the worktree, and a
    worktree's `.git` is a `gitdir:` pointer into the *parent* repository's administrative
    directory. The findings record that Codex resolves such a pointer and protects the target too,
    so the override either does nothing, silently, or reaches state shared with every concurrent
    run on that repository.
  * **Nothing needs it.** §3.3 has the framework commit through `commit=`.

**`NO_NETWORK` -> exact, in both directions.** Both non-bypass modes deny the network by default
and only `workspace-write` can be given it back. The override is emitted explicitly for `false` as
well as for `true` rather than leaning on the packaged default, because a packaged default can move
between releases and a run should not depend on one it never stated. Under `read-only` it is not
emitted at all: a key that provably does nothing would read, to the next person, like enforcement.

**`NO_SHELL` -> no exact mechanism, so it takes the approximate one *and* the words.**
`features.shell_tool` and `features.unified_exec` are both real names, both `stable` and both on by
default (`codex features list`). The override is not merely accepted:
`codex features list -c features.shell_tool=false` reports that flag as `false`, so it reaches the
registry Codex itself reads. That is one link further than the findings had, and still not the
whole chain - **nothing has established that a feature switched off in the registry removes the
tool from what the model is offered**, and the free instrument that settles so much else here
(`codex debug prompt-input`) renders messages and cannot see a tool list.

Two facts keep that doubt real rather than ceremonial. An unknown feature name is **silently
accepted**: `-c features.no_such_feature=false` loads, exits 0, warns nothing and appears nowhere,
so "the override was accepted" is no evidence at all about a name that has since been renamed. And
a tool removed is not a capability removed - `apply_patch` and the harness's other routes are
unaccounted for, and `unified_exec` is named here on the strength of its name rather than of a
measurement. So `NO_SHELL` is the member for which the port's second honest move is mandatory
rather than belt-and-braces. Silently dropping it is the third move, and it is not available.

**Why the words go with every restriction and not only that one.** The other three are enforced by
a kernel-level policy on a process, which is stronger than anything the Claude adapter has, so that
module's argument for always speaking - its patterns leak - does not carry over, and a different
one has to. It is this. A sandbox denial reaches the agent as a command that failed, and an agent
that does not know *why* retries, works around, or spends its turn discovering the wall; saying it
first is cheaper than letting it be found. And the mechanism can vanish with nothing said: a
managed or enterprise `requirements.toml` can pin `allowed_sandbox_modes`, and the binary's message
for that case is a **fallback**, not a refusal - *Configured value for `permission_profile` is
disallowed by requirements; falling back from `<x>` to required value `<y>`*. On such a machine the
sentence is the only part of the restriction still standing.

## The approval setting: the R2 checkpoint, settled by measurement rather than by preference

A framework run has nobody to approve a tool call; both CLI harnesses face that; two harnesses
agreeing is exactly the pressure that makes hoisting an approval mode to `ports/agent.py` look
obviously right - and hoisting it is §1.1's charge verbatim, *"an approval mode, as an unvalidated
string"*. What makes keeping it here safe is a measurement, 8.0's, reproduced independently for
this module in a third workspace: render the model-visible prompt for each
`(sandbox_mode, approval_policy)` pair, extract `<permission_profile>`, hash it. Fifteen cells,
five policies spanning `never`, `on-failure`, `on-request` and `granular` either way, and **three
distinct values, one per sandbox mode**: `read-only` `5d2937a4a5a7`, `workspace-write`
`9f4bb0e18d7d`, `danger-full-access` `d26091693415`. The first and third are byte-identical to
8.0's; the second differs from both of 8.0's, which is the control - only that profile embeds the
working root's path, so a measurement that reproduces where it should and moves where it should is
a measurement of the thing it claims to measure. **What a role is forbidden is decided entirely by
`sandbox_mode`. The approval setting is not in the policy at all.**

**One thing that table does not say, found by asking a wider question.** The invariance is over the
`<permission_profile>` element, not over the whole developer message: hash the *entire* rendered
text and the approval policy does move it. Under `never` the model is told, in one sentence,
*Approval policy is currently never. Do not provide the `sandbox_permissions` for any reason,
commands will be rejected.* Under `on-request` that sentence is replaced by an eighty-line
**Escalation Requests** section teaching it to request escalated privileges. So the setting is not
invisible: it decides whether the agent is taught to try a door. That is 8.0's reading arriving
with a mechanism attached - the setting governs only what becomes of a call the sandbox was going
to refuse anyway, and in `codex exec` every escalation is refused by seven named rejection
handlers. It also settles the value. `never` is the one that tells the agent not to try, and
teaching it to escalate into a harness that answers with a JSON-RPC error spends turns on a
bricked-up door.

**The mechanism is `-c`, and this is a correction to the findings.** 8.0 §1 lists
`-a, --ask-for-approval` among `codex exec`'s options and ends its recommended composition with
`always: -a never`. **On this build `codex exec` has no such flag** - measured three ways, all
free: absent from `codex exec --help`; `--ask-for-approval never` and `-a never` both rejected by
the argument parser with *unexpected argument*; and `-a` present on the *top-level* interactive
command, which is where that reading came from. `codex exec` carries `--approve-for-me` instead,
which routes approvals "through automatic review using the workspace-write sandbox" and which AGL
must not pass, for the same reason it must not pass
`--dangerously-bypass-approvals-and-sandbox`: both widen the sandbox that is the entire restriction
mechanism. Copied unchanged, the recommended composition would have exited 2 on every run.

## (b) `ModelId` -> a model slug: pinned, and refused when unserved

`OpenAI.SOL` becomes `"gpt-5.6-sol"`. The table is **pinned and does not follow the catalog's
priority ordering**, and the port's own docstring settles it: the version is dropped from the enum
deliberately so that "this provider's adapter needs an edit on a release where the Claude one does
not", which is only true of a pinned table. A table resolving `SOL` to whatever sits at priority 1
today would make one `ModelId` name different models on different days under a step fingerprint
(§3.6) that says nothing changed - and a fingerprint that matches while the model underneath moved
is worse than one that stops matching, because the second re-runs a step and the first quietly
answers a question with somebody else's answer. A pin fails loudly instead: a slug retired upstream
dies at second zero, in this file, with one line to edit.

That is the mirror image of the Claude adapter's argument for the opposite choice, and the
asymmetry is real rather than an inconsistency. Anthropic publishes `opus`/`sonnet`/`haiku` as
aliases and resolves them server-side, so a tier *is* the thing that can be sent; this provider
publishes dated slugs and nothing tier-shaped, so a tier has to be resolved somewhere, and an
adapter is where a vendor's release schedule belongs. The three slugs are that vendor's own catalog
at priorities 1, 2 and 3, read free and locally from `codex debug models`, all `visibility: "list"`
and `supported_in_api: true`. There is no `gpt-5`, which is what the port's `OpenAI` enum was
corrected at 8.0b to reflect.

An unknown or unserved `ModelId` - including every `Claude` member, which this adapter does not
serve and which `adapters/routing.py` should never have sent here - raises `InputError` and is
never substituted (§3.2), symmetrically with the Claude adapter and for the same reason: answering
a question about Terra with a run of Luna produces work nobody asked for.

**The leading-`-` guard §3.5 asks for lives in the test, not in a branch here.** Every value
reaching a command line is hostile regardless of provenance, and a slug reaches one - but these
come from a closed table in this file, so a runtime check would be a branch no input can reach and
no test can exercise without breaking the module first. `tests/adapters/test_openai_translate.py`
asserts that no slug begins with `-`, which fails on the commit that adds a bad one rather than on
the run that would have sent it.

## What this module deliberately does not do

**No argv.** Composing a command line - the prompt on stdin, `-C`, the hermeticity overrides,
`--json`, `--color never`, the MCP server injection - is `runner.py`'s: those are decisions about
how to run a session, not translations.

**No stream parsing, no `StopReason`, no `Question` mapping.** Reading JSONL is a stateful walk
over a subprocess's stdout, which is a session concern; `_reading.py` is what that walk consults
once it holds a decoded item, and it never does the walking.

**No capability set and no readiness probe.** `capabilities()` is a frozen constant belonging to
`runner.py` and `check_ready` is a subprocess call; the translation of its *failure* is one of the
names re-exported from `_reading.py`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from agl.adapters.openai._reading import activity, failure, launch_failure, unreadable, unready
from agl.ports.agent import ModelId, OpenAI, Restriction
from agl.ports.errors import InputError

__all__ = [
    "APPROVAL",
    "Sandbox",
    "activity",
    "failure",
    "launch_failure",
    "model_slug",
    "sandbox",
    "unready",
    "unreadable",
]


# The two sandbox values this adapter will ever choose. `danger-full-access` is the third and is
# deliberately absent: the sandbox *is* the restriction mechanism, so a mode that switches it off
# could only serve a role that declared no restrictions - and answering "nothing forbidden" with
# "no sandbox" would make an unrestricted role strictly more dangerous on this backend than on the
# other one, which is a difference no workflow author declared and none can see.
_READ_ONLY: Final = "read-only"
_WORKSPACE_WRITE: Final = "workspace-write"


# The approval setting, and the whole of it: a constant, not a function of anything.
#
# Its shape is the argument. `sandbox()` takes a role's restrictions and returns a mode, because
# that is the load-bearing mapping - what the agent is forbidden is decided there and nowhere else.
# This is a fixed pair of tokens with no parameter, because the approval policy does not appear in
# the policy handed to the model at all: fifteen renderings, three hashes, one per sandbox mode and
# none per approval policy. It decides only what becomes of a call the sandbox was going to refuse.
#
# `never` rather than one of the other three that load, because it is the one that tells the model
# not to attempt an escalation; `on-request` replaces that sentence with an eighty-line section
# teaching it to ask, and in `codex exec` every ask is refused with a JSON-RPC error.
#
# A `-c` override and not a flag: `codex exec` on 0.149.0 has no `-a/--ask-for-approval`, whatever
# the findings' flag table says - measured, the parser rejects it. `untrusted` must never be
# emitted here: it is in the binary's enum, it is in older documentation, and the loader refuses it
# outright with "no longer supported".
APPROVAL: Final[tuple[str, ...]] = ("-c", 'approval_policy="never"')


# The one key that gives the network back, and the only restriction-driven override emitted in both
# positions - explicitly for `false` as well as `true`, so that no run depends on a packaged
# default it never stated.
_NETWORK: Final = "sandbox_workspace_write.network_access"


# The features that carry command execution, both `stable` and both on by default (measured). Two
# rather than one because a harness whose working model is running commands plausibly has a second
# route, and disabling only the obvious one would be a restriction half-applied. Neither is
# verified to remove the tool from what the model is offered, which is why `NO_SHELL` also speaks.
_SHELL_FEATURES: Final = ("features.shell_tool", "features.unified_exec")


# The four limits in AGL's own words. Each names the *effect* rather than a mechanism: a model told
# "the shell tool is disabled" has been told about a tool it cannot see, and learns nothing about
# the second route or about what to do at the wall. `NO_SHELL`'s last sentence is the one that
# matters most - a tool removed is not a capability removed, so the agent is told to stop rather
# than to find a way around.
_IN_WORDS: Final[Mapping[Restriction, str]] = MappingProxyType(
    {
        Restriction.NO_VCS_WRITES: (
            "Leave version control alone. Do not commit, stage, branch, tag, merge, rebase, "
            "reset, stash, push, fetch, or write anything git keeps for itself. This workspace's "
            "history belongs to AGL, which records your work for you: change files, not the "
            "repository."
        ),
        Restriction.NO_FILE_WRITES: (
            "Change nothing on disk. Do not create, rewrite, move or remove a file by any route - "
            "not with an editing tool, not with a shell redirect, and not by running a program "
            "that writes one for you. Read, run, and report what you found."
        ),
        Restriction.NO_SHELL: (
            "Do not run commands. No shell, no build, no test run, and nothing that reaches a "
            "command line through some other tool. If the task cannot be finished without running "
            "something, say so and stop - working around this is a failed task, not a solved one."
        ),
        Restriction.NO_NETWORK: (
            "Do not reach the network. No fetching a page, no download, no package install, no "
            "clone, and no program that opens a connection on your behalf. Work with what is "
            "already in the workspace."
        ),
    }
)


# What introduces the sentences. It says whose limits these are and that they are not a description
# of the sandbox: Codex tells the model what the sandbox permits, in its own prose, and that is a
# different statement from what this role is forbidden. A managed policy can substitute a sandbox
# mode and announce it only in a fallback message nobody reads, in which case this paragraph is the
# only part of the restriction still standing.
_PREAMBLE: Final = (
    "AGL places the following limits on this task. They hold whatever the sandbox you are running "
    "under appears to allow, they are not open to negotiation, and finding a way around one is a "
    "failed task rather than a solved one:"
)


# The model slugs, pinned, and the whole of what this adapter serves. A mapping rather than a
# `match` because `ModelId` is deliberately open to subclassing (`ports/agent.py`), so no type
# checker can be asked whether this is exhaustive; `tests/adapters/test_openai_translate.py` asks
# that question over `OpenAI` itself, which is the place that can hold it.
_MODEL_SLUGS: Final[Mapping[ModelId, str]] = MappingProxyType(
    {
        OpenAI.SOL: "gpt-5.6-sol",
        OpenAI.TERRA: "gpt-5.6-terra",
        OpenAI.LUNA: "gpt-5.6-luna",
    }
)


@dataclass(frozen=True, slots=True)
class Sandbox:
    """A role's restrictions in the forms the Codex CLI will take them. All three, always.

    Never a subset. `mode` and `options` are what the harness enforces and `in_words` is what the
    agent is told, and the module docstring argues why a caller gets the sentences for every
    restriction rather than only for the one with no mechanism. A caller that dropped `in_words`
    would be enforcing a boundary whose shape the agent cannot see - and on a machine with a
    managed sandbox policy it might be enforcing nothing at all.
    """

    mode: str
    """The scalar the whole set collapsed onto: `read-only` or `workspace-write`.

    Handed over bare rather than pre-paired with the flag that carries it, because the collapse is
    what is interesting about this field: sixteen possible restriction sets, one value out of two,
    and a reader should see the value rather than a two-element tuple."""

    options: tuple[str, ...]
    """The configuration overrides that go with the mode, as command-line tokens, in a fixed order.

    Fixed rather than derived from the set's iteration order, because a `frozenset` of strings
    iterates in an order that changes between processes, and a command line that moved between two
    runs would show up as a difference in every log and every comparison of two of them.

    Every value here is a literal from this module: nothing interpolates the workspace, a model
    name, or anything else a caller supplied. That is what keeps §3.5's "every value reaching a
    command line is hostile" from having any work to do in this function."""

    in_words: str
    """The same limits as prose for the agent, or `""` when there were no restrictions at all.

    Where it goes is `runner.py`'s to decide - `codex exec` takes one prompt, so in practice it
    joins onto the instructions - because that is a question about how a session is composed. What
    is settled here is that it must reach the agent."""


def sandbox(restrictions: frozenset[Restriction]) -> Sandbox:
    """Render a role's restrictions into a sandbox mode, its overrides, and the words to go with.

    Total and deterministic: every one of the sixteen subsets of `Restriction` produces exactly one
    mode, by a single membership test, and the module docstring's three-row table is the whole of
    the arithmetic. An empty set is `workspace-write` with the network on and no sentences - not a
    permissive answer, since `workspace-write` is the posture in which `.git`, `.codex`, `.agents`
    and everything outside the working root stay read-only.

    Iteration for the sentences is over `Restriction` and not over the argument, which is what
    makes the result stable: enum members iterate in declaration order and a `frozenset` does not.

    Recorded rather than hidden: `{NO_FILE_WRITES}` without `NO_NETWORK` comes back with the
    network removed too, because `read-only` takes it and no override gives it back (measured both
    behaviourally and off the rendered prompt). The port has no vocabulary for "I enforced more
    than you asked", so the module docstring is where that is said, and this is the second place.
    """
    options: list[str] = []
    if Restriction.NO_FILE_WRITES in restrictions:
        # `read-only` permits reading and nothing else. The network goes with it, unasked; a
        # `network_access` override here would be accepted and would change nothing at all.
        mode = _READ_ONLY
    else:
        # `workspace-write` writes inside the working root and, by the harness's own default,
        # nowhere in `.git`, `.codex` or `.agents` - which is `NO_VCS_WRITES` enforced by adding
        # nothing. `writable_roots` is never widened; the module docstring says why.
        mode = _WORKSPACE_WRITE
        allowed = Restriction.NO_NETWORK not in restrictions
        options += ["-c", f"{_NETWORK}={'true' if allowed else 'false'}"]

    if Restriction.NO_SHELL in restrictions:
        # Approximate and unverified, and here because approximate beats nothing while the sentence
        # carries the rest. Both features, because either alone would be half a switch.
        for feature in _SHELL_FEATURES:
            options += ["-c", f"{feature}=false"]

    spoken = [f"- {_IN_WORDS[member]}" for member in Restriction if member in restrictions]
    return Sandbox(
        mode=mode,
        options=tuple(options),
        in_words="\n".join([_PREAMBLE, *spoken]) if spoken else "",
    )


def model_slug(model: ModelId) -> str:
    """Which model the Codex CLI should be asked to run. Raises `InputError` for anything else.

    A pinned slug rather than a tier resolved at run time - the module docstring argues it against
    the port's own `OpenAI` docstring, which only makes sense if this table is pinned.

    The refusal is the half worth reading. §3.2: "An adapter handed a `ModelId` it does not serve
    raises `InputError`; it never silently substitutes." Every `Claude` member lands here, and so
    would an `OpenAI` member added to the port without a line in `_MODEL_SLUGS` - the right failure
    for that mistake, since answering a request for one model with a run of another produces work
    nobody asked for and a result nobody can read.

    `InputError` rather than `NotFoundError` or `InternalError`, and the port settles it: a model
    is named by a workflow author declaring a role, nothing has been attempted when this refuses,
    and exit 2 sends the reader to the declaration rather than to a bug report against AGL.
    """
    slug = _MODEL_SLUGS.get(model)
    if slug is None:
        served = sorted(str(member) for member in _MODEL_SLUGS)
        raise InputError(
            f"the OpenAI adapter cannot run {str(model)!r}: it serves {served} and nothing else. "
            f"It will not stand in another model for this one - the model was named beside the "
            f"prompt because the choice was semantic, and substituting answers a different "
            f"question than the one the workflow asked"
        )
    return slug
