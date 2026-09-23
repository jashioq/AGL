# Run.integrate

Runs the project's build on a child's work merged into its parent and, when the build fails, puts
the parent back where it stood.

A child's work reaches its parent's worktree only through [`integrate`][agl.sdk.Run.integrate], so
call it on a child [`Run`][agl.sdk.Run] once the child's steps have committed the work. The parent's
later steps start from what landed.

The build is the project's `build` setting, run in the parent's worktree, and a project that sets it
to the empty string has no build gate.

## When a landing is conflicted

A landing comes back conflicted for one of two reasons, and
[`refused_by_the_gate`][agl.sdk.Integration.refused_by_the_gate] tells them apart.

- The work would not merge. The merge waits in the parent's worktree, which the conflict's
  [`summary`][agl.sdk.Conflict.summary] names. A person resolves the files there and stages them
  with `git add`, and [`retry`][agl.sdk.Integration.retry] finishes the merge. It takes a staged
  file as resolved whatever the file holds and, while any file that collided is still unstaged,
  leaves the landing conflicted.
- The build failed on the merged work. `retry` merges the child's branch again, so commit a fix on
  the child first, with a step that has `commit=`.

A merge a person resolved by hand goes through the build gate too. If the build fails, AGL throws
the resolution away with the rest of the merge, and the next `retry` brings the collision back for
the person to resolve again.

## Landings take turns

Landings into one parent take turns, and each one waits for a step the parent is running to end. A
conflicted landing holds the parent until the work lands, you give it up with
[`abort`][agl.sdk.Integration.abort], or a [`retry`][agl.sdk.Integration.retry] raises. Until then,
every other landing into that parent and every step of the parent waits. The child's own steps still
run, which is how the example below commits a new fix while the build gate's refusal holds the
parent.

If the workflow returns while a landing still holds its parent, AGL keeps every worktree and prints
a warning that names `agl resume`. A child whose work never landed keeps its branch, as
[Where a child's work goes](run-worktree.md#where-a-childs-work-goes) sets out.

## On a resume

AGL keeps no record of a landing, so on a resume [`integrate`][agl.sdk.Run.integrate] tries the
merge and the build gate again, and the gate can refuse work the parent already holds.

## Example

The example comes from a workflow that fixes each issue in a separate child, then lands each fix
with this function.

```python
--8<-- "fix_issues/__init__.py:land"
```

1. [`integrate`][agl.sdk.Run.integrate] returns once the fix has landed in the parent's worktree,
   or once a conflict holds the parent.
2. [`conflicted`][agl.sdk.Integration.conflicted] keeps the loop going for as long as a conflict
   holds the parent.
3. When [`refused_by_the_gate`][agl.sdk.Integration.refused_by_the_gate] is true, the parent holds
   no merge for a person to resolve, so the fix has to change in the child.
4. The step gives `fixing` the build's [`verdict`][agl.sdk.Integration.verdict] along with the
   issue, and commits the new fix on the child's branch.
5. Otherwise the fix would not merge, and `resolving`, the workflow's own function, returns a
   question that shows the [`conflict`][agl.sdk.Integration.conflict]'s summary, asks the person
   to resolve and stage the files, and offers "Land it again" or "Leave it on its branch".
6. When the person picks "Leave it on its branch", [`abort`][agl.sdk.Integration.abort] gives up
   the landing, and the fix stays on the child's branch.
7. Whichever kind of conflict it was, [`retry`][agl.sdk.Integration.retry] makes the next
   attempt, and the loop looks at its outcome again.

::: agl.sdk.Run.integrate

::: agl.sdk.Integration
    options:
      show_bases: false
      group_by_category: false
      members:
        - conflicted
        - refused_by_the_gate
        - verdict
        - conflict
        - head
        - retry
        - abort

::: agl.sdk.Conflict
    options:
      members:
        - paths
        - summary

## See also

- [`Run`][agl.sdk.Run]
- [`Run.step`][agl.sdk.Run.step]
- [`Run.worktree`][agl.sdk.Run.worktree]
- [`VerifierOutcome`][agl.sdk.VerifierOutcome]
- `Terminal`
