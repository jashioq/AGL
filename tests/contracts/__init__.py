"""Contract suites: one reusable pytest class per port, subclassed once per implementation.

A suite here is written against a port's docstring and against nothing else, before any of the
implementations it will be pointed at exists. That order is the point (§1.9): a subagent that
writes its own tests writes tests that pass, and stages 4-8 each end with "the contract suite
passes" - a sentence worth something only when the suite was written by someone with no stake in
the implementation.

**The real adapter and the fake subclass the same class.** That is the entire mechanism keeping a
fake from drifting into fiction: a fake that answers differently from the adapter is a fake that
fails a suite the adapter passes, and the drift surfaces here rather than in whichever workflow
test believed the fake.

Two rules bind every module in this directory. **Nothing here imports an adapter or names a
vendor** - a suite that knew what it was testing would be a suite the next implementation cannot
pass. And **nothing here assumes a backend**: no `Path`, no directory listing, no on-disk file, no
`tmp_path`. A test that would only pass against a filesystem is the wrong test, because the port
it asserts is equally a promise to an implementation kept in memory, in a database, or behind a
network.

The first rule has exactly one exception and the second has three, every one of them argued where it
is taken. `_agent_hermeticity` writes the literal filenames a harness reads - `CLAUDE.md`,
`.claude/`, `AGENTS.md`, `.codex/` - because §3.5's poisoned repository *is* those filenames, and a
suite that could not name them could not plant them. That exception is the table and reaches nothing
else: no test branches on which adapter it is talking to, and no assertion is conditional on one.
`_agent_tasks` builds a real directory, because `AgentTask.workspace` is a `Path` that the port
refuses unless absolute, and "the target repo contributes source code and nothing else" is a claim
about a directory. And `_workspace_files` reads and writes through `Workspace.path`, because that
port **exposes** a `Path` on purpose and says why - "a workspace genuinely is a directory: an agent
is pointed at one and a verifier's working directory is one" - so a suite that would not touch one
could not make a workspace dirty, and everything `Workspace`, `History` and `Integrator` promise is
about a workspace somebody dirtied. And `verifier` names a `Path` it never touches, because `verify`
**accepts** a working directory - the one member across these five ports that does - so a suite with
no directory to hand over could not call it at all.

None of the four licenses a fifth. The first is data, the second is one function, the third is taken
only where a port hands a `Path` over itself - what a *provider* must never accept is a location,
and nothing here computes one - and the fourth passes on a directory the implementation's own
fixture chose, reading, writing, listing and creating nothing under it. Past that line all five
suites are the same - no subprocess, no tool named, no program's output parsed, and no test that
knows what the thing underneath is.

There is one exception of a different kind, and it is `terminal.py`'s. Every other suite drives its
port with the port's own methods; that one cannot, because `Terminal` has no member that answers a
screen - answering is what a person does - and an interactive `show` does not come back until
somebody has. So `TerminalContract` asks for a second fixture, `TerminalDriver`, which is the only
knob across these five suites that is not the thing under test: two members, one reporting what is
displayed and one responding to it.

It is argued where it is taken, in `_terminal_driver`, with its cost stated out loud - a driver is
written by the party it exists to catch - and with a limit that keeps it from becoming a habit. The
driver only ever *reports*. Nothing on it dismisses, preempts, redraws or resolves, so the queues
are moved by `show` and by answering and by nothing else, and every ordering claim in that suite
rests on which `show` call an answer reached, which is the port's own surface. It licenses no second
fixture of its kind: a suite that cannot see something through its port asks first whether the port
is missing a member, and only then asks an implementer for a window.
"""
