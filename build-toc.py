#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Set to None to write to stdout; set to a Path(...) later if desired
OUTPUT_PATH = None

# Matches:
# * xref:page.adoc[]
# ** xref:module:page.adoc[Title]
# * xref:component:module:page.adoc#anchor[Title]
NAV_XREF_RE = re.compile(r'^(\*+)\s+xref:([^\[]+)\[[^\]]*\]\s*$')

# Matches a plain list item caption like:
# ** Carl Friedrich Bleeke's (1794) Children
NAV_TEXT_RE = re.compile(r'^(\*+)\s+(.+?)\s*$')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a Sphinx _toc.yml-style listing from a single Antora nav.adoc file."
    )
    parser.add_argument(
        "nav_adoc",
        type=Path,
        help="Path to a single Antora nav.adoc file",
    )
    parser.add_argument(
        "--module-name",
        default=None,
        help="Module name to use for xrefs without an explicit module prefix. "
             "Defaults to the parent directory name of nav.adoc.",
    )
    parser.add_argument(
        "--root",
        default="ROOT/index",
        help="Root document for the generated _toc.yml (default: ROOT/index)",
    )
    return parser.parse_args()


def parse_xref_target(target: str, current_module: str) -> str:
    """
    Convert an Antora xref target into a Sphinx docname-like path.

    Supported forms:
      page.adoc
      module:page.adoc
      component:module:page.adoc

    Any #fragment is ignored for TOC purposes.
    """
    target = target.strip()

    if "#" in target:
        target, _fragment = target.split("#", 1)

    if not target.endswith(".adoc"):
        raise ValueError(f"Unsupported xref target: {target}")

    target = target[:-5]  # strip .adoc
    parts = target.split(":")

    if len(parts) == 1:
        module = current_module
        doc = parts[0]
    elif len(parts) == 2:
        module = parts[0]
        doc = parts[1]
    elif len(parts) == 3:
        _component = parts[0]
        module = parts[1]
        doc = parts[2]
    else:
        raise ValueError(f"Unsupported xref target: {target}")

    return f"{module}/{doc}"


def parse_nav_file(nav_file: Path, current_module: str) -> list[dict]:
    roots: list[dict] = []
    stack: list[tuple[int, dict]] = []

    for raw in nav_file.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            continue
        if stripped.startswith("//"):
            continue

        xref_match = NAV_XREF_RE.match(line)
        text_match = NAV_TEXT_RE.match(line)

        if not text_match:
            continue

        level = len(text_match.group(1))

        while stack and stack[-1][0] >= level:
            stack.pop()

        if xref_match:
            target = xref_match.group(2)
            node = {"file": parse_xref_target(target, current_module)}
        else:
            title = text_match.group(2).strip()
            if not title or title.startswith("xref:"):
                continue
            node = {"caption": title, "entries": []}

        if not stack:
            roots.append(node)
        else:
            stack[-1][1].setdefault("entries", []).append(node)

        stack.append((level, node))

    return roots


def yaml_lines_for_entries(entries: list[dict], indent: int = 0) -> list[str]:
    lines: list[str] = []
    pad = " " * indent

    for entry in entries:
        if "file" in entry:
            lines.append(f"{pad}- file: {entry['file']}")
        elif "caption" in entry:
            lines.append(f"{pad}- caption: {entry['caption']}")
        else:
            continue

        children = entry.get("entries", [])
        if children:
            lines.append(f"{pad}  entries:")
            lines.extend(yaml_lines_for_entries(children, indent + 4))

    return lines


def main() -> None:
    args = parse_args()
    nav_adoc = args.nav_adoc.expanduser().resolve()
    if not nav_adoc.exists():
        raise FileNotFoundError(f"Nav file not found: {nav_adoc}")

    current_module = args.module_name or nav_adoc.parent.name
    entries = parse_nav_file(nav_adoc, current_module)

    # Remove any accidental duplicate of the declared root doc from top-level entries.
    entries = [entry for entry in entries if entry.get("file") != args.root]

    lines = [
        f"root: {args.root}",
        "entries:",
        *yaml_lines_for_entries(entries, indent=2),
        "",
    ]

    output_text = "\n".join(lines)

    if OUTPUT_PATH is None:
        print(output_text, end="")
    else:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(output_text, encoding="utf-8")
        print(f"Wrote {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
