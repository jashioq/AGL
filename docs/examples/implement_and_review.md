# implement_and_review

Source: [`AGL-workflows/implement_and_review`](https://github.com/jashioq/AGL-workflows/tree/main/implement_and_review)

`implement_and_review` has Claude Code make the change you ask for, and Codex review it. Claude
Code fixes what a review finds, for up to three reviews. A clean review finishes the run, with the
work committed on `agl/<label>`. A third review with findings stops it.

## Get it and run it

Download from [`AGL-workflows`](https://github.com/jashioq/AGL-workflows) repository:
```
agl get jashioq/AGL-workflows/implement_and_review
```
Run it:
```
agl run implement_and_review -n health-check -r "Add a health check endpoint"
```

## How it's built

`__init__.py` holds the workflow, `roles.py` its two roles and their tools, `display.py` what it
shows in the terminal, and `prompts/` a prompt for each role.

### Roles

`implementer` runs Opus through Claude Code. `reviewer` runs Sol through Codex and may not edit
files. Neither may change the repository with git.

[`roles.py`](https://github.com/jashioq/AGL-workflows/blob/d39353e3a6dae853d1ba368fa47ffc5ff3a9c82b/implement_and_review/roles.py):

```python
@role(model=Claude.OPUS, accepts=(str, Review))
def implementer(watch: ActivityReporter) -> Role[None]:
    return Role(
        name="implement",
        instructions=prompt_file("prompts/implement.md"),
        restrictions={Restriction.NO_VCS_WRITES},
        tools=(ask_question(),),
        on_activity=watch,
    )


@role(model=OpenAI.SOL, accepts=(str,))
def reviewer(watch: ActivityReporter) -> Role[Review]:
    return Role(
        name="review",
        instructions=prompt_file("prompts/review.md"),
        restrictions={Restriction.NO_FILE_WRITES, Restriction.NO_VCS_WRITES},
        tools=(ask_question(), record_review()),
        on_activity=watch,
    )
```

See [Restrict agent permissions](../build/role/restrict-agent-permissions.md).

### Review reporting tool

`record_review` is `reviewer`'s reporting tool, so the review step returns a `Review`, which
`implementer` accepts.

[`roles.py`](https://github.com/jashioq/AGL-workflows/blob/d39353e3a6dae853d1ba368fa47ffc5ff3a9c82b/implement_and_review/roles.py):

```python
@dataclass(frozen=True, slots=True)
class Review:
    findings: list[str] = describe(
        "each finding as one markdown item saying where and what is wrong; empty when there are none"
    )
...
def record_review() -> ReportingTool[Review]:
    return reporting_tool(
        "record_review",
        "Record this review's findings. Call it exactly once, at the end, even when there are none.",
        Review,
    )
```

See [Reporting tool](../build/role/tools-and-return-types.md#reporting-tool).

### Asking tool

Both agents can ask a question in the terminal with `ask_question`. Its function, `answered`, shows
the question and its `options` through `display.py`, and returns the answer.

[`roles.py`](https://github.com/jashioq/AGL-workflows/blob/d39353e3a6dae853d1ba368fa47ffc5ff3a9c82b/implement_and_review/roles.py):

```python
@dataclass(frozen=True, slots=True)
class Asked:
    question: str = describe("what you are asking, in full; one question per call, never several")
    options: tuple[str, ...] = describe("answers to offer, each worded as the answer", default=())


async def answered(asked: Asked) -> ToolResult:
    said = await answer(asked.question, asked.options)
    return ToolResult(text=said)


def ask_question() -> Tool:
    return tool(
        "ask_question",
        "Ask the person running this workflow a question, and wait for their answer.",
        Asked,
        answered,
    )
```

See [Asking questions](../build/role/tools-and-return-types.md#asking-questions).

### Terminal display

The workflow first shows `board` with `opened(run.terminal)`, and the terminal redraws it on every
frame. Each role's `watch` calls `report`, which stores the agent's latest activity line for the
board.

[`display.py`](https://github.com/jashioq/AGL-workflows/blob/d39353e3a6dae853d1ba368fa47ffc5ff3a9c82b/implement_and_review/display.py):

```python
now = {"agent": "", "line": ""}
...
def report(agent: str, line: str) -> None:
    now["agent"] = agent
    now["line"] = line


async def opened(run_terminal: Terminal) -> None:
    global terminal
    terminal = run_terminal
    await terminal.show(board, since=monotonic())
...
def board(*, since: float) -> Screen:
    return Screen(
        Rows([
            Row(f"implement and review  {_elapsed(since)}"),
            Row(""),
            Row(f"{now['agent']}  {now['line'][:60]}"),
        ])
    )
```

See [`Run.terminal`](../build/run/terminal.md) and
[Agent activity](../build/role/agent-activity.md).

### The loop

The first step commits the implementation. Each round then gets a review, and a review with no
findings finishes the run. Otherwise `implementer` fixes the findings in a new commit. If the third
review still has findings, the workflow raises `Stop` with them.

[`__init__.py`](https://github.com/jashioq/AGL-workflows/blob/d39353e3a6dae853d1ba368fa47ffc5ff3a9c82b/implement_and_review/__init__.py):

```python
    await run.step(implementing, request, commit="implement what the run was asked for")

    # Review and fix loop
    for round_number in range(MAX_ROUNDS):
        review = await run.step(reviewing, request)
        if not review.findings:
            return

        # If after MAX_ROUNDS review rounds issues are still found - stop.
        if round_number == MAX_ROUNDS - 1:
            break
        await run.step(
            implementing,
            request,
            review,
            commit=f"fix what review round {round_number + 1} found",
        )

    findings = "\n".join(review.findings)
    raise Stop(f"{MAX_ROUNDS} review rounds and the last one still had findings:\n\n{findings}")
```

See [`Run.step()`](../build/run/step.md) and [`Stop`](../build/stop.md).

## Build your own

- To run other models, change each role's [model and effort](../build/role/model-and-effort.md).
- To give a step more to work from, add a type to its role's
  [`accepts`](../build/role/accept-input-parameters.md) and a placeholder to its
  [prompt](../build/role/prompt.md).
- To get another result from a review, change the payload of its
  [reporting tool](../build/role/tools-and-return-types.md#reporting-tool).
