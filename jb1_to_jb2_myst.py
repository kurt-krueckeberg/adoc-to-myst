#!/usr/bin/env python3
"""
Convert JB1/Sphinx MyST Markdown files to JB2/MyST Markdown.

This converter is intentionally narrow and conservative.

It does:
  1. Convert selected sphinx_design block directives to raw HTML wrappers.
  2. Convert selected sphinx_design inline roles to HTML spans.
  3. Rewrite LOCAL Markdown file links:
       [text](doc1.md)     -> [text](doc1/)
       [text](../x/y.md)   -> [text](../x/y/)
     when --folder-links is used.
  4. Rewrite LOCAL Markdown file links:
       [text](doc1.md)     -> [text](doc1.html)
     when --html-links is used.

It does NOT:
  - convert [text](#anchor) into {ref}`text <anchor>`;
  - rewrite external URLs such as https://...;
  - rewrite URLs inside raw citation text;
  - rewrite links inside fenced code/directive blocks.

For your JB2 projects with `folders: true`, use:

  python3 jb1_to_jb2_myst.py SOURCE_DIR DEST_DIR --recursive --folder-links
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
from pathlib import Path


DIRECTIVE_START_RE = re.compile(
    r"^(?P<fence>`{3,}|~{3,})\{(?P<name>[A-Za-z0-9_-]+)\}\s*$"
)
OPTION_RE = re.compile(r"^:(?P<key>[A-Za-z0-9_-]+):\s*(?P<value>.*)$")
INLINE_ROLE_RE = re.compile(r"\{(?P<role>[A-Za-z0-9_-]+)\}`(?P<body>[^`]*)`")

# Deliberately strict:
# - target must end in .md, optionally followed by #anchor;
# - target may not contain spaces, tabs, newlines, parentheses, or ':'.
# This prevents corrupting external URLs and citation prose.
LOCAL_MD_LINK_RE = re.compile(
    r"\[(?P<label>[^\]]+)\]"
    r"\("
    r"(?P<target>(?![A-Za-z][A-Za-z0-9+.-]*:)[^)\s:]+\.md)"
    r"(?P<anchor>#[^)\s]+)?"
    r"(?P<title>\s+\"[^\"]*\")?"
    r"\)"
)

BARE_INTERNAL_LINK_RE = re.compile(
    r"\[(?P<label>[^\]]+)\]\((?P<target>image[A-Za-z0-9_.:-]*)\)"    
)

FENCE_START_RE = re.compile(r"^(?P<fence>`{3,}|~{3,})(?:\{[^}]*\}|[A-Za-z0-9_-]+)?\s*$")

SPHINX_DESIGN_BLOCK_DIRECTIVES = {
    "grid",
    "grid-item",
    "grid-item-card",
    "card",
    "card-carousel",
    "dropdown",
    "tab-set",
    "tab-item",
}

SPHINX_DESIGN_INLINE_ROLES = {
    "bdg",
    "bdg-primary",
    "bdg-secondary",
    "bdg-success",
    "bdg-info",
    "bdg-warning",
    "bdg-danger",
    "btn",
    "btn-primary",
    "btn-secondary",
    "btn-success",
    "btn-info",
    "btn-warning",
    "btn-danger",
}

REF_ROLE_RE = re.compile(
    r"\{ref\}`(?P<label>.*?)\s*<(?P<target>[A-Za-z0-9_.:-]+)>`",
    re.DOTALL,
)

LABEL_WITH_BLANK_RE = re.compile(
    r"^(\([A-Za-z0-9_.:-]+\)=)\n+",
    re.MULTILINE,
)


def convert_ref_roles_to_markdown_links(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        label = " ".join(m.group("label").split())
        target = m.group("target")
        return f"[{label}](#{target})"

    return REF_ROLE_RE.sub(repl, text)


def attach_myst_labels(text: str) -> str:
    return LABEL_WITH_BLANK_RE.sub(r"\1\n", text)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Conservatively convert JB1/Sphinx MyST Markdown to JB2/MyST Markdown."
    )
    parser.add_argument("src", type=Path, help="Source .md file or source directory")
    parser.add_argument("dst", type=Path, nargs="?", help="Destination file or directory. Omit with --in-place.")
    parser.add_argument("--recursive", action="store_true", help="Recursively process a directory tree")
    parser.add_argument("--in-place", action="store_true", help="Modify source files in place")
    parser.add_argument("--backup", action="store_true", help="When using --in-place, write .bak files first")
    parser.add_argument("--folder-links", action="store_true", help="Rewrite local file.md links to file/ links")
    parser.add_argument("--html-links", action="store_true", help="Rewrite local file.md links to file.html links")
    parser.add_argument("--keep-sphinx-design", action="store_true", help="Do not rewrite sphinx_design directives")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be changed without writing files")
    return parser.parse_args()


def split_directive_header(line: str) -> tuple[str, str] | None:
    m = DIRECTIVE_START_RE.match(line)
    if not m:
        return None
    return m.group("fence"), m.group("name")


def find_closing_fence(lines: list[str], start_index: int, fence: str) -> int | None:
    fence_char = fence[0]
    min_len = len(fence)
    closing_re = re.compile(rf"^{re.escape(fence_char)}{{{min_len},}}\s*$")
    for i in range(start_index + 1, len(lines)):
        if closing_re.match(lines[i]):
            return i
    return None


def strip_directive_options(block_lines: list[str]) -> tuple[dict[str, str], list[str]]:
    options: dict[str, str] = {}
    body_start = 0

    while body_start < len(block_lines):
        line = block_lines[body_start]
        if not line.strip():
            body_start += 1
            continue
        m = OPTION_RE.match(line)
        if not m:
            break
        options[m.group("key")] = m.group("value")
        body_start += 1

    if body_start < len(block_lines) and not block_lines[body_start].strip():
        body_start += 1

    return options, block_lines[body_start:]


def markdown_to_plainish_html(text: str) -> str:
    text = html.escape(text.strip())
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def block_to_html_directive(name: str, block_lines: list[str]) -> list[str]:
    options, body = strip_directive_options(block_lines)

    classes = ["jb1-sphinx-design", f"jb1-sd-{name}"]
    for opt_name in ("class-card", "class-item", "class-container", "class"):
        if opt_name in options:
            classes.extend(options[opt_name].split())

    title = ""
    if name in {"card", "grid-item-card", "dropdown", "tab-item"} and body:
        title = body[0].strip()
        body = body[1:]
        if body and not body[0].strip():
            body = body[1:]

    class_attr = html.escape(" ".join(classes), quote=True)

    out: list[str] = []
    out.append("```{raw} html")
    out.append(f'<div class="{class_attr}">')
    if title:
        out.append(f'<div class="jb1-sd-title">{markdown_to_plainish_html(title)}</div>')
    out.append("```")
    out.append("")
    out.extend(body)
    if body and body[-1].strip():
        out.append("")
    out.append("```{raw} html")
    out.append("</div>")
    out.append("```")
    return out


def convert_sphinx_design_blocks(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0

    while i < len(lines):
        parsed = split_directive_header(lines[i])
        if not parsed:
            out.append(lines[i])
            i += 1
            continue

        fence, name = parsed
        close = find_closing_fence(lines, i, fence)
        if close is None:
            out.append(lines[i])
            i += 1
            continue

        if name not in SPHINX_DESIGN_BLOCK_DIRECTIVES:
            out.extend(lines[i:close + 1])
            i = close + 1
            continue

        block_body = lines[i + 1:close]
        out.extend(block_to_html_directive(name, block_body))
        i = close + 1

    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def convert_inline_roles_outside_fences(text: str) -> str:
    def convert_segment(segment: str) -> str:
        def repl(m: re.Match[str]) -> str:
            role = m.group("role")
            body = m.group("body")
            if role not in SPHINX_DESIGN_INLINE_ROLES:
                return m.group(0)
            css_class = html.escape(role.replace("_", "-"), quote=True)
            return f'<span class="{css_class}">{html.escape(body)}</span>'

        return INLINE_ROLE_RE.sub(repl, segment)

    return transform_outside_fences(text, convert_segment)


def is_local_md_target(target: str) -> bool:
    if not target.endswith(".md"):
        return False
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        return False
    if any(ch.isspace() for ch in target):
        return False
    return True


def rewrite_markdown_links_outside_fences(text: str, *, folder_links: bool, html_links: bool) -> str:
    if not folder_links and not html_links:
        return text

    def convert_segment(segment: str) -> str:
        def repl(m: re.Match[str]) -> str:
            label = m.group("label")
            target = m.group("target")
            anchor = m.group("anchor") or ""
            title = m.group("title") or ""

            if not is_local_md_target(target):
                return m.group(0)

            if target.endswith("index.md"):
                if folder_links:
                    new_target = target[:-len("index.md")]
                else:
                    new_target = target[:-3] + ".html"
            elif folder_links:
                new_target = target[:-3] + "/"
            else:
                new_target = target[:-3] + ".html"

            return f"[{label}]({new_target}{anchor}{title})"

        return LOCAL_MD_LINK_RE.sub(repl, segment)

    return transform_outside_fences(text, convert_segment)


def transform_outside_fences(text: str, transform) -> str:
    """
    Apply transform() only outside fenced blocks.

    This prevents accidental edits inside code blocks, image directives,
    raw HTML blocks, notes, and other fenced MyST directives.
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []

    in_fence = False
    fence_char = ""
    fence_len = 0
    buffer: list[str] = []

    def flush_buffer() -> None:
        nonlocal buffer
        if buffer:
            out.append(transform("".join(buffer)))
            buffer = []

    for line in lines:
        stripped = line.rstrip("\n\r")
        if not in_fence:
            m = FENCE_START_RE.match(stripped)
            if m:
                flush_buffer()
                fence = m.group("fence")
                in_fence = True
                fence_char = fence[0]
                fence_len = len(fence)
                out.append(line)
            else:
                buffer.append(line)
        else:
            out.append(line)
            closing_re = re.compile(rf"^{re.escape(fence_char)}{{{fence_len},}}\s*$")
            if closing_re.match(stripped):
                in_fence = False
                fence_char = ""
                fence_len = 0

    flush_buffer()
    return "".join(out)

def convert_bare_image_anchor_links(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        label = m.group("label")
        target = m.group("target")
        return f"[{label}](#{target})"

    return BARE_IMAGE_ANCHOR_LINK_RE.sub(repl, text)

def convert_text(text: str, args: argparse.Namespace) -> str:
    converted = text

    converted = convert_ref_roles_to_markdown_links(converted)
    converted = attach_myst_labels(converted)
    converted = convert_bare_image_anchor_links(converted)

    if not args.keep_sphinx_design:
        converted = convert_sphinx_design_blocks(converted)
        converted = convert_inline_roles_outside_fences(converted)

    converted = rewrite_markdown_links_outside_fences(
        converted,
        folder_links=args.folder_links,
        html_links=args.html_links,
    )

    return converted

def iter_markdown_files(src: Path, recursive: bool) -> list[Path]:
    if src.is_file():
        if src.suffix.lower() != ".md":
            raise SystemExit(f"Source file is not a .md file: {src}")
        return [src]

    if not src.is_dir():
        raise SystemExit(f"Source does not exist: {src}")

    pattern = "**/*.md" if recursive else "*.md"
    return sorted(src.glob(pattern))


def destination_for(src_file: Path, src_root: Path, dst_root: Path | None, in_place: bool) -> Path:
    if in_place:
        return src_file
    if dst_root is None:
        raise SystemExit("Destination is required unless --in-place is used.")
    if src_root.is_file():
        return dst_root
    return dst_root / src_file.relative_to(src_root)


def convert_file(src_file: Path, dst_file: Path, args: argparse.Namespace) -> bool:
    original = src_file.read_text(encoding="utf-8")
    converted = convert_text(original, args)

    changed = original != converted

    if args.dry_run:
        print(("CHANGED " if changed else "unchanged ") + str(src_file))
        return changed

    if not changed and src_file == dst_file:
        return False

    if args.in_place and args.backup and changed:
        backup = src_file.with_suffix(src_file.suffix + ".bak")
        if not backup.exists():
            shutil.copy2(src_file, backup)

    dst_file.parent.mkdir(parents=True, exist_ok=True)
    dst_file.write_text(converted, encoding="utf-8")
    return changed


def main() -> None:
    args = parse_args()

    if args.folder_links and args.html_links:
        raise SystemExit("Use either --folder-links or --html-links, not both.")

    if not args.in_place and args.dst is None:
        raise SystemExit("Provide a destination path, or use --in-place.")

    src = args.src.expanduser().resolve()
    dst = args.dst.expanduser().resolve() if args.dst else None

    files = iter_markdown_files(src, args.recursive)
    changed_count = 0

    for src_file in files:
        dst_file = destination_for(src_file, src, dst, args.in_place)
        if convert_file(src_file, dst_file, args):
            changed_count += 1

    print(f"Processed {len(files)} file(s); changed {changed_count} file(s).")


if __name__ == "__main__":
    main()
