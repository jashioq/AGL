"""Structural test: C8 - nothing in `src/` or `tests/` cites a number that can be deleted quietly.

CLAUDE.md's comment convention states the rule: **cite nothing that can be deleted without breaking
a build.** Refer to a module, a symbol, a test or an `ARCHITECTURE.md` heading, so a stale reference
breaks loudly rather than quietly pointing at nothing.

## Why this rule earns a mechanism when the other nine do not

It is the one rule in the convention with a measured survival rate. `ARCHITECTURE.md`'s
"Deliberately not built" moved more than two hundred lines down that file over five commits, and
every citation of it *by name* survived all six moves without anybody touching one. Numbered
cross-references in the same tree have now been repaired twice and came back both times, because
nothing notices them: a heading renumbered, a list item deleted, a section moved, and every gate in
this repository stays green while the citation points somewhere else or nowhere.

The other nine rules of the convention need a reader. This one needs an index, and an index is the
thing a machine is better at than a reviewer.

## What counts as a citation, and why the list is by name rather than by shape

`CITED` is a closed list of words that only ever introduce a pointer into a document, plus the
section mark. It is deliberately not "a word followed by a number": half this suite's prose is full
of those - `Summary("review #0")`, `PYTHONHASHSEED` values, `line 1` inside a JSON decoder's own
message - and a scan reading them would be a scan nobody kept.

Three shapes found in this tree are **not** on the list, and each is left off for its own reason:

  * **`gap` and `item`.** These cite the numbered lists under "What this suite does NOT prove" in
    `tests/contracts/`, and they are the same defect - a numbered list item in a docstring, movable
    and deletable in silence. There are 64 such lines across fifteen files. They are not gated
    because gating them means naming eight of those lists item by item first, which is a repair of
    the same size again rather than a clause in this one. Adding `gap` to `CITED` is what closes it,
    and the repair has to come first or the build goes red on work nobody has done yet.
  * **`clause`.** `tests/test_measurable_targets.py`'s `_counted` numbers three clauses and then
    refers to them three lines later, inside one docstring. The referent moves with the citation and
    a reader sees both at once, which is not the failure C8 is about.
  * **A bare `#N`.** Overwhelmingly data here rather than citation - a step label, an attempt
    counter - so the word in front of the number is what makes it a citation, and the word is what
    this reads.

## The two exemptions, and the anchor that makes each one live

A number is a citation when it points into prose and an identifier when something resolves it. Both
exemptions are the second kind, and both were checked by breaking them rather than by reading them.

**Contract numbers.** `[importlinter:contract:1]` through `[importlinter:contract:6]` are section
ids import-linter itself consumes. `tests/test_contract_firing.py`'s `CONTRACT_TYPES` builds a
contract object per number, `tests/test_contract_listings.py` names three of the sections as
constants, and `tests/test_measurable_targets.py`'s `_contract` resolves one against the real file.
Renumbering the sixth contract to a seventh was tried: five tests fail and name it.

**Target numbers.** `tests/test_measurable_targets.py`'s `SETTLED` is a `Mapping[int, ...]` keyed by
target number, and `test_all_twelve_targets_are_accounted_for` pins its key set to `range(1, 13)`.
Deleting the eighth target's entry was tried: that assertion fails and names the gap in the run.

**Both are repo-wide rather than file-scoped, and that is the reading C8's own words force.** The
test is "can this be deleted without breaking a build", not "is the citation next to its
definition". A target number cited from `tests/test_api.py` resolves to a key that cannot be deleted
quietly, so it is a live citation there exactly as it is in the file that pins it. Reading it the
other way would forbid the 26 target citations in seventeen other modules, every one of them
already anchored, and would forbid them for being far away rather than for being fragile.

**The exemption is by anchor and not by word.** `_live_numbers` reads the section ids out of the
real `.importlinter` and the keys out of the real `SETTLED`, so a contract number nothing declares
and a target number nothing settles are both reported like any other. That makes the exemption
self-correcting: delete a contract and every citation of it turns into a finding here, which is the
loud break C8 asks for and the reason this file is worth having.

## Why a text scan and not an AST one

`test_ports_stdlib_only.py` argues the other way round for its own rule - a grep draft matched prose
lines beginning "from whether its entry exists", so parsing was the only correct version. Here the
thing being read *is* prose, and the argument inverts: **`ast` discards comments entirely**, and the
largest single class of defect this rule was written for was a comment heading of the form
`# --- Rule N: ... ---`. A scan that parsed would be a scan that could not see them.

The three places prose lives in this repository - a comment, a docstring, an assertion message - are
all source text, and one regex over lines reads all three without a taxonomy of node kinds. The cost
is that a citation split across a line break is not read; nothing in this tree writes one, and a
finding is a line either way.

## Why a test rather than a `scripts/check` gate

`tests/test_contract_listings.py`'s docstring settles where a rule of this kind goes - a shell gate
for a blunt textual rule, a test for anything that parses one thing and compares it against another
- and `tests/test_ports_stdlib_only.py` gives the three criteria. This lands on the same side.

The comparison is not textual on both ends. One end is source text; the other is a live set of
numbers read out of a parsed `.importlinter` and a parsed `SETTLED`, and neither is a thing `grep`
can hold. It has to be proved to fire, and the scan is a pure function over source text, so the
fabricated cases at the bottom hand it one of every gated form and watch it answer - including the
two that prove the exemptions are keyed on the anchor rather than on the word. And `mypy --strict`
covers `tests/` and does not cover a bash heredoc.

## What this does not close

The scan is a fence around the citation words in `CITED`, not a theory of citation. A pointer
written some other way - "the second bullet above", "the earlier list" - is as fragile and is not
read here. Widening it is a one-line change: a word goes into `CITED`, and what must not happen
instead is a word coming *out* to make a citation legal.

It says nothing about whether a citation by name is correct, only that the thing it names is there
to be checked. `JOURNAL_HEADINGS` is where that gets as tight as it gets cheaply: the six names that
replaced `test_journal.py`'s numbered rule headings are asserted to still be headings there, so
deleting one breaks the build the way a number never did. Nothing asserts that a module citing one
spells it correctly, and a misspelling is the way back in.

## This file holds no numbered citation of its own

Every gated form is written here with `N` where a number would go, which is a letter and not a
digit, so the prose above is not an instance of what it forbids. The fabricated cases build their
citations at runtime - `"rule " + "7"` - on `test_no_literal_surrogates.py`'s reasoning, which holds
its lone surrogate as `chr(0xD800)` for the same purpose. The scan reads this file like every other.
"""

import ast
import re
from collections.abc import Iterator, Mapping
from collections.abc import Set as AbstractSet
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent

# The two trees the comment convention governs, which is the whole of the code in this repository.
TREES: Final = ("src", "tests")

IMPORTLINTER_FILE: Final = REPO_ROOT / ".importlinter"
TARGETS_FILE: Final = REPO_ROOT / "tests" / "test_measurable_targets.py"
JOURNAL_FILE: Final = REPO_ROOT / "tests" / "sdk" / "test_journal.py"

# The words that introduce a pointer into a document and never anything else, in this corpus. See
# this file's docstring for the three numbered shapes deliberately left off.
CITED: Final = ("contract", "gate", "invariant", "part", "rule", "section", "stage", "target", "uf")

# U+00A7, built rather than written, so this module holds no instance of what it forbids.
SECTION_MARK: Final = chr(0xA7)

# import-linter's own section id, minus the number it ends in.
CONTRACT_PREFIX: Final = "importlinter:contract"

# The mapping in `test_measurable_targets.py` whose keys are the twelve target numbers.
TARGETS_SYMBOL: Final = "SETTLED"

# The names that replaced `test_journal.py`'s numbered rule headings, each asserted below to still
# be a heading there. Eleven other modules cite one, so a rename here is a rename in all of them.
JOURNAL_HEADINGS: Final = (
    "The scoped counter",
    "Sort every set",
    "No `repr()` shortcut",
    "The qualified type name",
    "What a tool contributes",
    "The canonical text",
)

# How a heading is written in this suite: three dashes, the name, dashes to the right margin.
HEADING_MARK: Final = "# --- "

# The floor, in the spirit of the hermeticity test's `sessions >= 2`. 108 modules under `src/` and
# 126 under `tests/` when this was written; 150 is a floor and not a measurement, so an ordinary
# edit never moves it and a walk that found the wrong directory cannot clear it.
FILES_TODAY: Final = 150

# A number, optionally behind spaces, a hyphen or a `#`: `contract N`, `target #N`, `UF-N`, `UFN`.
_NUMBER: Final = r"[ \t-]*#?[ \t]*(\d+)"

_CITATION: Final = re.compile(
    "(" + "|".join([*(rf"\b{word}s?" for word in CITED), re.escape(SECTION_MARK)]) + ")" + _NUMBER,
    re.IGNORECASE,
)

# A second and third number on one opener: `rules N and M`, `contracts N and M`, `targets #N, #M`.
_ALSO: Final = re.compile(r"[ \t]*(?:,|and)[ \t]*#?[ \t]*(\d+)")

@dataclass(frozen=True)
class Citation:
    """One numbered cross-reference: the line it is written on, the kind of thing, and the number.

    `kind` is the singular lower-case word, so `Contracts N and M` and `contract N` arrive as the
    same kind - that being what decides whether an exemption's anchor has anything to say about it.
    """

    line: int
    kind: str
    number: int

def numbered_citations(source: str, *, live: Mapping[str, AbstractSet[int]]) -> list[Citation]:
    """Every numbered cross-reference in `source` whose number is not a live key of its kind.

    `live` maps a kind to the numbers something in this repository resolves - contract numbers to
    `.importlinter`'s section ids, target numbers to `SETTLED`'s keys. A kind absent from it has no
    exemption at all, which is the state every kind but those two is in.

    Pure: takes text, returns findings, touches no disk. The fabricated cases at the bottom of this
    file depend on that, and they are what make the real comparison mean anything.
    """
    found = {
        citation
        for number, line in enumerate(source.splitlines(), 1)
        for citation in _in_one_line(number, line)
        if citation.number not in live.get(citation.kind, frozenset())
    }
    return sorted(found, key=lambda citation: (citation.line, citation.kind, citation.number))

def _in_one_line(number: int, line: str) -> Iterator[Citation]:
    """Every citation written on one line, a list of numbers on one opener counting as several."""
    for match in _CITATION.finditer(line):
        # A `\uf0a1` escape ends in `uf` followed by a digit and is not a citation. Nothing else
        # in either tree writes a backslash in front of one, so the whole class goes at once.
        if line[match.start() - 1 : match.start()] == "\\":
            continue
        kind = match.group(1).lower().rstrip("s")
        yield Citation(number, kind, int(match.group(2)))
        position = match.end()
        while (more := _ALSO.match(line, position)) is not None:
            yield Citation(number, kind, int(more.group(1)))
            position = more.end()

def _live_numbers() -> Mapping[str, frozenset[int]]:
    """The two kinds whose numbers are identifiers, read out of the files that make them so."""
    return {"contract": _contract_numbers(), "target": _target_numbers()}

def _contract_numbers() -> frozenset[int]:
    """Every `[importlinter:contract:N]` section id in the real `.importlinter`.

    Read with `ConfigParser` rather than by pattern, because that is what import-linter reads it
    with: a number this cannot see is a number that is not a contract.
    """
    config = ConfigParser()
    config.read_string(IMPORTLINTER_FILE.read_text(encoding="utf-8"))
    return frozenset(
        int(section.rpartition(":")[2])
        for section in config.sections()
        if section.startswith(f"{CONTRACT_PREFIX}:") and section.rpartition(":")[2].isdigit()
    )

def _target_numbers() -> frozenset[int]:
    """Every key of `SETTLED` in `tests/test_measurable_targets.py`, parsed out of the file.

    Parsed rather than imported, on that file's own reasoning about `pyproject.toml`: what makes a
    target number an identifier is the edit somebody makes to that mapping, and the edit is a line
    in this file rather than a value in an interpreter that has already imported it.
    """
    for node in ast.walk(ast.parse(TARGETS_FILE.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        if TARGETS_SYMBOL not in _bound(node) or not isinstance(node.value, ast.Dict):
            continue
        return frozenset(
            key.value
            for key in node.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, int)
        )
    raise AssertionError(
        f"{TARGETS_FILE} no longer binds {TARGETS_SYMBOL} to a dict literal. That mapping's keys "
        f"are what make a target number an identifier rather than a pointer into prose, so this "
        f"file cannot tell which target numbers are live and the exemption has lost its anchor. "
        f"See this file's docstring, and test_all_twelve_targets_are_accounted_for."
    )

def _bound(node: ast.AnnAssign | ast.Assign) -> frozenset[str]:
    """The plain names an assignment binds, ignoring anything that is not a bare name."""
    written = node.targets if isinstance(node, ast.Assign) else [node.target]
    return frozenset(target.id for target in written if isinstance(target, ast.Name))

def _points_at_something_deletable(shown: str, citation: Citation) -> str:
    return (
        f"{shown}:{citation.line} cites {citation.kind} {citation.number} by number.\n"
        f"\n"
        f"CLAUDE.md's C8: cite nothing that can be deleted without breaking a build. A number in a "
        f"comment, a docstring or an assertion message points at a heading, a list item or a "
        f"paragraph, and all three can be deleted, renumbered or moved with every gate in this "
        f"repository still green - so the citation quietly means something else, or nothing. "
        f"ARCHITECTURE.md's \"Deliberately not built\" moved more than two hundred lines down that "
        f"file over five commits and every citation of it by name survived; the numbered ones have "
        f"been repaired twice.\n"
        f"\n"
        f"Name the thing instead: a module, a symbol, a test, or a heading spelled out in words. "
        f"tests/sdk/test_journal.py is the worked example - its six numbered rule headings are now "
        f"{', '.join(JOURNAL_HEADINGS)}, and the modules citing them say those words.\n"
        f"\n"
        f"Two kinds of number are exempt, and both are exempt by anchor rather than by word: a "
        f"contract number that is a section id in .importlinter, and a target number that is a key "
        f"of SETTLED in tests/test_measurable_targets.py. Deleting either breaks a build, which is "
        f"the whole of what C8 asks. {citation.number} is not one of those today, so if it is "
        f"meant to be an identifier, the file that pins it is what changes first."
    )

# --- The real comparison -------------------------------------------------------------------------

def test_no_module_in_src_or_tests_cites_a_number_that_can_be_deleted_quietly() -> None:
    """`src/` and `tests/`, line by line, against C8 and the two anchored exemptions.

    Two assertions, and the second is what keeps the first honest. No line cites a numbered thing
    outside the exemptions, and the scan is asserted to have walked both trees - so a version of
    this file matching nothing could not be green while checking nothing.
    """
    live = _live_numbers()
    problems: list[str] = []
    walked = 0
    for tree in TREES:
        for source in sorted((REPO_ROOT / tree).rglob("*.py")):
            walked += 1
            problems += [
                _points_at_something_deletable(str(source.relative_to(REPO_ROOT)), citation)
                for citation in numbered_citations(
                    source.read_text(encoding="utf-8"), live=live
                )
            ]

    assert not problems, "\n\n".join(problems)
    assert walked >= FILES_TODAY, (
        f"only {walked} module(s) were found under {TREES} below {REPO_ROOT}, and there were 234 "
        f"when this was written. Every assertion above is silent about a module holding no "
        f"citation, so a walk that found none of them would be green and checking nothing"
    )

def test_the_contract_numbers_this_file_exempts_are_section_ids_import_linter_reads() -> None:
    """The first exemption's anchor, asserted rather than described.

    An empty set here would not fail the comparison above - it would make every contract citation a
    finding - but it would mean the exemption had silently stopped being about anything, and the
    complaint a reader got would name a rule nobody had broken.
    """
    numbers = _contract_numbers()
    assert numbers, (
        f"{IMPORTLINTER_FILE} declares no [{CONTRACT_PREFIX}:N] section at all. Either the file "
        f"moved or its sections are spelled some other way; either way the exemption in this file "
        f"has lost its anchor and every contract cited by number is about to be reported"
    )
    assert numbers == frozenset(range(1, max(numbers) + 1)), (
        f"the contracts in {IMPORTLINTER_FILE} are numbered {sorted(numbers)}, which has a hole in "
        f"it. A hole means a contract was deleted and the rest were not renumbered, so a citation "
        f"of the missing number now reads as a live identifier to everything except this test"
    )

def test_the_target_numbers_this_file_exempts_are_keys_of_the_mapping_that_pins_them() -> None:
    """The second exemption's anchor. `SETTLED`'s keys, parsed out of the file that pins them."""
    numbers = _target_numbers()
    assert numbers == frozenset(range(1, len(numbers) + 1)), (
        f"{TARGETS_SYMBOL} in {TARGETS_FILE} is keyed {sorted(numbers)}, which is not a run from "
        f"one. test_all_twelve_targets_are_accounted_for is what normally says so; if it has been "
        f"relaxed, the exemption here is exempting a number nothing pins any more"
    )

def test_every_name_the_journal_suite_is_cited_by_is_still_a_heading_inside_it() -> None:
    """The six names that replaced numbered rule headings, against `tests/sdk/test_journal.py`.

    This is the half a scan for numbers cannot reach. Renaming a number to a name only helps if the
    name is there to be found, and eleven other modules cite one of these six - so a heading
    reworded alone leaves those citations pointing at nothing, exactly as the numbers did.
    """
    source = JOURNAL_FILE.read_text(encoding="utf-8")
    headings = {line.removeprefix(HEADING_MARK) for line in source.splitlines()}
    missing = [
        name for name in JOURNAL_HEADINGS if not any(one.startswith(name) for one in headings)
    ]
    assert not missing, (
        f"{JOURNAL_FILE} has no heading starting {missing}. Those names are how this repository "
        f"cites that file - they replaced numbered headings under C8 - so a rename here is a "
        f"rename in every module that cites one, and in JOURNAL_HEADINGS above"
    )

# ---------------------------------------------------------------------------------------------
# Non-vacuity: the scan on fabricated source, one case per gated form and one per exemption, so
# that a rewrite which broke it into always answering "nothing here" fails below instead of
# passing over the whole tree. Every citation below is built at runtime out of two string
# literals, so this module holds no instance of what it forbids and is scanned like any other.
# ---------------------------------------------------------------------------------------------

_NOTHING: Final[Mapping[str, AbstractSet[int]]] = {}

def test_the_scan_reports_a_numbered_rule_which_is_the_shape_this_gate_exists_for() -> None:
    """The defect that bought this file: a comment heading cited by its number from elsewhere."""
    assert numbered_citations("# " + "rule " + "7" + "\n", live=_NOTHING) == [
        Citation(1, "rule", 7)
    ]

def test_the_scan_reports_every_other_word_on_the_cited_list_as_well() -> None:
    """One line per gated form, so a word quietly dropped from `CITED` fails here and not in prose.

    Written from `CITED` itself rather than from a second copy of it: a word added there without a
    thought about spelling is a word this hands straight to the scan.
    """
    for word in CITED:
        line = "# see " + word + " " + "3"
        assert numbered_citations(line, live=_NOTHING) == [Citation(1, word, 3)], word

def test_the_scan_reports_the_section_mark_which_is_the_form_no_word_introduces() -> None:
    """`U+00A7` is a citation on its own and needs no word in front of it."""
    assert numbered_citations("# " + SECTION_MARK + "4" + "\n", live=_NOTHING) == [
        Citation(1, SECTION_MARK, 4)
    ]

def test_the_scan_reports_a_citation_spelled_with_a_hash_a_hyphen_or_neither() -> None:
    """`target #N`, `UF-N` and `UFN` are one form written three ways, and all three are read."""
    assert numbered_citations("# " + "target #" + "8", live=_NOTHING) == [Citation(1, "target", 8)]
    assert numbered_citations("# " + "UF-" + "3", live=_NOTHING) == [Citation(1, "uf", 3)]
    assert numbered_citations("# " + "UF" + "3", live=_NOTHING) == [Citation(1, "uf", 3)]

def test_the_scan_reports_both_numbers_when_one_opener_carries_a_list_of_them() -> None:
    """`rules N and M` is two citations, and a scan reading the first alone would pass on a line
    whose second number is the dead one."""
    assert numbered_citations("# " + "rules " + "2 and 3", live=_NOTHING) == [
        Citation(1, "rule", 2),
        Citation(1, "rule", 3),
    ]

def test_the_scan_reads_a_citation_wherever_prose_lives_and_not_only_in_a_comment() -> None:
    """A docstring and an assertion message are prose and are read; `ast` would see neither."""
    assert numbered_citations('"""' + "stage " + "2" + '."""', live=_NOTHING) == [
        Citation(1, "stage", 2)
    ]
    assert numbered_citations('assert x, "' + "see part " + "5" + '"', live=_NOTHING) == [
        Citation(1, "part", 5)
    ]

def test_the_scan_is_silent_on_a_contract_number_the_import_config_actually_declares() -> None:
    """The first exemption doing its job, against a number read out of the real `.importlinter`."""
    live = _live_numbers()
    declared = min(live["contract"])
    assert not numbered_citations("# " + "contract " + str(declared), live=live)

def test_the_scan_reports_a_contract_number_the_import_config_does_not_declare() -> None:
    """And the same word one number higher, which is the exemption being keyed on the anchor."""
    live = _live_numbers()
    absent = max(live["contract"]) + 1
    assert numbered_citations("# " + "contract " + str(absent), live=live) == [
        Citation(1, "contract", absent)
    ]

def test_the_scan_is_silent_on_a_target_number_the_settled_mapping_actually_keys() -> None:
    """The second exemption doing its job, against a key read out of the real mapping."""
    live = _live_numbers()
    settled = min(live["target"])
    assert not numbered_citations("# " + "target #" + str(settled), live=live)

def test_the_scan_reports_a_target_number_the_settled_mapping_does_not_key() -> None:
    """A thirteenth target is prose about a target nothing settles, and is reported as one."""
    live = _live_numbers()
    absent = max(live["target"]) + 1
    assert numbered_citations("# " + "target #" + str(absent), live=live) == [
        Citation(1, "target", absent)
    ]

def test_the_scan_is_silent_on_a_cited_word_with_no_number_behind_it() -> None:
    """"the contract suite" and "a later stage" are prose about a thing, not pointers at one."""
    assert not numbered_citations(
        "# the contract suite, at a later stage, names the rule and the target\n", live=_NOTHING
    )

def test_the_scan_is_silent_on_a_number_no_word_from_the_list_introduces() -> None:
    """The step labels and attempt counters this suite is full of, which are data and not prose."""
    assert not numbered_citations(
        'assert first == Summary("review #0")\nPYTHONHASHSEED = "31337"\n', live=_NOTHING
    )

def test_the_scan_is_silent_on_a_unicode_escape_whose_tail_spells_a_cited_word() -> None:
    """A `\\uf0a1` escape ends `uf` and a digit, and the backslash in front of it is the tell."""
    assert not numbered_citations('X = "\\uf0a1"\n', live=_NOTHING)
    assert numbered_citations("# " + "uf" + "0a1", live=_NOTHING) == [Citation(1, "uf", 0)]

def test_the_scan_is_silent_on_a_cited_word_inside_a_longer_one() -> None:
    """`subcontract 4` names something else, and `parts[3]` is a slice rather than a citation."""
    assert not numbered_citations("# a subcontract 4 and parts[3]\n", live=_NOTHING)

def test_the_scan_reports_the_line_a_citation_is_written_on_and_not_the_first() -> None:
    """A finding is read by opening the file at the line, so the line is half of what it says."""
    assert numbered_citations("# nothing here\n#\n# " + "gate " + "2", live=_NOTHING) == [
        Citation(3, "gate", 2)
    ]
