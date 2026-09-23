# Docs guidelines

House style for the AGL documentation at agents-gl.com. Read it before changing anything under
`docs/`, `overrides/` or `tests/docs/`, and before changing a docstring in `src/agl/sdk/` or
`src/agl/ports/`. If a brief contradicts it, stop and ask.

## Scope

- The docs are for engineers building workflows. They say what AGL does for a workflow and how
  to use it. How AGL or a backend implements it stays out, and so does anything only a
  contributor to AGL needs.
- The site documents the public surface: `agl.sdk` and the `agl` CLI. Nothing else gets a page.
- Pages describe the code on `main`. Deploy the site on release, so it matches what
  `uv tool install agents-gl` installs.
- When a docstring or the help text disagrees with the code, the page follows the code and the
  disagreement goes in the session report.
- Docs change in the same commit as the code they describe.

## Page types

Every page is exactly one type.

| Type | Section | Answers | Keeps out |
|---|---|---|---|
| Tutorial | Get started | "Get me to a first success." | Options, edge cases, explanation longer than a sentence |
| API | Build workflows | "How do I use this?" | How AGL implements it |
| Feature | Features | "What does AGL do for me, and what can I rely on?" | Signatures and parameter lists, which belong on the API page |
| Reference | Reference | "What exactly is the flag, key, path or code?" | Narrative |
| Example | Examples | A complete workflow, explained | Nothing yet: a placeholder until release |

The Features index lists every feature, each in one sentence that links to its page. The home page
shows the top six.

A class gets its own page when users write code against it and it has behaviour to explain.
Small value types render on the page of the concept they serve.

## One home per fact

Each fact lives on one page. Any other page that needs it gives one sentence and a link. Before
writing a fact, search `docs/` for it.

| Fact | Home |
|---|---|
| What makes a recorded step run again | Features › Memoized steps and resume |
| What each restriction takes away | The `Restriction` API page |
| Placeholder grammar and storable values | Features › Typed inputs and results |
| Worktree paths, branch names and name rules | Reference › Files and branches |
| `[tool.agl]` keys, project settings and environment variables | Reference › Configuration |
| Commands, flags and exit codes | Reference › CLI |

## Templates

### API class page

1. The short name as the title: `# Run`.
2. One sentence on what the class is for, in words its name and signature don't already give.
   Don't repeat the name, and don't write "this class".
3. When to use it, and what to use instead when it's the wrong tool, in one or two sentences.
4. An example of 5 to 20 lines, included from `tests/docs/`, with an annotation on each SDK call.
5. How it works, in at most three short paragraphs. Mechanics belong on the feature page; link
   to it.
6. The members in task groups, essentials first, one line each. A member with its own page is a
   link; the rest render on this page.
7. The `:::` block, with its `members` listed.
8. See also: at most five links.

### API member and function page

1. The qualified name as the title: `# Run.step`.
2. One sentence starting with a verb ending in -s, such as "Runs one agent task and …".
3. When to use it, then the behaviour people trip on.
4. One to three examples, smallest first.
5. The `:::` block.
6. See also.

### Feature page

1. What you get, in one paragraph, described as behaviour rather than adjectives.
2. One concrete run, walked through in order: what AGL does and what you see.
3. The rules and edge cases an author can run into, as tables when they are a list.
4. A difference between Claude Code and Codex only where it changes what the author writes or
   gets back.
5. Where you meet it in the SDK: links to the API pages.

### Tutorial page

1. Every prerequisite, first.
2. Numbered actions, one per item, each followed by what you should see.
3. Every file shown is a snippet from `tests/docs/`. Every command was run against the code
   before the page shipped, with its output in the session report.

Never title a section "Step 1". Step is an AGL word.

### Reference page

Tables, no narrative. Keep them true with a test wherever possible: take `--help` output from
golden captures, and compare the exit-code table with `agl.ports.errors.EXIT_CODES`.

## Linking

- Every SDK name in prose is in code font and links to its page at its first mention in a
  section. Don't link the same target twice in one section.
- Write the full public path, because short forms don't resolve in prose.
- Never write `[Run][]`. It resolves to a page title by its slug, not to the API object.
- In docstrings, a scoped reference is fine where the strict build accepts it. Otherwise use the
  full path.
- Name only exported types. An unexported type can't be linked, and in a signature it renders as
  a plain name with no warning. Describe it in words.
- A name inside a longer code expression stays unlinked, as in
  `Claude.OPUS(effort=ClaudeEffort.HIGH)`. If the reader needs the link, name it in the
  sentence around the expression.
- Link to a section of another page with a relative path and its anchor, so the build can check
  both.
- Link text says where it goes. Never "here" or "this page".

In prose:

```markdown
[`run.step`][agl.sdk.Run.step] replays a recorded step or runs its [`Role`][agl.sdk.Role].
```

## Rendering the API

- Every identifier renders exactly once on the site. A second rendering gives no warning, and
  links go to whichever copy is nearer.
- A `:::` block uses the public path, `agl.sdk.Run`, never the defining module.
- Every class page lists its `members` and leaves out the members that have their own page.
- Never turn on `members = true`, `show_if_no_docstring`, `merge_init_into_class` or
  `show_source`. Each one puts internals on the page: `Run`'s plumbing fields, or `Role`'s
  `_model` and `_accepts`.
- A name without a docstring doesn't render. Fix the docstring, not the config.

## Code on the page

- AGL code on a page is always included from a real file under `tests/docs/`, whole or by marked
  section.
- Every snippet file passes ruff and `mypy --strict`, and imports nothing from AGL except
  `agl.sdk`. Every example workflow loads in a test the way `agl workflows <name>` loads it.
- Shell commands, TOML and terminal output may be written on the page. Take `--help` output from
  the golden captures.
- Code that claims to be complete contains no `...` and no placeholders. The `agl new` scaffold is
  the exception, because its `...` is what the file really contains.
- Annotations use `# (1)!` markers. One annotation is one sentence and one link.
- Nothing ending in `.py` goes under `docs/`. Everything there is published.

Including a whole file, then a marked section:

```markdown
--8<-- "implement/roles.py"
--8<-- "implement/__init__.py:call"
```

The section sits between `# --8<-- [start:call]` and `# --8<-- [end:call]` in the source file.

## Building and checking

The docs gate builds the site into `site/` and checks it in four steps. They live in
`scripts/docs`, which `./scripts/check` runs with the other gates as "docs site". The deploy,
`.github/workflows/docs.yml`, runs the same script before it uploads `site/`, and runs only when
dispatched by hand. To run the gate on its own, run `scripts/docs`.

| Step | Does | Fails when |
|---|---|---|
| build | Deletes `.cache/`, then runs `zensical build --clean --strict` | Zensical reports an issue, such as an unresolved cross-reference or a link to a missing page or anchor, or can't find a snippet |
| Griffe | Loads `agl` as mkdocstrings does and parses every docstring in it, including the ones no page renders | Griffe logs a record at WARNING or above, such as for an `Args:` entry the signature lacks, or any record that mentions "shadow" |
| llms.txt | Writes `llms.txt`, `llms-full.txt` and the pages' Markdown copies with llmstxt-standalone | llmstxt-standalone fails, either file is missing, or a page in the nav has no Markdown copy |
| links | Runs lychee offline over every HTML file in `site/` except the theme's `404.html` | A link points at a missing file or anchor, including a link written in raw HTML |

- The build and Griffe steps always run. The llms.txt and links steps read the build, so they run
  only when it passed.
- `scripts/docs` exits 0 when every step passes, 1 when any fails, and 2 when `.venv` lacks one of
  its tools or the script is given an argument.
- A new page goes in both `nav` and `[project.plugins.llmstxt.sections]` in `zensical.toml`. Only
  the pages that table lists get a Markdown copy, so the llms.txt step fails on a nav page it
  leaves out. Nothing fails a page left out of the nav: it builds and publishes all the same.
- Links to other sites are never checked, because lychee runs offline.

To preview the site, run `.venv/bin/zensical serve` from the repository root and open
`http://localhost:8000/`. It rebuilds when a page changes and prints the issues it finds, but only
`scripts/docs` fails on them.

## Vocabulary

These words mean these things everywhere: pages, docstrings, help text and printed output.

| Word | Means | Not |
|---|---|---|
| workflow | An `async` function decorated with `@workflow`, declared by a workflow directory | pipeline, script |
| workflow directory | A directory directly under `<AGL_HOME>/workspace/workflows/` whose `pyproject.toml` declares workflows | package, unless you mean the Python package |
| run | One execution of a workflow, named by its label | job, session |
| `Run` | The object a workflow receives. Always in code font | the run object |
| `agl run` | The command. Always in code font | |
| label | The name given with `-n`. It names the branch `agl/<label>` | run ID |
| step | One agent task, started by `run.step` | task, call |
| role | What a step runs: a model with instructions, restrictions and tools | agent, when you mean the role |
| role factory | A function decorated with `@role`. Calling it returns a `Role` | |
| agent | The Claude Code or Codex session that a step drives | |
| effort | The reasoning level given with `effort=` | reasoning mode |
| record | What AGL keeps for a run: `run.json` and its step entries | cache |
| replay | A step returning its recorded value without running an agent | cache hit |
| worktree | A git checkout AGL makes for a run, and for each `run.worktree(namespace)` | sandbox |
| namespace | The name given to `run.worktree` | |
| land, landing | Merging a child's work into its parent with `integrate()` | merge queue |
| build gate | The project's `build` command, which every landing must pass | CI |
| restriction | A limit on what an agent may do | sandbox, permission |
| reporting tool | The one tool whose payload becomes the step's result | output tool |
| payload | The dataclass a tool's arguments arrive as | |
| board | A `Screen` without answers | dashboard |
| question | A `Screen` with answers | human in the loop |
| project | A repository AGL registered on its first `agl run` | |
| workspace | `<AGL_HOME>/workspace`, which holds the workflow directories in its `workflows/` | |
| preflight | The checks AGL makes before a run's first step | |

## Claims the docs don't make

Each of these was believed and turned out false in the code. Update this list when the code
changes.

- Restrictions say what an agent may not do. Don't call them a sandbox, and don't describe how a
  backend enforces them.
- `agl resume` refuses a run whose workflow directory changed. Never promise "edit a prompt and
  resume".
- There is no merge queue. Landings into one target take turns.
- There is no fan-out API. Parallel work is asyncio over child `Run`s, and steps in one worktree
  run one at a time.
- There is no question API. A question is a tool whose handler shows a screen.
- Worktrees live beside the repository, never inside it. AGL writes nothing into your checkout
  and pushes nothing.
- Nothing that doesn't exist yet: no Homebrew tap, no `agl publish`, no marketplace.

## Evidence

- Every statement about behaviour is backed by code or a test. The session report lists each new
  statement with its path:line. The page carries no citations.
- If you can't find the code or test behind a statement, don't write it.

## Sentences

- Second person, present tense, active voice.
- The condition comes first: "To resume a run, run `agl resume <label>`."
- Headings in sentence case.
- The first sentence of a page or section says what it is for.
- One idea per paragraph. Short paragraphs.
- A number or a rule, never an adjective: no "fast", "powerful", "seamless", "simply", "just" or
  "easily".
- Spelling follows AGENTS.md.
- A docstring summary is one short clause: no colon and second half, no "so that".
- A docstring leaves AGL's machinery out: fingerprints, replay, the record and canonicalising.
- A docstring keeps a consequence only where it destroys the author's work.
- A docstring entry is short, capitalised, and says what the value is. `Raises:` says when.

## Docstrings

Docstrings become the API reference, word for word.

- Google style: `Args:`, `Returns:`, `Raises:`.
- A function or method summary says what it does, starting with a verb ending in -s: "Runs …",
  "Returns …".
- A property summary is a noun phrase that says what the value is.
- A class summary says what the class is for, without its name, unless the name is also the plain
  word for the thing, as with `Claude`, `OpenAI` and `Text`.
- An `Args:` entry starts with "The" or "A". A boolean says what happens when it is true and when
  it is false. A default says what the default does.
- `Returns:` starts with "The" and says when the result is `None`. A boolean `Returns:` starts
  with `True`, not "The", and says when it is `True` and when it is `False`.
- `Raises:` lists every AGL error a caller can meet.
- Every public field, enum member and exported type alias has a docstring, because without one it
  doesn't render. The exception is the plumbing listed in `PLUMBING` in
  `tests/test_docstring_fields.py`, which stays undocumented so it stays off the page.
- References to other SDK names follow the linking rules.
