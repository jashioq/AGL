"""The reading half of the Codex vendor boundary: failures and frames, coming the other way.

`translate.py` is the boundary and this is one side of it. That module holds what AGL *says* to
the harness - a sandbox mode, an approval setting, a model slug - and this one holds what AGL
*makes of what comes back*: an exit status and a stream of frames, turned into `errors.py`'s
classes and into activity strings. `translate.py` re-exports every name below, so a caller has one
import and gate 5's promise still reads "one place knows what this harness calls things".

**The split is by obligation, not by line count.** The saying half has to be *total*: every subset
of `Restriction` renders to exactly one mode, every served `ModelId` to exactly one slug, and
anything else is refused rather than guessed. The reading half has the opposite duty: it must
never raise on something it did not expect. A frame kind it has never met, a field of the wrong
JSON type, a `changes` array that is not an array - each of those is a harness release, not a
failure, and an adapter that treated them as failures would turn one into an outage. Two rules
that strict and that opposed do not belong in one reader's head at once.

**Every measurement cited here is free and none of it spent a token.** `codex exec` was never run.

## Exit codes and stderr -> `AglError`

§3.1: adapters translate at their boundary, and nothing above one sees a vendor's stop strings or
a raw exit status. `errors.py` chooses by what the reader of an exit code should do - **nothing
started, or the far side never answered** is `UpstreamUnavailable`, whose promise is that the same
call may well succeed later; **it answered and the answer cannot be read** is `UpstreamUnexpected`,
where our understanding is what failed and a retry answers identically.

**The exit code is one signal and not the primary one, and that is the honest position rather than
a cautious one.** `docs/codex-cli-findings.md` reports Codex's exit codes as undocumented and not
established, because settling the interesting ones costs a `codex exec`. Free and reproducibly,
the two ends are these:

  * **2 is the argument parser refusing the command line before anything runs.** Measured three
    ways on 0.149.0 - an unknown long flag at the top level, an unknown long flag on `codex exec`,
    and `--sandbox` given a value outside its `[possible values]` - all three exit 2 with
    `error: unexpected argument` or `error: invalid value` and a usage block. Nothing reaches a
    model. That is `UpstreamUnexpected`: the binary is fine, this adapter's idea of its command
    line is not, and no retry changes it.
  * **1 is overloaded and therefore says almost nothing.** Measured: a `-c` override the loader
    rejects exits 1; a `CODEX_HOME` that does not exist exits 1; `codex login status` exits 1
    saying `Not logged in`. And the findings read off the source that a *turn failure* also exits
    1, on an `if error_seen` at the end of a run that did reach a model. So 1 spans "never
    started" and "started, ran, and failed", which are opposite answers to the only question a
    caller has.

Hence the ordering in `failure`: **what the stream said comes first, and the exit code is
consulted only when the stream said nothing.** A `turn.failed` or a top-level `error` event
carries the harness's own words, which are worth more than a number whose meaning was never
written down. It is a rule rather than a table because a table would be an invention; when 8.2
settles the codes against a loopback, this is one function to revisit.

**`StopReason.LIMIT` is unreachable for this backend, and that is a decision.** The findings offer
a `LIMIT` row - match the binary's usage-limit prose on a `turn.failed` and call it a limit rather
than an error - and it is declined here. That string is vendor marketing copy with at least four
spellings and no stability promise, and a `turn.failed` from an exhausted allowance is honestly
`UpstreamUnavailable`: nothing usable came back, and the same call may well succeed tomorrow,
which is that class's promise exactly. It is also what the Claude adapter does with the same
situation, so the two backends agree rather than differing for no reason a workflow author could
see. The cost is the quality of one error message, and the row is one predicate to add. A reader
who finds `StopReason.LIMIT` unreachable in an adapter is entitled to know it was decided.

## Frames -> activity strings: a match on frame kind, and no per-tool table

§3.7 gives the adapter a plain string the router passes through untouched, and forbids "a shared
verb taxonomy, no `Activity` type, no framework lookup table". What that rules out is a mapping
from a *tool* to an English verb - one adapter accumulating an opinion about a vendor's tool set
that the next adapter would then have to mirror. This is not that. Codex's JSONL surfaces tool
calls **typed**: the item kind says what the call is, and the field carrying the interesting value
is the field that kind is *about*. Four kinds, four fields, and no tool ever named -
`command_execution` has `command`, `file_change` has `changes[].path`, `mcp_tool_call` has
`server` and `tool`, `web_search` has `query`. The findings established the item kinds twice
independently (the 0.149.0 string pool and `exec_events.rs` on `main`, agreeing) and the tag run
was re-read off the binary for this module - `command_execution` `file_change` `mcp_tool_call`
`web_search` `todo_list`, contiguous and in that order. So none of the Claude adapter's
first-string-value-in-schema-order heuristic is needed here; that exists only because its harness
delivers opaque tool payloads.

**The phrasing is deliberately not the Claude adapter's, and the cosmetic inconsistency is §3.7's
point rather than a defect in it.** `Bash: ./gradlew build` is the shape of a harness whose unit
is a named tool; Codex's unit is a typed event, and forcing it into the other vendor's
`Name: subject` shape would be this adapter learning to speak Claude Code, which is the first
entry in the table that must not exist.

Everything else returns `None`: `agent_message` and `reasoning` are content and not activity,
`todo_list` and `error` are the run's business rather than a dashboard's, and **an unrecognised
kind is `None` and never an exception** - the findings' rule, and stage 7's before it, since
`collab_tool_call` sits in the source enum and in neither the documentation nor this build's
string pool. Two rules about the *value* carry over from the Claude adapter unchanged, because the
reasoning does: a value beginning with the task's workspace is shown relative to it by a plain
prefix test that builds no `Path` and touches no filesystem (the string is one a model produced,
not a promise that a file exists), and the result is one line and capped, because a `command` can
be a heredoc and a dashboard cell has room for one line.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

from agl.ports.errors import AglError, UpstreamUnavailable, UpstreamUnexpected
from agl.ports.run import JsonValue

__all__ = [
    "activity",
    "failure",
    "launch_failure",
    "unready",
    "unreadable",
]


# The one exit status this module reads as a meaning, because it is the one that was established:
# the argument parser refusing the command line before anything ran. Every other non-zero status is
# read as no more than "not zero" - the module docstring says why 1 cannot be read as anything.
_ARGV_REJECTED: Final = 2


# How much of a value reaches an activity line. One dashboard cell, one line: long enough for a
# build command or a path from a repository root, short enough not to wrap. What is cut is cut from
# the end, where a long command's arguments are, rather than from the middle.
_ACTIVITY_LIMIT: Final = 120


# What each frame kind is called in a dashboard, and the whole of the match `activity` performs.
# AGL's own English over Codex's own frame kinds, and deliberately not the Claude adapter's
# `Tool: subject` shape. One word each, chosen to be true of every case its kind covers:
# `Changing` rather than `Editing`, because a `file_change` may be an add or a delete.
_LABELS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "command_execution": "Running",
        "file_change": "Changing",
        "mcp_tool_call": "Calling",
        "web_search": "Searching",
    }
)


def launch_failure(error: OSError) -> UpstreamUnavailable:
    """What it means that the CLI could not be started at all. Returned, so call sites `raise`.

    Returned rather than raised so a call site reads `raise launch_failure(error) from error`,
    which names the line that failed and keeps the original in the traceback while never being
    what a caller catches.

    Always `UpstreamUnavailable`, and the class is the point: nothing was attempted, nothing
    reached a model, and installing the binary or fixing its mode makes the same call succeed.
    """
    if isinstance(error, FileNotFoundError):
        return UpstreamUnavailable(
            f"the Codex CLI is not installed or is not on PATH: {_said(error)}. Nothing was "
            f"attempted, so this is not a failed task - install Codex, or point AGL at an "
            f"existing installation, and the same call may well succeed"
        )
    if isinstance(error, PermissionError):
        return UpstreamUnavailable(
            f"the Codex CLI was found and could not be executed: {_said(error)}. That is a file "
            f"mode or a quarantine attribute on the binary rather than anything about this run"
        )
    return UpstreamUnavailable(
        f"AGL could not start the Codex CLI: {_said(error)}. Nothing reached a model, so the same "
        f"call may well succeed once whatever stopped the process from starting is fixed"
    )


def unready(exit_code: int, output: str) -> UpstreamUnavailable:
    """What a failed readiness probe means. Always unavailable, and the reason is the CLI's own.

    `AgentRunner.check_ready` has exactly one refusal - "Raise `UpstreamUnavailable` with a reason
    a person can act on" - and `tests/contracts/_agent_preflight.py` fails an adapter that raises
    anything else, because §3.2's first preflight check catches that class and nothing else:
    anything else reaches the top of the CLI as exit 70 and tells the reader to file a bug about
    their own logged-out session.

    So this is not `failure` under another name. A probe attempts nothing and asks one question -
    could this harness serve a run - and every way of failing it is the same answer, *not now*,
    including the ways `failure` would call `UpstreamUnexpected`: a CLI whose output this adapter
    cannot read is a CLI this adapter cannot run against either.

    Free on this backend, which is worth knowing at the call site: the probe is
    `codex login status`, which exits 0 printing `Logged in using ChatGPT` and 1 printing
    `Not logged in` - both measured, the second against a credential-free home directory. The
    Claude adapter cannot answer the same question without spending a turn.
    """
    return UpstreamUnavailable(
        f"the Codex CLI is installed and is not ready to run: {_said(output)}. A session that was "
        f"never authenticated, one whose credentials have expired, and a configuration the CLI "
        f"refuses to load all arrive this way, so the message above is the part to act on - "
        f"{_status(exit_code)}"
    )


def failure(*, reported: str | None, exit_code: int, stderr: str) -> AglError:
    """What a run that produced no answer means. Returned, so call sites `raise`.

    The ordering is the argument, and the module docstring has it in full: **what the stream said
    comes first**, and `exit_code` is consulted only when the stream said nothing. Codex's exit
    codes are undocumented, and 1 spans "the configuration would not load" and "a turn ran and
    failed" - opposite answers to the only question a caller has. A `turn.failed` event or a
    top-level `error` event carries the harness's own words about which of those happened, and
    those words are worth more than a number whose meaning was never written down.

    `reported` is that message, or `None` when the stream said nothing at all - which is what an
    empty or blank string is treated as too. `stderr` is the fallback and may be empty. Three
    outcomes and no table: the stream explained itself, so `UpstreamUnavailable` carrying the
    explanation; it did not and the status is the parser's refusal, so `UpstreamUnexpected`,
    because the binary works and this adapter's idea of its command line does not; it did not and
    the status is anything else, so `UpstreamUnavailable` carrying stderr, which is the findings'
    recommended fallback and stays the fallback until 8.2 settles the codes against a loopback.

    A usage-limit failure arrives on the first branch as `UpstreamUnavailable` rather than as
    `StopReason.LIMIT`. That is a decision, it matches what the Claude adapter does with an
    exhausted allowance, and the module docstring records why.
    """
    said = (reported or "").strip()
    if said:
        return UpstreamUnavailable(
            f"the Codex CLI stopped and reported an error instead of finishing: {said}. A session "
            f"that is not authenticated, an exhausted allowance, a sandbox that refused something "
            f"the run needed and an unusable request all arrive this way, so the message above is "
            f"the part to act on"
        )
    if exit_code == _ARGV_REJECTED:
        return UpstreamUnexpected(
            f"the Codex CLI rejected the command line AGL built for it: {_said(stderr)}. That "
            f"status is the argument parser refusing to start, so nothing reached a model and "
            f"nothing will on a retry - this is a version mismatch or an AGL bug rather than a "
            f"backend that was busy"
        )
    return UpstreamUnavailable(
        f"the Codex CLI exited without answering and without saying why: {_said(stderr)}. Nothing "
        f"usable came back from the far side, so the same call may well succeed once whatever "
        f"stopped it is fixed - {_status(exit_code)}"
    )


def unreadable(line: str, reason: str) -> UpstreamUnexpected:
    """What a line this adapter cannot read means. Returned, so call sites `raise`.

    `UpstreamUnexpected`, and `errors.py` makes the case: the far side is working and our
    understanding of it is what failed, so retrying the same call unchanged answers the same way.

    **This is for output that is not JSON, and not for an item kind this adapter has never met.**
    An unrecognised frame is ignored, never raised on - see `activity`, and see the findings' rule,
    which is stage 7's rule: an adapter that raises on an unknown tag will one day fail on a
    feature it never asked for. Confusing the two turns a harness release into an outage.
    """
    return UpstreamUnexpected(
        f"the Codex CLI printed a line on its event stream that AGL cannot read: {reason}. The "
        f"line was {_shortened(line)!r}. The CLI is working and this adapter's reading of it is "
        f"not, so the same call will answer the same way - this is a version mismatch or an AGL "
        f"bug, not a busy backend"
    )


def activity(item: Mapping[str, JsonValue], workspace: Path) -> str | None:
    """What to show while `item` is in flight, or `None` when it is not activity at all.

    `Running: ./gradlew build`, `Changing: domain/usecase.kt`, `Calling: agl/ask`,
    `Searching: seatbelt deny file-write`. A match on the item's own `type`, formatting the field
    that kind is about - not a table of tools, which §3.7 forbids and which this harness does not
    need, because its frames are typed.

    `None` covers three different things and deliberately does not distinguish them, because the
    caller does the same thing with all three: content (`agent_message`, `reasoning`), a frame
    that is the run's business rather than a dashboard's (`todo_list`, `error`), and **any kind
    this adapter has never heard of**. The last is load-bearing: an item kind exists in the
    harness's source that appears in neither its documentation nor this build, so silence is the
    only safe answer to a tag from the future.

    `workspace` is the task's, and shortens a value that begins with it. Passing it is what keeps
    the shortening a rule about a prefix rather than a rule about which kinds carry paths.
    """
    kind = item.get("type")
    if not isinstance(kind, str):
        return None
    label = _LABELS.get(kind)
    if label is None:
        return None
    shown = _shortened(_subject(kind, item, workspace).strip())
    # A frame of a known kind carrying nothing readable still says something - a command is
    # running, a file is being changed - so the bare label is the honest line, where `Running: `
    # with nothing after the colon is not.
    return f"{label}: {shown}" if shown else label


def _subject(kind: str, item: Mapping[str, JsonValue], workspace: Path) -> str:
    """The field this kind is about, as a string. `""` when it is missing or the wrong JSON type.

    One branch per kind and no fallback across kinds, which is what makes this a match on frame
    kind rather than the Claude adapter's search for a first string value. Nothing here raises:
    these values were produced by a model and serialised by a harness, so losing a dashboard line
    is the right price for a field that arrived in a shape this did not expect.

    The workspace prefix is removed from every value the line is built from, which for a
    `file_change` means **each path separately**. Shortening the joined string instead would
    relativise the first path and leave every later one at full length, which is the worst of both:
    a column that is neither aligned nor complete.
    """
    if kind == "command_execution":
        return _relative(_text(item.get("command")), workspace)
    if kind == "file_change":
        return ", ".join(_relative(path, workspace) for path in _paths(item.get("changes")))
    if kind == "mcp_tool_call":
        named = (_text(item.get("server")), _text(item.get("tool")))
        return "/".join(part for part in named if part)
    return _relative(_text(item.get("query")), workspace)


def _paths(changes: JsonValue) -> list[str]:
    """The `path` of each change in a `file_change` item, in order, skipping anything unreadable.

    A `changes` that is not a list, an entry that is not an object and a `path` that is not a
    string each contribute nothing, and the caller then renders the bare label.
    """
    if not isinstance(changes, list):
        return []
    found = (_text(change.get("path")) for change in changes if isinstance(change, dict))
    return [path for path in found if path]


def _text(value: JsonValue) -> str:
    """A JSON value as the string it is, or `""` when it is anything else. Never raises."""
    return value if isinstance(value, str) else ""


def _relative(text: str, workspace: Path) -> str:
    """`text` without the workspace it sits in, when it begins with one. Otherwise unchanged.

    A prefix test and nothing more: no `Path` is built, nothing is resolved and no filesystem is
    touched, because this runs on a value an agent chose and a value an agent chose is not a
    promise that anything is there. §3.7's examples are relative because a run's worktree lives
    under a trees root under a home directory, and an eighty-character prefix repeated down a
    dashboard column is the same eighty characters in every row.
    """
    prefix = f"{workspace}{os.sep}"
    return text[len(prefix) :] if text.startswith(prefix) and len(text) > len(prefix) else text


def _shortened(text: str) -> str:
    """One line of `text`, with runs of whitespace closed up, capped, and marked when it was cut.

    A `command` can be a heredoc, so the first line is taken and the rest is represented by the
    ellipsis rather than dropped silently: a reader seeing `Running: cat > f.txt <<'EOF'...` knows
    there was more, where the same line without the mark would read as the whole command.
    """
    first, newline, _ = text.partition("\n")
    line = " ".join(first.split())
    cut = bool(newline)
    if len(line) > _ACTIVITY_LIMIT:
        line, cut = line[:_ACTIVITY_LIMIT].rstrip(), True
    return f"{line}..." if cut else line


def _said(reported: object) -> str:
    """Whatever the far side said, as something an error message can hold. Never empty.

    `tests/contracts/_agent_preflight.py` asserts that `check_ready`'s refusal carries a message
    and the port asks for "a reason a person can act on", so a CLI that failed silently on both
    streams would otherwise produce an error with a blank where the reason goes. An `OSError`
    renders as its own text, which already folds in `errno` and the path it was reaching for.
    """
    said = str(reported).strip()
    return said or "it said nothing on either output stream"


def _status(exit_code: int) -> str:
    """The exit status, reported and never interpreted.

    It goes into the message because a person debugging wants it, and it is framed as a number
    rather than as a meaning because on this harness it has none that was ever written down: 1
    covers a configuration that would not load, a home directory that does not exist, a session
    that is not logged in, and a turn that ran and failed. The one status this module does read as
    a meaning is handled before this is ever called.
    """
    return f"it exited {exit_code}, a status this backend documents no meaning for"
