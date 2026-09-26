# Docs guidelines

House style for the AGL documentation at agents-gl.org. Read it before changing anything under
`docs/`, `overrides/` or `tests/docs/`, or a docstring in `src/agl/sdk/` or `src/agl/ports/`. If a
brief contradicts it, stop and ask.

## Audience

- The docs are technical, for engineers building workflows: what AGL does and how to use it, never
  how AGL or a backend implements it, and nothing only a contributor to AGL needs.
- Only the public surface gets a page: `agl.sdk` and the `agl` CLI, with the settings they read.
- Every statement about behaviour is backed by the code or a test, or it isn't written, and pages
  carry no citations. Where a docstring or the help text disagrees with the code, the page follows
  the code and the session report lists the disagreement.
- Pages describe the code on `main`, and the site deploys on release, so it matches what
  `uv tool install agents-gl` installs. Docs change in the same commit as the code they describe.

## Page shapes

A group's own page, Run or Role, opens its group. A file follows its place in `nav`: `Run.step()`
is `docs/build/run/step.md`. A title is the page's nav name, in plain text: a class by its name
(Run), a method with `()` (Run.step()), a property or field without (Run.terminal), a concept in
sentence case (Model and effort). Prose names them the same way, in code font.

- **Section page**, each tab's own: the tab's name, a sentence or two on what the section is for,
  then its work in order. Home is titled AGL: a one-line description, the install command high
  enough to show without scrolling, a short paragraph, Features (each a sentence on what you get,
  one or two on how, and a link), Getting started, and Next.
- **Class page**, Run and Role: the title; a short paragraph with inline links on what it is, which
  an example and a paragraph may follow; How it works, at most one paragraph, then a list linking
  each member or concept page with one line; See also, a list of links; Reference.
- **Member or concept page**, Run's nine members, and Role's six pages, Stop, Configuration and Exit
  codes: the title; one line on what it does ("Land a worktree's work in its parent.", or a noun
  phrase for a property or field); short paragraphs, each followed by a short example, from the
  simplest call to the fullest, though a paragraph stating a rule or a limit may stand alone; a
  sub-heading only for a part that stands on its own; Reference, if it renders a name. No See also.
- **Command entry**, a section of Run workflows or Download workflows: headed by the command, then
  a code block with the command as you type it, what it does, and each option worth showing as a
  sentence ending in a colon and its example.

## Voice

- Technical and plain. Say where things happen, not who is there: "asks a question in the
  terminal", not "asks the person".
- Second person, present tense, active voice, condition first: "To run agents at the same time,
  give each one its own worktree."
- The first sentence of a page or section says what it is for. One idea per short paragraph.
- A number or a rule, never an adjective: no "fast", "powerful", "seamless", "simply", "just" or
  "easily".
- Headings in sentence case, never "Step 1": step is an AGL word. Spelling follows AGENTS.md.
- A list that defines names gives each one line: `- <name> - <what it is or does>.`

## Vocabulary

These words mean these things everywhere: pages, docstrings, help text and printed output.

| Word | Means | Not |
|---|---|---|
| workflow | An `async` function decorated with `@workflow`, declared by a workflow directory | pipeline, script |
| workflow directory | A directory directly under `<AGL_HOME>/workspace/workflows/` whose `pyproject.toml` declares workflows | package, unless you mean the Python package |
| run | One execution of a workflow, named by its label | job, session |
| `Run` | What a workflow receives, the top-level `Run`, and what `Run.worktree()` returns. "Run is the workflow" is fine | the run object |
| label | The name given with `-n`, which names the branch `agl/<label>` | run ID |
| step | One `Run.step()` call and the agent it runs | task, call |
| agent role, role | What a step runs, made with `@role`: a model, a prompt, and what the agent may use. Say "agent role" where a page outside the Role pages introduces it | |
| agent | The Claude Code or Codex session doing a step's work, named after its role: "the `reviewer` agent" | |
| parameter | A value `Run.step()` passes to a role, of a type it accepts, or one the workflow is run with, in `Run.params` | |
| effort | The reasoning level given with `effort=` | reasoning mode |
| record | What AGL keeps for a run: `run.json` and its step entries | cache |
| replay | A step returning its recorded result without running its agent | cache hit |
| worktree | A separate checkout on a branch of its own, for a run and for each `Run.worktree()` | sandbox |
| land, landing | Merging a worktree's work into its parent with `Run.integrate()` | merge queue |
| build | The repository's `build` setting, which every landing must pass | CI |
| restriction | Something a role's agent may not do | sandbox |
| reporting tool | The one tool whose payload, the dataclass its arguments arrive as, becomes the step's result | output tool |
| board | A `Screen` without answers | dashboard |
| question | A `Screen` with answers | human in the loop |

## Linking

- Every SDK name, command, flag, path and setting in prose is in code font.
- An SDK name, or a term with a page of its own, links to the page that covers it at its first
  mention on a page, and not again there. How it works and See also are exempt, and a page never
  links to itself.
- Link text is the term as the sentence uses it, never "here" or "this page".
- Link a page by a relative path to its file, and a section by that path and the heading's anchor.
- An autorefs link, `[Run.step()][agl.sdk.Run.step]`, lands on the name's entry under Reference:
  use it for the entry, and in docstrings. On a page it takes the full public path; in a docstring,
  a scoped reference is fine where the strict build accepts it.
- Never write `[Run][]`: it resolves to a page title by its slug, not to the API object.
- Name only exported types. An unexported one can't be linked, and in a signature it renders as a
  plain name with no warning, so describe it in words.
- A name inside a longer code expression, as in `Claude.OPUS(effort=ClaudeEffort.HIGH)`, stays
  unlinked. If the reader needs the link, name it in the sentence around the expression.
- A fact lives on one page. Another page that needs it says it in a sentence and links there.

## Rendering the API

- Every exported name renders exactly once, in the Reference section of one page: the page about
  it, or about the member or concept it serves, as `VerifierOutcome` on Run.verify(). A second
  rendering gives no warning, and links go to whichever copy is nearer.
- Every API page, one that renders a name, ends with a `## Reference` heading holding its `:::`
  blocks. A block uses the public path, `agl.sdk.Run`, never the defining module.
- A class's block lists its `members`, leaving out those with pages of their own. `Run`'s renders
  its own docstring only.
- Never turn on `members = true`, `show_if_no_docstring`, `merge_init_into_class` or
  `show_source`. Each puts internals on the page, such as `Role`'s `_model` and `_accepts`.
- A name without a docstring doesn't render. Fix the docstring, not the config.

## Code on the page

- Examples are short and written on the page, one idea each, without imports, the definitions
  around the call they show, or annotations.
- Only the Build workflows page's small workflow is included, from `tests/docs/implement/`, whole
  (`--8<-- "implement/roles.py"`) or by the section between `# --8<-- [start:call]` and
  `# --8<-- [end:call]` (`--8<-- "implement/__init__.py:call"`).
- No gate runs an example written on a page, so write each against the real SDK: every name,
  parameter and result in it exists and does what the page says.
- Code that claims to be complete has no `...` and no placeholders, except the `agl new` scaffold.
- Shell commands, TOML and terminal output are written as the code takes and prints them.
- Nothing ending in `.py` goes under `docs/`: everything there is published.
- A file under `tests/docs/` passes ruff and `mypy --strict` and imports nothing from AGL except
  `agl.sdk`. It is never named `test_*.py`, `*_test.py` or `conftest.py`, no two modules outside a
  package share a basename, and no example directory takes a standard-library module's name.

## Docstrings

Docstrings become the API reference, word for word. Google style: `Args:`, `Returns:`, `Raises:`.
References to other SDK names follow the linking rules.

- A summary is one short clause, with no colon and second half and no "so that". A function's or
  method's starts with a verb ending in -s: "Runs …". A property's is a noun phrase for the value.
  A class's says what the class is for, without its name, unless the name is also the plain word
  for the thing, as with `Claude`, `OpenAI` and `Text`.
- An entry is short, capitalised, and says what the value is. An `Args:` entry starts with "The"
  or "A"; a boolean's says what true and false each do, and a default's what the default does.
- `Returns:` starts with "The" and says when the result is `None`. A boolean `Returns:` starts with
  `True` and says when it is `True` and when it is `False`.
- `Raises:` lists every AGL error a caller can meet, and says when.
- A docstring leaves AGL's machinery out, such as fingerprints, replay, the record and
  canonicalising, and keeps a consequence only where it destroys the author's work.
- Every public field, enum member and exported type alias has a docstring, or it doesn't render.
  Only `PLUMBING` in `tests/test_docstring_fields.py` stays undocumented, to stay off the page.

## Claims the docs don't make

Each of these was believed and turned out false in the code. Update the list when the code changes.

- Restrictions aren't a sandbox, and the docs don't say how a backend enforces them.
- `agl resume` refuses a run whose workflow files changed. Never promise "edit a prompt and resume".
- There is no merge queue. Landings into one parent take turns.
- There is no fan-out API. Parallel work is asyncio over the `Run`s that `Run.worktree()` returns,
  and steps on one `Run` take turns.
- There is no question API. An agent asks a question through a tool whose function shows a screen.
- Worktrees live beside the repository, never inside it. AGL writes nothing into your checkout and
  pushes nothing.
- Nothing that doesn't exist yet: no Homebrew tap, no `agl publish`, no marketplace.

## Building and checking

`scripts/docs` runs four checks that build the site into `site/` and check it. It is the "docs site"
gate in `./scripts/check`, and `.github/workflows/docs.yml` runs it before a hand-dispatched deploy.

| Check | Does | Fails when |
|---|---|---|
| build | Deletes `.cache/`, then runs `zensical build --clean --strict` | Zensical reports an issue, such as an unresolved cross-reference or a link to a missing page or anchor, or can't find a snippet |
| Griffe | Loads `agl` as mkdocstrings does and parses every docstring in it, including the ones no page renders | Griffe logs a record at WARNING or above, such as for an `Args:` entry the signature lacks, or any record that mentions "shadow" |
| llms.txt | Writes `llms.txt`, `llms-full.txt` and the pages' Markdown copies with llmstxt-standalone, then compares the pages under `docs/` with the nav | llmstxt-standalone fails, either file is missing, a page in the nav has no Markdown copy, or a page under `docs/` is not in the nav |
| links | Runs lychee offline, so never on other sites, over every HTML file in `site/` except the theme's `404.html` | A link points at a missing file or anchor, including a link written in raw HTML |

- The build and Griffe checks always run. The llms.txt and links checks read the build, so they
  run only when it passed.
- `scripts/docs` exits 0 when every check passes, 1 when any fails, and 2 when `.venv` lacks one of
  its tools or the script is given an argument.
- Every page goes in both `nav` and `[project.plugins.llmstxt.sections]` in `zensical.toml`, whose
  sections mirror the nav. Only the pages that table lists get a Markdown copy.

To preview, run `.venv/bin/zensical serve` from the repository root and open
`http://localhost:8000/`. It prints the issues it finds, but only `scripts/docs` fails on them.
