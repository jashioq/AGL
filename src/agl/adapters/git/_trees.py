"""The trees root as a filesystem: the directories a run's checkouts sit in, and the two locks.

`workspace.py` speaks git - what to add, what to commit, what to prune - and everything it says
goes through `_runner.py`. Underneath that there is a directory tree to make and unmake and two
locks to hold, and none of it involves git at all: a `mkdir`, an `rmtree`, an `rmdir` and an
`flock(2)`. That is this module, and the line between the two is that **nothing here runs a
process and nothing there raises an `OSError`**. It is also where the one platform assumption
lives, so that the module implementing the ports carries no `fcntl` import: `flock` makes this
POSIX-only, which v1.1 already is.

Private by its leading underscore, like `_runner.py` and for the same reason: it is one layout's
plumbing rather than a capability anything could implement, and nothing outside `agl/adapters/git/`
names it.

## The registry lock, and why each half of it is what it is

`git worktree add` and `git worktree prune` mutate `.git/worktrees/` and nothing else AGL does
touches it, so a mutex guards exactly those two calls (§3.9) and is let go of before anything
long-running starts - never across a merge, a build, or a person deciding something.

**Cross-process**, because two `agl run` invocations are two processes. A `threading.Lock` would
serialise the coroutines of one of them, pass every test that can be written from inside it, and
leave two concurrent runs corrupting one registry; it is the failure that looks exactly like
success until the day it does not.

**`flock(2)` rather than a PID file**, because the kernel drops it when the holder dies. A PID
file needs stale-lock handling, and stale-lock handling is a second guess about whether a process
that wrote a number is the process running under it now.

**A file in the trees root**, which is where §3.9 puts it. A project's trees root and its
repository are one pair - `init` writes both into one project file - so addressing the lock from
the root the provider was handed keeps this module from having to resolve a repository's common
directory in order to find somewhere to put a file. The consequence is worth stating: two trees
roots over one repository would be two locks and would not exclude each other, which `init` does
not produce and nothing in the framework asks for.

**Waited for with a non-blocking attempt and an `await`**, not with a blocking `flock` in a worker
thread. A thread parked in `flock` cannot be cancelled, and §3.9 runs several children under a
group that unwinds; the sleep is where a cancellation lands.

**Never unlinked.** A lock file deleted on release is one a second process can still be holding by
inode while a third creates a new file at the same path and takes that - two holders, both
correct, of a mutex that has quietly become two.

## The run lock, which is the same primitive answering a different question

§3.10 says `clear` "refuses while a run holds a lock" and had no mechanism behind that sentence:
there is no durable "this run is live" record, §3.11 refuses stored status by name, and the
registry mutex above is a millisecond lock around two git subcommands rather than a liveness
claim. The fix §3.10 asks for is "a `flock` on the run directory held for the life of the process:
an OS lock that releases on death, the same shape §3.9 already uses, and not stored status", and
`run_lock` is it.

**On the run's own directory**, `.trees/<label>/`, which is the directory `made` creates, `tidied`
takes away and the registry lock's file is a sibling of. Not a file inside it: a file would have to
be either unlinked on release - the two-holders hazard above - or left behind in a directory whose
whole purpose is to be `rmdir`-able once the last checkout in it has gone. The directory is the
thing being claimed, and `flock(2)` takes a descriptor on one as readily as on a file.

**Non-blocking, and that is the whole difference from `registry_lock`.** That one is a mutex held
for as long as a checkout takes to write, so a waiter is waiting for work that is genuinely
happening and polling is right. This one is held for the life of a whole run - hours - so a `clear`
that waited for it would look wedged rather than refused, and the honest answer is `ConflictError`
at once, naming the label. There is therefore no deadline here and nothing to sleep on.

**It makes the directory it locks**, because `api.run` takes it before anything durable and a run
that has provisioned nothing yet has no directory. That costs nothing anywhere it is taken: `run`
and `resume` provision a checkout inside that very directory, and `clear` goes on to `remove`,
whose `tidied` takes it away again in the same call.

**Released by the OS if the holder dies**, which is what makes it a liveness claim at all - and the
reason it is this primitive rather than a PID file or a recorded flag, for the argument the
registry lock makes one paragraph up.
"""

import asyncio
import fcntl
import os
import shutil
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Final

from agl.ports.errors import AglError, ConflictError, DeniedError, UpstreamUnavailable
from agl.ports.tree_layout import TreesRoot

__all__ = ["deleted", "made", "registry_lock", "run_lock", "tidied"]


# The lock file, in the trees root beside the runs. Nothing can collide with it: `ids.py` refuses
# a `.lock` suffix in any case as a run label, having taken git's own convention one notch
# stricter, so no run's directory can ever be spelled this way.
_LOCK_FILENAME: Final = "worktrees.lock"

# How long a caller waits for the registry before giving up on it. Generous on purpose: the lock
# is held across a `worktree add`, which copies a whole source tree, and §3.9's own arithmetic is
# eighteen checkouts for three runs of five children - so a last waiter under real contention is
# waiting for work that is genuinely happening. What the deadline buys is that a wedged holder is
# reported, with the file named, rather than hanging every other run for as long as the machine is
# up.
_LOCK_TIMEOUT: Final = 600.0

# How often a waiter retries. Only a contended lock ever sleeps - the first attempt is
# non-blocking and succeeds when nothing holds it - so this is latency on the rare path only.
_LOCK_POLL: Final = 0.05

# The lock file is AGL's own state, read and taken by the user who ran it. Nothing is ever written
# into it: what is being locked is the name.
_LOCK_MODE: Final = 0o644


@asynccontextmanager
async def registry_lock(trees: TreesRoot) -> AsyncIterator[None]:
    """Hold §3.9's cross-process lock on the worktree registry, and let go of it.

    Taken around `worktree add` and `worktree prune` and around nothing else; the module docstring
    argues every word of that. Unlocked explicitly and then closed, though closing alone would do
    it - the explicit release is what says the hold ends here rather than whenever a descriptor
    happens to be collected.
    """
    lock = trees.path / _LOCK_FILENAME
    handle = _opened(lock)
    try:
        await _held(handle, lock)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)


@asynccontextmanager
async def run_lock(directory: Path, label: str) -> AsyncIterator[None]:
    """Claim this run for this process for as long as the caller holds it, or refuse at once.

    §3.10's "it refuses while a run holds a lock", made mechanical; the module docstring argues
    every half of it. The directory is made if it is not there, because the first caller takes this
    before the run has provisioned anything, and it is deliberately **not** taken away again on the
    way out - a directory unlinked while somebody may be about to lock it is the two-holders hazard
    the registry lock is never unlinked to avoid, and `tidied` inside `remove` is what removes this
    one for real.

    `label` is carried only so that the refusal can name what an operator would type. Nothing here
    parses it, and the exclusion is between two descriptors on one inode rather than between two
    strings, so two trees roots over one repository are two locks - the consequence the registry
    lock states in the same words. Unlocked explicitly and then closed, exactly as `registry_lock`
    is, and for its reason.
    """
    made(directory)
    handle = _opened_run(directory)
    try:
        _claimed(handle, directory, label)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)


def made(directory: Path) -> None:
    """The run's own directory under the trees root, before a checkout goes into it.

    git would make it on the way past, and making it here is what keeps that from being the only
    thing that does: this is the directory `tidied` takes away again, and one module creating and
    removing it makes the pair legible.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise _translated(error, f"the run directory at {directory}") from error


def deleted(checkout: Path) -> None:
    """Take a checkout's files away. Absence is success and says nothing.

    Deleting the directory is safe *because* a linked worktree's `.git` is a file rather than a
    repository, and because the path always comes out of `tree_layout` - so nothing that reaches
    here can be pointed at the user's own checkout.

    Not `ignore_errors=True`, for `FilesystemStore.remove`'s reason: that flag turns a directory
    AGL may not write into a successful removal, and `clear` would report having taken back a
    checkout that is still sitting there. Absence is caught by name; everything else is translated.
    """
    try:
        shutil.rmtree(checkout)
    except (FileNotFoundError, NotADirectoryError):
        return
    except OSError as error:
        raise _translated(error, f"the checkout at {checkout}") from error


def tidied(directory: Path) -> None:
    """Take the run's directory away if the checkout just removed was the last one in it.

    So that §3.10's `clear` really does remove `.trees/<label>/` while holding only the two verbs
    the port offers. `rmdir` and not `rmtree`: a directory still holding a sibling's checkout
    refuses, which is the condition and the check in one syscall, and a failure of any kind means
    the directory is still wanted or already gone - both of which are this function having nothing
    to do.
    """
    try:
        directory.rmdir()
    except OSError:
        return


def _opened(lock: Path) -> int:
    """A descriptor on the lock file, making the file and the trees root if they are not there.

    `O_CREAT` rather than a check and a create: the gap between those two is the race, and the
    file's contents are never read or written, so there is nothing to initialise inside it.
    """
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        return os.open(lock, os.O_CREAT | os.O_RDWR, _LOCK_MODE)
    except OSError as error:
        raise _translated(error, f"the worktree lock at {lock}") from error


def _opened_run(directory: Path) -> int:
    """A descriptor on the run's own directory, for `flock` to be taken on.

    `O_RDONLY` because nothing is ever read through it and nothing may be written into it: what is
    being locked is the directory itself, and a descriptor is only how `flock(2)` is addressed. It
    is opened after `made`, so the one race left - somebody removing the directory between the two
    - arrives as the `OSError` every other syscall here is translated the same way.
    """
    try:
        return os.open(directory, os.O_RDONLY)
    except OSError as error:
        raise _translated(error, f"the run directory at {directory}") from error


def _claimed(handle: int, directory: Path, label: str) -> None:
    """Take the run lock or refuse it. One attempt, no deadline, nothing to wait for.

    `ConflictError` because that is what this state is: something reachable is holding the run and
    nothing here has been changed, which is exactly `errors.py`'s "the world already holds
    something this operation would have to take or overwrite". It is also the class §3.10's two
    neighbouring refusals already use, so a run and a `clear` that collide with a live invocation
    both exit 4.

    The message names the label rather than the directory first, because what an operator does next
    is wait for that run or find the process running it, and the path is there for the case where
    the holder is a process nobody remembers starting.
    """
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ConflictError(
            f"the run {label!r} is already live: something else is holding {directory}, and one "
            f"run cannot be walked twice at once. AGL takes that lock for the whole of an `agl "
            f"run` or `agl resume` and lets go of it when that ends, so wait for the invocation "
            f"that has it or stop it. Nothing here has been changed"
        ) from None
    except OSError as error:
        raise _translated(error, f"the run directory at {directory}") from error


async def _held(handle: int, lock: Path) -> None:
    """Take the lock, waiting for whoever has it, and give up if that goes on long enough.

    `ConflictError` on the deadline, in that class's own words: another process holds it, nothing
    has been changed, and the caller waits or clears the old run. The message names the file,
    because that is the one thing a person needs in order to find out who is holding it.
    """
    deadline = time.monotonic() + _LOCK_TIMEOUT
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise ConflictError(
                    f"another process has held the worktree lock at {lock} for more than "
                    f"{_LOCK_TIMEOUT:g}s. It is taken only around adding and pruning worktrees, so "
                    f"either several runs are checking out large trees ahead of this one or the "
                    f"process holding it is wedged; nothing here has been changed"
                ) from None
        except OSError as error:
            raise _translated(error, f"the worktree lock at {lock}") from error
        await asyncio.sleep(_LOCK_POLL)


def _translated(error: OSError, what: str) -> AglError:
    """The `AglError` an `OSError` means here. Returned, so call sites read as `raise ... from`.

    The same two-way split `FilesystemStore` makes and for the same reasons: a refusal is
    something reachable saying no, and everything else - a full disk, a mount that went away -
    left nothing behind, so the same call may well succeed later. `except PermissionError` catches
    the filesystem's `EACCES` and nothing of AGL's, which is what `errors.py` renamed its own class
    to keep true.
    """
    if isinstance(error, PermissionError):
        return DeniedError(f"the filesystem refused {what}: {error}")
    return UpstreamUnavailable(f"the filesystem could not reach {what}: {error}")
