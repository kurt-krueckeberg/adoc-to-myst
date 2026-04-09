#!/usr/bin/env python3

import argparse
import yaml
from pathlib import Path
import re

import sys

def main():
    parser = argparse.ArgumentParser(
        description="Convert Antora navigation (antora.yml + nav.adoc) to Sphinx _toc.yml"
    )
    parser.add_argument("--antora", required=True, help="Path to antora.yml")
    parser.add_argument("--modules-dir", required=True, help="Path to Antora modules directory")
    parser.add_argument("-o", "--output", required=True, help="Output _toc.yml file")

    if len(sys.argv) == 1:
        parser.print_usage()
        sys.exit(1)

    args = parser.parse_args()

    antora = load_antora_yaml(args.antora)
    modules_dir = Path(args.modules_dir)

    toc = build_toc(antora, modules_dir)

    with open(args.output, "w", encoding="utf-8") as f:
        yaml.dump(toc, f, sort_keys=False)

    print(f"✔ Wrote {args.output}")

def load_antora_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_nav_adoc(path):
    """
    Parse Antora nav.adoc into a tree structure.

    Supports:
    * xref:file.adoc[Label]
    * Nested lists via indentation
    """
    lines = path.read_text(encoding="utf-8").splitlines()

    root = []
    stack = [(0, root)]

    for line in lines:
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip())
        content = line.strip()

        if not content.startswith("*"):
            continue

        content = content.lstrip("* ").strip()

        # Parse xref
        m = re.match(r"xref:([^\[]+)\[([^\]]*)\]", content)
        if not m:
            continue

        target, label = m.groups()
        label = label.strip() or None

        node = {
            "file": normalize_target(target),
        }

        if label:
            node["title"] = label

        # Find parent by indentation
        while stack and indent <= stack[-1][0]:
            stack.pop()

        parent = stack[-1][1]
        parent.append(node)

        node["entries"] = []
        stack.append((indent, node["entries"]))

    return root


def normalize_target(target):
    """
    Convert Antora xref target → Sphinx file path
    """
    target = target.strip()

    # Remove fragment
    if "#" in target:
        target = target.split("#")[0]

    # Remove .adoc
    if target.endswith(".adoc"):
        target = target[:-5]

    # Remove module prefix like module:page.adoc
    parts = target.split(":")
    if len(parts) > 1:
        target = parts[-1]

    return target


def clean_tree(entries):
    """
    Remove empty entries arrays and normalize structure
    """
    cleaned = []
    for e in entries:
        node = {k: v for k, v in e.items() if k != "entries"}

        children = clean_tree(e.get("entries", []))
        if children:
            node["entries"] = children

        cleaned.append(node)

    return cleaned


def build_toc(antora, modules_dir):
    toc = {
        "root": "ROOT/index",
        "subtrees": []
    }

    nav_files = antora.get("nav", [])

    subtree = {
        "caption": antora.get("title", "Documentation"),
        "entries": []
    }

    for nav_file in nav_files:
        nav_path = modules_dir / nav_file
        entries = parse_nav_adoc(nav_path)
        subtree["entries"].extend(entries)

    subtree["entries"] = clean_tree(subtree["entries"])
    toc["subtrees"].append(subtree)

    return toc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--antora", required=True)
    parser.add_argument("--modules-dir", required=True)
    parser.add_argument("-o", "--output", required=True)

    args = parser.parse_args()

    antora = load_antora_yaml(args.antora)
    modules_dir = Path(args.modules_dir)

    toc = build_toc(antora, modules_dir)

    with open(args.output, "w", encoding="utf-8") as f:
        yaml.dump(toc, f, sort_keys=False)

    print(f"✔ Wrote {args.output}")


if __name__ == "__main__":
    main()
