# Accept input parameters

A [role](index.md) declares the types of the parameters [`Run.step()`](../run/step.md) may pass
it, in `accepts`.

```python
@role(model=Claude.OPUS, accepts=(Request, Review))
```

```python
await run.step(builder, request, review)
```

AGL matches each parameter to its type, so their order doesn't matter. A role gets one value of
each type. To pass two of a kind, wrap them in one dataclass. A value of a type the role doesn't
accept is refused before the agent starts.

A parameter can be a dataclass, `str`, `int`, `float`, `bool` or `None`, or a `list`, `tuple`, `set`
or `str`-keyed `dict` of them, and so can each field of a dataclass. Anything else is refused
before the agent starts.

Every type a role accepts must appear in its [prompt](prompt.md). A type the step doesn't pass
shows as `Not provided`.
