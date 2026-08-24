"""Re-export facade over `agl.ports.questions`: `Question` and `Answer`, at the name a workflow
author imports. **No logic**, exactly as `sdk/terminal.py` beside it holds none.

The pair a `Role`'s `on_question` handler is written against (§3.7): `async (Question) -> Answer`,
a closure over the workflow's own `Run`, routing whatever the agent stopped to ask to a view through
the one entry point that shows anything.

    async def approve(q: Question) -> Answer:
        picked = await run.terminal.show(views.approve_backlog, question=q, priority=5)
        return Answer(picked.as_text())

Both types live in `ports/` because an `AgentRunner` speaks them - the adapter maps whatever payload
its backend produced into a `Question`, awaits the handler, and serialises the `Answer` back into
the same live session - and `ports` may not import `sdk` without `.importlinter`'s contract 1
inverting on its lowest edge. `ARCHITECTURE.md` §5 states the rule; `sdk/terminal.py` carries the
argument at length, and it is one argument covering two modules rather than two.

**Both names, and nothing curated out.** They are the whole of `ports.questions.__all__`: a handler
takes the first and returns the second, so a facade offering one of the two would send an author
into `agl.ports` for the other, which is the thing this module exists to prevent.

**The spelling is `from agl.sdk import Question, Answer`**, and `from agl.sdk.questions import
Question, Answer` beside it. 15.1 left the shorter one false - `src/agl/sdk/__init__.py` held no
re-exports - on the argument that making it true for two modules alone would leave the surface with
two import styles, and that the decision belonged to a deliverable taking the whole front door at
once. 16.5 is that deliverable and re-exported all of it, so there is one style; `sdk/terminal.py`
carries the argument in full, and this module is where the package root takes these two names from.

**What is deliberately not re-exported here is `Role`.** `on_question` is a field on it and
`sdk/roles.py` is where an author meets both; this module holds the vocabulary that crosses the
port, and pulling `Role` in would make a facade over `ports.questions` a second place the authoring
surface is assembled.
"""

from agl.ports.questions import Answer, Question

# Listed rather than computed, for `sdk/terminal.py`'s reason: a re-export assembled at runtime is
# invisible to `ruff`, to `mypy` and to a reader. `tests/sdk/test_run_terminal.py` pins both lists.
__all__ = ["Answer", "Question"]
