# Run.terminal

Display data in the terminal while a workflow runs, and ask questions in it.

A screen without answers is a board. It stays on screen until the next board replaces it, and
`show()` returns at once.

```python
def progress(done: int, total: int) -> Screen:
    return Screen(Rows([Row("Fixed", f"{done} of {total}")]))

await run.terminal.show(progress, done=3, total=8)
```

The terminal calls the function again on every frame, with the same arguments, so a board that
reads a list stays current as the list grows.

A screen with answers is a question. `show()` waits until it is answered in the terminal and
returns the answer, which here decides whether to end the run with [`Stop`](../stop.md). The
terminal lists the answers by number, and typing one and pressing Enter picks it.

```python
def approve(plan: str) -> Screen[bool]:
    return Screen(Text(plan), [Choice("Go ahead", True), Choice("Stop", False)])

if not await run.terminal.show(approve, plan=plan.text):
    raise Stop("Plan rejected.")
```

`TextInput` asks for a line of text instead of a choice, and its function turns the line into the
answer. Screens are built from `Text`, `Row` and `Rows`, and a plain string stands for a `Text`.

```python
def name_it() -> Screen[str]:
    return Screen("Name the release.", [TextInput("Name", str)])
```

Questions from [worktrees](worktree.md) working at once take turns, one on screen at a time.

To let an agent ask a question, give its [role](../role/index.md) a
[tool that shows one](../role/tools-and-return-types.md#asking-questions).

## Reference

::: agl.sdk.Run.terminal

::: agl.sdk.Terminal
    options:
      show_bases: false
      group_by_category: false
      members:
        - show
        - pending

::: agl.sdk.Screen
    options:
      members:
        - body
        - responses

::: agl.sdk.Rows
    options:
      members:
        - rows

::: agl.sdk.Row
    options:
      members:
        - cells

::: agl.sdk.Text
    options:
      members:
        - value

::: agl.sdk.Choice
    options:
      members:
        - label
        - value

::: agl.sdk.TextInput
    options:
      show_attribute_values: false
      members:
        - label
        - maps

::: agl.sdk.Component

::: agl.sdk.Response
