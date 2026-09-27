# chat

Source: [`AGL-workflows/chat`](https://github.com/jashioq/AGL-workflows/tree/main/chat)

`chat` has Haiku, through Claude Code, and Luna, through Codex, talk about a topic you give it. They
run at the same time and take turns saying one line each, and the terminal shows the chat as it
goes. The chat ends after 20 lines.

## Get it and run it

Download from [`AGL-workflows`](https://github.com/jashioq/AGL-workflows) repository:
```
agl get jashioq/AGL-workflows/chat
```
Run it:
```
agl run chat -n tabs-or-spaces -r "Tabs or spaces"
```

## How it's built

`__init__.py` holds the workflow, `roles.py` its two roles and their tools, `display.py` what it
shows in the terminal, and `prompts/` a prompt for each role.

### Roles

`haiku_speaker` runs Haiku through Claude Code, and `luna_speaker` runs Luna through Codex. Each
gets a `say` and a `listen` built for its own name and the cap on lines. Neither has a reporting
tool, so each step returns `None`.

[`roles.py`](https://github.com/jashioq/AGL-workflows/blob/d39353e3a6dae853d1ba368fa47ffc5ff3a9c82b/chat/roles.py):

```python
@role(model=Claude.HAIKU(effort=ClaudeEffort.LOW), accepts=(str,))
def haiku_speaker(cap: int) -> Role[None]:
    return Role(
        name="haiku",
        instructions=prompt_file("prompts/haiku.md"),
        tools=(says(HAIKU, cap), listens(HAIKU, cap)),
    )


@role(model=OpenAI.LUNA(effort=OpenAIEffort.LOW), accepts=(str,))
def luna_speaker(cap: int) -> Role[None]:
    return Role(
        name="luna",
        instructions=prompt_file("prompts/luna.md"),
        tools=(says(LUNA, cap), listens(LUNA, cap)),
    )
```

See [Model and effort](../build/role/model-and-effort.md).

### Tool payloads

The agents reach each other through two tools, `say` and `listen`. `say` takes a `Line`, and
`listen` takes `Nothing`, an empty dataclass, as it has no arguments. Both tools use `transcript`,
the chat so far, and `turn`, an event for each side. `listen` also reads `gone`, the sides whose
step has ended.

[`roles.py`](https://github.com/jashioq/AGL-workflows/blob/d39353e3a6dae853d1ba368fa47ffc5ff3a9c82b/chat/roles.py):

```python
transcript: list[str] = []
gone: set[str] = set()
# One event a side, set by the other one's `say`, so a waiter is never woken by its own line
turn: Final = {HAIKU: asyncio.Event(), LUNA: asyncio.Event()}


@dataclass(frozen=True, slots=True)
class Line:
    message: str = describe(
        "your next line in the chat: 200 characters at most, one sentence, no name in front of it"
    )


# `listen` takes no arguments, and a tool payload is a dataclass whatever it carries
@dataclass(frozen=True, slots=True)
class Nothing:
    ...
```

See [`tool()`](../build/role/tools-and-return-types.md#agl.sdk.tool).

### Say tool

`says` builds a side's `say`. Its function adds the line to `transcript` and to the board, and sets
the other side's event, which wakes that side's `listen`. When the chat is already at the cap, or
the same side said the last line, it returns `rejected=True`.

[`roles.py`](https://github.com/jashioq/AGL-workflows/blob/d39353e3a6dae853d1ba368fa47ffc5ff3a9c82b/chat/roles.py):

```python
def says(name: str, cap: int) -> Tool:
    async def spoken(line: Line) -> ToolResult:
        if len(transcript) >= cap:
            return ToolResult(text=OVER, rejected=True)
        if transcript and transcript[-1].startswith(f"{name}:"):
            return ToolResult(text=TWICE, rejected=True)
        transcript.append(f"{name}: {line.message}")
        said(COLOUR[name], name, line.message)
        # Woken whether the cap has just been reached or not: the other side is waiting on this
        # event either for a line to answer or to be told the chat is over
        other = _other(name)
        turn[other].set()
        if len(transcript) >= cap:
            quiet()
            return ToolResult(text=OVER)
        waiting(COLOUR[other], other)
        return ToolResult(text="Said. Now listen for the answer.")

    return tool("say", "Say your next line, which is how the other one hears you.", Line, spoken)
```

See [Tools](../build/role/tools-and-return-types.md#tools).

### Listen tool

`listens` builds a side's `listen`. Its function waits for the side's own event, then returns the
other side's last line, or tells the agent the chat is over once the cap is reached or the other
side's step has ended. Haiku opens, so its `listen` before the first line tells it to speak.

[`roles.py`](https://github.com/jashioq/AGL-workflows/blob/d39353e3a6dae853d1ba368fa47ffc5ff3a9c82b/chat/roles.py):

```python
def listens(name: str, cap: int) -> Tool:
    async def heard(_: Nothing) -> ToolResult:
        # Nothing would ever wake the one who opens, so it is told to speak rather than left to
        # wait on a line the other one is itself waiting for
        if not transcript and name == OPENS:
            return ToolResult(text=OPENING)
        await turn[name].wait()
        turn[name].clear()
        if len(transcript) >= cap or _other(name) in gone:
            return ToolResult(text=OVER)
        return ToolResult(text=transcript[-1])

    return tool(
        "listen",
        "Wait for the other one to say something, and read it. Takes no arguments.",
        Nothing,
        heard,
    )
```

See [`ToolResult`](../build/role/tools-and-return-types.md#agl.sdk.ToolResult).

### Terminal display

The workflow shows `board` with `opened`, and the terminal redraws it on every frame. `say` adds
each line to `spoken` through `said`, and puts the side that speaks next in `thinking` through
`waiting`. `board` draws each line after its speaker's name in colour, a spinner for the side in
`thinking`, and drops the oldest rows once the chat is taller than the terminal.

[`display.py`](https://github.com/jashioq/AGL-workflows/blob/d39353e3a6dae853d1ba368fa47ffc5ff3a9c82b/chat/display.py):

```python
spoken: list[tuple[str, str, str]] = []
thinking: list[tuple[str, str]] = []


async def opened(terminal: Terminal, header: str) -> None:
    await terminal.show(board, header=header)
...
def board(*, header: str) -> Screen:
    width, height = shutil.get_terminal_size()
    blocks = [_rows(*line, width) for line in spoken] + [_spinning()]
    # A blank row ahead of every block but the first, so one turn is easy to tell from the next
    drawn = [row for block in blocks if block for row in (Row(""), *block)][1:]
    # A board taller than the terminal has its last rows cropped away, and the last row is the
    # line that just landed - so the older end of the chat is what goes, and it scrolls nowhere
    room = max(height - len(PADDING) - 1, 1)
    return Screen(Rows([Row(header), *PADDING, *drawn[-room:]]))
```

See [`Run.terminal`](../build/run/terminal.md).

### Two agents at once

The workflow runs both steps at once in an `asyncio.TaskGroup`, each in a worktree of its own and
with no `commit`. When a step ends, `ended` marks its side gone and wakes the
other side's `listen`. When both steps have returned, the workflow raises `Stop` with the number
of lines said.

[`__init__.py`](https://github.com/jashioq/AGL-workflows/blob/d39353e3a6dae853d1ba368fa47ffc5ff3a9c82b/chat/__init__.py):

```python
talking_haiku = haiku_speaker(MAX_TURNS)
talking_luna = luna_speaker(MAX_TURNS)


@workflow
async def chat(run: Run[Parameters]) -> None:
    await opened(run.terminal, f"{HAIKU} and {LUNA}'s chat")

    async with asyncio.TaskGroup() as group:
        group.create_task(talking(run, talking_haiku, HAIKU))
        group.create_task(talking(run, talking_luna, LUNA))

    raise Stop(f"the chat ended after {len(transcript)} of the {MAX_TURNS} lines it is capped at")


async def talking(run: Run[Parameters], speaking: Role[None], name: str) -> None:
    try:
        await run.worktree(name.lower()).step(speaking, run.params.topic)
    finally:
        ended(name)
```

See [`Run.step()`](../build/run/step.md), [`Run.worktree()`](../build/run/worktree.md) and
[`Stop`](../build/stop.md).

## Build your own

- To have other models talk, change each role's
  [model and effort](../build/role/model-and-effort.md), and the model names in its
  [prompt](../build/role/prompt.md).
- To give the chat more than a topic, add a type to each role's
  [`accepts`](../build/role/accept-input-parameters.md) and a placeholder to its prompt.
- To get a result back from the chat, give a role a
  [reporting tool](../build/role/tools-and-return-types.md#reporting-tool), have its prompt tell the
  agent to call it, and return the step's result from `talking`.
