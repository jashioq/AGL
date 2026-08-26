"""AGL's own operations - run, resume, clear, init, list_workflows - as an importable library.

(Plus `workflow_help`, which is 16.4's `agl workflows <name>` and extends §3.10's grammar; the
section on the two listing functions argues why it is a name of its own and not a parameter.)

§1.5's charge is that there was no importable AGL: `main()` *was* the composition, every decision
lived inside an `argparse` callback, and `_cmd_run` ended in a bare `except Exception` rendering any
bug as `error: <str>`. §1.4's is the same fault from the other side - `_cmd_clean` and `_cmd_init`
were use cases living in the CLI, and `Git(Path.cwd())` was constructed four times, once per
command. This module closes both: the five operations §3.10 names are functions here, each callable
from a test, a harness or another program, and `cli/` is left with argv, an event loop and an exit
code.

The division is exact. `cli/main.py` resolves configuration and dispatches to one of the five;
everything that decides anything - which workflow, whether the label is free, what a run's record
says - is here. A command that grew a second `read_record`, or a second opinion about what `--from`
defaults to, would be §1.4 happening again.

## Composition is per-command (§3.10), and the five signatures below are where that is written

"`main.py` resolves settings and dispatches; each operation then resolves its own prerequisites.
`run`, `resume` and `clear` resolve a project and build a container; `init` takes settings alone;
`list_workflows` takes neither." That is not a note about the CLI, it is the shape of this module -
and a uniform signature is exactly what made composition universal in the first place. 10.4 handed
every operation a `Services` so that the dispatch had one shape to remember, and 11.0 is the bill:
`init` *writes* the project file a container needs in order to be constructible, so an `init` taking
a bundle is an operation nothing could ever reach, and `list_workflows` reads packaging metadata, so
a `list_workflows` taking one makes `agl workflows` demand a registered repository in order to list
what is merely installed.

So the three operations addressed to a run take `(services, project, ...)`; `init` takes `Settings`
plus what the invocation said - a `cwd` and how to ask one question, both argued below - and
`list_workflows` takes nothing but the entry-point seam this module already had. Five signatures
where there was one shape is the price, and it is paid in exactly one place - `cli/main.py`'s
dispatch, the only caller that has to know all five - rather than by the two operations that would
otherwise have had to be built out of reach.

## No operation builds a port, including the ones that are handed none

`config/container.py` is the only module that may say `new` (contract 5), so an `api` that
constructed its own ports would be a second composition root and `lint-imports` would say so. That
is why `init` losing the bundle is not `init` gaining a container: what it is handed shrank, and
what it may construct is unchanged at nothing. Taking the bundle rather than building one is also
what keeps measurable target #8 reachable: an operation runs end to end on `container.fakes()` with
no network, no git and no process, because substituting every implementation at once is one argument
rather than a fixture. `tests/test_api.py` does exactly that, which is the walking skeleton proved
from the library side before 10.4 wired the argv side.

`run` takes the project's **name** and not `config.schema.Project`. A run's address under `AGL_HOME`
is `RunScope(project, label)` and the name is the whole of what that needs; the rest of a `Project`
- its repository, its trees root, its build command - has already been spent by the container in
constructing the ports handed in beside it. Taking the whole object would put a `config` type in a
signature a library caller has to satisfy, in exchange for seven fields nothing here reads.

## Async where the ports are, and the event loop belongs to `cli/`

There is no `asyncio.run` in this file and there must not be. `Store` and `History` are async
because an implementation may go out of process, and a library that started a loop of its own could
not be called from inside one - which is precisely what 16.5's harness, and every `pytest.mark
.asyncio` test below, do.

**Three of the six are not async, and the rule is the same one read the other way**: a function that
awaits nothing is not declared async in order to look like its neighbours. `list_workflows` reads
packaging metadata and sorts strings, `workflow_help` imports a package and formats a parser, and
`init` walks the filesystem and writes one file - no port is involved in any of them, which is the
same fact stated in the vocabulary that decides it. `cli/main.py` gives that as its reason for
leaving `asyncio.run` to the command rather than to the dispatch: two of the five commands start no
loop, and a dispatch that awaited everything would make them pretend otherwise.

## What `run` does, in order, and the two things it deliberately does not

Load the workflow, refuse a label that is already taken, refuse a deliverable branch that already
exists, ask §3.2's preflight whether the backends this workflow's module names are ready, pin the
base ref to a full object name, claim the run, write `run.json`, provision
the run's own `_base` worktree from that pin, then open the terminal, await the workflow's function
inside it, and give back every integration lease it was still holding. The order is load-and-parse
first because those two refuse with no I/O at all - §3.3's "before anything runs" read as strictly
as it can be - then the two checks that decide whether this run may exist, then preflight, then the
claim and the three things addressed to the repository, and the terminal last of all because it is
the only one of them a person can see.

**The branch check is the record check asked about the other half of a label**, and it is 17.0's.
A `clear` that keeps an unmerged `agl/<label>` (§3.10) takes the record away and leaves the branch,
so the label reads as free to the store and is not free in the repository - and a `run` that
carried on would attach to that branch, start from its tip, and ignore `--from` in silence. It sits
where it does because it costs one repository read: after the record check, which is cheaper, and
in front of preflight, which is the only refusal here that costs real turns.

**Preflight sits between those refusals and the record**, and both sides of that are the same
argument read in two directions. It is the one refusal here that costs real turns - `check_ready`
asks a live harness - so every refusal that is free goes in front of it. And it is the last thing
that can refuse while this run has left *nothing* behind: `write_record` and `workspaces.open` are
both durable, so a run refused after them is one an operator has to `agl clear` before they can
retry the one they meant. A missing binary or a logged-out session is exactly the failure somebody
fixes in ten seconds and immediately re-runs, and it should cost them one command and not two.

**The run is claimed for the process before either durable line and let go of at the end**, which
is §3.10's "it refuses while a run holds a lock" arriving three verbs at once: `run` takes it,
`resume` takes it, and `clear` takes it briefly around its removals, so a `clear` aimed at a run
live in another `agl` refuses at exit 4 instead of taking that run's checkouts away underneath it.
It is `WorkspaceProvider.hold`, an OS lock the kernel drops when the holder dies, and it is not
stored status - which §3.11 refuses by name and which a crash would leave behind as a lie.

**The record is written before the workflow is invoked**, so a crash mid-run leaves something behind
to resume or to clear. It is the one value in AGL with no other copy anywhere (`ports/store.py`), so
the cost of writing it early is a stale record after a crash - which `clear` takes away - and the
cost of writing it late is a run that happened and cannot be named.

**And it is written before the workspace is provisioned**, which is the same argument at the sharper
end and the reason those two lines are in the order they are. `WorkspaceProvider` offers no
enumeration on purpose (`ports/workspace.py`), so `run.json` is the only thing that names a run at
all: a crash after `open()` must still leave a record naming the label, or `agl/<label>` and
`.trees/<label>/_base/` are a branch and a directory nothing can ever reach again. Writing first
costs a record for a run whose checkout was never cut, which is one `agl clear -f` away; writing
second costs a leak that no command in AGL has a way to address. 16.3 is what put the flag in that
sentence, and `clear` says why: the containment question is asked about `agl/<label>`, a run refused
here never created one, and both `History` implementations raise for a ref that names nothing rather
than answering "no". `-f` asks nothing, so it is the spelling that reaches this state.

**The exposure this changed, stated rather than left to be found.** §3.9's known leak is a crash
between `open()` and the first entry write, and 13.4 makes that window start earlier - at this
function rather than at the first step - so it now covers the whole of a workflow, including one
that never steps at all. What it does **not** widen is the half of that leak nothing can address:
`_base` is addressed by `namespace=None`, which is derivable from the label alone, so a record on
disk is the whole of what `clear` needs in order to reach it, and the two lines above are in the
order that guarantees one. The unreachable half belongs to *children* and is untouched here - a
child's checkout is opened by `sdk/_engine/steps.py` on its first step, `Store.namespaces` lists
only namespaces that have recorded something, so a crash in between leaves a directory `clear`
cannot see and afterwards cannot `rmdir` past. Closing that is not this deliverable's, and widening
this window did not make it worse.

**A worktree and a branch now, and no lock and no persistence beyond `run.json`.** 13.4 is what put
the first two here, and §3.9 is why they belong to this function rather than to the first step: AGL
never writes into the target repository except through a `Workspace` - its own integration branch
included, which lives in `_base` and not in the user's checkout - and "`agl/<label>` is a real ref
from run start and advances with each `integrate()`, so progress is inspectable live - `git log
agl/auth`, `git diff main..agl/auth`". That sentence was false for a run whose workflow had not yet
taken a step, because the checkout was opened lazily by `run.step` and a workflow that ran no steps
opened nothing. `RunSpec.branch` is still written here and still not composed for the provider:
`WorkspaceProvider.open` derives `run_branch(label)` itself, so the record and the ref agree by both
reading `tree_layout` rather than by one of them being handed the other's answer. Steps persist
their own entries, from inside the workflow, through the `Run` built on the last line; integration
is 14. The one lock §3.9 asks for is on git's worktree registry and is taken inside the adapter,
around the two commands that mutate it and nothing else.

## `run` catches nothing at all, which is how the `Stop` ordering hazard is met

§3.1 makes it a stage-10 acceptance criterion: `Stop` descends from `AglError`, so a handler that
catches the base first swallows a deliberate end and reports 6 or 70 where the contract promises 7.
In this module the hazard is *wrapping* rather than reporting - any `except AglError` that
translated, annotated or re-raised would turn a workflow's `ReviewNotConverging(Stop)` into
something else on the way out, and the exit code would be right by accident or wrong by one edit.

So there is no `except` in this file, and there never may be. A workflow's exception leaves
`api.run` as the object it raised, with its own traceback under it, and `cli/exit_codes.exit_status`
answers 7 for it without either module having learned what `ReviewNotConverging` is. That is
stronger than catching `Stop` first, and it is pinned by identity in the suite rather than by class.

**14.1 put a `try` here and the rule is unchanged, because the rule was about catching.** §3.4 gives
the framework a lease per integration target and makes run exit "the sweeper, not the lifetime" for
one no verb settled, so the last two lines of `run` are a `finally` around the workflow's function.
A `finally` sees no exception, names no class and cannot decide anything: control leaves it carrying
whatever arrived, `Stop` subclass and all. What would break the criterion is an `except` of any
width, which is why the sentence above is written about that word rather than about `try`.

**15.1 put an `async with` here and the rule survives it mechanically.** `Terminal.__aexit__` is
annotated `-> None` on the port; suppressing an exception from a context manager means returning
something *truthy*, `None` is falsy, and `mypy --strict` is a gate - so no conforming terminal can
swallow a workflow's `Stop`, and that is a fact about the signature rather than a promise an
implementation keeps. Like the `finally`, it sees the exception in flight and can decide nothing
about it. What it can still do is **fail**: a teardown that raises replaces the exception in flight
with its own. That is the hazard the `finally` has had since 14.1 - `release_all()` could raise too
- and it is a crash in AGL either way, never a translation of a workflow's.

## The terminal is open around the workflow's function and around nothing else

`ports/terminal.py` makes a `show` outside the context an `InternalError`, on the argument that "the
framework opens the terminal, so a call outside it is AGL's own ordering bug rather than anything a
workflow author did". This function is that framework, and until 15.1 nothing here entered one - so
every `show` in a real run raised. One `async with services.terminal` closes it, and the question
worth writing down is where it goes, because the answer is not "as early as possible".

**It opens after the record and after `_base`, because nothing above it shows anything.** The
context is exactly the region in which `show` is legal, and the only thing in this function that can
`show` is the workflow. Opening earlier would widen that region over code where a `show` would be
AGL's own bug and would now be quietly accepted, and it would take a person's display over in order
to draw nothing across the refusals a person has to read - a name nothing registers, a flag the
params refuse, a label already taken. It is also a real resource and not a flag: `RichTerminal`
starts a redraw loop and takes the console, so entering before `write_record` would make a failure
there unwind through a display teardown for a run that does not exist. It is entered exactly once,
which every implementation requires - a second `__aenter__` is refused.

**It closes inside the lease `finally`, and neither ordering is load-bearing.** The two teardowns
are independent: `release_all()` releases in-process locks and shows nobody anything, and handing
the display back takes no lease, so neither needs the other and each runs whatever the other does.
What settles it is scope - the context means "`show` is legal here" and `release_all()` cannot show
anything, so it belongs outside - and, second, that the display is then handed back before the last
thing this function does, so a teardown that goes wrong reports onto a terminal that has been
restored. Written the other way round the `async with` would also have had to take the `finally`
inside it, and 14.1 argued that construct's scope where it stands.

**`resume` carries the same three lines and it had to be built to notice.** A resumed run shows the
same screens the run showed, so the whole of the argument above applies to it word for word - and
`docs/agl-build-stages.md` records that "nothing in the repository would notice its absence",
because until 15.1 no test drove a `show` through an `api` entry point at all and the hole was
therefore invisible for every stage that had one. What closes it is not a rule written here but a
test per entry point that goes red when the line is deleted, which `tests/sdk/test_run_terminal.py`
now holds for both.

## The registry, and the one seam it left open

`config/registry.py` split itself into a pure core taking entry points and one impure line asking
the interpreter what is installed, "so a test drives them with `EntryPoint` values it constructs
itself". This module keeps that split rather than closing it: `points=` defaults to
`registry.installed()`, which is what every real invocation wants, and a caller that has its own set
- this suite, and 16.5's harness running a workflow the author has not installed yet - supplies one.
The alternative was for `api` to call `installed()` unconditionally and for callers above to
monkeypatch a module attribute to test anything, which is a seam too, without a signature.

`registry.load` is generic over the type its caller expects, and the annotation on the result is
load-bearing: a bare generic class in `type[T]` position infers `Workflow[Any]`, PEP 696 default
notwithstanding, so the call site writes `wf: Workflow[object]` and the `Any` stops here.
`Workflow[object]` cannot be passed as `kind` instead - `isinstance` refuses a subscripted generic.
Everything downstream then follows at `object`, which is the honest type for "some workflow's
params, and this module does not care which".

## `RunSpec.workflow` records the name that was typed, not `wf.name`

The two are the same string by convention and nothing here compares them, which `sdk/workflow.py`
notes is a comparison only this module could make. It is deliberately not made, because the field's
job settles which of the two belongs in it: `resume` reads `run.json` and asks the registry for that
workflow again, and the registry indexes by the **entry-point key**. Storing what the workflow calls
itself would produce a record that resumes only while the two agree, and fails with "no workflow
named ..." on the day a package renames one of them - naming the string the operator never typed.

## What `resume` does, in order, and the one thing it deliberately does not

Read the record and refuse a label that has none, parse it, load the workflow the record names,
refuse a version that is not the one it was stamped with, rebuild the params instance out of the
record, ask preflight the same two questions `run` asked, claim the run, reopen its own `_base`
worktree from the commit the record pins, and then open the terminal and await the workflow's
function inside it. The shape is `run`'s with the record write taken out and one comparison put
in, which is the honest description of what a resume is: the same run, walked again - and the
claim is `run`'s too, in the same position, because a run being walked again is a run that is
live.

**And the refusals in front of preflight are all four of them, which is `run`'s rule and not a
resemblance to it.** Preflight is the one call here that costs real turns, so everything that can
refuse for free goes first: the record's existence, its shape, the workflow's name, its version and
its params. Each of those is a store read or a comparison, and an ordering that spent a
`check_ready` on a live harness before telling a workflow author they edited a params dataclass and
left the `version` line alone would be charging for the most common way any of this fires.

**The record is not rewritten, and that is §3.6 rather than an economy.** `base_sha` pins the
resolved commit "not just the ref name" so that a commit landing on `main` between run and resume
cannot move the first step's starting head - so a resume that re-resolved `base_ref` and stored the
answer would perform the failure the field exists to prevent, in the operation the field exists
for. The same reading covers the rest of it: `created_at` is when the run started rather than when
it was last picked up, and a `workflow_version` stamped over instead of compared against is a
migration written as an assignment.

**The version comparison is `ConflictError`, the same class `run` answers a taken label with**, and
the symmetry is the argument. Both are the two ways a run and a world fail to match: `run` finds
the world already holding the name it was given, `resume` finds it holding a different workflow
under the name the record gives. Neither is `NotFoundError` - in both cases everything named was
found - and `ports/errors.py` puts that distinction on the class in as many words, "the world
already holds something this operation would have to take or overwrite ... the exact mirror of
`NotFoundError`".

**`workspaces.open` is called here for `run`'s own reason**, and the fact that it is idempotent is
what makes that free rather than merely safe. §3.9 promises `agl/<label>` is a real ref a person can
`git log` from run start, and `run.step`'s open is lazy, so a resumed run whose workflow takes no
step would otherwise leave nothing - and the state a resume exists to recover from is a crash,
which includes a crash between `write_record` and `open` that left a record naming a checkout
nobody ever cut. On a run that has one, "an existing workspace is returned exactly as it stands"
means this line reads a table and returns, ignoring the base it was handed, so it cannot rewind a
checkout that has advanced.

## What `clear` does, in order, and why the records go last

§3.10's own list is "`.trees/<label>/`, the `agl/_work/<label>/*` child branches, and the run
directory". In order: read the record and refuse a label that has none, enumerate the run's
namespaces, take each child's checkout back and then delete the line of work it carried, take the
run's own `_base` checkout back, decide about `agl/<label>`, and remove the records last.

**The records go last because they are the enumeration.** `Store.namespaces` is the only place the
set of namespaces a run used is written down - `WorkspaceProvider` deliberately offers none, and
`ports/store.py` names `clear` as that member's one consumer - so a `clear` that removed the records
first would have thrown away, in one call, the list of everything it still had to take back, and
every checkout the run held would be stranded with nothing in AGL able to name it again. Nothing
below that line has to be ordered against anything else: both teardown verbs tolerate absence in the
port's own words, which is what makes `clear` after a crash the ordinary case and `clear` twice the
whole of the recovery.

**Each namespace is `remove` then `discard`, in that order, because the port says why**: "an
implementation is within its rights to refuse to delete a line of work that something still has
open, and calling these in this order means no caller has to know whether it does."

**And every one of them is a bare `Namespace`, never a path and never a scope**, which is §3.9's
decision paying out three stages later. `AGL_HOME` nests arbitrarily, so the enumeration below is a
real traversal through `RunScope.inside`; the trees root is flat, because a worktree inside another
worktree's working tree is untracked files to the parent. Namespace names are therefore unique
run-wide rather than merely among siblings, so a scope two levels down in the store is one flat
directory in the trees root and the provider takes the name alone. Without run-wide uniqueness this
loop would have to carry each namespace's ancestry to the provider and the provider would have to
compose a nested path out of it - which is the shape §3.9 refused.

## The leak `clear` does not close, stated exactly

**What is left behind.** A child's checkout directory `.trees/<label>/<namespace>/`, that child's
branch `agl/_work/<label>/<namespace>`, and - because that directory is still standing -
`.trees/<label>/` itself, whose `rmdir` in `_trees.tidied` then declines.

**What causes it.** `Store.namespaces` reports a namespace because something was *recorded* under
it. `sdk/_engine/steps.py` opens a child's checkout at the top of its first step and writes that
step's entry at the bottom, so a crash in between leaves a directory this module cannot see. §3.9
calls that window "a crash between a *child's* `open()` and its first entry write" and does not say
how long it is; the honest answer is the length of that first step, which is an agent turn.

**Why it cannot be closed within the ports.** No port can enumerate `agl/_work/<label>/*`, by
design. `History` is seven questions about the past and none of them is a listing - `exists` and
`message` both answer about one name the caller already composed, which is why neither is one;
`ports/workspace
.py` argues at length that a provider offers no enumeration, "because an enumeration method would
buy tidiness by requiring that every implementation be able to list, which a service handing out
checkouts to many clients may not honestly be able to do". Nor can this module go and look: a
`Services` carries no trees root, and a `clear` that computed a path under one would be §1.4's
`_cmd_clean` reaching past the `Store` port, inside the operation that exists to answer that charge.

**Why §3.10 accepts it** - the same asymmetry the branch decision below is made on. A retained
directory and a retained ref cost a stale name. The verb that would find them costs a port member
that every implementation has to provide and every contract suite has to assert, for one caller and
one crash.

**It is child-only, and that is what writing `run.json` before provisioning buys.** The run's own
checkout and its own branch are addressed by `namespace=None`, which is derivable from the label
alone, so `clear` reaches both with no enumeration at all - `ids.py` refuses every spelling of
`_base` as a `Namespace`, so a caller cannot even build the alternative. A record on disk is the
whole of what `clear` needs, and `run` writes one before it provisions for exactly this reason.

**`clear` cannot report any of it, and does not pretend to.** `_trees.tidied` swallows the failed
`rmdir` by design - "a failure of any kind means the directory is still wanted or already gone" - so
a leaked child leaves `.trees/<label>/` standing with no signal anywhere on this path. Every way of
producing one is either a new port member or a filesystem read from a module that holds no root, so
what is owed is this paragraph rather than an invented warning.

## All five verbs are built, and 16.4 is the deliverable that finished the surface

§3.10's five verbs are this module's row in `ARCHITECTURE.md` §6, and the CLI's dispatch has been
written against that surface since 10.4 rather than against whichever part of it existed. `init` was
a signature that refused, naming this deliverable; it is a function now, `_unbuilt` is gone with it,
and nothing in AGL declares an operation it cannot perform.

## `init` takes a `cwd`, and that is the one place §3.10's "settings alone" is read against

§3.10 asks `init` to "take settings alone" *and* to "detect the git root", and after 11.0 the two
cannot both be literally true: `Path.cwd()` travels inside `cli/main.py`'s deferred thunk, so an
`init` taking `Settings` and nothing else would have to read the working directory ambiently from
here. It takes a `cwd: Path` instead, and the argument has three parts.

**This is a library.** `agl.api.init(settings, cwd, ask)` is callable from a test, a harness or
another program without `os.chdir`, which is process-global, hostile to a suite that runs workflows
in-process, and irreversible in the way that matters - a failure between the chdir and the restore
leaves every later test somewhere else. An ambient read would make `init` the one operation in this
module that cannot be driven except by moving the whole process.

**The working directory is environment**, and `config/sources.py` states the contract that closes
this: "nothing downstream may re-read the environment or re-parse a settings file. After `resolve`
returns, the answer is fixed for the invocation." A `Path.cwd()` below that line is a second answer
to a question the composition root closed, free to differ from the first the moment anything in the
process moves - and `sources.Resolved.project(cwd)` already takes the directory as an argument for
exactly this reason, so an `init` that read it would be the one asker that did not.

**And "settings alone" is drawn against "resolve a project and build a container".** The sentence it
lives in is about *composition*: "`run`, `resume` and `clear` resolve a project and build a
container; `init` takes settings alone; `list_workflows` takes neither." What it fixes is that
`init` needs no container - it writes the file a container is built from. A `cwd` is neither a
container nor a project; it is what the invocation said, the same category as `argv` on `run` and
`label` on `resume`, and it is what keeps `Path.cwd()` written exactly once in the process
(`cli/main.py` reads it, `Invocation` carries it, this takes it).

## `init` asks through a callable, and this module never names `input`

§3.10 has `init` "ask for the build command", and `_BUILD_GUESSES` is named there only to say why:
inferring it is unreliable, so AGL asks instead of guessing. There is therefore no build-tool
detection anywhere in this codebase, which is half of §1.4's charge against `_cmd_init` answered by
not writing something.

The question is put through `ask`, a `Callable[[str], str]` this function is handed. It has **no
default**, and that is the decision rather than an omission. `api.clear`'s docstring settles the
matching case one direction over: a sentence printed from here "would be one a library caller, a
harness and 16.5's testing bundle could not see and could not suppress", and there is no `print`
under `src/agl/` outside `cli/`. Reading a person's stdin is that same boundary from the other side,
and `input()` writes its prompt to stdout on the way. A parameter with no default is what keeps
`input` out of this module *mechanically*: it cannot be called without a caller saying how the
question is asked, and `cli/main.py` is where the real answer - `Invocation.ask`, defaulting to
`input` - is written down, once, at the edge where a person is.

It is deliberately not `points=`' shape. That seam spells its real default `None` because
`registry.installed()` is a call that must be deferred and is inert when it happens; there is no
honest `None` here, because this module would have to name `input` to interpret one.

**The prompt is this module's**, because the question is: what AGL needs is the command a merge gate
runs, and the CLI's job is to carry the words to a person and the answer back. A blank answer is
refused rather than looped on - a loop is an interaction run against a callable that may not be a
person at all - and refused *before* anything is written, which is `schema.Project`'s own rule about
a blank build applied one step earlier, where the operator can still retype it.

## `list_workflows` and `workflow_help` are two functions, and the split is the guarantee

`agl workflows` lists, and `agl workflows <name>` prints one workflow's own flags (16.4 - and see
`cli/commands/workflows.py`, which records that the second half extends §3.10's grammar). The
temptation is one function with an optional name; they are two, for three reasons that are really
one.

**The listing imports nothing and that is its whole value.** `config/registry.py`: "one workflow
package that fails to import still appears in the listing, and every other workflow still runs. A
registry that imported the world to print a list would let any broken third-party package take down
the command an operator runs to find out what they have." A function that sometimes loads a package
cannot carry that promise in its name, its docstring or its type - and the promise is the reason the
listing is worth having on a machine where something is broken.

**The return types differ** - a tuple of names, or one block of help text - so a single function
would answer at a union that every caller narrows, on a parameter that is also what decides which
half of the union comes back.

**And they are two different registry operations**: `registry.names` never calls `load`, and `load`
is the one that runs somebody else's code. Two names keep that visible at every call site.
"""

from collections.abc import Callable, Iterable, Sequence
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Final

from agl.config import registry, sources, toml_file
from agl.config.schema import Settings
from agl.ports.errors import ConflictError, InputError, NotFoundError
from agl.ports.history import History
from agl.ports.home_layout import RunScope
from agl.ports.ids import Namespace, ProjectName, RunLabel
from agl.ports.run import RunSpec
from agl.ports.store import Store
from agl.ports.tree_layout import TreesRoot, run_branch
from agl.sdk import params
from agl.sdk._engine import preflight
from agl.sdk._engine.integration import Leases
from agl.sdk._engine.services import Services
from agl.sdk.workflow import Run, Workflow

__all__ = ["Ask", "clear", "init", "list_workflows", "resume", "run", "workflow_help"]

# Where `init` puts a repository's working checkouts: `<repo's parent>/.agl-trees/<name>`, which is
# §3.10's own example. Beside the repository and never under it (§3.5), and spelled once - a second
# module choosing a trees root would be a second answer to where AGL's checkouts live.
_TREES_DIRNAME: Final = ".agl-trees"

# What `init` asks a person, and the whole of what AGL asks anybody. It says what the command is
# for, because "build command:" alone invites the *other* build command - the one a workflow writes
# into a prompt, which §3.11 keeps out of the framework entirely.
_BUILD_PROMPT: Final = (
    "What command builds and tests this project? AGL runs it at the merge gate, through a shell, "
    "in a worktree of its own - `./gradlew build`, `make test`, `npm run build`.\n"
    "build command: "
)


type Ask = Callable[[str], str]
"""How `init` puts its one question to whoever is running it: a prompt in, their answer out.

The seam the module docstring argues, and a type rather than a bare `Callable` at two signatures so
that the two agree by construction. `cli/main.py` holds the real one - `input` - and a test, a
harness or another program hands in whatever answers for it."""


async def run(
    services: Services,
    project: ProjectName,
    name: str,
    label: RunLabel,
    argv: Sequence[str] = (),
    *,
    base_ref: str | None = None,
    points: Iterable[EntryPoint] | None = None,
) -> None:
    """Start a run: `agl run <workflow> -n <label> [workflow flags] [--from <ref>]` (§3.10).

    `name` indexes the `agl.workflows` entry points and `argv` is the workflow's own flags alone,
    the generic parser having taken its arguments off the front. `base_ref` is `--from`, and `None`
    means the repository's default (§3.9) - the configuration does not record one and the command
    line cannot see the repository, so `History` is what answers.

    Raises, and nothing else reports: `NotFoundError` for a name nothing registers (exit 3),
    `InputError` for flags the workflow's params refuse (exit 2), `ConflictError` for a label that
    already has a record, for a deliverable branch that already exists, and for a run of this label
    that is live in another process (exit 4), `DeniedError` for a role requiring a capability its
    backend does not offer (exit 5 - something reachable said no, and `ports/errors.py` names this
    case on that class), `UpstreamUnavailable` for a harness that is missing, out of date or
    logged out (exit 6, raised by the adapter that said so and passed on untouched), and whatever
    the workflow itself raises, untouched - a `Stop` subclass included, which is the ordering
    criterion §3.1 makes of this stage.
    """
    wf: Workflow[object] = registry.load(_points(points), name, Workflow)
    # Parsed before any port is touched: a flag the workflow will not accept costs nothing to
    # refuse here and would otherwise be discovered after a record had been written for it.
    given = params.parse(wf.params, argv, prog=f"agl run {name}")

    scope = RunScope(project, label)
    if await services.store.read_record(scope) is not None:
        # §3.10's refusal, verbatim but for the em dash, which no message under `src/` spells.
        # It is left verbatim although the refusal below makes it incomplete: `agl clear auth` may
        # keep `agl/auth` and leave the label taken, so "or `agl clear auth`" is a first step
        # rather than the whole way out. What carries an operator on from there is the sentence
        # `clear` answers with when it keeps a branch (`_kept`), which names the label's fate and
        # what deletes the ref - and the plan's own words are not this module's to improve.
        raise ConflictError(
            f"run {str(label)!r} already exists - `agl resume {label}` or `agl clear {label}`."
        )

    # 17.0's refusal, and it is the one above asked about the other half of what a run takes. A
    # `clear` that kept an unmerged `agl/<label>` (§3.10) took the record away and left the branch,
    # so from here the label reads as free while the name a run needs is not - and `open` would
    # take its *attaching* path, cut nothing, and start this run from the old tip with `--from`
    # silently ignored. §3.10 names that outcome and refuses to price it: "a silently wrong base is
    # not a cost the asymmetry argument priced."
    #
    # **The fix is here and not in the port.** `open`'s "base is consulted only when provisioning"
    # is correct and argued - a child's base advances with every integration, so re-cutting on a
    # reopen loses work - and its attaching path is what an `open` after a `remove` needs. What is
    # wrong is starting a run over a name somebody else's run is still under, which is exactly what
    # §3.10 refuses one line up and what `ports/workspace.py` gives the reason for: "adopting it is
    # how a typo'd label silently continues somebody else's work".
    #
    # **`ConflictError`, for the reason the neighbouring refusal is one**: everything named was
    # found, and the world already holds something this operation would have to take or overwrite,
    # which is `ports/errors.py`'s own line about this class. Exit 4 follows from the class, and
    # every this-name-is-taken refusal in this module answers with it.
    #
    # **Its position is the ordering rule and not an exception to it.** Everything that can refuse
    # without asking anybody anything goes first, and preflight goes last among the refusals
    # because it costs real turns. This costs one repository read, so it goes after the record
    # check - the cheaper of the two, and the one whose message names both ways out - and in front
    # of preflight.
    branch = run_branch(label)
    if await services.history.exists(branch):
        raise ConflictError(
            f"the branch {branch!r} already exists, so run {str(label)!r} cannot start: AGL would "
            f"attach this run to that line of work and carry on from wherever it got to, with "
            f"whatever `--from` said ignored (§3.10). This is what an unfinished run leaves - "
            f"`clear` keeps a branch whose work is not yet in the base ref, and takes that run's "
            f"records away with everything else, so there is nothing left here for `agl clear "
            f"{label} -f` to address. `git log {branch}` is what is on it, `git branch -D "
            f"{branch}` frees the label, and any other label starts a run of its own."
        )

    # §3.2's preflight, and its position is the whole of what 16.1 decided here. It is the one
    # refusal in this function that costs real turns, so everything that can refuse for free goes
    # first: the registry, the params, and the conflict check, which is a store read that decides
    # whether this run may exist at all. And it is *before* the record and before `_base`, because a
    # run refused at preflight must leave nothing behind - otherwise an operator has to `agl clear`
    # a run that never started before they can retry the one they meant. Before the terminal too,
    # for the reason the module docstring already gives about that `async with`: a refusal a person
    # has to read should not be drawn across a display AGL has taken over.
    #
    # `services.agents` and `wf.fn`, not the bundle: `sdk/_engine/preflight.py` takes one port and
    # the workflow's own function, so that the module whose job is to refuse before anything
    # happens cannot grow a second reader. The function is what names the registry - UF1.3 took
    # `roles=` off `@workflow`, and the `@role(model=…)` factories a workflow can reach are the
    # ones bound in the module its `def` ran in - so nothing here has to know how a role is found.
    # 16.2 makes this same call from `resume`: the record names the workflow, the registry hands
    # back the same `Workflow`, and it is the same module.
    await preflight.check(services.agents, wf.fn)

    # `base_ref` is what the user said and `base_sha` what it meant now. Without the second, a
    # commit landing between run and resume moves the first step's starting head (§3.6).
    ref = await services.history.default_ref() if base_ref is None else base_ref
    spec = RunSpec(
        workflow=name,
        workflow_version=wf.version,
        label=label,
        base_ref=ref,
        base_sha=await services.history.resolve(ref),
        branch=branch,
        params=params.to_json(given),
        created_at=services.clock.now(),
    )

    # §3.10's run lock, opened here because here is the first durable thing this function does.
    # `WorkspaceProvider.hold` is a non-blocking claim on the run's own directory that the OS lets
    # go of if this process dies - what §3.10 asks for, and what §3.11 will not let it be instead:
    # "stored status: derivable from which entries exist. Two sources of truth is what forces
    # `reconcile_on_resume.py` to exist." Everything below is inside it, so it is held for the life
    # of the invocation, and a `clear` aimed at this run while it runs refuses at exit 4 rather
    # than taking its checkouts away underneath it.
    #
    # **Above the record and below every refusal**, which is one decision read from two sides. It
    # has to be above `write_record` and `open`, because those are what a concurrent `clear` would
    # be racing. It may not be above the refusals, because the claim is what this invocation makes
    # once it is committed to being a run, and everything before this line is still deciding
    # whether the run may exist at all. That is also what makes taking it free of consequence: a
    # claim makes `.trees/<label>/` if it is not there, and every path reaching this line
    # provisions a checkout inside that very directory two lines down.
    #
    # **A `finally` that cannot be an `except`**, like the two constructs below it: `__aexit__` is
    # `-> None` on the port, and suppression means returning something truthy, so a workflow's
    # `Stop` leaves this line as the object it was raised as.
    async with services.workspaces.hold(label):
        await services.store.write_record(scope, spec.to_json())

        # §3.9's `_base`, cut eagerly and **after** the record, which is the whole of what these two
        # lines' order buys: `run.json` is the only enumeration `clear` has, so a crash after this
        # call must still leave a record naming the run - see the module docstring, and
        # `ports/workspace.py` for why no provider will ever be able to list what it holds.
        #
        # `spec.base_sha` and never `ref`, never `base_ref`: `open` takes a ref expression or a
        # commit id, `Journal` takes only the second, and the run's own base is pinned precisely so
        # that a commit landing on `main` between this line and the first step cannot move where the
        # checkout was cut from (§3.6). The record and the checkout therefore agree by construction,
        # being the one value spent twice.
        #
        # The `Workspace` is deliberately dropped rather than carried into `Run`. `open` is
        # idempotent by contract - "an existing workspace is returned exactly as it stands" - so
        # `run.step`'s lazy open in `sdk/_engine/steps.py` hands back this very checkout on first
        # use and cuts nothing. Nothing else moves: this call is not a new path into the engine, it
        # is the same call made earlier, so that a workflow which takes no steps at all still leaves
        # `agl/<label>` a real ref.
        await services.workspaces.open(label, None, spec.base_sha)

        # §3.4's lease per integration target, constructed here and not left to `Run`'s own default,
        # because being the sweeper for a lease no verb settled needs something above the workflow
        # to be holding the handle - and a defaulted field is built where nothing can reach it. This
        # is the one of `Run`'s three shared tables the composition root passes.
        leases = Leases()
        # The `Run` is built from what this function already computed and nothing else: `scope` is
        # the address the record above went to, and `base` is the same resolved commit the record
        # pins and the checkout was cut from.
        #
        # **The `try` is a `finally` and never an `except`**, which is what keeps the module
        # docstring's `Stop` argument true: nothing here catches, translates, annotates or re-raises
        # a workflow's exception, so it still leaves this function as the object it raised. What the
        # `finally` adds is that an unresolved conflict does not outlive the run holding a lease and
        # a namespace's step lock - a workflow that returned without deciding, raised, or was
        # stopped mid-decision leaves a live integration, and the object it is reachable from is
        # going away with the workflow.
        #
        # **It releases the lease and deliberately does not abort the adapter's hold.** The hold is
        # durable by design (§3.4) so that a later invocation can find one it did not take, and 14.0
        # made a pre-existing hold answer as a `Conflict` rather than exit 70 - so aborting on the
        # way out would silently discard a partial resolution somebody may be in the middle of
        # making, which is the shortcut §3.4 forbids by name. `sdk/_engine/integration.py` argues
        # the whole of it.
        try:
            # §3.7's terminal, entered around the workflow and around nothing else. `show` outside
            # the context is `InternalError` by the port's own rule, so without this line every
            # screen in every real run would refuse - and the region where `show` is legal is
            # exactly the region a workflow runs in, which is why this is here and not up beside the
            # record write. The module docstring argues the placement and the ordering against the
            # `finally` below.
            #
            # Not an `except` and not able to become one: `__aexit__` is `-> None` on the port, and
            # a context manager suppresses only by returning something truthy - so a `Stop` on its
            # way out of `wf.fn` passes through this line untouched, mechanically rather than by
            # promise.
            async with services.terminal:
                await wf.fn(
                    Run(
                        params=given,
                        services=services,
                        scope=scope,
                        base=spec.base_sha,
                        leases=leases,
                    )
                )
        finally:
            leases.release_all()


async def resume(
    services: Services,
    project: ProjectName,
    label: RunLabel,
    *,
    points: Iterable[EntryPoint] | None = None,
) -> None:
    """Continue a run from its record: `agl resume <label>` (§3.10).

    The label only - params come from `run.json`, which is why nothing here takes argv, no workflow
    name and no `--from`. Every one of those is read back out of the record instead: the
    entry-point key the run was started with, the version it was stamped under, the commit it was
    pinned to, and the parameters it was given. §3.10: "`resume` takes the label only; params come
    from `run.json`. `resume` on a missing label errors symmetrically. Keeping both verbs makes a
    typo'd label a loud error rather than a silent replay of something unrelated."

    Raises, and nothing else reports: `NotFoundError` for a label with no record (exit 3, the exact
    mirror of `run`'s refusal of one that has, and the two messages are written as a pair) and for a
    workflow the record names that nothing registers, `ConflictError` for a record whose
    `workflow_version` is not the installed workflow's (exit 4), `InputError` for a record whose
    params that workflow's current class will not take (exit 2, `sdk/params.py`'s refusal),
    `DeniedError` and `UpstreamUnavailable` out of preflight exactly as `run` raises them, and
    whatever the workflow itself raises, untouched - a `Stop` subclass included, which is §3.1's
    ordering criterion and is as true of this function as of `run`, for the same reason: there is
    no `except` here either.

    **The record is read and never rewritten**, and the absence is §3.6's whole point about a
    resume rather than an economy. `base_sha` "pins the resolved commit, not just the ref name"
    precisely so that "a commit landing on `main` between run and resume" cannot move "the first
    step's starting head" - so a resume that re-resolved `base_ref` and wrote the answer down would
    be the failure that field exists to prevent, performed by the operation the field exists for.
    Nothing else in the record has a reason to move either: `created_at` is when the *run* started,
    not when it was last picked up, and `workflow_version` is compared against rather than updated,
    a resume that stamped the installed version over the recorded one being a migration written as
    an assignment.
    """
    scope = RunScope(project, label)
    record = await services.store.read_record(scope)
    if record is None:
        # §3.10's symmetric refusal, and the mirror image of `run`'s above: that one says the label
        # is taken and names the two verbs that free it, this one says it is free and names the
        # verb that takes it. Read as a pair, they are what makes a typo'd label loud in both
        # directions rather than a silent replay of something unrelated.
        raise NotFoundError(
            f"run {str(label)!r} does not exist - `agl run <workflow> -n {label}` starts one."
        )
    spec = RunSpec.from_json(record)

    # `spec.workflow` and never `wf.name`, which is the field's whole job: the registry indexes by
    # the entry-point key, so a record storing what a workflow calls itself would resume only while
    # the two agree and would fail naming a string the operator never typed. The module docstring
    # argues it where the record is written.
    wf: Workflow[object] = registry.load(_points(points), spec.workflow, Workflow)

    # §3.11's schema migration in one line: "stamp the version, refuse on mismatch. Runs live
    # hours." Compared with `==` and never parsed, because `ports/run.py` keeps this a `str` for
    # exactly that - "parsing implies an ordering, an ordering implies 'newer than', and 'newer
    # than' is the first line of a migration nobody is going to write".
    #
    # The flag is 17.0's and is not a strengthening of the advice for its own sake: an unforced
    # `agl clear` keeps `agl/<label>` when its work is not yet in the base ref (§3.10), and `run`
    # now refuses a label whose branch is still standing - so "clear it and start again" without
    # the flag is an instruction that fails on its second half for exactly the runs this message
    # is about, which are the ones that got far enough to commit something. `-f` is also the
    # honest verb here on its own terms: what is being proposed is abandoning this run's work and
    # starting the same request over on another version of the workflow.
    #
    # `ConflictError`, and it is the same class `run` answers a taken label with. The record exists
    # and the workflow exists and each is fine on its own; what fails is that they do not fit,
    # which is `ports/errors.py`'s "the world already holds something this operation would have to
    # take or overwrite ... the exact mirror of `NotFoundError`". Every step already on this run's
    # ledger was produced by the workflow as it was then, so finishing it under another version is
    # overwriting a run's history with a stranger's - and `NotFoundError` would be wrong twice
    # over, the label having been found and the workflow with it.
    if wf.version != spec.workflow_version:
        raise ConflictError(
            f"run {str(label)!r} was started by {spec.workflow!r} version "
            f"{spec.workflow_version!r} and the installed {spec.workflow!r} is version "
            f"{wf.version!r}. A run stamps its workflow's version and AGL refuses a mismatch "
            f"rather than migrating one (§3.11): every step already on this run's ledger was "
            f"produced by the workflow as it was then. Install {spec.workflow_version!r} to finish "
            f"this run, or `agl clear {label} -f` and start it again on {wf.version!r}."
        )

    # The params, rebuilt from the record rather than parsed from a line nobody typed - §3.3's
    # "persisted into `run.json`, which is why `agl resume auth` takes no flags", read backwards.
    #
    # **What this refusal is**: not an operator-facing check, but the version stamp's backstop. The
    # values are a record AGL wrote through `params.to_json` rather than something anyone typed, so
    # the only way it fires is a workflow whose params class moved while its `version` stood still
    # - the one case the comparison above cannot see, since the two records agree about the version
    # and disagree about everything the version was supposed to cover.
    #
    # **Why it is nonetheless in front of preflight**, which is the ordering rule and not an
    # exception to it. `run` puts everything that can refuse for free ahead of the one refusal that
    # costs real turns, and that paragraph is a property of these functions rather than a note
    # about the params parse: this reads a mapping and compares two key sets, so it costs
    # microseconds wherever it sits, and an exception to the rule that buys nothing is not an
    # exception. What leaving it below would cost is a `check_ready` turn on a live harness spent
    # before the operator is told about it - and forgetting the version line after editing a params
    # dataclass is the way this fires in practice, repeatedly, to whoever is iterating on the
    # workflow.
    given = params.from_json(wf.params, spec.params)

    # §3.2's preflight, over the same namespace `run` walked, and `sdk/_engine/preflight.py` says
    # in as many words that nothing had to move for this call: the record names the workflow, the
    # registry hands back the same `Workflow`, and its function was written in the same module. It
    # is here for `run`'s reason and one of its own - a resume happens on a machine the first
    # invocation may not have been made on, hours later, and "is this backend ready" is the
    # question whose answer is most likely to have changed in between. Everything above it refuses
    # for free; nothing below it does.
    await preflight.check(services.agents, wf.fn)

    # §3.9's `_base`, provisioned here for the reason `run` provisions it: "`agl/<label>` is a real
    # ref from run start and advances with each `integrate()`, so progress is inspectable live",
    # and a workflow that takes no step opens nothing of its own - `run.step`'s open is lazy. A
    # resume that skipped this would make that sentence false for exactly the runs it is most
    # wanted for, since the state a resume exists to recover from is a crash, and a crash between
    # `write_record` and `open` leaves a record whose checkout was never cut at all.
    #
    # **Idempotent, so this cannot disturb a run that has one**: "an existing workspace is returned
    # exactly as it stands" (`ports/workspace.py`), which also means the `base` argument is ignored
    # on a reopen - so this line cannot rewind a checkout that has advanced through steps and
    # landings, and the `Workspace` is dropped here exactly as `run` drops it.
    #
    # `spec.base_sha` and never `spec.base_ref`, which is the whole of what the record's pin buys:
    # `open` takes a ref expression too, so handing it the ref would cut this checkout from
    # wherever `main` has got to since the run started, and §3.6 pins the commit so that a resume
    # hours later starts where the run did.
    #
    # §3.10's run lock, in `run`'s position and for `run`'s reason: above everything durable this
    # function does and below every refusal, so that a `clear` aimed at this run while it is being
    # walked again refuses at exit 4 instead of taking its checkouts away underneath it. The only
    # asymmetry with `run` is that a resumed run's directory is usually already there, so the claim
    # finds it rather than making it - and where a crash left none, this is the same crash the
    # `open` below is about to provision past anyway.
    async with services.workspaces.hold(label):
        await services.workspaces.open(label, None, spec.base_sha)

        # From here on this is `run`'s last paragraph, line for line, and deliberately so: a resumed
        # run is the same run. §3.4's lease is constructed above the workflow so that `release_all`
        # can be the `finally`, §3.7's terminal is entered around the workflow's function and around
        # nothing else - without which every `show` in a resumed run would raise `InternalError` by
        # the port's own rule - and there is no `except` of any width, so a workflow's own exception
        # leaves this function as the object it raised. The `Run` is built from `scope` and
        # `spec.base_sha`, the address the record is at and the commit it pins, and its three
        # remaining shared tables take their defaults: §3.6's counter is rebuilt from nothing on
        # purpose ("`n` is never persisted; replay walks the same calls in the same order and
        # reproduces the same values"), the namespace table is empty because `worktree()` is what
        # fills it as the workflow walks, and `Capabilities` holds no record of what preflight saw
        # by `sdk/_engine/preflight.py`'s design.
        leases = Leases()
        try:
            async with services.terminal:
                await wf.fn(
                    Run(
                        params=given,
                        services=services,
                        scope=scope,
                        base=spec.base_sha,
                        leases=leases,
                    )
                )
        finally:
            leases.release_all()


async def clear(
    services: Services, project: ProjectName, label: RunLabel, *, force: bool = False
) -> str | None:
    """Take a run away: `agl clear <label> [-f]` (§3.10).

    The module docstring holds the order and the leak; this one holds the one decision `clear`
    makes and the one sentence in §3.10 that has no mechanism behind it.

    Answers with the **warning an operator has to read**, or `None` when there is nothing to say.
    Not a `print`: `api` is a library, and `cli/commands/run.py` is emphatic that a command "renders
    what came back", so a sentence written to stdout from here would be one a library caller, a
    harness and 16.5's testing bundle could not see and could not suppress. There is no `print`
    anywhere under `src/agl/` outside `cli/`, and this operation is not the one that starts.

    A `str | None` and not a value object, because there is exactly one bit here anybody acts on -
    whether the run's own line of work survived - and the *reason* it survived is what they act on
    it with. A record of what else was taken away would be a field with no reader: everything else
    is unconditional, so "it was removed" is the postcondition rather than an outcome.

    Raises, and nothing else reports: `NotFoundError` for a label with no record (exit 3, written as
    the third member of `run`'s and `resume`'s pair) and for a base ref or a run branch that no
    longer names anything, `ConflictError` for a line of work something still holds open or a
    worktree registry another process has wedged (exit 4, out of the adapter that said so), and
    `InternalError` for a record AGL can no longer read back. There is no `except` here either.

    **Two of those are unreachable with `-f` and one is not**, which is the honest description of
    what the flag buys beyond `git branch -D`'s semantics. It asks nothing, so it parses no record
    and looks up no ref: the `InternalError` and the missing-ref `NotFoundError` both belong to the
    unforced path alone, and `-f` is therefore the spelling that clears a run whose own state has
    gone wrong. The case an operator actually meets is a run that crashed between `write_record` and
    `open`: the record names a branch that was never created, and `contains` refuses a ref that
    names nothing rather than answering "no" (`ports/history.py` argues why that refusal is the
    right one), so `agl clear <label>` reports the missing ref and `agl clear <label> -f` takes the
    record away - which is why `run`'s own docstring carries the flag. The `ConflictError` is not
    skipped: `-f` still deletes the branch, so a line of work something has open refuses either way,
    and that is §3.10's lock sentence rather than an exception to the flag.

    ## `git branch -d`, and the ref it is asked about

    §3.10: "It deletes `agl/<label>` **only if merged into the base ref**; otherwise it warns and
    keeps it. `-f` deletes regardless - exactly `git branch -d` versus `-D`. The rationale is
    asymmetric cost: a retained branch costs a stale ref, a deleted one costs the entire run."

    "Merged" is `History.contains(ancestor, descendant)` with the run's branch as the **ancestor**
    and the base ref as the **descendant**: is the run's work already in what the base records.

    **`base_ref` and never `base_sha`**, and the two mean different things to this question.
    `base_sha` is the commit the run was cut from and cannot have moved (§3.6 pins it so that
    nothing can), so `contains(branch, base_sha)` is true exactly when the run committed nothing at
    all - it would delete the branches of runs that did no work and keep every branch that did,
    which is the answer inverted. `base_ref` is where the work was heading and is the thing that may
    have advanced to include it. §3.10 says "the base ref" and this is why it has to.

    **The branch AGL is about to delete is `run_branch(label)`, not `RunSpec.branch`.** The record
    stores a derivable value on purpose, but `WorkspaceProvider.discard` derives its own name from
    `tree_layout` and takes no branch - so asking about the recorded string would be asking about
    one ref and deleting another the day the scheme changes. `run` above makes the same argument at
    the other end: the record and the ref agree by both reading the layout, never by one being
    handed the other's answer.

    **The question is asked here and not up beside the refusals**, which is `api.py`'s
    cheapest-refusal-first rule applied rather than excepted from: that rule orders *refusals*, and
    this is not one - both of its answers are success. It belongs beside the deletion it decides,
    and after `remove`, because a line of work something still has checked out is one an
    implementation may refuse to delete.

    ## "It refuses while a run holds a lock" (§3.10), and 17.0 is where that became true

    **The mechanism is `WorkspaceProvider.hold`, taken around every removal below.** §3.10 asked
    for "a `flock` on the run directory held for the life of the process: an OS lock that releases
    on death, the same shape §3.9 already uses, and not stored status", and that is what it is:
    `api.run` and `api.resume` hold it across everything durable they do, this holds it briefly,
    and a `clear` aimed at a run live in another `agl` refuses with `ConflictError` at exit 4
    having removed nothing. Nothing is written down anywhere - §3.11 refuses stored status by name,
    on the grounds that two sources of truth is what forces reconciliation code to exist - and a
    claim that ends when its holder ends is the one kind of liveness answer no crash leaves stale.

    **What it still does not cover, stated exactly.** The claim is on `.trees/<label>/`, and
    `remove(label, None)` takes that directory away in the middle of this function, so from that
    line to the end a concurrent `agl run` under the same label can make a directory of its own and
    claim that. What is below that line is the branch decision and the record removal; a run that
    got in would be refused by `run`'s branch check for as long as `agl/<label>` is still there,
    and would otherwise be racing a record this function is about to delete. Closing it would mean
    claiming something `clear` does not remove - a never-unlinked file per run, left in the trees
    root forever, for a window that opens after the destructive half is already done.

    **Two refusals it inherits, and neither one detects a run in progress.** They are still here,
    and worth naming because they fire for reasons the claim does not:

      * **§3.9's registry mutex.** `_trees.registry_lock` is a cross-process `flock(2)` on a file
        in the trees root, taken inside `GitWorkspaceProvider.remove` around the `worktree prune`
        and let go of immediately, so a `clear` and a concurrent `run` cannot mutate
        `.git/worktrees/` at once. A holder that is wedged is refused on a deadline with
        `ConflictError`, naming the file. That is a refusal on a *timeout*, not on liveness.

      * **git's own `worktree lock`.** Measured against git 2.50.1: `worktree prune` silently skips
        a locked worktree even after its directory has gone, so the registration survives `remove`;
        `git branch -D` then refuses with "cannot delete branch ... used by worktree at ...", and
        `discard` re-raises that as `ConflictError` having asked whether the branch is still there.
        So `agl clear` on a locked worktree really does refuse, at exit 4, and nothing here catches
        it.

    `GitWorkspaceProvider.remove` inherits neither of `git worktree remove`'s own refusals, because
    it does not call it: it deletes the directory and prunes, which that module chose precisely to
    avoid "three refusals to tolerate in a verb whose whole job is to be unconditional". That is
    why the claim above had to be AGL's own rather than something read off git.

    """
    scope = RunScope(project, label)
    record = await services.store.read_record(scope)
    if record is None:
        # The third member of the pair `run` and `resume` are written as: that one says the label is
        # taken and names the two verbs that free it, `resume` says it is free and names the verb
        # that takes it, and this one says it is free and there is therefore nothing to take away.
        raise NotFoundError(f"run {str(label)!r} does not exist - there is nothing to clear.")

    # §3.10's run lock, around the whole of the teardown and around nothing else. Until 17.0 that
    # section's last sentence had no mechanism behind it: there is no durable "this run is live"
    # record, §3.11 refuses stored status by name, and §3.4's leases are in-process, so a `clear`
    # aimed at a run live in another `agl` took its checkouts away underneath it and said nothing.
    # Taking the same claim `api.run` holds for the life of its invocation is the whole of what
    # this operation has to do about it: a live run refuses here, at exit 4, with nothing removed.
    #
    # **After the record check and around everything else.** A label with no record is nothing to
    # clear and nothing to claim, and that refusal is the one this operation shares with its two
    # neighbours, so it keeps its place at the top. From there down every line is destructive and
    # belongs inside - `store.remove` included, which is the last of the removals rather than
    # something after them.
    #
    # **Briefly, and it is the same verb a run holds for hours.** One member serves both callers
    # because it is one question: a separate probe would answer about a moment already past by the
    # time this acted on it, and refusing is how the answer arrives without one.
    #
    # The claim makes `.trees/<label>/` if a crash left none, which costs nothing here: `remove`
    # below takes that directory away again in this same invocation, once the last checkout in it
    # has gone (`_trees.tidied`).
    async with services.workspaces.hold(label):
        # Enumerated before anything is removed and used after the checkouts are gone, which is what
        # keeps `store.remove` at the bottom of this function: this list is the only record anywhere
        # of what the run held. `Store.namespaces` answers about immediate children, so `_under`
        # recurses.
        for namespace in await _under(services.store, scope):
            # `remove` then `discard`, per namespace, in the order `ports/workspace.py` requires.
            # The bare `Namespace` is §3.9's flat trees root arriving here - see the module
            # docstring.
            await services.workspaces.remove(label, namespace)
            await services.workspaces.discard(label, namespace)

        # The run's own checkout, addressed by the absence of a namespace. This is also the call
        # that takes `.trees/<label>/` itself away, once the last checkout in it has gone
        # (`_trees.tidied`), which is why §3.10's directory half needs no verb the port does not
        # already have.
        await services.workspaces.remove(label, None)

        branch = run_branch(label)
        # `-f` deletes regardless, so it asks nothing and reads nothing - which is also why the
        # record is parsed here rather than beside the existence check above. `RunSpec.from_json`
        # refuses a record AGL cannot read back, and `clear` is the one command that has to keep
        # working on a run whose state has gone wrong: `agl clear <label> -f` takes it away knowing
        # only the label.
        kept = (
            None
            if force
            else await _kept(services.history, label, branch, RunSpec.from_json(record).base_ref)
        )
        if kept is None:
            await services.workspaces.discard(label, None)

        # Last, and the module docstring argues it: this is the enumeration, and removing it first
        # would strand every checkout it names. At depth zero it takes the record, the entries and
        # every nested scope under them (`ports/store.py`), which is §3.10 removing a run wholesale.
        await services.store.remove(scope)
        return kept


def init(settings: Settings, cwd: Path, ask: Ask) -> Path:
    """Register this repository as a project: `agl init` (§3.10). Answers with the file it wrote.

    No bundle and no project, which is the one signature here that could not have been read off
    `container.real`'s inputs: this is the operation that *creates* the project file every other one
    is already resolved against, so a `Project` does not exist when it is called and a container
    built from one cannot either. `Settings` resolve fine outside a registered repository -
    `schema.Settings` is written to that requirement in as many words - and `home` is the whole of
    what is read off them, `AGL_HOME/projects/<name>.toml` being where the answer goes.

    `cwd` is where to start looking for a git root and `ask` is how the build command is asked for;
    the module docstring argues both at length, and neither is a container.

    **Sync, for `list_workflows`' reason**: it awaits nothing. No port is touched - `Store` holds
    runs and this is not one, and `config/toml_file.py` is "the only module that knows TOML", so the
    write goes there. So `cli/commands/init.py` starts no event loop, which is what `cli/main.py`
    means by leaving the loop to the command rather than to the dispatch.

    ## What it does, in order, and why that is the order

    Find the git root, name the project after it, refuse a repository that already has a file, pick
    a trees root, refuse one that would sit inside the repository, ask for the build command, refuse
    a blank answer, and write. Everything that can refuse without asking anybody anything goes
    first, which is `run`'s rule about preflight applied to the one thing here that costs more than
    a syscall: a person's attention. A build command typed into a prompt and then thrown away
    because the project was registered last week is that rule ignored.

    **The name is the repository's directory name**, which is what makes §3.10's example file
    consistent with itself - `repo = "/Users/jan/dev/myapp"` and `name = "myapp"` - and what makes
    `agl init` take no arguments at all. A directory name the filesystem admits and `ids.py` does
    not is `ProjectName`'s own `InputError`, uncaught here for the reason this module catches
    nothing: it says which characters it refused and where, and a sentence added on the way past
    would be a fourth copy of that rule.

    **All five of §3.10's keys are written**, `build_timeout` included, and the number is not stated
    here: `sources.DEFAULT_BUILD_TIMEOUT` is where the fourth layer lives and this reads it. So a
    freshly registered project resolves its timeout from the *file* rather than from the default
    layer, which is what makes the value visible to somebody who wants to change it - and which
    means a project keeps the timeout it was registered with if AGL's own default later moves.
    `sources.py` states that property beside the constant.

    **The trees root is `<repo's parent>/.agl-trees/<name>`**, §3.10's example, and beside the
    repository rather than under it (§3.5). `check_trees_root` is asked all the same and is not a
    formality: `.agl-trees` may already be a symlink into the repository, and that is a *resolved*
    fact no rule about the unresolved path can see - which is the whole reason 16.1 made the check
    impure and exported it. Asked here, where the root is chosen, rather than only in the reader,
    which would let `init` write a file the next command refuses.

    Raises, and nothing else reports: `NotFoundError` for a directory that is not inside a git
    repository (exit 3, `git_root`'s own message), `ConflictError` for a repository that already has
    a project file (exit 4, the same class `run` answers a taken label with and written as the
    fourth member of that family), and `InputError` for a directory whose name is not a usable
    project name, a trees root that resolves inside the repository, a blank build command and a file
    that cannot be written (exit 2). There is no `except` here either.
    """
    # §3.10's "detects the git root", by walking the filesystem: `toml_file.git_root` is the same
    # walk `resolve_project` makes, so the root this registers under and the root a later invocation
    # looks the project up by are found the one way. Uncaught, and its message already says AGL
    # works on a repository and to run `agl init` inside one - which is what was just typed.
    root = toml_file.git_root(cwd)
    name = ProjectName(root.name)

    # §3.10's "runs once per repo", refused for free and in front of the question below. The write
    # refuses again out of an exclusive create, which is what makes it race-free rather than early;
    # `config/toml_file.py` argues the pair, and the path comes back because the refusal after it
    # names the file this is about.
    destination = toml_file.check_unregistered(settings.home, name)

    trees = TreesRoot(root.parent / _TREES_DIRNAME / str(name))
    toml_file.check_trees_root(destination, root, trees.path)

    # The one thing AGL cannot work out for itself (§3.10), asked through the seam and stripped
    # because what comes back is a line somebody typed, newline and all.
    build = ask(_BUILD_PROMPT).strip()
    if not build:
        # `schema.Project` refuses a blank build where the file is *read*, and this is that rule one
        # step earlier: a file written blank is one every later command refuses, so the operator
        # would learn about it from a command that was not asking. Nothing has been written yet.
        raise InputError(
            "a build command is what AGL runs at the merge gate before a run's work is landed "
            "(§3.10), so an empty one would make every gate pass without building anything. "
            "Nothing has been written - run `agl init` again and give the command this project is "
            "built and tested with. If it genuinely has none, that is a decision to make in the "
            "project's settings file rather than a value that arrives here empty"
        )
    # All five of §3.10's keys, and the timeout is **read** rather than restated:
    # `sources.DEFAULT_BUILD_TIMEOUT` is "the only place in AGL that states any of" the fourth
    # layer, and this is its second reader. Writing the key rather than leaving the file silent
    # about it is the editing-surface decision `sources.py` argues where the constant lives - a
    # build that outgrows ten minutes is the ordinary case, and a knob absent from the one file an
    # operator would open is a knob nobody finds.
    return toml_file.write_project(
        settings.home, name, root, trees, build, sources.DEFAULT_BUILD_TIMEOUT
    )


def list_workflows(*, points: Iterable[EntryPoint] | None = None) -> tuple[str, ...]:
    """Every registered workflow name, sorted: `agl workflows` (§3.10). The command is 16.4's.

    Nothing is imported to answer it, which is `registry.names`' own guarantee: one workflow package
    that fails to import still appears here, and a broken third-party package cannot take down the
    command an operator runs to find out what they have.

    Neither a bundle nor a project, which §3.10 states outright and which the body is the argument
    for: this reads packaging metadata, a fact about the installation and not about any repository.
    10.4 handed it a `Services` it never read, so that the dispatch had one shape - and the shape
    was the defect, because a listing that took a container could only be produced from inside a
    registered repository, which is the one place an operator asking "what do I have installed?" is
    least likely to be standing.

    Sync, because it awaits nothing.
    """
    return registry.names(_points(points))


def workflow_help(name: str, *, points: Iterable[EntryPoint] | None = None) -> str:
    """One workflow's own flags, as help text: `agl workflows <name>` (16.4). The command prints it.

    §3.10 writes `agl workflows` with no argument, so this half is an extension of that grammar and
    is reported as one; `cli/commands/workflows.py` holds the argument for it and the gap it closes.

    **This is the one operation that loads a workflow in order to look at it**, and the sentence
    `cli/commands/run.py` uses to decline exactly that - "§1.4's charge with better manners" - is
    about a command that loads one on *every* `agl run` in order to police flags nobody asked about.
    Here the load happens behind an explicit request for that workflow by name, so a package that
    fails to import fails loudly for the name that was asked for and for no other, and
    `list_workflows` still answers about all of them without importing anything.

    `params.parser_for` and not a format of our own: that function is public "because a parser can
    be inspected", the parser it builds is the very one `agl run <name>` parses with, and
    `format_help()` is argparse's own rendering of it. So what an operator reads here is what will
    actually be accepted, rather than a second description of it kept in agreement by nobody. The
    `prog=` is `agl run <name>` for the same reason `parse` passes it: the usage line has to name
    the command these flags are typed on, which is not this one.

    `add_help=False` on that parser means `-h` is absent from what comes back, which is correct and
    is the other half of the decision. `agl run <name> -h` prints AGL's `run` help and always will;
    two parsers claiming one word would make it mean two helps depending on where it appeared
    (`sdk/params.py`), and this command exists so that the second help has a name of its own.

    Raises, and nothing else reports: `NotFoundError` for a name nothing registers (exit 3, listing
    what is registered), `InputError` for an entry point that will not load or loads the wrong
    object and for a params class `parser_for` refuses (exit 2), and `ConflictError` for a name two
    installed packages both register (exit 4) - every one of them the registry's own, unwrapped.

    Sync, because it awaits nothing. It does import a package, which is the difference from
    `list_workflows` that the module docstring makes the argument for two functions out of.
    """
    wf: Workflow[object] = registry.load(_points(points), name, Workflow)
    return params.parser_for(wf.params, prog=f"agl run {name}").format_help()


async def _under(store: Store, scope: RunScope) -> tuple[Namespace, ...]:
    """Every namespace recorded anywhere below `scope`, parents before the children they carry.

    `Store.namespaces` answers about immediate children only "and the caller recurses through
    `RunScope.inside`", which is that port's own instruction and the reason this is a traversal
    rather than a loop: §3.6 nests `worktrees/` arbitrarily, and a flattened answer from the port
    would have lost which parent each name hung from - which is what the recursion needs.

    The **names alone** come back, deliberately flattened here where the port would not flatten
    them. A namespace's ancestry is what addresses it in the store and is nothing to the trees root,
    which is flat and whose names are unique run-wide (§3.9), so the one consumer of this list
    passes each name to a provider that takes a bare `Namespace`. Handing back scopes would be
    handing the caller a depth it must then throw away.

    Order is `Store.namespaces`' stable order, walked depth-first, so one recorded set yields one
    sequence and a `clear` that failed halfway fails the same way twice. Nothing here depends on the
    order being any particular one: the trees root is flat and the child branches are siblings, so
    there is no containment between two of these to get wrong.
    """
    found: list[Namespace] = []
    for namespace in await store.namespaces(scope):
        found.append(namespace)
        found.extend(await _under(store, scope.inside(namespace)))
    return tuple(found)


async def _kept(history: History, label: RunLabel, branch: str, base_ref: str) -> str | None:
    """Why `branch` was kept, in the words an operator reads - or `None`, meaning delete it.

    §3.10's `git branch -d`, and the whole of the decision is the one call below. `contains` is
    asked with the run's own line of work as the ancestor and the base ref as the descendant, which
    is "is this run's work already in what the base records"; `clear`'s docstring argues why the ref
    and not the pin, and why the question sits here rather than in front of the removals.

    A `History` and not a `Services`, for `preflight.check`'s reason: the function that decides
    whether a name survives should not be able to grow a second reader of anything.

    The sentence names both refs and the flag, because those are the three things somebody does
    something with next: the branch is what `git log` is pointed at, the base ref is what it is not
    yet in, and `-f` is the other way out. `NotFoundError` if the base ref no longer names anything
    - the work is unmerged into something that is gone, and the answer is `-f` rather than a guess.

    **What it says the retained branch costs was wrong until 17.0.** §3.10 priced it as "a stale
    ref" and then said in the next breath that the retained side is worse than that, because a
    later `agl run ... -n <label>` took `open`'s attaching path and started from the old tip with
    `--from` ignored. `run` refuses that outright now, so the real consequence an operator has to
    read here is that this label is *taken* until the branch goes - which is a thing to act on,
    where "a stale ref" was a thing to shrug at. The asymmetry argument is left where it belongs,
    in §3.10 and in `clear`'s own docstring: it is why the branch was kept, not what keeping it
    costs the person reading this.

    **And what frees it is not `agl clear -f`, which this sentence used to say.** By the time
    anybody reads this, the records are gone - `clear`'s last line removes them whichever way this
    decision went - so the flag has nothing left to address and a second `agl clear` answers
    `NotFoundError` at exit 3. The tense is what makes that honest rather than a correction: `-f`
    is what *would have* deleted the branch in the call that produced this sentence, and what
    deletes it now is deleting the ref. Naming a tool to say so follows this same message's
    existing `git log`, and there is no AGL verb to name instead: `clear` is addressed to a run and
    this is a branch outliving one, which is the gap §3.10's asymmetry buys and does not close.
    """
    if await history.contains(branch, base_ref):
        return None
    return (
        f"the branch {branch!r} was kept: it is not yet in {base_ref!r}, and everything else this "
        f"run held has been taken away, its records included. Until that branch goes, `agl run "
        f"... -n {label}` is refused rather than started from the wrong place - so `git log "
        f"{branch}` is what is still there, and `git branch -D {branch}` is what frees the label "
        f"now. `agl clear {label} -f` is what would have deleted it in this call."
    )


def _points(points: Iterable[EntryPoint] | None) -> Iterable[EntryPoint]:
    """What is installed, unless the caller brought its own - the seam the module docstring argues.

    One helper rather than the same conditional twice, because the two operations that discover
    workflows must discover the same ones: a listing that answered about a different set from the
    one `run` loads from would be a registry with two answers.
    """
    return registry.installed() if points is None else points
