from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
DUMP = REPO / "scratchpad" / "stripped-comments.md"

DIRECTIVE = re.compile(r"^#\s*(noqa|type:|pragma|fmt:|mypy:|ruff:)")
NOQA_CODES = re.compile(r"^#\s*noqa\s*:\s*([A-Za-z]+[0-9]+(?:\s*,\s*[A-Za-z]+[0-9]+)*)")
NOQA_BARE = re.compile(r"^#\s*noqa\s*$")


@dataclass
class Removal:
    path: str
    start: int
    end: int
    kind: str
    qualname: str
    text: str

    @property
    def span(self) -> str:
        return f"L{self.start}" if self.start == self.end else f"L{self.start}-L{self.end}"


@dataclass
class FileResult:
    path: str
    removals: list[Removal] = field(default_factory=list)
    ellipsis_bodies: list[tuple[int, str, str]] = field(default_factory=list)
    directives_kept: list[tuple[int, str, str]] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    became_empty: bool = False
    lines_before: int = 0
    lines_after: int = 0
    changed: bool = False


def is_str_expr(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def assign_target_name(node: ast.stmt) -> str | None:
    if isinstance(node, ast.AnnAssign):
        if isinstance(node.target, ast.Name):
            return node.target.id
        if isinstance(node.target, ast.Attribute):
            return node.target.attr
        return None
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                return target.id
            if isinstance(target, ast.Attribute):
                return target.attr
    return None


Block = tuple[list[ast.stmt], str, str]


def child_blocks(node: ast.stmt, prefix: str) -> Iterator[Block]:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        yield node.body, f"{prefix}{node.name}" if prefix else node.name, "function"
        return
    if isinstance(node, ast.ClassDef):
        yield node.body, f"{prefix}{node.name}" if prefix else node.name, "class"
        return
    inner = prefix.rstrip(".")
    if isinstance(node, ast.If | ast.For | ast.AsyncFor | ast.While | ast.With | ast.AsyncWith):
        yield node.body, inner, "other"
        for orelse in (getattr(node, "orelse", None) or [],):
            if orelse:
                yield orelse, inner, "other"
        return
    if isinstance(node, ast.Try | ast.TryStar):
        yield node.body, inner, "other"
        for handler in node.handlers:
            yield handler.body, inner, "other"
        if node.orelse:
            yield node.orelse, inner, "other"
        if node.finalbody:
            yield node.finalbody, inner, "other"
        return
    if isinstance(node, ast.Match):
        for case in node.cases:
            yield case.body, inner, "other"
        return


def scan(
    stmts: list[ast.stmt],
    owner_qual: str,
    owner_kind: str,
    prefix: str,
    result: FileResult,
    lines: list[str],
    delete: set[int],
    subst: dict[int, str],
) -> None:
    removed_here = 0
    for index, node in enumerate(stmts):
        if is_str_expr(node):
            value = node.value
            assert isinstance(value, ast.Constant)
            start, end = value.lineno, value.end_lineno or value.lineno
            head = lines[start - 1][: value.col_offset]
            tail = lines[end - 1][value.end_col_offset or 0 :]
            if head.strip() or tail.strip():
                result.anomalies.append(
                    f"{result.path}:{start}: string statement shares its line with code "
                    f"(head={head!r} tail={tail!r}) - left in place"
                )
                continue
            if index == 0 and owner_kind in {"module", "class", "function"}:
                kind = f"{owner_kind} docstring"
                name = owner_qual
            elif index > 0 and (target := assign_target_name(stmts[index - 1])) is not None:
                kind = "attribute docstring"
                name = f"{owner_qual}.{target}" if owner_qual else target
            else:
                kind = "free-standing string"
                name = owner_qual
            result.removals.append(
                Removal(
                    result.path,
                    start,
                    end,
                    kind,
                    name,
                    "\n".join(lines[start - 1 : end]),
                )
            )
            delete.update(range(start, end + 1))
            removed_here += 1
        for block, qual, block_kind in child_blocks(node, prefix):
            child_prefix = f"{qual}." if block_kind in {"function", "class"} else prefix
            scan(block, qual, block_kind, child_prefix, result, lines, delete, subst)

    if stmts and removed_here == len(stmts) and owner_kind != "module":
        first = stmts[0]
        indent = " " * first.col_offset
        subst[first.lineno] = f"{indent}..."
        result.ellipsis_bodies.append((first.lineno, owner_qual, owner_kind))


def reduce_directive(comment: str) -> tuple[str, bool]:
    if (match := NOQA_CODES.match(comment)) is not None:
        codes = ", ".join(part.strip() for part in match.group(1).split(","))
        return f"# noqa: {codes}", True
    if NOQA_BARE.match(comment) is not None:
        return "# noqa", True
    return comment, False


def multiline_string_lines(source: str) -> set[int]:
    protected: set[int] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in {tokenize.STRING, getattr(tokenize, "FSTRING_MIDDLE", -1)}:
                if token.end[0] > token.start[0]:
                    protected.update(range(token.start[0], token.end[0] + 1))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return protected


def collapse(source: str) -> str:
    if not source.strip():
        return ""
    protected = multiline_string_lines(source)
    out: list[str] = []
    run = 0
    for number, line in enumerate(source.split("\n"), start=1):
        blank = not line.strip() and number not in protected
        if blank:
            run += 1
            if run > 2:
                continue
        else:
            run = 0
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out) + "\n"


def normalise(tree: ast.AST) -> str:
    for node in ast.walk(tree):
        for name in ("body", "orelse", "finalbody"):
            block = getattr(node, name, None)
            if isinstance(block, list):
                setattr(
                    node,
                    name,
                    [
                        stmt
                        for stmt in block
                        if not (
                            isinstance(stmt, ast.Expr)
                            and isinstance(stmt.value, ast.Constant)
                            and (
                                isinstance(stmt.value.value, str)
                                or stmt.value.value is Ellipsis
                            )
                        )
                    ],
                )
    return ast.dump(tree, include_attributes=False)


def process(path: Path) -> FileResult:
    rel = str(path.relative_to(REPO))
    result = FileResult(path=rel)
    source = path.read_text(encoding="utf-8")
    result.lines_before = source.count("\n")
    lines = source.split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        result.anomalies.append(f"{rel}: will not parse ({error}) - skipped entirely")
        return result

    delete: set[int] = set()
    subst: dict[int, str] = {}
    edit: dict[int, str] = {}

    scan(tree.body, "", "module", "", result, lines, delete, subst)

    pending_block: list[Removal] = []

    def flush() -> None:
        if not pending_block:
            return
        first, last = pending_block[0], pending_block[-1]
        result.removals.append(
            Removal(
                rel,
                first.start,
                last.end,
                "comment",
                "",
                "\n".join(item.text for item in pending_block),
            )
        )
        pending_block.clear()

    previous_line = -10
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        row, col = token.start
        raw = token.string
        head = lines[row - 1][:col]
        bare, reduced = reduce_directive(raw) if DIRECTIVE.match(raw) else (None, False)
        if bare is not None:
            result.directives_kept.append((row, raw, bare))
            if not reduced:
                result.anomalies.append(
                    f"{rel}:{row}: directive comment kept verbatim (no safe reduction): {raw!r}"
                )
            if raw != bare:
                edit[row] = f"{head.rstrip()}  {bare}" if head.strip() else f"{head}{bare}"
                result.removals.append(
                    Removal(
                        rel,
                        row,
                        row,
                        "trailing comment (directive reduced)",
                        "",
                        raw,
                    )
                )
            continue
        if head.strip():
            flush()
            previous_line = -10
            edit[row] = head.rstrip()
            result.removals.append(Removal(rel, row, row, "trailing comment", "", raw))
        else:
            if row != previous_line + 1:
                flush()
            pending_block.append(Removal(rel, row, row, "comment", "", raw))
            previous_line = row
            delete.add(row)
    flush()

    out: list[str] = []
    for number, line in enumerate(lines, start=1):
        if number in subst:
            out.append(subst[number])
        elif number in delete:
            continue
        elif number in edit:
            out.append(edit[number])
        else:
            out.append(line)

    new_source = collapse("\n".join(out))

    try:
        new_tree = ast.parse(new_source)
    except SyntaxError as error:
        result.anomalies.append(f"{rel}: REWRITE DOES NOT PARSE ({error}) - not written")
        return result
    if normalise(ast.parse(source)) != normalise(new_tree):
        result.anomalies.append(f"{rel}: AST CHANGED BY REWRITE - not written")
        return result

    result.became_empty = new_source == ""
    result.lines_after = new_source.count("\n")
    result.changed = new_source != source
    if result.changed:
        path.write_text(new_source, encoding="utf-8")
    return result


KIND_ORDER = [
    "module docstring",
    "class docstring",
    "function docstring",
    "attribute docstring",
    "free-standing string",
    "comment",
    "trailing comment",
    "trailing comment (directive reduced)",
]


NOT_CODE = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
        tokenize.ENCODING,
    }
)


def code_lines(source: str) -> int:
    spans = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                text = node.value
                spans.append(
                    (
                        (text.lineno, text.col_offset),
                        (text.end_lineno or text.lineno, text.end_col_offset or 0),
                    )
                )
    seen: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in NOT_CODE:
            continue
        if token.type == tokenize.STRING:
            if any(lo <= token.start and token.end <= hi for lo, hi in spans):
                continue
        seen.update(range(token.start[0], token.end[0] + 1))
    return len(seen)


def count() -> int:
    physical = code = 0
    for path in sorted(SRC.rglob("*.py")):
        raw = path.read_bytes()
        physical += raw.count(b"\n")
        code += code_lines(raw.decode("utf-8"))
    print(f"src/: physical={physical} code={code}")
    return 0


def verify() -> int:
    left_comments: list[str] = []
    left_strings: list[str] = []
    bad_eof: list[str] = []
    blank_runs: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        raw = path.read_bytes()
        if raw and (not raw.endswith(b"\n") or raw.endswith(b"\n\n")):
            bad_eof.append(str(path))
        source = raw.decode("utf-8")
        if not source:
            continue
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                left_comments.append(f"{path}:{token.start[0]}: {token.string}")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    left_strings.append(f"{path}:{node.lineno}")
        run = 0
        for number, line in enumerate(source.split("\n"), start=1):
            run = run + 1 if not line.strip() else 0
            if run == 3:
                blank_runs.append(f"{path}:{number}")
    print(f"comments left:          {len(left_comments)}")
    for note in left_comments:
        print(f"    {note}")
    print(f"string statements left: {len(left_strings)}")
    for note in left_strings:
        print(f"    {note}")
    print(f"bad end-of-file:        {len(bad_eof)} {bad_eof}")
    print(f"runs of 3+ blank lines: {len(blank_runs)} {blank_runs[:10]}")
    stray = [note for note in left_comments if "# noqa: BLE001" not in note]
    return 1 if stray or left_strings or bad_eof or blank_runs else 0


def strip(force: bool) -> int:
    if DUMP.exists() and not force:
        print(f"{DUMP} already exists. Re-running would overwrite the recovery corpus with")
        print("whatever is left in an already-stripped tree. Pass --force if that is intended.")
        return 2
    files = sorted(SRC.rglob("*.py"))
    results = [process(path) for path in files]

    counts: dict[str, int] = dict.fromkeys(KIND_ORDER, 0)
    comment_lines = 0
    for result in results:
        for removal in result.removals:
            counts[removal.kind] = counts.get(removal.kind, 0) + 1
            if removal.kind == "comment":
                comment_lines += removal.end - removal.start + 1
            elif removal.kind.startswith("trailing comment"):
                comment_lines += 1

    touched = [r for r in results if r.changed]
    before = sum(r.lines_before for r in results)
    after = sum(r.lines_after if r.changed else r.lines_before for r in results)
    ellipsis_total = sum(len(r.ellipsis_bodies) for r in results)
    empty_files = [r.path for r in results if r.became_empty]
    anomalies = [note for r in results for note in r.anomalies]

    with DUMP.open("w", encoding="utf-8") as handle:
        handle.write("# Everything stripped from `src/`\n\n")
        handle.write(
            "Verbatim dump of every comment and string-literal statement removed from "
            "`src/agl/` by `scratchpad/strip_comments.py`. One section per file in sorted "
            "path order; entries in source-line order, with the line numbers they occupied "
            "in the pre-strip source.\n\n"
        )
        handle.write("## Totals\n\n")
        handle.write(f"- files under `src/`: {len(results)}; files changed: {len(touched)}\n")
        handle.write(
            f"- physical lines: {before} before, {after} after ({before - after} removed)\n"
        )
        handle.write(f"- removals recorded: {sum(len(r.removals) for r in results)}\n")
        for kind in KIND_ORDER:
            handle.write(f"  - {kind}: {counts.get(kind, 0)}\n")
        handle.write(f"- physical `#` comment lines removed: {comment_lines}\n")
        handle.write(f"- docstring-only bodies replaced with `...`: {ellipsis_total}\n")
        handle.write(f"- files reduced to 0 bytes: {len(empty_files)}\n")
        handle.write("\n")
        for result in results:
            if not result.removals:
                continue
            handle.write(f"## {result.path}\n\n")
            for removal in sorted(result.removals, key=lambda item: (item.start, item.end)):
                label = removal.kind
                if removal.kind.endswith("docstring") and removal.qualname:
                    label = f"{removal.kind} of `{removal.qualname}`"
                elif removal.kind == "free-standing string" and removal.qualname:
                    label = f"free-standing string in `{removal.qualname}`"
                handle.write(f"### {removal.span} - {label}\n\n")
                handle.write("```\n")
                handle.write(removal.text.replace("\r", ""))
                handle.write("\n```\n\n")

    print(f"files scanned:            {len(results)}")
    print(f"files changed:            {len(touched)}")
    print(f"physical lines before:    {before}")
    print(f"physical lines after:     {after}")
    print(f"physical lines removed:   {before - after}")
    print(f"removals recorded:        {sum(len(r.removals) for r in results)}")
    for kind in KIND_ORDER:
        print(f"  {kind:38s} {counts.get(kind, 0)}")
    print(f"physical comment lines:   {comment_lines}")
    print(f"`...` bodies:             {ellipsis_total}")
    for result in results:
        for line, qual, kind in result.ellipsis_bodies:
            print(f"    {result.path}:{line} {kind} {qual}")
    print(f"0-byte files:             {len(empty_files)}")
    for name in empty_files:
        print(f"    {name}")
    print(f"directives kept:          {sum(len(r.directives_kept) for r in results)}")
    for result in results:
        for line, raw, bare in result.directives_kept:
            print(f"    {result.path}:{line} {raw!r} -> {bare!r}")
    print(f"anomalies:                {len(anomalies)}")
    for note in anomalies:
        print(f"    {note}")
    return 1 if anomalies else 0


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "strip"
    if mode == "strip":
        return strip(force="--force" in argv)
    if mode == "verify":
        return verify()
    if mode == "count":
        return count()
    print(f"usage: {Path(__file__).name} [strip [--force] | verify | count]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
