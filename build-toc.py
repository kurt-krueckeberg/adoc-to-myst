#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

NAV_XREF_RE = re.compile(r'^(\*+)\s+xref:([^\[]+)\[([^\]]*)\]\s*$')
NAV_TEXT_RE = re.compile(r'^(\*+)\s+(.+?)\s*$')
TITLE_RE = re.compile(r'^\.([^\s].*)$')


def parse_args():
    p = argparse.ArgumentParser(
        description="Convert Antora nav.adoc to sphinx-external-toc _toc.yml"
    )
    p.add_argument("nav_adoc", type=Path, help="Path to nav.adoc")
    p.add_argument("--module-name", default=None, help="Default Antora module name")
    p.add_argument("--root", default="ROOT/index", help="Root document for _toc.yml")
    return p.parse_args()


def parse_xref_target(target: str, current_module: str) -> str:
    if "#" in target:
        target, _ = target.split("#", 1)
    target = target.strip()
    if not target.endswith(".adoc"):
        raise ValueError(f"Unsupported xref target: {target}")
    target = target[:-5]
    parts = target.split(":")
    if len(parts) == 1:
        module = current_module
        doc = parts[0]
    elif len(parts) == 2:
        module, doc = parts
    elif len(parts) == 3:
        _, module, doc = parts
    else:
        raise ValueError(f"Unsupported xref target: {target}")
    return f"{module}/{doc}"


def yaml_quote(text: str) -> str:
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def parse_nav(nav_file: Path, module: str):
    stack: list[tuple[int, dict]] = []
    roots: list[dict] = []
    pending_title: str | None = None

    for raw_line in nav_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped or stripped.startswith("//"):
            continue

        m_title = TITLE_RE.match(stripped)
        if m_title:
            pending_title = m_title.group(1).strip()
            continue

        m_text = NAV_TEXT_RE.match(line)
        if not m_text:
            continue

        level = len(m_text.group(1))
        body = m_text.group(2).strip()

        if pending_title:
            title_level = max(level - 1, 0)
            while stack and stack[-1][0] >= title_level:
                stack.pop()
            title_node = {"type": "caption", "caption": pending_title, "children": []}
            if not stack:
                roots.append(title_node)
            else:
                stack[-1][1]["children"].append(title_node)
            stack.append((title_level, title_node))
            pending_title = None

        while stack and stack[-1][0] >= level:
            stack.pop()

        m_xref = NAV_XREF_RE.match(line)
        if m_xref:
            node = {
                "type": "file",
                "file": parse_xref_target(m_xref.group(2), module),
                "children": [],
            }
        else:
            node = {
                "type": "caption",
                "caption": body,
                "children": [],
            }

        if not stack:
            roots.append(node)
        else:
            stack[-1][1]["children"].append(node)

        stack.append((level, node))

    return roots


def emit_caption_block(node: dict, indent: int) -> list[str]:
    lines: list[str] = []
    pad = " " * indent
    lines.append(f"{pad}- caption: {yaml_quote(node['caption'])}")
    emit_children_into(lines, node.get("children", []), indent + 2)
    return lines


def emit_file_block(node: dict, indent: int) -> list[str]:
    lines: list[str] = []
    pad = " " * indent
    lines.append(f"{pad}- file: {node['file']}")
    emit_children_into(lines, node.get("children", []), indent + 2)
    return lines


def emit_children_into(lines: list[str], children: list[dict], indent: int) -> None:
    file_children = [c for c in children if c["type"] == "file"]
    caption_children = [c for c in children if c["type"] == "caption"]

    if file_children:
        pad = " " * indent
        lines.append(f"{pad}entries:")
        for child in file_children:
            lines.extend(emit_file_block(child, indent + 2))

    if caption_children:
        pad = " " * indent
        lines.append(f"{pad}subtrees:")
        for child in caption_children:
            lines.extend(emit_caption_block(child, indent + 2))


def emit_toc(tree: list[dict], root: str) -> str:
    lines = [f"root: {root}"]
    emit_children_into(lines, tree, 0)
    return "\n".join(lines) + "\n"


def main():
    args = parse_args()
    nav = args.nav_adoc.resolve()
    module = args.module_name or nav.parent.name
    tree = parse_nav(nav, module)
    print(emit_toc(tree, args.root), end="")


if __name__ == "__main__":
    main()
