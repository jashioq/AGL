# AGL comment convention

## The test
If it can be figured out by looking at the code for thirty seconds, it does not get a
comment. What survives is what a reader cannot derive: non-obvious usage requirements,
what a thing does in one line, the meaning of an input or output where it is not evident.

## The eight rules

**C1. Say what the code cannot say. Never restate it.**
A comment earns its place only by carrying a fact from outside the file: the behaviour of
a vendor tool, an OS or protocol guarantee, a measured number, a units/ownership/lifetime
fact the type does not encode. If deleting the comment loses nothing a reader could not
recover from the code in thirty seconds, delete it.

**C2. Module docstring: one line. Two at the outside.**
Name what the module is and what is singular about it. If a module needs more than two
lines to introduce, that is a design report, not a docstring - see C7.

**C3. Class docstring: one line, in the shape "what this is: its parts."**
Only add a second paragraph for a usage requirement a caller must obey.

**C4. Function docstring: one line, and only when the signature does not already say it.**
A private helper whose name and types are self-evident gets none. Add lines only for a
non-obvious precondition, a documented edge case, or the meaning of a return that the
type does not carry.

**C5. Attribute docstring: one line, and only where the field's type under-describes it.**
Say what the value means to a reader, not what it is. Fields whose name and type already
answer get nothing.

**C6. Inline `#`: for the line beneath it, and at most four lines.**
The highest-value comment in this repo is a short one recording an external fact at the
exact line that depends on it. Put it there, keep it to the fact.

**C7. Length ceiling: 10 lines for any one comment or docstring; 2 lines for a module
docstring. Anything longer is not a comment.**
If it exceeds the ceiling, it is one of three things and each has a home:
  - a *requirement* -> a test, named for the sentence it enforces;
  - an *architectural rule* -> ARCHITECTURE.md, or a `.importlinter` contract;
  - a *design narrative* -> human documentation outside `src/`.
Workflows never get large explanatory comments; how a workflow is built is documentation.

**C8. Named, not numbered. Cite nothing that can be deleted without breaking a build.**
No `§3.6`, no `14.1`, no `UF2.2`, no `stage 13`, no `docs/*.md`. Refer to things by name -
a module, a symbol, a test, a heading in ARCHITECTURE.md - so the reference breaks loudly
or not at all. This rule is the repo's own: `.importlinter:164` and `scripts/check:445`.

**C9. Record the outcome, not the history.**
Write the rule that holds now. "X, because Y" - never "we used to do X", "N.N changed
this", "originally". Git holds the history.

**C10. State no fact you cannot check, in a place that cannot check it.**
If a sentence is load-bearing - a real cost, an invariant, a forbidden implementation -
it belongs in a test, an assertion or a type. A comment may summarise the guard in one
line and name it. It may not BE the guard.
