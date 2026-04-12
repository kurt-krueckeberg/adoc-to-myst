#!/usr/bin/env python3

from __future__ import annotations

import re
import sys
from pathlib import Path


ANTORA_YML = Path.home() / "antora-nla" / "antora.yml"
# Set to None to write to stdout; set to a Path(...) later if desired
OUTPUT_PATH = None

NAV_LINE_RE = re.compile(r'^(\*+)\s+xref:([^\[]+)\[\]\s*$')
NAV_REF_RE = re.compile(r'^(?:(?P<module>[^:]+):)?(?P<doc>.+?)\.adoc$')


def read_antora_nav_list(antora_yml: Path) -> list[str]:
    nav_files: list[str] = []
    in_nav = False

    for raw in antora_yml.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()

        if not in_nav:
            if re.match(r'^\s*nav:\s*$', line):
                in_nav = True
            continue

        stripped = line.strip()

        if not stripped:
            continue

        if stripped.startswith("#"):
            continue

        if re.match(r'^\S.*:\s*$', line):
            break

        m = re.match(r'^\s*-\s+(.+?)\s*$', line)
        if m:
            value = m.group(1).strip()
            if not value.startswith("#"):
                nav_files.append(value)

    return nav_files


def parse_xref_target(target: str, current_module: str) -> str:
    target = target.strip()
    m = NAV_REF_RE.match(target)
    if not m:
        raise ValueError(f"Unsupported xref target: {target}")

    explicit_module = m.group("module")
    doc = m.group("doc")
    module = explicit_module if explicit_module else current_module

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
        if stripped.startswith("."):
            continue

        m = NAV_LINE_RE.match(line)
        if not m:
            continue

        level = len(m.group(1))
        target = m.group(2)

        node = {"file": parse_xref_target(target, current_module)}

        while stack and stack[-1][0] >= level:
            stack.pop()

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
        lines.append(f"{pad}- file: {entry['file']}")
        children = entry.get("entries", [])
        if children:
            lines.append(f"{pad}  entries:")
            lines.extend(yaml_lines_for_entries(children, indent + 4))

    return lines


def main() -> None:
    nav_list = read_antora_nav_list(ANTORA_YML)

    all_entries: list[dict] = []

    for rel_nav in nav_list:
        nav_path = (Path.home() / "antora-nla" / rel_nav).resolve()
        if not nav_path.exists():
            raise FileNotFoundError(f"Nav file not found: {nav_path}")

        current_module = nav_path.parent.name
        entries = parse_nav_file(nav_path, current_module)
        all_entries.extend(entries)

    lines = [
        "root: ROOT/index",
        "entries:",
        *yaml_lines_for_entries(all_entries, indent=2),
        "",
    ]

    output_text = "\n".join(lines)

    if OUTPUT_PATH is None:
        print(output_text, end="")
    else:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(output_text, encoding="utf-8")
        print(f"Wrote {OUTPUT_PATH}", file=sys.stderr)

    print(f"Read {len(nav_list)} nav files", file=sys.stderr)


if __name__ == "__main__":
    main()
