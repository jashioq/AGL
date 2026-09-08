import re
from collections.abc import Mapping, Sequence
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
        f"the role {role!r}, built by the factory {factory!r}, writes {sorted(padded)} in its "
        f"instructions, and a placeholder is spelled `{{{{Name}}}}` with nothing inside the braces "
        f"but the name. Padded, it is literal text: nothing substitutes it, the agent is handed it "
        f"exactly as it stands, and the scan that compares a prompt against `accepts=` does not "
        f"see it either - so a placeholder written this way fails in silence, which is the one "
        f"thing this refusal exists to stop. The name is matched against a type's `__qualname__` "
        f"and there is no space in one, so a spelling that had to be trimmed before it matched "
        f"would be a second spelling of one placeholder with nothing holding the two together. "
        f"Every templating engine an author has written pads the braces, so this is the reflex "
        f"rather than a rare slip: write {sorted(set(padded.values()))} instead"
    )

def _unfillable(
    factory: str, role: str, unfillable: frozenset[str], declared: frozenset[str]
) -> str:
    return (
        f"the role {role!r}, built by the factory {factory!r}, writes the placeholders "
        f"{sorted(unfillable)} and accepts {sorted(declared)}, so nothing can ever fill them. A "
        f"step's inputs are recorded under the name of the declared type each was matched to, so a "
        f"placeholder naming a type this role does not accept stands for a value no call can "
        f"supply: it renders `{_MISSING}` at every step this role ever runs, and the run pays for "
        f"each of them. Either the name is misspelled, or the type belongs in `accepts=` on the "
        f"factory's own decorator - `@role(model=..., accepts=(...))`, which is where it is "
        f"declared and never on the `Role` itself"
    )

def _unnamed(factory: str, role: str, unnamed: frozenset[str], written: frozenset[str]) -> str:
    return (
        f"the role {role!r}, built by the factory {factory!r}, accepts {sorted(unnamed)} and "
        f"writes no placeholder for any of them - the placeholders in its instructions are "
        f"{sorted(written)}. An input reaches the text its agent is handed through `{{{{Name}}}}` "
        f"and through nothing else, so a value of an accepted type nothing names is validated, "
        f"keyed and fingerprinted and then dropped: the step is paid for and answered without the "
        f"thing it was about, and two calls differing only in that value are two digests over one "
        f"prompt, so neither ever replays the other. Write `{{{{TypeName}}}}` where the value "
        f"belongs, or drop the type from `accepts=` on the factory"
    )
