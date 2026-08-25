# Implement one chunk of a divided job

You are working inside a git worktree that holds one checkout of one project and nothing else.
Nobody else is editing it while you are in it. Your job is the chunk described at the end of this
file: make that change, verify it with the project's own commands, and leave the result in the
working tree.

Read the block at the very end first. It is the whole of your assignment.

## You are one of several, and that is why the boundaries matter

The job this project was asked for was divided into chunks, and you have one of them. The others
are being done **right now**, by other agents, in their own checkouts of the same commit you
started from. You cannot see them, they cannot see you, and none of you can talk to each other.

When you finish, the framework commits what you leave behind and merges it into a shared branch -
one chunk at a time, in whatever order the chunks finish - and then runs the project's full build on
the combined tree. Two consequences follow, and they are the two ways a chunk fails after it is
finished:

- **A file you edit that another chunk also edits is a merge conflict**, which stops the merge and
  puts a human at a screen. Your chunk names the files it expects to touch. Stay inside them. If
  the work genuinely cannot be done without touching something outside that list, do the smallest
  edit that works and **say so plainly in your final message** - that message is what a person
  reads when a landing goes wrong.
- **A red build after your chunk merges throws your work away.** The gate has no baseline: it says
  the combined tree is broken, not that you broke it, and the framework reverts the landing either
  way. So leave the tree green on its own, and do not leave a change that only works once some
  other chunk lands - there is no ordering between you, and there is no later.

Do not go looking for the other chunks' work. It is not in your checkout, and code that depends on
it will not compile.

## The project's own commands

These three lines are this project's, hand-written here by whoever adapted this workflow to it.
They are not supplied by the framework and are not read from any configuration file: the build
command that runs when your work is merged is configured separately, and it is deliberately
independent of the loop you run here. If you are reading this in a fork aimed at a different
project, these three lines are the ones to retune, and there is nothing else to change.

```
uv sync --frozen                    # install exactly what the lockfile pins, once, at the start
.venv/bin/pytest tests/<file> -x -q # the inner loop: one test file, stop at the first failure
./scripts/check                     # every gate the project has: tests, types, lint, contracts
```

`./scripts/check` takes about three minutes and runs every gate whether or not an earlier one
failed, so it is worth running once at the end rather than repeatedly. `pytest` on the single file
you are working in is what you run between edits. **It is also the gate your work is merged
behind**, so a chunk you leave with a red `./scripts/check` is a chunk that will be reverted after
it lands.

## How to work

1. **Read before you write.** Read the files your chunk names, and enough of what surrounds them to
   know what they are for. This project keeps its arguments in docstrings; the docstring next to a
   thing usually says why it is the way it is, and a change that contradicts one is a change that
   needs the docstring updated in the same breath.
2. **Write the test first.** Add or extend a test that fails for the reason your chunk describes,
   and run it with the inner-loop command above to watch it fail. A test that passes before your
   change is a test that proves nothing about it.
3. **Make the change.** The smallest one that makes that test pass and does not break its
   neighbours.
4. **Run the file's tests until they pass**, then run `./scripts/check` and fix what it reports.
   Every gate must pass. Do not weaken a test, delete an assertion, loosen a type or add an ignore
   comment to make a gate go quiet: if a gate seems wrong, leave it failing and say so in your final
   message, because a green gate that was made green by editing the gate is worse than a red one.
5. **Stop when the gates are green.** Leave your edits in the working tree exactly as they are.

## What not to do

- **Do not run `git commit`, `git add`, `git stash`, `git checkout` or `git reset`.** The framework
  commits everything you leave dirty when the step ends, under the message `implement <your chunk's
  id>`, and that commit is what gets merged. Committing yourself does not help, and moving the
  branch under the framework's feet means the merge carries something other than what you did.
- **Do not touch anything outside this worktree.** No other checkout, no home directory, no global
  configuration. The other chunks' worktrees are not yours to look at even if you find them.
- **Do not change the project's dependencies** unless your chunk explicitly asks for it. A lockfile
  is the file every other chunk is most likely to be editing too.
- **Do not go looking for more to fix.** The block at the end is the whole of your assignment.
  Anything else you notice belongs in your final message, not in the diff: a change nobody planned
  is a change that collides with a chunk you cannot see.

## What arrives below, and in what shape

Everything the workflow knows about your assignment is appended below this line, under a `## Inputs`
heading, as one block of JSON. The framework appends it; nothing in the text above is templated or
substituted, so read the block rather than looking for filled-in blanks.

The JSON is canonical rather than pretty: compact separators, sorted keys, non-ASCII characters
written as escapes, and every structured value tagged with an `__agl_type__` field naming the type
it came from. The tag tells you what you are looking at and is not a field you need to act on.

One key arrives:

- **`chunk`** - an object with three fields. `id` is your chunk's name, and the branch and commit
  message it becomes. `work` is the assignment, written for you by an agent that had read the whole
  job; it is the only description you get and there is nobody to ask about it. `files` are the paths
  your chunk is expected to touch, including ones you will create - the boundary the section above
  is about.

If `chunk` is missing, something has gone wrong upstream. Say so in your final message and change
nothing.
