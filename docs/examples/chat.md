# chat

Source: [`AGL-workflows/chat`](https://github.com/jashioq/AGL-workflows/tree/main/chat)

`chat` has Haiku, through Claude Code, and Luna, through Codex, talk about a topic you give it. They
run at the same time and take turns saying one line each, and the terminal shows the chat as it
goes. The chat ends after 20 lines, or as many as `-l` gives.

## Get it and run it

Download from [`AGL-workflows`](https://github.com/jashioq/AGL-workflows) repository:
```
agl get jashioq/AGL-workflows/chat
```
Run it:
```
agl run chat -n tabs-or-spaces -r "Tabs or spaces" -l 10
```

## How it's built

`__init__.py` holds the workflow, `roles.py` its two roles and their tools, `display.py` what it
shows in the terminal, and `prompts/` a prompt for each role.

### Roles

`haiku_speaker` runs Haiku through Claude Code, and `luna_speaker` runs Luna through Codex. Each
gets its `say` and `listen` from the `Conversation` it is given. Neither has a reporting tool, so
each step returns `None`.

[`roles.py`](https://github.com/jashioq/AGL-workflows/blob/a3aacaf0971de4f2f4c5ead4045f3010471c2d8a/chat/roles.py):

```python
@role(model=Claude.HAIKU(effort=ClaudeEffort.LOW), accepts=(str,))
def haiku_speaker(conversation: Conversation) -> Role[None]:
    return Role(
        name="haiku",
        instructions=prompt_file("prompts/haiku.md"),
        tools=conversation.tools(HAIKU),
    )


@role(model=OpenAI.LUNA(effort=OpenAIEffort.LOW), accepts=(str,))
def luna_speaker(conversation: Conversation) -> Role[None]:
    return Role(
        name="luna",
        instructions=prompt_file("prompts/luna.md"),
        tools=conversation.tools(LUNA),
    )
```

See [Model and effort](../build/role/model-and-effort.md).

### Conversation

One `Conversation` holds the chat for both sides: its `lines`, whether it is `over`, and `turn`, an
event for each side that is set while it is that side's turn. Its `tools()` builds a side's `say`,
which takes a `Line`, and its `listen`, which takes no arguments.

[`roles.py`](https://github.com/jashioq/AGL-workflows/blob/a3aacaf0971de4f2f4c5ead4045f3010471c2d8a/chat/roles.py):

```python
@dataclass(frozen=True, slots=True)
class Line:
    message: str = describe(
        "your next line in the chat: 200 characters at most, no name in front of it"
    )
...
    def tools(self, name: str) -> tuple[Tool, Tool]:
        say = tool(
            "say",
            "Say your next line, which is how the other one hears you.",
            Line,
            lambda line: self.say(name, line.message),
        )
        listen = Tool(
            name="listen",
            description="Wait for the other one to say something, and read it. Takes no arguments.",
            payload_schema={"type": "object", "properties": {}},
            handler=lambda _: self.listen(name),
        )
        return say, listen
```

See [`tool()`](../build/role/tools-and-return-types.md#agl.sdk.tool) and
[`Tool`](../build/role/tools-and-return-types.md#agl.sdk.Tool).

### Say tool

`say` returns `rejected=True` once the chat is over, or when it is not the side's turn. Otherwise it
ends the side's turn, adds the line to `lines` and to the board, and hands the turn to the other
side, which wakes its `listen`. The line that reaches the limit ends the chat instead.

[`roles.py`](https://github.com/jashioq/AGL-workflows/blob/a3aacaf0971de4f2f4c5ead4045f3010471c2d8a/chat/roles.py):

```python
    async def say(self, name: str, message: str) -> ToolResult:
        if self.over:
            return ToolResult(text=OVER, rejected=True)
        if not self.turn[name].is_set():
            return ToolResult(text=NOT_YOUR_TURN, rejected=True)
        self.turn[name].clear()
        self.lines.append(f"{name}: {message}")
        said(COLOUR[name], name, message)
        if len(self.lines) >= self.limit:
            self.end()
            return ToolResult(text=OVER)
        self._hand_to(_other(name))
        return ToolResult(text="Said. Now listen for the answer.")
```

See [Tools](../build/role/tools-and-return-types.md#tools).

### Listen tool

`listen` waits for the side's event, then returns the other side's last line, or tells the agent the
chat is over. Haiku opens, so its `listen` before the first line tells it to speak. `end` marks the
chat over and sets both events, so no `listen` is left waiting.

[`roles.py`](https://github.com/jashioq/AGL-workflows/blob/a3aacaf0971de4f2f4c5ead4045f3010471c2d8a/chat/roles.py):

```python
    async def listen(self, name: str) -> ToolResult:
        await self.turn[name].wait()
        if self.over:
            return ToolResult(text=OVER)
        if not self.lines:
            return ToolResult(text=OPENING)
        return ToolResult(text=self.lines[-1])


    def end(self) -> None:
        self.over = True
        quiet()
        for turn in self.turn.values():
            turn.set()
```

See [`ToolResult`](../build/role/tools-and-return-types.md#agl.sdk.ToolResult).

### Terminal display

The workflow shows `board` with `opened`, and the terminal redraws it on every frame. `say` adds
each line to `spoken` through `said`, and puts the side that speaks next in `thinking` through
`waiting`. `board` draws each line after its speaker's name in colour, a spinner for the side in
`thinking`, and drops the oldest rows once the chat is taller than the terminal.

[`display.py`](https://github.com/jashioq/AGL-workflows/blob/a3aacaf0971de4f2f4c5ead4045f3010471c2d8a/chat/display.py):

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

The workflow makes one `Conversation` with the `--lines` limit, then runs both steps at once in an
`asyncio.TaskGroup`, each in a worktree named after its role and with no `commit`. When a step ends,
`end` tells the other side the chat is over. When both steps have returned, the workflow raises
`Stop` with the number of lines said.

[`__init__.py`](https://github.com/jashioq/AGL-workflows/blob/a3aacaf0971de4f2f4c5ead4045f3010471c2d8a/chat/__init__.py):

```python
@workflow
async def chat(run: Run[Parameters]) -> None:
    await opened(run.terminal, f"{HAIKU} and {LUNA}'s chat")

    conversation = Conversation(run.params.lines)
    async with asyncio.TaskGroup() as group:
        group.create_task(talking(run, conversation, haiku_speaker(conversation)))
        group.create_task(talking(run, conversation, luna_speaker(conversation)))

    raise Stop(
        f"the chat ended after {len(conversation.lines)} of the {conversation.limit} lines it is "
        f"capped at"
    )


async def talking(run: Run[Parameters], conversation: Conversation, speaking: Role[None]) -> None:
    try:
        await run.worktree(speaking.name).step(speaking, run.params.topic)
    finally:
        conversation.end()
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
