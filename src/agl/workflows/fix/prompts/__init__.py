"""`fix`'s prompt files. Markdown, read by `prompt_file()` at import - no Python lives here.

**This file exists to satisfy `tests/test_tree.py`, and that is worth stating plainly rather than
leaving as a puzzle.** That test asserts every directory under `src/agl/` carries an `__init__.py`,
so that the tree is fully importable. §3.7's sanctioned prompt layout is a `prompts/` subdirectory
inside the workflow's own package - `prompt_file("prompts/decompose.md")` is how the plan and
`sdk/roles.py` both write it - and a directory of markdown is not a package in any sense the test
means. The two collide, and the cheap resolutions were to flatten the prompts into `fix/` beside
the modules or to loosen the test. Neither is right: the first drops the plan's own layout for a
rule about Python files, and the second edits an assertion to accommodate the thing it caught. So
the directory becomes a package that holds no code, and this docstring is the argument for why.

Stage 18's `split` will meet exactly the same collision, and every workflow after it. The finding
belongs to `tests/test_tree.py` rather than to this file: what it means to say is that the tree is
*importable*, and a directory holding no `.py` at all cannot make it otherwise.

`prompt_file()` reads these files at declaration time and hands back their text, so the `Role`s in
`roles.py` hold prompts and never filenames - §3.6 fingerprints `role.instructions`, and a role
holding a path would fingerprint the path. Nothing imports this package; the two files beside this
one are opened by name and read as UTF-8 text.
"""
