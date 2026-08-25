"""`split`'s prompt files. Markdown, read by `prompt_file()` at import - no Python lives here.

**This file exists to satisfy `tests/test_tree.py`**, which asserts that every directory under
`src/agl/` carries an `__init__.py` so that the tree is fully importable. §3.7's sanctioned prompt
layout is a `prompts/` subdirectory inside the workflow's own package, and a directory of markdown
is not a package in any sense that test means. `fix/prompts/__init__.py` argues the collision in
full and predicted this file in as many words - "stage 18's `split` will meet exactly the same
collision, and every workflow after it" - so the argument is made once, there, and this file does
not restate it. The finding it records belongs to `tests/test_tree.py` and not to either package.

`prompt_file()` reads these files at declaration time and hands back their text, so the `Role`s in
`roles.py` hold prompts and never filenames - §3.6 fingerprints `role.instructions`, and a role
holding a path would fingerprint the path. Nothing imports this package; the two files beside this
one are opened by name and read as UTF-8 text.
"""
