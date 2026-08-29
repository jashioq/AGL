# D5 survey counts (all from scans; method stated per line)

## Corpus shape (parse of scratchpad/stripped-comments.md -> 1500 entries)
function docstring 659 | comment 380 | attribute docstring 194 | class docstring 149
| module docstring 105 | free-standing string 13

Lines of prose by kind (sum of entry line-spans):
  module docstring  10260 (45% of all removed prose)   median 78L  max 440L
  function docstring 8054                              median  9L  max 105L
  class docstring    1718                              median  9L  max  91L
  comment            1533                              median  3L  max  24L
  attribute docstring1067                              median  5L  max  47L
  TOTAL 22722 prose lines vs 10809 surviving code lines

## Length: a small tail carries half the bulk
116 entries >40 lines = 7.7% of entries but 11807 lines = 52% of all removed prose.
Of those 116: 85 module docstrings, 27 function, 3 class, 1 attribute.
38 of 105 module docstrings are >100 lines. 13 are 1 line (all __init__.py).

## THE dominant failure mode: citation into a document that no longer exists
(regex scan of the 1500 entries; docs/ is deleted - confirmed by git status)
  §N.N section citation   1319 occurrences in  503 entries (33.5%)
  bare stage number       272 occurrences in  118 entries (7.9%)
  UFN.N                    75 occurrences in   33 entries (2.2%)
  "stage N" in words       74 occurrences in   47 entries (3.1%)
  docs/*.md path            8 occurrences in    7 entries (0.5%)
  ANY dead anchor: 518 of 1500 entries = 35%
    module docstring  86/105 = 82%
    function docstring 235/659 = 36%
    class docstring    54/149 = 36%
    attribute docstring 49/194 = 25%
    comment            89/380 = 23%

## Same scan on the UNSTRIPPED corpora (grep -roE counts)
  tests/          §:1434  UF:81  stage N:91  docs/*.md:11
  scripts/check   §:0     UF:0   stage N:2   docs/*.md:0
  .importlinter   §:0     UF:0   stage N:2   docs/*.md:0
The two files with near-zero dangling refs are the two that state the rule:
  .importlinter:164  "(Named, not numbered: gates get inserted, and the numbers move.)"
  scripts/check:445  "(Named, not numbered: gates get inserted, and the numbers move. ...)"

## Genres that did NOT turn out to be the problem
  "argues with itself" markers   34 entries (2%)
  "records history" markers      93 entries (6%)
  future/aspirational tense      12 entries (1%)
  restates the signature: 98 single-line fn docstrings scanned; only 11 repeat every
    content word of their own name, and all 11 still add a fact. NOT a genre here.

## NAMING (ast scan of src/ + tests/, 14625 named things)
src: class 149 | field 231 | function 371 | method 364 | module 105 | modvar 366
     | local 605 | param 1515 | typealias 23
tests: class 268 | function 1987 | method 486 | module 125 | modvar 907 | param 3360

### Private helpers: grammar tracks return type
src module-level functions 371; private (_) 247.
  _check_*   n=4  ALL -> None (validate and raise)
  _checked_* n=8  ALL -> a value
  participle overall: 70 -> value, 10 -> None   (87% transformation)
  non-participle:    151 -> value, 12 -> None
The 9 participle-named helpers that ACT rather than transform (the violations):
  _written  src/agl/adapters/git/_working.py:67   (3 call sites)
  _emptied  src/agl/adapters/git/_working.py:50   (2)
  _removed  src/agl/adapters/git/_working.py:76   (2)
  _drained  src/agl/adapters/shell/verifier.py:70 (2)
  _signalled src/agl/adapters/shell/verifier.py:90(4)
  _stopped  src/agl/adapters/git/_runner.py:149   (5)
  _served   src/agl/adapters/claude_code/fake.py:151 (4)
  _claimed  src/agl/adapters/git/_trees.py:93     (4 src + 2 tests)
  _held     src/agl/adapters/git/_trees.py:107    (7 src + 6 tests)
Compare _drain src/agl/adapters/openai/_session.py:192 -> None (verb, correct) doing
the same job as _drained.

### Duplicate private helper names
38 names reused across modules covering 92 definitions; 14 have DIVERGENT return types:
  _text _wrong _prompt _hints _required _agent _read _stopped _given _lines _body
  _claimed _at _item

### Spelling
identifiers: British 18 occurrences / 16 distinct; American 7 / 3.
  src/ British: _normalised (sdk/_engine/journal.py:330), cancellation
  src/ American: _initialize (adapters/openai/_tools.py:159) - VENDOR-FORCED, mirrors
    the MCP wire method at adapters/openai/_tools.py:145 `if method == "initialize"`.
    NOT an inconsistency.
prose: behaviour 99 / behavior 0; recognise 39 / recognize 0; normalise 25 / normalize 1;
  serialise 86 / serialize 47 (genuinely mixed; American skews to the concurrency sense
  34/47, British covers both senses - a tendency, not a clean split).

### Constants / classes / aliases - already uniform
272/272 module constants SCREAMING_SNAKE; 270/272 annotated Final; 253 private, 19 public.
149/149 classes CamelCase; 16 private classes _CamelCase.
23 type aliases, all CamelCase, private ones _CamelCase.

### Abbreviations - already disciplined
Exactly ONE single-letter name in all of src/: `w` at src/agl/workflows/split/__init__.py:31
25 two-letter (at x9, fn x5, tb x4, wf x3).
Abbreviations used are domain-standard: ref, cli, json, repo, sha, http, rpc, toml, api.

### Cross-layer concept naming - NOT inconsistent
digest 14/14 uniform; project 13/13; namespace 15/16.
label(28) vs name(12) vs run(6) is NOT a split: label=run label, name=the name of some
other thing (workflow/tool/step/namespace), run=the Run object. Correct as-is.
Exception: worktree(name=) src/agl/sdk/workflow.py:66 and worktrees.open(name=)
  src/agl/sdk/_engine/worktrees.py:18 take a NAMESPACE name.

### Type-name collisions
Answer: src/agl/ports/questions.py:37 (class, what a person answered)
     vs src/agl/adapters/openai/_http.py:12 (type alias, a JSON-RPC response body)
     BOTH in scope in the openai adapter. 4 call sites. GENUINE AMBIGUITY.
Entry: src/agl/sdk/_engine/journal.py:99 vs src/agl/adapters/rich_terminal/queues.py:29
Deliberate parallel structure, NOT collisions: Asking, Conversation, FakeAgentRunner,
Script, _Place, _Commands.
_wrong x3: sources.py:218 -> InputError, toml_file.py:366 -> InputError,
  sdk/tools.py:226 -> None (APPENDS to a problems list - a collector, not a factory).

### Module underscore rule - two different rules under one mark
23 underscored modules of 105.
  adapters/: 16 of 16 imported ONLY inside their own package. Rule held perfectly.
  sdk/_engine/: 7 of 7 leak outward.
    _engine.services <- agl.api, agl.cli.commands, agl.cli.main, agl.config.container,
                        agl.sdk.workflow  (Services is NOT in sdk.__all__, len 44)
  .importlinter has NO contract naming _engine - the mark is unenforced.

### Test names - one shape, and it is consistent
1427 test functions/methods.
  81.1% begin with a determiner (a/the/an/every/two/no/both/each/nothing/one/there).
  The other 18.9% begin with a subject noun (an API name) or a gerund - still sentences.
  median 11 words; 90.2% are >=8 words; ZERO are <=3 words.
  only 10.6% use an explicit _when_/_if_/_unless_ connective.
  => the test_<what>_<condition> shape is NOT in use. NOT an inconsistency.

## Ruff config today (pyproject.toml:87-88)
select = ["E", "F", "I", "UP", "B"]  -- no N (pep8-naming), no D (pydocstyle).
