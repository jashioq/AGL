# Tools and return types

Give an agent tools to call. One of them can be its reporting tool: the agent calls it to hand back
a result, and [`Run.step()`](../run/step.md) returns it.

## Reporting tool

```python
@dataclass(frozen=True)
class Review:
    issues: list[str] = describe("Every problem you found.")

@role(model=Claude.OPUS, accepts=(Request,))
def reviewer_role() -> Role[Review]:
    return Role(
        name="reviewer",
        instructions=prompt_file("prompts/review.md"),
        tools=[reporting_tool("report_review", "Report what you found.", Review)],
    )
```

```python
review = await run.step(reviewer, request)
```

`describe()` tells the agent what a field is for. A field can be a `str`, `bool`, `int`, `float` or
another dataclass, a `list` or `tuple` of them, or optional, as `X | None`. A field with a default
can be left out.

If the agent sends a payload that doesn't fit, AGL sends it the problems and asks it to try again.
The first payload that fits counts. If the agent never reports, the step raises
`RoleIncompleteError`, and its work is wiped. A [role](index.md) has at most one reporting tool.
Without one, `Run.step()` returns `None`.

## Tools

```python
async def look_up(query: Query) -> ToolResult:
    return ToolResult(text=search_docs(query.text))

tool("look_up", "Search the project's docs.", Query, look_up)
```

AGL checks the agent's arguments against the payload before your function runs, and sends the
agent the problems if they don't fit. Return `rejected=True` to tell the agent the call failed. If
your function raises, the step stops, its work is wiped, and `Run.step()` raises the same error.

## Asking questions

A tool can ask a question in the terminal. Its function shows the
[question](../run/terminal.md) and returns the answer as the tool's result, while the agent waits
in the same session. To reach the terminal, the role's function takes the [`Run`](../run/index.md)
as an argument.

```python
def asking(text: str) -> Screen[str]:
    return Screen(text, [TextInput("Answer", str)])

@role(model=Claude.OPUS, accepts=(Request,))
def planner_role(run: Run) -> Role[Plan]:
    async def ask(question: Question) -> ToolResult:
        answer = await run.terminal.show(asking, text=question.text)
        return ToolResult(text=answer)

    return Role(
        name="planner",
        instructions=prompt_file("prompts/plan.md"),
        tools=[
            tool("ask", "Ask a question in the terminal.", Question, ask),
            reporting_tool("report_plan", "Report the plan.", Plan),
        ],
    )
```

Call the role's function in the workflow, with its `Run`.

```python
plan = await run.step(planner_role(run), request)
```

A step that [replays](../run/step.md#recorded-steps) runs no agent, so its tools aren't called and
their questions aren't asked again.

## Reference

::: agl.sdk.reporting_tool

::: agl.sdk.ReportingTool
    options:
      members:
        - name
        - description
        - payload
        - rejection
        - read

::: agl.sdk.describe

::: agl.sdk.tool

::: agl.sdk.ToolResult
    options:
      members:
        - text
        - rejected

::: agl.sdk.Tool
    options:
      members:
        - name
        - description
        - payload_schema
        - handler

::: agl.sdk.JsonValue

::: agl.sdk.RoleIncompleteError
