"""What a review found, and the tool the reviewer reports it through.

§3.3 gives the workflow's own example as `if findings.high():`, and that one line settles where
this module lives: `findings` is what `run.step("review", reviewer)` returned, `high()` is a method
on it, and the framework has no type with a method about severity on it. A reporting tool's payload
type is the workflow's own vocabulary - the framework stores it as JSON, reads it back as this
class, and never learns what a finding is - so `Finding`, `Findings` and the branch the workflow
takes over them all belong here, in `fix/`, beside the prompt that asks for them.

## Why a `str` severity and not an enum, and why it is checked anyway

`sdk/tools.py` refuses an enum field outright, and says why: "an enum member is not a JSON value;
it is a Python object whose `value` happens to be one", so `StrEnum` round-trips by an accident of
inheritance that every other `Enum` does not share. Its advice is that a field whose values are a
fixed set is a `str` field whose description names them - which it now points at `describe()` for,
having spent one deliverable with nowhere to write one.

**That advice had no spelling until 19.2, and this module is why it has one.** `_object_schema`
derived `type`, `title`, `properties`, `required` and `additionalProperties` and nothing else, so a
`str` field reached the model as `{"type": "string"}` and the only places this payload could name
its own vocabulary were the *tool's* description and the reviewer's prompt. That was reported here
as a gap in the SDK rather than worked around, and 19.2 closed it: `sdk/tools.py::describe()` puts a
`description` on one field's schema, and `severity` below carries `SEVERITIES` interpolated into it.

**So the constant is written once and read three ways.** The field description the model is shown,
`Findings.high()`'s comparison against `HIGH`, and `Finding.__post_init__`'s check are all the one
tuple; editing it edits all three on one screen. `prompts/review.md` says the three words a second
time and stays prose, deliberately - see below.

**So the vocabulary is enforced by `Finding.__post_init__`, and that is not belt-and-braces.**
`Findings.high()` is a string comparison, and the workflow branches on its result: a reviewer that
answers `"critical"` for the one defect that matters would produce an empty `high()`, no repair
step, and a run that reports success over an unfixed high-severity finding. Nothing anywhere would
raise. An unknown severity is therefore not a cosmetic problem with a report; it is the workflow
silently taking the wrong branch, which is the one failure mode a check is worth paying for.

The check costs almost nothing to reach the model, either. `sdk/tools.py::_instance` constructs the
payload inside a `try` and turns whatever it raises into a rejection carried back into the same
conversation, so a reviewer that invents a severity is told the three words it may use and sends
another call. A plain `ValueError` is the right class for it: this is a value that is wrong, the
text is read by a model rather than by an operator, and reaching into `agl.ports` for `InputError`
would put a framework exception hierarchy inside a workflow's payload type.

**The cost this module used to pay, and no longer does.** §3.6 rule 6 names this exact case as the
one the fingerprint cannot see: a `__post_init__` "is invisible to a derived schema", so adding a
severity to `SEVERITIES` - or removing one - changed what converts while changing no digest, and an
entry recorded under the old vocabulary could stop converting with its fingerprint still matching.
That surfaced as `InternalError` out of `ReportingTool.read` on a resume, naming this type. It was
written down here as the accepted price of the check, with "do not edit `SEVERITIES` under a run
that is still resumable" as the whole of the mitigation.

**It is paid off, and by the same edit that removed the duplication.** `SEVERITIES` is interpolated
into `severity`'s `describe()` text, a field description is a term of the derived schema, and the
schema is a term of `base_of` - so editing the tuple now moves every digest that reports through
this payload and the stale entry is discarded, which is what §3.6 said would happen all along.
`tests/sdk/test_tools.py::test_editing_a_fields_description_changes_the_steps_base` is the
measurement, and `tests/workflows/test_fix.py` pins it against this workflow's own reviewer. The
general hole rule 6 names is still open in `sdk/tools.py` - a `__post_init__` rule that is *not*
stated where the model can read it is still invisible - and this module simply has no such rule
left.

`file` and `summary` are deliberately not checked. A wrong-but-present string in either is a review
comment a human reads and judges; it changes no branch, and refusing it would be this module having
opinions about prose. They are *described*, which is the other half: a description tells the model
what to write and a check refuses what it wrote, and only one of those two is worth having here.

**`prompts/review.md`'s copy stays prose, and is not the duplication that was worth removing.**
Two reasons, and the second is the one that decides it. `prompt_file()` reads a file and hands back
its text unchanged - that is the whole mechanism by which §3.6 fingerprints the prompt rather than a
filename - so deriving the markdown from `SEVERITIES` would mean a `Role` holding a string composed
at import out of a Python constant, which is a second way for a prompt to exist and one that no
longer round-trips to a file a person can read and edit. And what the markdown actually says is not
the list: it says what `high` *means* - "this must be fixed before the change can ship... every
finding you mark `high` is another agent run" - which is guidance about how to choose among the
three, written for a reader, and no substitution produces it. The three words appear inside it
because the sentence needs them, not because the vocabulary is stored there.

## Tuples, not lists

`Findings.findings` is a `tuple[Finding, ...]` and `high()` returns one. Three reasons, in the
order they matter:

* **`high()`'s result is a step input.** `run.step("repair", implementer, findings=findings.high())`
  hands it to `sdk/_engine/journal.py::_canonical`, which walks a `list | tuple` identically and
  tags each dataclass at every depth with its qualified name (rule 6). A tuple of dataclasses
  survives the fingerprint exactly as a list of them does - measured, not assumed - so nothing here
  has to be wrapped in a dataclass to be passable. §3.3's own tickets example passes a bare list for
  the same reason.
* **These values are frozen and shared.** The instance a step returns is handed to the next step and
  read again on replay; a `list` field on a frozen dataclass is a mutable interior with an immutable
  wrapper around it, which is the shape that reads as safe and is not.
* **`sdk/tools.py` builds the field at the type it was declared**, so the JSON array the model sent
  comes back as a tuple rather than being flattened into a list by the round trip.

`findings` has no default. A reviewer that found nothing reports `{"findings": []}` and says so
explicitly, where an optional field would let "found nothing" and "forgot to fill this in" arrive as
the same call.
"""

from dataclasses import dataclass
from typing import Final

from agl.sdk import describe, reporting_tool

__all__ = ["HIGH", "SEVERITIES", "Finding", "Findings", "report_findings"]

HIGH: Final = "high"
"""The one severity the workflow branches on. `Findings.high()` compares against this and the
`repair` step runs when the result is non-empty, so this string is the whole of what "worth another
agent" means in `fix`."""

SEVERITIES: Final = (HIGH, "medium", "low")
"""Every severity a reviewer may report, in descending order of what it costs.

Three and not five: the vocabulary exists so that one comparison can decide whether to pay for a
repair pass, and a scale finer than *fix it now* / *worth knowing* / *noted* asks a model to make a
distinction the workflow then throws away. `high` is the only member with a mechanical consequence;
the other two are what a human reads afterwards."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing wrong with the change, as the reviewer reports it.

    Frozen and slotted, following every payload and role declaration in AGL: the instance a step
    returns is read again by the next step and again on replay, and the one thing it must not be is
    editable by whoever holds it.
    """

    severity: str = describe(
        # The one place `SEVERITIES` is spelled out for the model, and the reason this module no
        # longer pays §3.6 rule 6's price: the text lands in the derived schema, the schema is a
        # term of `base_of`, so editing the tuple moves the digest that `__post_init__` alone could
        # not. `HIGH` is named separately because the *consequence* is what makes the choice, and a
        # bare list of three words would leave the model to guess which one costs another agent.
        f"One of {', '.join(SEVERITIES)}. Use {HIGH!r} only for something that must be fixed "
        f"before this change can ship: that is the one value that sends the change back to be "
        f"repaired, and every finding marked with it is another agent run."
    )
    """One of `SEVERITIES`. Described to the model and refused below when it is not - the module
    docstring argues why this is the field worth checking, why the other two are not, and why
    describing it and checking it out of one constant is what closes rule 6's hole here."""

    file: str = describe("Where it is, as a path relative to the root of the repository.")
    """Where it is, as a path relative to the root of the worktree. Unchecked prose as far as this
    module is concerned: it is read by the repair agent and by a human, and neither needs it to
    have been validated by the type."""

    summary: str = describe(
        "One or two sentences naming what is wrong and why it matters, written so that somebody "
        "repairing it without the diff in front of them knows what to do."
    )
    """What is wrong and why it matters, in the reviewer's own words. This is what the repair agent
    is given to act on, so the description above asks for a sentence a reader could act on without
    the diff in front of them."""

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(
                f"severity is {self.severity!r}, and a finding's severity is one of "
                f"{', '.join(SEVERITIES)}. The workflow decides whether to run a repair pass by "
                f"comparing this field, so a severity outside that list is a finding it would "
                f"silently skip rather than one it would fail to understand"
            )


@dataclass(frozen=True, slots=True)
class Findings:
    """Everything one review pass found: the payload of `report_findings`, and what
    `run.step("review", reviewer)` hands back.

    A wrapper around one sequence rather than the sequence itself, because a reporting tool's
    payload is a dataclass (`sdk/tools.py` refuses anything else) and because §3.3's
    `findings.high()` wants a method to live somewhere. It is also what lets a later version of
    this workflow grow a second field - a verdict, a count of files read - without changing what
    the step returns.
    """

    findings: tuple[Finding, ...] = describe(
        "Every problem this review found, one entry per defect. Report an empty list when the "
        "change is sound: that is a result, not a failure to find anything."
    )
    """Every finding, in the order the reviewer reported them. Required, and empty is the correct
    report for a clean change - see the module docstring."""

    def high(self) -> tuple[Finding, ...]:
        """The findings worth another agent. §3.3's own `if findings.high():`, and the one decision
        this workflow makes for itself.

        Returns a tuple rather than a `Findings`, and that is deliberate: the value is passed
        straight into `run.step("repair", implementer, findings=...)`, where it is fingerprinted by
        `_canonical` and appended to the prompt as canonical JSON. A tuple of dataclasses walks that
        path unchanged - the module docstring says where it was checked - so wrapping it would buy
        nothing and would put a second type with a `findings` field in front of the repair agent.

        Filtering rather than sorting or de-duplicating: two reviewers do not run here, the order is
        the reviewer's own, and a workflow that quietly dropped a finding it thought was a duplicate
        would be making a review judgement in Python.
        """
        return tuple(finding for finding in self.findings if finding.severity == HIGH)


report_findings: Final = reporting_tool(
    "report_findings",
    # What the *tool* is, and nothing about a field. Each field says what it is where it is
    # declared, through `describe()`, which is why this sentence no longer enumerates `SEVERITIES`
    # or explains what a `file` is: `ReportingTool.description` is documented as "what the model
    # reads to decide whether to call it", and a paragraph of per-field rules in it was that
    # sentence being untrue for want of anywhere else to put them.
    "Report everything this review found, and end the review. Call this exactly once, when you "
    "have finished reading the change: it is the only way to record a result, and a review that "
    "ends without calling it has produced nothing and will be run again.",
    Findings,
)
"""The reviewer's one tool, and what makes `review` a reporting step.

Declared here rather than in `roles.py` because §3.3 lists tools and their payload schemas as one
of the four things an author writes, and the payload is above: a payload whose field description
enumerates `SEVERITIES` and a `__post_init__` that enforces it should be able to disagree only by
being edited on one screen - and since 19.2 they cannot disagree at all, both being that tuple."""
