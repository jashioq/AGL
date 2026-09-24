import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Final
from agl.ports.errors import InputError
from agl.sdk._engine.journal import canonical_json

__all__ = ["check_placeholders", "composed"]

# A dotted Python name, which is what a `type.__qualname__` is - `Outer.Inner` for a nested class.
# Spelled once and shared by both patterns below, so the grammar `composed` fills and the grammar
# `check_placeholders` reads cannot drift into two languages with nothing holding them together.
_NAME: Final = r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"

# `{{` cannot occur in JSON - a `{` there is followed by a key's quote or by `}` - so a prompt
# quoting a payload schema, which is most of what these prompts are, cannot spell a placeholder by
# accident.
_PLACEHOLDER: Final = re.compile(r"\{\{(" + _NAME + r")\}\}")

# The same name with the braces padded, which is how Jinja, Handlebars, Mustache and Vue all spell
# a substitution - so `{{ Ticket }}` is the one near-miss an author types by reflex. Anything else
# between a `{{` and a `}}` still matches nothing here: two words, a filter, a block tag, an empty
# pair. A prompt quoting one of those engines stays writable, and only the reflex is refused.
_PADDED: Final = re.compile(r"\{\{\s*(" + _NAME + r")\s*\}\}")

# Two words and no sentence: what a missing input means is the prompt author's to write - "if it
# is missing, work it out" and "if it is missing, stop" are both real endings, and a framework
# explaining itself here would be arguing with whichever one they wrote.
_MISSING: Final = "Not provided"

def composed(instructions: str, inputs: Mapping[str, object]) -> str:
    def _substituted(found: re.Match[str]) -> str:
        name = found[1]
        # The journal's own serialiser and not a second one: what stands at the placeholder is the
        # canonical text this value contributes to the `inputs` term, tags and separators included,
        # so there is one answer in AGL to "what was this value" rather than two free to disagree.
        return canonical_json(inputs[name]) if name in inputs else _MISSING

    # One pass, and `re.sub` resumes at the end of each match in the *original* string: a value
    # spelling `{{Decisions}}` is written out and never scanned again, where a `str.replace` per
    # name would expand it on the next name's turn. Nothing this writes is read back, so there is
    # no injection to guard against - `tests/sdk/test_run_step.py` pins that.
    return _PLACEHOLDER.sub(_substituted, instructions)

def check_placeholders(
    factory: str, role: str, instructions: str, accepts: Sequence[type[object]]
) -> None:
    # The padding is asked about first because it is usually the *cause* of a set that disagrees:
    # `{{ Ticket }}` beside `accepts=(Ticket,)` is a prompt naming nothing and a declaration naming
    # one type, and a refusal about the missing placeholder would send an author looking for a line
    # to add while the line they wrote is on screen.
    padded = {
        found[0]: _spelled(found[1])
        for found in _PADDED.finditer(instructions)
        if found[0] != _spelled(found[1])
    }
    if padded:
        raise InputError(_padded_braces(factory, role, padded))
    written = frozenset(found[1] for found in _PLACEHOLDER.finditer(instructions))
    declared = frozenset(kind.__qualname__ for kind in accepts)
    unfillable = written - declared
    if unfillable:
        raise InputError(_unfillable(factory, role, unfillable, declared))
    unnamed = declared - written
    if unnamed:
        raise InputError(_unnamed(factory, role, unnamed, written))

def _spelled(name: str) -> str:
    return "{{" + name + "}}"

def _padded_braces(factory: str, role: str, padded: Mapping[str, str]) -> str:
    return (
        f'Role factory "{factory}" built role "{role}" with placeholders that AGL does not '
        f"substitute, because of whitespace inside their braces: {_quoted(padded)}. Write "
        f"{_quoted(set(padded.values()))} instead."
    )

def _unfillable(
    factory: str, role: str, unfillable: frozenset[str], declared: frozenset[str]
) -> str:
    accepted = _quoted(declared) if declared else "no classes"
    return (
        f'Role factory "{factory}" built role "{role}" with placeholders that no class in '
        f"`accepts=` fills: {_quoted(map(_spelled, unfillable))}. It accepts {accepted}, so "
        f"correct each placeholder, or add its class to `accepts=`."
    )

def _unnamed(factory: str, role: str, unnamed: frozenset[str], written: frozenset[str]) -> str:
    named = f"only {_quoted(map(_spelled, written))}" if written else "no placeholders"
    return (
        f'Role factory "{factory}" built role "{role}" with no placeholder for these classes in '
        f"`accepts=`: {_quoted(unnamed)}. Its instructions hold {named}, so write "
        f"{_quoted(map(_spelled, unnamed))} where each value belongs, or drop its class from "
        f"`accepts=`."
    )

# `_PADDED`'s `\s` takes a newline or a tab, which `json.dumps` escapes onto the message's one line.
def _quoted(texts: Iterable[str]) -> str:
    return ", ".join(json.dumps(text, ensure_ascii=False) for text in sorted(texts))
