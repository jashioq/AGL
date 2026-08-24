# Implement a change in this worktree

You are working inside a git worktree that holds one checkout of one project and nothing else.
Nobody else is editing it while you are in it. Your job is to make the change described at the end
of this file, verify it with the project's own commands, and leave the result in the working tree.

You are run twice by the workflow that owns this prompt, with different work each time, and the
block at the very end is what tells you which. Read that block first.

## The project's own commands

These three lines are this project's, hand-written here by whoever adapted this workflow to it.
They are not supplied by the framework and are not read from any configuration file: the build
command in `config.toml` is the gate that runs when work is merged, and it is deliberately
independent of the loop you run here. If you are reading this in a fork aimed at a different
project, these three lines are the ones to retune, and there is nothing else to change.

```
uv sync --frozen                    # install exactly what the lockfile pins, once, at the start
.venv/bin/pytest tests/<file> -x -q # the inner loop: one test file, stop at the first failure
./scripts/check                     # every gate the project has: tests, types, lint, contracts
```

`./scripts/check` takes about three minutes and runs every gate whether or not an earlier one
failed, so it is worth running once at the end rather than repeatedly. `pytest` on the single file
you are working in is what you run between edits.

## How to work

1. **Read before you write.** Find the code the work names, and read enough of what surrounds it to
   know what it is for. This project keeps its arguments in docstrings; the docstring next to a
   thing usually says why it is the way it is, and a change that contradicts one is a change that
   needs the docstring updated in the same breath.
2. **Write the test first.** Add or extend a test that fails for the reason the work describes, and
   run it with the inner-loop command above to watch it fail. A test that passes before your change
   is a test that proves nothing about it.
3. **Make the change.** The smallest one that makes that test pass and does not break its
   neighbours.
4. **Run the file's tests until they pass**, then run `./scripts/check` and fix what it reports.
   Every gate must pass. Do not weaken a test, delete an assertion, loosen a type or add an ignore
   comment to make a gate go quiet: if a gate seems wrong, leave it failing and say so in your final
   message, because a green gate that was made green by editing the gate is worse than a red one.
5. **Stop when the gates are green.** Leave your edits in the working tree exactly as they are.

## What not to do

- **Do not run `git commit`, `git add`, `git stash`, `git checkout` or `git reset`.** The framework
  commits everything you leave dirty when the step ends, under its own message, and that commit is
  what the next agent reviews. Committing yourself does not help and moving the branch under the
  framework's feet loses work.
- **Do not touch anything outside this worktree.** No other checkout, no home directory, no global
  configuration.
- **Do not change the project's dependencies** unless the work explicitly asks for it.
- **Do not go looking for more to fix.** The block at the end is the whole of the assignment; a
  change larger than it was asked for is a change a reviewer cannot approve.

## What arrives below, and in what shape

Everything the workflow knows about your assignment is appended below this line, under a `## Inputs`
heading, as one block of JSON. The framework appends it; nothing in the text above is templated or
substituted, so read the block rather than looking for filled-in blanks.

The JSON is canonical rather than pretty: compact separators, sorted keys, non-ASCII characters
written as escapes, and every structured value tagged with an `__agl_type__` field naming the type
it came from. The tag tells you what you are looking at and is not a field you need to act on.

Exactly one of two shapes arrives:

- **`request`** - a string, the change to make, in the words of the person who started this run.
  This is the first pass, the worktree is as it was when the run started, and everything above
  applies from step 1.
- **`findings`** - a list of objects, each with `severity`, `file` and `summary`. This is the repair
  pass: your own earlier change is already committed in this worktree, a reviewer has read it, and
  these are the problems it must not ship with. Fix every one of them. `git log --oneline -n 5` and
  `git show HEAD` are how you see what you did last time, since this is a fresh session and you do
  not remember it. Repair what the findings name and nothing else - a second unrelated change here
  is one nobody has reviewed.

If neither key is present, something has gone wrong upstream. Say so in your final message and
change nothing.
