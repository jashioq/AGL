"""`FilesystemStore` - the real `Store`: one JSON file per address, published by `os.replace`.

§3.6's layout is a file per thing AGL knows and this is the adapter that puts them there. A run
record is one file at the top of a run; a step entry is one file named for its digest, under the
scope and the step that produced it. Where exactly those sit is not this module's business and it
deliberately does not know: **every path below comes out of `home_layout`**, which is §1.10's rule
- the charge against the previous implementation being that a filesystem-shaped helper decided
where the `Store` port kept its things - and the practical form of it here is that not one segment
of the layout is spelled in this file. Not one string literal below is a segment of it - `steps`,
`worktrees`, `run.json` and `.json` appear in this codebase in `home_layout` and, as prose, here.
That is what leaves the layout changeable in the one module that owns it.

## The whole of the atomicity guarantee is three lines

The port asks for one thing and asks for it absolutely - **a written value exists complete or not
at all** - because §3.6 makes the *existence* of an entry the ledger, so a torn entry is a step
that reads as done, hands back half a result and is believed, with no stored status anywhere to
disagree. Here that clause is three lines of `_write_atomically`:

    handle, partial = tempfile.mkstemp(dir=destination.parent, ...)   # one filesystem
    os.fsync(opened.fileno())                                         # content before name
    os.replace(partial, destination)                                  # one atomic step

`dir=` is not tidiness about where scratch files live. `os.replace` is atomic *within* one
filesystem; across two it raises `EXDEV`, and on configurations that paper over that it degrades
into copy-then-delete, which is a reader watching a file grow - exactly the torn value the port
forbids. Creating the temp file in the destination's own directory makes the two paths the same
filesystem by construction, rather than by luck about where `/tmp` happens to be mounted.

**The file is fsynced and the parent directory deliberately is not**, and that asymmetry is the
port's own reading of what may be lost. Syncing the file before the rename is what stops a power
loss leaving the new *name* visible over content that never reached the disk - a torn value, which
is forbidden absolutely. Syncing the directory afterwards would make the *rename* durable, and
§3.6 already accepts losing a whole entry to a crash: "an agent that commits and dies before its
entry is written loses that commit". A lost entry costs a re-run. A torn one costs the run.

## There is no lock in this file, and its absence is the requirement

No mutex, no `asyncio.Lock`, no queue, nothing serialised. Two children recording their own
`implement` step at the same moment write two different files and never meet - §3.6 gives every
step its own address precisely so that a completion is one `os.replace`, "no lock, no
coordination", and the port restates it as a clause of its own. A lock here would *pass the
contract suite*: `tests/contracts/store.py` lists "that distinct addresses are written without a
shared lock" among the things it cannot see, because a global mutex is correct and merely slow and
slowness is not something a suite can assert on. It would then surface at stage 13 as concurrency
that quietly is not there. Nothing below the suite can catch its return, so this paragraph is what
guards it.

## Every method is `async` and not one of them awaits

These are small local-filesystem operations - a few kilobytes, once per step completion - and
`asyncio.to_thread` around each would buy a thread hop and a context switch to hide a syscall that
has already returned. Stage 3.1's concurrency suite was written knowing this: it says in its own
docstring that "an implementation whose write does all its work without awaiting is never observed
part-way through", and asserts against that on purpose rather than by omission. The methods are
`async` because the port is, uniformly, so that an implementation across a network can await.

If the terminal's redraw loop is ever *observed* to stall on a store write - a slow network mount
under `AGL_HOME` is the plausible way - the change is to move the body of `_write_atomically` and
`_read` behind `asyncio.to_thread`. Nothing above this module would notice, which is the point of
the methods being awaitable already.

## The copy the port asks for is the serialisation

§3.6 has the store copy any mapping it is handed and return copies on read, so that a caller
reusing a builder dict cannot silently edit an entry already on the ledger, and a caller editing
what a read returned cannot edit the store. For this adapter both directions fall out of the
format: `json.dumps` at write time reads the caller's mapping once and produces bytes that share
nothing with it, and `json.loads` at read time builds every container fresh, which is
deep independence by construction and not by a `deepcopy` somebody has to remember. The one
condition is *when*: the encode has to happen on the caller's own line of execution, before the
method could hand control anywhere else. `write_record` and `write_entry` say so where they do it.

## Translating what the filesystem says

Adapters translate at their boundary and nothing that is not an `AglError` leaves this module:

  * builtin `PermissionError` -> `DeniedError`. Something reachable said no, which is that class's
    own sentence, and it names "the filesystem refused the write". This is the module `DeniedError`
    was renamed for: because AGL's error is *not* called `PermissionError`, `except
    PermissionError` here still catches `EACCES` rather than shadowing the builtin with an AGL
    class nothing raises here and letting the real refusal escape untranslated (`errors.py`).
  * `FileNotFoundError` and `NotADirectoryError` on a read -> `None`. Both mean nothing is recorded
    at that address: the second is a path component that turned out to be a file, which is the same
    answer arrived at one directory earlier. On `remove` they mean the same thing and the method
    returns quietly, the port requiring tolerance of absence.
  * any other `OSError` - ENOSPC, EIO, EXDEV, a mount that went away -> `UpstreamUnavailable`.
    Nothing landed at the address, so the same call may well succeed later, which is exactly what
    that class promises.
  * `json.JSONDecodeError`, `UnicodeDecodeError`, or a parsed value that is not a JSON object ->
    `UpstreamUnexpected`. The filesystem answered and the answer is not something we can act on.
    AGL writes these files whole, so content we cannot parse did not come from us.
  * `TypeError` or `ValueError` out of the serialisation - `json.dumps` and the UTF-8 encode that
    finishes it -> `InternalError`. That is our own invariant, not the world's: the caller handed
    us something AGL cannot write down. `UnicodeEncodeError` is a `ValueError` and so lands here,
    which is the write-side counterpart of the `UnicodeDecodeError` above: a lone surrogate is a
    `str` that `JsonValue` admits and that UTF-8 has no encoding for at all. `_encoded` argues
    why the encode is spent there rather than at the file handle.

Every one of them names the address in AGL's own terms - project, label, namespaces, step, digest -
because that is what a reader has in hand; the `OSError` it is chained to carries the path.
"""

import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Final

from agl.ports.errors import (
    AglError,
    DeniedError,
    InputError,
    InternalError,
    UpstreamUnavailable,
    UpstreamUnexpected,
)
from agl.ports.home_layout import AglHome, RunScope, run_record, scope_dir, step_entry
from agl.ports.ids import Namespace, StepName
from agl.ports.run import JsonValue
from agl.ports.store import Store

__all__ = ["FilesystemStore"]


# Written as UTF-8 and read back as UTF-8, said explicitly in both directions: the default is the
# locale's, and a record written under one locale must be readable under another. Spent exactly
# once each way - `_encoded` encodes, `_read` decodes - and never at a file handle, so the temp
# file is opened binary and a document that has no UTF-8 encoding fails where `_encoded` already
# translates that into an `AglError` rather than mid-write with a partial file on disk.
_ENCODING: Final = "utf-8"

# `os.replace` publishes an entry, so a temp file is visible only to a crash or a failed write.
# A leftover one is harmless twice over: the prefix holds a `-`, which no sha256 hexdigest does, so
# nobody reading the superseded entries §3.6 keeps can mistake it for one - and the only two
# directories a write ever creates a temp file in are a run's own and a step's, never a
# `worktrees/` container, so `namespaces` cannot see one either (and skips non-directories anyway).
_PARTIAL_PREFIX: Final = "partial-"

# Two spaces. §3.6 keeps superseded entries because they answer "why did this re-run", and they
# are kept for a person to read; one minified line is not a thing a person reads.
_INDENT: Final = 2

# A `Namespace` that exists to be thrown away - see `_worktrees_container`.
_PROBE: Final = Namespace("probe")


class FilesystemStore(Store):
    """`Store` over a directory tree under `AGL_HOME`, one file per address.

    Constructed with the root and nothing else, by `config/container.py` like every other adapter.
    It holds no state beyond that root: there is no cache, no index and no open handle, so two of
    these over one `AGL_HOME` - two `agl` invocations, which §3.9 expects - are the same store, and
    the atomic rename above is what makes that safe rather than an arrangement between them.
    """

    def __init__(self, home: AglHome) -> None:
        self._home = home

    async def read_record(self, scope: RunScope) -> dict[str, JsonValue] | None:
        """The run's own record, or `None`. `home_layout.run_record` drops the namespaces."""
        return _read(run_record(self._home, scope), _record_address(scope))

    async def write_record(self, scope: RunScope, value: Mapping[str, JsonValue]) -> None:
        """Record what this run was asked to do, whole or not at all."""
        address = _record_address(scope)
        # Encoded here, on the caller's own line of execution, before anything else can run. This
        # *is* the copy §3.6 asks for, and it is only a copy while nothing happens in between:
        # stash the mapping and encode it at write time and a caller reusing its builder dict has
        # edited the ledger. Anything that puts an `await` before this line breaks that.
        payload = _encoded(value, address)
        _write_atomically(run_record(self._home, scope), payload, address)

    async def read_entry(
        self, scope: RunScope, step: StepName, digest: str
    ) -> dict[str, JsonValue] | None:
        """One recorded run of one step, or `None`. The digest is checked by `home_layout`."""
        address = _entry_address(scope, step, digest)
        return _read(step_entry(self._home, scope, step, digest), address)

    async def write_entry(
        self, scope: RunScope, step: StepName, digest: str, value: Mapping[str, JsonValue]
    ) -> None:
        """Record what this run of this step produced. The write §3.6's ledger rests on."""
        address = _entry_address(scope, step, digest)
        # Encoded before anything else, for `write_record`'s reason and with the same consequence.
        payload = _encoded(value, address)
        _write_atomically(step_entry(self._home, scope, step, digest), payload, address)

    async def namespaces(self, scope: RunScope) -> tuple[Namespace, ...]:
        """The namespaces recorded immediately under this scope, sorted by name.

        Sorted is a choice this adapter makes inside the freedom the port leaves: it asks for a
        *stable* order and declines to say sorted by what, because the order is a tie-break, and
        sorting satisfies it while making a `clear` traversal reproducible and a failure the same
        failure twice.

        **A directory name a `Namespace` refuses is skipped rather than raised on.** Every write
        path into this tree goes through a `Namespace`, so AGL cannot have created such a
        directory; it is somebody else's, and raising would make `clear` - this member's one
        caller - fail on something AGL did not write and would not have deleted anyway. Entries
        that are not directories are skipped for the same reason. A missing container answers `()`:
        a run that recorded nothing under a namespace has no namespaces, and `clear` after a crash
        is the ordinary case.

        Creates nothing. This is a read, and a read that made a directory would put a namespace
        into the answer of a later call by having been asked the question.
        """
        container = _worktrees_container(self._home, scope)
        try:
            names = sorted(child.name for child in container.iterdir() if child.is_dir())
        except (FileNotFoundError, NotADirectoryError):
            return ()
        except OSError as error:
            raise _translated(error, f"the namespaces of {_scope_address(scope)}") from error
        found: list[Namespace] = []
        for name in names:
            try:
                found.append(Namespace(name))
            except InputError:
                continue
        return tuple(found)

    async def remove(self, scope: RunScope) -> None:
        """Remove this scope's directory and everything below it. Tolerant of absence.

        Not atomic, and the port says why: a removal that stops halfway leaves less than there was,
        never something that reads as more, and tolerance of absence makes running it again the
        whole of the recovery. So this is one `shutil.rmtree` and no temp-directory dance.

        Deliberately **not** `ignore_errors=True`. That flag would swallow a refusal - a directory
        AGL may not write to comes back as a successful removal, and `clear` reports having taken a
        run away that is still there. Absence is caught by name and everything else is translated.

        Nothing prunes the now-empty parents. `runs/` and `projects/` are the layout rather than
        this run's leavings, and a store that tidied them would be racing every other run in the
        project for the privilege.
        """
        try:
            shutil.rmtree(scope_dir(self._home, scope))
        except (FileNotFoundError, NotADirectoryError):
            return
        except OSError as error:
            raise _translated(error, f"the removal of {_scope_address(scope)}") from error


def _worktrees_container(home: AglHome, scope: RunScope) -> Path:
    """The directory a scope's child worktrees sit in, obtained without naming it.

    `home_layout` does not expose this directory and says so on purpose: "Neither `steps/` nor
    `worktrees/` is addressable on its own", because a caller holding the container could join a
    namespace onto it and the nesting rule would then be written down in two places. `namespaces`
    is the one member that needs the container itself, and it gets there by asking for a path one
    segment *deeper* - the scope inside a throwaway namespace - and taking that path's parent.

    So the segment is still spelled exactly once, in `home_layout.scope_dir`, and this module holds
    no copy of it. The alternative is a second literal `"worktrees"` here, which would agree with
    the layout right up until somebody changed the layout - and a filesystem-shaped copy of a
    layout, drifting quietly from the module that owns it, is precisely what §1.10 charges the
    previous implementation with and what `home_layout` was written to prevent.
    """
    return scope_dir(home, scope.inside(_PROBE)).parent


def _encoded(value: Mapping[str, JsonValue], address: str) -> bytes:
    """`value` as the bytes that will be written - and, by being those bytes, the copy of it.

    `dict(value)` at the top level and nowhere below it. The port admits any `Mapping` on the way
    in so that a caller need not copy what it already has, `RunSpec.params` really is a
    `MappingProxyType`, and `json.dumps` refuses a mapping that is not a `dict`. One level down
    `JsonValue` spells its objects `dict[str, JsonValue]`, so nested mappings are already `dict`s
    and a deeper copy would be work `json.dumps` is about to do again anyway.

    `allow_nan=False` is this adapter's own decision, not something the port imposes: the port has
    no opinion on non-finite floats and the contract suite writes none, deliberately. Left at its
    default, `json` writes a bare `NaN` or `Infinity` token that is not JSON, that no other reader
    accepts, and that comes back unequal to itself - so a value written that way would break the
    port's round-trip promise at read time instead of failing here. `ports/run.py::_checked_json`
    refuses them for exactly that reason and this module agrees rather than writing a file AGL
    itself could not read back.

    `ensure_ascii=False` keeps a value's unicode as unicode: §3.6 keeps these files for a person to
    read, and `\\u65e5\\u672c\\u8a9e` is not something a person reads.

    **The encode to UTF-8 happens here and not at the file handle**, and that placement is the
    whole of one refusal. `JsonValue` admits any `str`, and `json.loads('"\\ud800"')` hands one
    back holding a lone surrogate - an unpaired UTF-16 code unit, which an agent's reporting-tool
    payload really can carry this far - and a lone surrogate has no UTF-8 encoding whatsoever.
    Written through a handle opened `encoding=_ENCODING`, that surfaced as a `UnicodeEncodeError`
    raised by `opened.write` inside `_write_atomically`; a `UnicodeEncodeError` is a `ValueError`
    and not an `OSError`, so it went past that function's `except OSError` untranslated - an
    exception that is not an `AglError` leaving this module, against the invariant at the top of it
    - and took the `os.unlink` of the temp file with it, orphaning a `partial-` file in the entry's
    own directory. Encoding inside this `try` moves the failure to the one branch that already
    translates it, on the caller's own line of execution, before a directory is made and before any
    temp file exists. That is the same "costs an exception and no state" the other unwritable
    values already got, reached by taking a failure path away rather than by adding a branch.

    Not `ensure_ascii=True`, which spells a lone surrogate `\\ud800` and would write the file
    without complaint. That trade goes the wrong way: it gives up the paragraph above - every
    document's unicode escaped, for every reader of every superseded entry §3.6 keeps - to
    accommodate one pathological input, and what it buys is a file holding half a character. AGL
    cannot write a lone surrogate down, which is exactly what `InternalError` says, and what
    `ports/run.py::_checked_json` says of the values it refuses for the same kind of reason.
    """
    try:
        text = json.dumps(dict(value), ensure_ascii=False, allow_nan=False, indent=_INDENT)
        return text.encode(_ENCODING)
    except (TypeError, ValueError) as error:
        raise InternalError(
            f"{address} holds a value AGL cannot write down: {error}. A stored document is JSON, "
            f"and something above this port handed it one that is not"
        ) from error


def _write_atomically(destination: Path, payload: bytes, address: str) -> None:
    """Put `payload` at `destination` so that a reader sees all of it or nothing recorded there.

    The three lines that matter are argued in the module docstring; what is left here is the
    housekeeping around them. Directories are created on the way in and only here - a write is the
    one operation entitled to make one - with `exist_ok=True` so that two children provisioning
    under a shared parent at the same moment do not fight over which of them made it.

    `payload` arrives already encoded, so the handle is opened binary and there is no `encoding=`
    anywhere below. That is deliberate and it is what makes this function's failures *all* the
    filesystem's: a text handle would encode at `opened.write`, and a document with no UTF-8
    encoding would raise a `UnicodeEncodeError` here - a `ValueError`, which `except OSError` does
    not catch, so it would escape untranslated and skip the `os.unlink` below. `_encoded` owns the
    encode and owns that refusal; see it, and `_ENCODING`.

    `mkstemp` creates at mode 0600 and the entry keeps that mode after the rename, which is the
    right answer for a file under `AGL_HOME`: this is AGL's own state, read by the user who ran it.

    A failure after the temp file exists takes it away again. Failing to take it away is not itself
    a failure worth reporting - the error being raised is the one the caller needs, and a stray
    partial file is bytes rather than a torn value: no read here lists a directory of entries, and
    the one directory `namespaces` does list is never written into. See `_PARTIAL_PREFIX`.
    """
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # `dir=` is load-bearing and is the whole same-filesystem clause: `os.replace` is atomic
        # within one filesystem and raises `EXDEV` across two, and a temp file in the system temp
        # directory is a different filesystem on any machine where `/tmp` is its own mount.
        handle, partial = tempfile.mkstemp(dir=destination.parent, prefix=_PARTIAL_PREFIX)
    except OSError as error:
        raise _translated(error, address) from error
    try:
        with os.fdopen(handle, "wb") as opened:
            opened.write(payload)
            opened.flush()
            # The file, and never the parent directory: see the module docstring. This one stops a
            # crash publishing a name over unwritten content; the directory's would only make the
            # rename survive a crash, and §3.6 accepts losing a whole entry to one.
            os.fsync(opened.fileno())
        os.replace(partial, destination)
    except OSError as error:
        with suppress(OSError):
            os.unlink(partial)
        raise _translated(error, address) from error


def _read(path: Path, address: str) -> dict[str, JsonValue] | None:
    """The document at `path`, or `None` if nothing is recorded there.

    Opened and caught, never `exists()` then opened: the gap between those two is a race, and the
    answer it would give is one the open gives exactly. Nothing here creates anything - not the
    file, not a parent directory - because a read that made a directory would answer a later
    `namespaces` with a name that got there by being asked about.

    What comes back is `json.loads`'s own containers, built fresh out of the text: deeply
    independent of anything this store holds, by construction rather than by a copy somebody has to
    remember to take. The caller may edit it to the bottom and the file is untouched.

    A stored JSON `null` is a recorded value and not an absence - `None` here means "nothing
    recorded" and can mean nothing else, which is what makes the port's missing `exists` honest -
    so absence is decided by the open failing and never by what parsed.
    """
    try:
        text = path.read_text(encoding=_ENCODING)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except UnicodeDecodeError as error:
        raise UpstreamUnexpected(
            f"{address} is not {_ENCODING}: AGL writes these files whole and writes them as "
            f"{_ENCODING}, so this one did not come from AGL. {error}"
        ) from error
    except OSError as error:
        raise _translated(error, address) from error
    try:
        document: object = json.loads(text)
    except json.JSONDecodeError as error:
        raise UpstreamUnexpected(
            f"{address} is not JSON: {error}. AGL publishes these files with one atomic rename, "
            f"so a half-written one is not a state this store can produce"
        ) from error
    if not isinstance(document, dict):
        raise UpstreamUnexpected(
            f"{address} holds a {type(document).__name__}, and both kinds of document AGL stores "
            f"are JSON objects"
        )
    return document


def _translated(error: OSError, address: str) -> AglError:
    """The `AglError` an `OSError` means at this boundary. Returned, so callers `raise ... from`.

    `except PermissionError` catches `EACCES` and `EPERM` and nothing of ours, which is the trap
    `errors.py` renamed the AGL class to avoid: had it kept the plan's name `PermissionError`, the
    import at the top of this module would shadow the builtin, this branch would stop catching the
    filesystem's refusal, and the refusal would escape this adapter untranslated.

    Everything else is `UpstreamUnavailable` rather than `UpstreamUnexpected`, and the distinction
    is the one that class draws: nothing landed at the address, so the same call may succeed later.
    A full disk, a read-only mount, a mount that went away - and `EXDEV`, which the `dir=` argument
    exists to make unreachable and which is mapped here anyway, a translation with a hole in it
    being no translation.
    """
    if isinstance(error, PermissionError):
        return DeniedError(f"the filesystem refused {address}: {error}")
    return UpstreamUnavailable(f"the filesystem could not reach {address}: {error}")


def _scope_address(scope: RunScope) -> str:
    """A scope in AGL's own words: the project, the label, and the namespaces it is nested in."""
    nesting = "/".join(str(namespace) for namespace in scope.namespaces)
    inside = f", inside {nesting}" if nesting else ""
    return f"project {str(scope.project)!r}, run {str(scope.label)!r}{inside}"


def _record_address(scope: RunScope) -> str:
    """A run's record. `scope.run` because there is one per run and it belongs to the run."""
    return f"the run record for {_scope_address(scope.run)}"


def _entry_address(scope: RunScope, step: StepName, digest: str) -> str:
    """One step entry: the three parts that are together its address, in the port's vocabulary."""
    return f"the entry for step {str(step)!r} at digest {digest!r} in {_scope_address(scope)}"
