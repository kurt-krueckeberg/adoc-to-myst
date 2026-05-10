#!/usr/bin/env python3
"""
Convert JB1/Sphinx MyST Markdown files to JB2/MyST Markdown.

Main purpose:
- keep ordinary MyST Markdown unchanged;
- replace common sphinx_design directives, which JB2 generally will not process;
- optionally rewrite local .md links to folder-style .html links;
- process one file or an entire directory tree.

This is intentionally conservative. It does not try to re-author your prose.

Usage examples:

  # Convert one file in place, keeping a .bak copy
  python jb1_to_jb2_myst.py page.md --in-place --backup

  # Convert a directory tree to another directory
  python jb1_to_jb2_myst.py ~/sphinx-nla ~/jupyter-nla --recursive

  # Convert and rewrite local markdown links to folder URLs
  python jb1_to_jb2_myst.py ~/sphinx-nla ~/jupyter-nla --recursive --folder-links
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
from pathlib import Path

DIRECTIVE_START_RE = re.compile(r"^(?P<fence>`{3,}|~{3,})\{(?P<name>[A-Za-z0-9_-]+)\}\s*$")
FENCE_ONLY_RE = re.compile(r"^(?P<fence>`{3,}|~{3,})\s*$")
OPTION_RE = re.compile(r"^:(?P<key>[A-Za-z0-9_-]+):\s*(?P<value>.*)$")
INLINE_ROLE_RE = re.compile(r"\{(?P<role>[A-Za-z0-9_-]+)\}`(?P<body>[^`]*)`")
MD_LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<target>[^)]+\.md(?P<anchor>#[^)]+)?)(?P<title>\s+\"[^\"]*\")?\)")

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
    "bdg", "bdg-primary", "bdg-secondary", "bdg-success", "bdg-info", "bdg-warning", "bdg-danger",
    "btn", "btn-primary", "btn-secondary", "btn-success", "btn-info", "btn-warning", "btn-danger",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert JB1/Sphinx MyST Markdown to JB2-compatible MyST Markdown."
    )
    parser.add_argument("src", type=Path, help="Source .md file or source directory")
    parser.add_argument("dst", type=Path, nargs="?", help="Destination file or directory. Omit with --in-place.")
    parser.add_argument("--recursive", action="store_true", help="Recursively process a directory tree")
    parser.add_argument("--in-place", action="store_true", help="Modify source files in place")
    parser.add_argument("--backup", action="store_true", help="When using --in-place, write .bak files first")
    parser.add_argument("--folder-links", action="store_true", help="Rewrite local file.md links to file/index.html-style links")
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
    # A closing fence must be at least as long and use the same character.
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

    # Remove only one blank separator after options.
    if body_start < len(block_lines) and not block_lines[body_start].strip():
        body_start += 1

    return options, block_lines[body_start:]


def markdown_to_plainish_html(text: str) -> str:
    """Small, safe conversion for titles/labels used inside generated HTML."""
    text = html.escape(text.strip())
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def block_to_html_directive(name: str, block_lines: list[str]) -> list[str]:
    options, body = strip_directive_options(block_lines)
    classes = ["jb1-sphinx-design", f"jb1-sd-{name}"]
    if "class-card" in options:
        classes.extend(options["class-card"].split())
    if "class-item" in options:
        classes.extend(options["class-item"].split())
    if "class-container" in options:
        classes.extend(options["class-container"].split())

    title = ""
    if name in {"card", "grid-item-card", "dropdown", "tab-item"} and body:
        # sphinx_design commonly treats the first body line in cards/dropdowns/tabs as a title.
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


def convert_inline_roles(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        role = m.group("role")
        body = m.group("body")
        if role not in SPHINX_DESIGN_INLINE_ROLES:
            return m.group(0)
        css_class = html.escape(role.replace("_", "-"), quote=True)
        return f'<span class="{css_class}">{html.escape(body)}</span>'

    return INLINE_ROLE_RE.sub(repl, text)


def rewrite_markdown_links(text: str, *, folder_links: bool, html_links: bool) -> str:
    if not folder_links and not html_links:
        return text

    def repl(m: re.Match[str]) -> str:
        label = m.group("label")
        target = m.group("target")
        title = m.group("title") or ""

        # Leave absolute URLs and special schemes alone.
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
            return m.group(0)

        anchor = ""
        if "#" in target:
            target, anchor = target.split("#", 1)
            anchor = "#" + anchor

        if target.endswith("index.md"):
            new_target = target[:-len("index.md")] if folder_links else target[:-3] + ".html"
        elif folder_links:
            new_target = target[:-3] + "/"
        else:
            new_target = target[:-3] + ".html"

        return f"[{label}]({new_target}{anchor}{title})"

    return MD_LINK_RE.sub(repl, text)


def convert_text(text: str, args: argparse.Namespace) -> str:
    converted = text
    if not args.keep_sphinx_design:
        converted = convert_sphinx_design_blocks(converted)
        converted = convert_inline_roles(converted)
    converted = rewrite_markdown_links(
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
