#!/usr/bin/env python3
"""
Copy a Jupyter Book 1 (Sphinx/MyST) book to a new directory, making the few
Markdown changes that Jupyter Book 2 (mystmd) needs so that no content is lost.

JB2 reads almost all JB1 MyST unchanged, so this script deliberately does
little. Every .md file gets these rewrites (never inside code or raw blocks):

  ```{div} cls            ->  ```{div}  +  :class: cls
  {ref}`text<newline><x>` ->  {ref}`text <x>`     (JB2 can't parse split roles)
  {doc}`text <path>`      ->  [text](path.md)
  [text](label)           ->  [text](#label)      (label defined as (label)=)
  ~~text~~                ->  {del}`text`
  <u>text</u>             ->  {u}`text`
  [^1]:<newline>text      ->  [^1]: text
  (krückeberg-x)=         ->  (krueckeberg-x)=    (and every reference to it;
                                                  JB2 truncates non-ASCII labels)

All other files (images, _config.yml, _toc.yml, CSS, ...) are copied as-is.
If the book uses {flat-table}, jb2-plugins/flat-table.mjs is copied to the book root.
Afterwards run `jupyter-book init` in the destination to migrate the config,
and list flat-table.mjs under project: plugins: in myst.yml (jb1tojb2 does both).

Constructs that JB2 or its Typst/PDF output would drop or need help with are
listed in a report at the end.

Usage:
  python3 jb1_to_jb2_myst.py SOURCE_DIR DEST_DIR
  python3 jb1_to_jb2_myst.py SOURCE.md DEST.md
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import unicodedata
from pathlib import Path

SKIP_DIRS = {"_build", ".git", ".venv", "venv", "__pycache__", ".ipynb_checkpoints", "node_modules"}
BOOK_ROOT_MARKERS = ("_config.yml", "_toc.yml", "myst.yml")
FLAT_TABLE_PLUGIN = Path(__file__).resolve().parent / "jb2-plugins" / "flat-table.mjs"

# Directives whose body is literal text, not Markdown.
LITERAL_DIRECTIVES = {
    "code", "code-block", "sourcecode", "code-cell", "literalinclude",
    "raw", "math", "mermaid", "csv-table", "eval-rst",
}

FENCE_RE = re.compile(r"^(?P<indent>\s*)(?P<fence>`{3,}|~{3,}|:{3,})(?P<info>.*)$")
DIRECTIVE_INFO_RE = re.compile(r"^\{(?P<name>[\w:-]+)\}\s*(?P<arg>.*)$")
OPTION_RE = re.compile(r"^\s*:(?P<key>[\w-]+):\s*(?P<value>.*)$")
LABEL_DEF_RE = re.compile(r"^\((?P<label>[^()\s]+)\)=\s*$", re.MULTILINE)
NAME_OPTION_RE = re.compile(r"^\s*:name:\s*(?P<label>\S+)\s*$", re.MULTILINE)
GERMAN_ASCII = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}

SPLIT_ROLE_RE = re.compile(r"\{(?P<role>[\w:-]+)\}`(?P<body>[^`]*\n[^`]*)`")
DOC_ROLE_RE = re.compile(r"\{doc\}`(?:(?P<text>[^`<]*?)\s*<(?P<target>[^`>]+)>|(?P<bare>[^`<]+))`")
BARE_LINK_RE = re.compile(r"(?<!!)\[(?P<text>[^\]]*)\]\((?P<target>[^()\s#/.:]+)\)")
STRIKE_RE = re.compile(r"~~(?=\S)(?P<text>[^~\n]+?)(?<=\S)~~")
UNDERLINE_RE = re.compile(r"<u>(?P<text>[^<\n]+?)</u>")
FOOTNOTE_DEF_RE = re.compile(r"^(?P<def>[ \t]*\[\^[^\]]+\]:)[ \t]*\n(?=[ \t]*\S)", re.MULTILINE)

# Inline HTML tags worth reporting. <br> is fine: JB2 turns it into a line break.
REPORT_HTML_RE = re.compile(
    r"<(?P<tag>a|b|i|s|u|em|strong|span|div|p|table|tr|td|th|img|iframe|sup|sub|"
    r"del|ins|font|center|details|summary|small|big|mark|style|script)\b[^>\n]*>",
    re.IGNORECASE,
)


class Report:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.flat_tables = 0

    def add(self, path: Path, lineno: int, msg: str) -> None:
        self.items.append(f"{path}:{lineno}: {msg}")


def find_book_root(path: Path) -> Path:
    for d in [path.parent, *path.parent.parents]:
        if any((d / m).exists() for m in BOOK_ROOT_MARKERS):
            return d
    return path.parent


def iter_book_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def collect_labels(root: Path) -> set[str]:
    labels: set[str] = set()
    for p in iter_book_files(root):
        if p.suffix == ".md":
            text = p.read_text(encoding="utf-8")
            labels.update(LABEL_DEF_RE.findall(text))
            labels.update(NAME_OPTION_RE.findall(text))
    return labels


def ascii_label(label: str) -> str:
    for ch, repl in GERMAN_ASCII.items():
        label = label.replace(ch, repl)
    return unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()


def build_label_map(labels: set[str], report: Report, root: Path) -> dict[str, str]:
    """Map each non-ASCII label to an ASCII one that doesn't clash."""
    label_map: dict[str, str] = {}
    for label in sorted(labels):
        if label.isascii():
            continue
        new = ascii_label(label)
        if new in labels or new in label_map.values():
            report.add(root, 0, f"label {label!r} not renamed: {new!r} already exists")
        else:
            label_map[label] = new
    return label_map


def rename_labels(text: str, label_map: dict[str, str]) -> str:
    for old, new in label_map.items():
        o = re.escape(old)
        text = re.sub(rf"^(\s*)\({o}\)=", rf"\g<1>({new})=", text, flags=re.MULTILINE)
        text = re.sub(rf"^(\s*:name:\s*){o}\s*$", rf"\g<1>{new}", text, flags=re.MULTILINE)
        text = re.sub(rf"(\{{(?:ref|numref)\}}`(?:[^`]*<)?){o}(>?`)", rf"\g<1>{new}\g<2>", text)
        text = re.sub(rf"\]\(#?{o}\)", f"](#{new})", text)
    return text


def split_segments(lines: list[str]) -> list[tuple[bool, list[str]]]:
    """Split lines into (is_markdown, lines) runs.

    Fence lines and the bodies of code/raw blocks are non-Markdown runs.
    Bodies of content directives ({note}, {list-table}, {div}, ...) are
    Markdown and are transformed like ordinary text.
    """
    segments: list[tuple[bool, list[str]]] = []
    stack: list[tuple[str, int, bool]] = []  # (fence char, length, literal)

    def emit(is_md: bool, line: str) -> None:
        if segments and segments[-1][0] == is_md:
            segments[-1][1].append(line)
        else:
            segments.append((is_md, [line]))

    for line in lines:
        m = FENCE_RE.match(line.rstrip("\n"))
        in_literal = bool(stack) and stack[-1][2]
        if m:
            fence, info = m.group("fence"), m.group("info").strip()
            char, length = fence[0], len(fence)
            if stack and not info and char == stack[-1][0] and length >= stack[-1][1]:
                stack.pop()
                emit(False, line)
                continue
            if not in_literal and (char != ":" or info.startswith("{")):
                d = DIRECTIVE_INFO_RE.match(info)
                literal = d is None or d.group("name") in LITERAL_DIRECTIVES
                stack.append((char, length, literal))
                emit(False, line)
                continue
        emit(not in_literal, line)
    return segments


def convert_directive_headers(lines: list[str], labels: set[str]) -> list[str]:
    """Fix directive opening lines.

    ```{div} cls -> ```{div} with :class: cls (merged with any :class:), and
    [text](label) -> [text](#label) in content-directive titles.
    """
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = FENCE_RE.match(line.rstrip("\n"))
        d = DIRECTIVE_INFO_RE.match(m.group("info").strip()) if m else None
        if d and d.group("name") not in LITERAL_DIRECTIVES:
            line = BARE_LINK_RE.sub(lambda b: bare_link(b, labels), line)
        if not (d and d.group("name") == "div" and d.group("arg")):
            out.append(line)
            i += 1
            continue

        indent = m.group("indent")
        out.append(f"{indent}{m.group('fence')}{{div}}\n")
        classes = d.group("arg").split()
        i += 1
        options: list[str] = []
        while i < len(lines) and (o := OPTION_RE.match(lines[i])):
            if o.group("key") == "class":
                classes += [c for c in o.group("value").split() if c not in classes]
            else:
                options.append(lines[i])
            i += 1
        out.append(f"{indent}:class: {' '.join(classes)}\n")
        out.extend(options)
    return out


def bare_link(m: re.Match[str], labels: set[str]) -> str:
    target = m.group("target")
    if target in labels:
        return f"[{m.group('text')}](#{target})"
    return m.group(0)


def convert_markdown(text: str, src_file: Path, book_root: Path, labels: set[str]) -> str:
    def join_split_role(m: re.Match[str]) -> str:
        if re.search(r"\n\s*\n", m.group("body")):
            return m.group(0)
        return f"{{{m.group('role')}}}`{' '.join(m.group('body').split())}`"

    def doc_role(m: re.Match[str]) -> str:
        target = (m.group("target") or m.group("bare")).strip()
        text = (m.group("text") or "").strip()
        if target.startswith("/"):
            target = os.path.relpath(book_root / target.lstrip("/"), src_file.parent)
        if not target.endswith(".md"):
            target += ".md"
        return f"[{text}]({target})"

    text = SPLIT_ROLE_RE.sub(join_split_role, text)
    text = DOC_ROLE_RE.sub(doc_role, text)
    text = BARE_LINK_RE.sub(lambda m: bare_link(m, labels), text)
    text = STRIKE_RE.sub(lambda m: f"{{del}}`{m.group('text')}`", text)
    text = UNDERLINE_RE.sub(lambda m: f"{{u}}`{m.group('text')}`", text)
    text = FOOTNOTE_DEF_RE.sub(lambda m: m.group("def") + " ", text)
    return text


def report_file(text: str, path: Path, report: Report) -> None:
    lineno = 0
    for is_md, seg in split_segments(text.splitlines(keepends=True)):
        for line in seg:
            lineno += 1
            stripped = line.strip()
            if not is_md:
                m = FENCE_RE.match(line.rstrip("\n"))
                d = DIRECTIVE_INFO_RE.match(m.group("info").strip()) if m else None
                if d and d.group("name") == "flat-table":
                    report.flat_tables += 1
                if d and d.group("name") == "include" and d.group("arg").endswith((".html", ".htm")):
                    report.add(path, lineno, f"includes raw HTML file {d.group('arg')} (dropped in PDF)")
                continue
            if (o := OPTION_RE.match(line)) and o.group("key") == "widths":
                report.add(path, lineno, ":widths: is ignored by JB2 (column widths lost)")
            for h in REPORT_HTML_RE.finditer(stripped):
                report.add(path, lineno, f"raw HTML <{h.group('tag')}> (dropped in PDF)")


def convert_file(
    src: Path, dst: Path, book_root: Path, labels: set[str],
    label_map: dict[str, str], report: Report, dry_run: bool,
) -> bool:
    original = src.read_text(encoding="utf-8")
    lines = convert_directive_headers(original.splitlines(keepends=True), labels)
    parts = []
    for is_md, seg in split_segments(lines):
        chunk = "".join(seg)
        parts.append(convert_markdown(chunk, src, book_root, labels) if is_md else chunk)
    converted = rename_labels("".join(parts), label_map)

    report_file(converted, dst, report)
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(converted, encoding="utf-8")
    return converted != original


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy a JB1 book to a new directory, converted for JB2.")
    parser.add_argument("src", type=Path, help="JB1 book directory, or one .md file")
    parser.add_argument("dst", type=Path, help="Destination directory, or .md file")
    parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing")
    args = parser.parse_args()

    src = args.src.expanduser().resolve()
    dst = args.dst.expanduser().resolve()
    if src == dst or src in dst.parents:
        raise SystemExit("Destination must not be the source or inside it.")

    report = Report()
    changed = total = copied = 0

    if src.is_file():
        if src.suffix != ".md":
            raise SystemExit(f"Not a .md file: {src}")
        root = find_book_root(src)
        if dst.is_dir():
            dst = dst / src.name
        labels = collect_labels(root)
        total = 1
        changed = convert_file(
            src, dst, root, labels, build_label_map(labels, report, root), report, args.dry_run
        )
    elif src.is_dir():
        labels = collect_labels(src)
        label_map = build_label_map(labels, report, src)
        for f in iter_book_files(src):
            out = dst / f.relative_to(src)
            if f.suffix == ".md":
                total += 1
                changed += convert_file(f, out, src, labels, label_map, report, args.dry_run)
            elif not args.dry_run:
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out)
                copied += 1
    else:
        raise SystemExit(f"Source does not exist: {src}")

    print(f"Converted {total} .md file(s) ({changed} changed); copied {copied} other file(s).")
    if report.flat_tables:
        plugin_dir = dst if src.is_dir() else find_book_root(dst)
        if not args.dry_run:
            shutil.copy2(FLAT_TABLE_PLUGIN, plugin_dir / FLAT_TABLE_PLUGIN.name)
        print(f"{report.flat_tables} flat-table(s): copied {FLAT_TABLE_PLUGIN.name} to {plugin_dir}")
    if report.items:
        print(f"\nNeeds attention ({len(report.items)}):")
        for item in report.items:
            print("  " + item)


if __name__ == "__main__":
    main()
