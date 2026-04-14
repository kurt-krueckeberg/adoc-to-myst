#!/usr/bin/env python3

from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

NAV_XREF_RE = re.compile(r'^(\*+)\s+xref:([^\[]+)\[[^\]]*\]\s*$')
NAV_TEXT_RE = re.compile(r'^(\*+)\s+(.+?)\s*$')


def parse_args():
    p = argparse.ArgumentParser(
        description="Convert Antora nav.adoc → sphinx-external-toc _toc.yml"
    )
    p.add_argument("nav_adoc", type=Path, help="Path to Antora nav.adoc")
    p.add_argument(
        "--module-name",
        default=None,
        help="Override module name; defaults to parent directory name of nav.adoc",
    )
    p.add_argument(
        "--root",
        default="ROOT/index",
        help=(
            "Root document. May be a Sphinx docname (e.g. family-church-records/understand) "
            "or a filesystem path (e.g. ~/gen/m/family-church-records/understand.md)."
        ),
    )
    p.add_argument(
        "--module-dir",
        default="~/gen/m",
        help=(
            "Filesystem base directory that contains module content directories. "
            "Used only when --root is given as a filesystem path."
        ),
    )
    return p.parse_args()


def strip_known_suffix(path_text: str) -> str:
    for suffix in (".adoc", ".md", ".rst"):
        if path_text.endswith(suffix):
            return path_text[:-len(suffix)]
    return path_text

def split_root(tree, root_docname):
    """
    Return a tree whose body does not redundantly include the root doc.

    If the first top-level file node matches root_docname, then its children
    become the first body content, followed by the remaining top-level nodes.
    """
    if not tree:
        return []

    first = tree[0]
    if first["type"] == "file" and first["file"] == root_docname:
        return first["children"] + tree[1:]

    return tree

def normalize_root(root_value: str, module_dir: str) -> str:
    """
    Convert --root into a Sphinx docname.

    Accepted forms:
      family-church-records/understand
      family-church-records/understand.md
      ~/gen/m/family-church-records/understand
      ~/gen/m/family-church-records/understand.md

    Returns:
      family-church-records/understand
    """
    root_value = root_value.strip()
    module_base = Path(module_dir).expanduser().resolve()

    # First treat obvious docname forms as docnames, not paths.
    if not root_value.startswith("/") and not root_value.startswith("~"):
        root_docname = strip_known_suffix(root_value).lstrip("/")
        return root_docname

    # Otherwise treat as filesystem path.
    root_path = Path(root_value).expanduser().resolve()
    root_no_suffix = Path(strip_known_suffix(str(root_path)))

    try:
        rel = root_no_suffix.relative_to(module_base)
    except ValueError as exc:
        raise SystemExit(
            f"--root path '{root_value}' is not under module base '{module_base}'.\n"
            f"Either pass a Sphinx docname such as 'family-church-records/understand'\n"
            f"or set --module-dir appropriately."
        ) from exc

    return rel.as_posix()


def parse_xref_target(target, current_module):
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


def parse_nav(nav_file, module):
    stack = []
    roots = []

    for line in nav_file.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("//"):
            continue

        m_text = NAV_TEXT_RE.match(line)
        if not m_text:
            continue

        level = len(m_text.group(1))
        body = m_text.group(2).strip()

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


def emit_nodes(nodes, indent=0):
    lines = []
    pad = " " * indent

    for n in nodes:
        if n["type"] == "file":
            lines.append(f"{pad}- file: {n['file']}")

            if n["children"]:
                if any(c["type"] == "caption" for c in n["children"]):
                    lines.append(f"{pad}  subtrees:")
                    lines.extend(emit_mixed_as_subtrees(n["children"], indent + 4))
                else:
                    lines.append(f"{pad}  entries:")
                    lines.extend(emit_nodes(n["children"], indent + 4))

        elif n["type"] == "caption":
            if not n["children"]:
                continue

            lines.append(f"{pad}- caption: {n['caption']}")
            lines.append(f"{pad}  entries:")
            lines.extend(emit_nodes(n["children"], indent + 4))

    return lines


def emit_mixed_as_subtrees(nodes, indent):
    lines = []
    pad = " " * indent

    file_children = [n for n in nodes if n["type"] == "file"]
    caption_children = [n for n in nodes if n["type"] == "caption"]

    if file_children:
        lines.append(f"{pad}- entries:")
        lines.extend(emit_nodes(file_children, indent + 2))

    for n in caption_children:
        if not n["children"]:
            continue

        lines.append(f"{pad}- caption: {n['caption']}")
        lines.append(f"{pad}  entries:")
        lines.extend(emit_nodes(n["children"], indent + 4))

    return lines


def emit_subtrees(nodes, indent):
    lines = []
    pad = " " * indent

    for n in nodes:
        if n["type"] == "caption":
            if not n["children"]:
                continue

            lines.append(f"{pad}- caption: {n['caption']}")
            lines.append(f"{pad}  entries:")
            lines.extend(emit_nodes(n["children"], indent + 4))

        elif n["type"] == "file":
            lines.append(f"{pad}- entries:")
            lines.append(f"{pad}    - file: {n['file']}")

            if n["children"]:
                if any(c["type"] == "caption" for c in n["children"]):
                    lines.append(f"{pad}      subtrees:")
                    lines.extend(emit_mixed_as_subtrees(n["children"], indent + 8))
                else:
                    lines.append(f"{pad}      entries:")
                    lines.extend(emit_nodes(n["children"], indent + 8))

    return lines


def main():
    args = parse_args()
    nav = args.nav_adoc.expanduser().resolve()
    module = args.module_name or nav.parent.name
    root_docname = normalize_root(args.root, args.module_dir)

    tree = parse_nav(nav, module)
    tree = split_root(tree, root_docname)

    if any(n["type"] == "caption" for n in tree):
        body_key = "subtrees"
        body = emit_subtrees(tree, 2)
    else:
        body_key = "entries"
        body = emit_nodes(tree, 2)

    out = [f"root: {root_docname}", f"{body_key}:"]
    out.extend(body)
    out.append("")

    print("\n".join(out))


if __name__ == "__main__":
    main()
