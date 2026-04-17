import xml.etree.ElementTree as ET
import re
import os
from pathlib import PurePosixPath, Path

COMPONENT_ROOTS = {}
COMPONENTS_FILE_SUPPLIED = False
SOURCE_ROOT = None

def die(msg):
    raise SystemExit(msg)

def normalize_component_root_path(path_value):
    p = Path(path_value).expanduser()
    if p.name == "modules":
        return p.resolve()
    modules_child = p / "modules"
    if modules_child.is_dir():
        return modules_child.resolve()
    return p.resolve()

def parse_components_file(path_value):
    path = Path(path_value).expanduser()
    if not path.is_file():
        die(f"Error: components file not found: {path_value}")

    text = path.read_text(encoding="utf-8")

    try:
        import yaml  # type: ignore
    except Exception:
        yaml = None

    data = None
    if yaml is not None:
        data = yaml.safe_load(text)
    else:
        components = {}
        in_components = False
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "components:":
                in_components = True
                continue
            if in_components:
                m = re.match(r'^([A-Za-z0-9_-]+)\s*:\s*(.+?)\s*$', stripped)
                if m:
                    components[m.group(1)] = m.group(2)
                elif not raw_line.startswith((" ", "\t")):
                    break
        data = {"components": components}

    if not isinstance(data, dict):
        die(f"Error: invalid YAML in --components-file: {path_value}")

    components = data.get("components")
    if not isinstance(components, dict):
        die(f"Error: --components-file must contain a top-level 'components' mapping: {path_value}")

    normalized = {}
    for name, root in components.items():
        if not isinstance(name, str) or not isinstance(root, str):
            die(f"Error: invalid component mapping in --components-file: {path_value}")
        normalized[name] = normalize_component_root_path(root)

    return normalized

def split_antora_target(target):
    target = (target or "").strip()
    if not target:
        return None

    fragment = ""
    if "#" in target:
        target, frag = target.split("#", 1)
        fragment = "#" + frag

    normalized_target = target
    if normalized_target.endswith(".xml"):
        normalized_target = normalized_target[:-4] + ".adoc"
    elif normalized_target.endswith(".md"):
        normalized_target = normalized_target[:-3] + ".adoc"

    def looks_like_page_ref(value):
        suffix = PurePosixPath(value).suffix.lower()
        return suffix in ("", ".adoc", ".md", ".xml")

    parts = normalized_target.split(":")
    if len(parts) >= 3 and looks_like_page_ref(parts[-1]):
        component = parts[0]
        module = parts[1]
        page = ":".join(parts[2:])
        return {
            "kind": "cross_component_page",
            "component": component,
            "module": module,
            "page": page,
            "fragment": fragment,
        }

    if len(parts) == 2:
        left, right = parts
        if looks_like_page_ref(right):
            return {
                "kind": "same_component_page",
                "module": left,
                "page": right,
                "fragment": fragment,
            }
        return {
            "kind": "same_component_asset",
            "module": left,
            "asset": right,
            "fragment": fragment,
        }

    return {
        "kind": "path",
        "path": target,
        "fragment": fragment,
    }

def myst_external_doc_role(component, module, page, label=None):
    doc_path = PurePosixPath(module) / PurePosixPath(page).with_suffix("")
    target = doc_path.as_posix()
    if label:
        return f"{{external+{component}:doc}}`{escape_markdown_link_text(label)} <{target}>`"
    return f"{{external+{component}:doc}}`{target}`"

def format_cross_component_xref_for_error(target):
    target = (target or "").strip()
    if target.endswith(".xml"):
        target = target[:-4] + ".adoc"
    elif target.endswith(".md"):
        target = target[:-3] + ".adoc"
    return f"xref:{target}[]"

def require_component_mapping_for_empty_cross_component_xref(target):
    parsed = split_antora_target(target)
    if not parsed or parsed["kind"] != "cross_component_page":
        return

    xref_text = format_cross_component_xref_for_error(target)

    if not COMPONENTS_FILE_SUPPLIED:
        die(
            f"Error: cross-component xref {xref_text} requires --components-file, but it was not supplied."
        )

    if parsed["component"] not in COMPONENT_ROOTS:
        die(
            f"Error: cross-component xref {xref_text} requires a mapping for component '{parsed['component']}' in --components-file, but none was found."
        )

def normalize_docbook_href(target, current_doc):
    target = (target or "").strip()
    if not target:
        return target

    if "://" in target or target.startswith("#"):
        return target

    parsed = split_antora_target(target)
    if not parsed:
        return target

    if parsed["kind"] == "cross_component_page":
        return myst_external_doc_role(parsed["component"], parsed["module"], parsed["page"])

    fragment = parsed.get("fragment", "")
    current_doc = PurePosixPath(current_doc)
    source_root = current_doc.parent.parent

    if parsed["kind"] == "same_component_page":
        page = parsed["page"]
        if page.endswith(".xml"):
            page = page[:-4] + ".md"
        elif page.endswith(".adoc"):
            page = page[:-5] + ".md"
        elif PurePosixPath(page).suffix == "":
            page = page + ".md"
        target_path = source_root / parsed["module"] / page
    else:
        path = parsed.get("path")
        if not path:
            return fragment or target

        if path.endswith(".xml"):
            path = path[:-4] + ".md"
        elif path.endswith(".adoc"):
            path = path[:-5] + ".md"

        p = PurePosixPath(path)
        if p.is_absolute():
            target_path = p
        elif len(p.parts) >= 2 and p.parts[0] != current_doc.parent.name:
            target_path = source_root / p
        else:
            target_path = current_doc.parent / p

    rel = os.path.relpath(str(target_path), start=str(current_doc.parent))
    return rel.replace("\\", "/") + fragment

def fallback_label_from_target(target):
    target = (target or "").strip()
    if not target:
        return ""

    target = target.rsplit("#", 1)[0]
    parsed = split_antora_target(target)
    if not parsed:
        return ""

    if parsed["kind"] == "cross_component_page":
        stem = PurePosixPath(parsed["page"]).stem
        return f"{parsed['component']}:{parsed['module']}:{stem}"

    if parsed["kind"] == "same_component_page":
        page = parsed["page"]
        if page.endswith(".xml"):
            page = page[:-4] + ".md"
        elif page.endswith(".adoc"):
            page = page[:-5] + ".md"
        elif PurePosixPath(page).suffix == "":
            page = page + ".md"
        stem = PurePosixPath(page).stem
        if stem == "index":
            return parsed["module"]
        return f"{parsed['module']}:{stem}"

    normalized = normalize_docbook_href(target, "dummy/current.md")
    return PurePosixPath(normalized).stem

def current_adoc_source_from_current_doc(current_doc):
    if SOURCE_ROOT is None or not current_doc:
        return None

    current_doc = PurePosixPath(current_doc)
    page = current_doc.name
    if page.endswith(".xml"):
        page = page[:-4] + ".adoc"
    elif page.endswith(".md"):
        page = page[:-3] + ".adoc"
    elif page.endswith(".rst"):
        page = page[:-4] + ".adoc"
    elif PurePosixPath(page).suffix == "":
        page = page + ".adoc"

    return SOURCE_ROOT / current_doc.parent.name / "pages" / page


def normalize_page_ref_to_adoc(page):
    if page.endswith(".xml"):
        return page[:-4] + ".adoc"
    if page.endswith(".md"):
        return page[:-3] + ".adoc"
    if page.endswith(".rst"):
        return page[:-4] + ".adoc"
    if PurePosixPath(page).suffix == "":
        return page + ".adoc"
    return page


def adoc_source_from_target(target, current_doc=None):
    target = (target or "").strip()
    if not target:
        return None

    target = target.rsplit("#", 1)[0]
    parsed = split_antora_target(target)
    if not parsed:
        return None

    if parsed["kind"] == "cross_component_page":
        root = COMPONENT_ROOTS.get(parsed["component"])
        if root is None:
            return None
        page = normalize_page_ref_to_adoc(parsed["page"])
        return root / parsed["module"] / "pages" / page

    if SOURCE_ROOT is None:
        return None

    if parsed["kind"] == "same_component_page":
        page = normalize_page_ref_to_adoc(parsed["page"])
        return SOURCE_ROOT / parsed["module"] / "pages" / page

    if parsed["kind"] == "path":
        page = normalize_page_ref_to_adoc(parsed["path"])
        current_src = current_adoc_source_from_current_doc(current_doc)
        if current_src is None:
            return None
        return (current_src.parent / PurePosixPath(page)).resolve()

    return None

def extract_adoc_title(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()

                if not s:
                    continue

                # Skip common AsciiDoc preamble lines before the document title
                if s.startswith("//"):
                    continue
                if s.startswith(":") and s.count(":") >= 2:
                    continue
                if s.startswith("[") and s.endswith("]"):
                    continue
                if s in ("ifdef::env-github[]", "endif::[]", "ifndef::env-github[]"):
                    continue

                if s.startswith("= "):
                    return s[2:].strip()

                # If we hit real content before a title, stop.
                break

    except OSError:
        return None

    return None

def render_xref(elem, current_doc):
    target = (
        elem.attrib.get("linkend", "").strip()
        or elem.attrib.get("endterm", "").strip()
    )
    if not target:
        return ""

    label = render_inline(elem, current_doc).strip()

    auto_label = (
        not label
        or label == target
        or label == os.path.basename(target)
        or label.endswith(".xml")
    )

    parsed = split_antora_target(target)
    if parsed and parsed["kind"] == "cross_component_page":
        if auto_label:
            require_component_mapping_for_empty_cross_component_xref(target)
            src = adoc_source_from_target(target, current_doc)
            if src:
                title = extract_adoc_title(src)
                if title:
                    label = title
                else:
                    label = fallback_label_from_target(target)
            else:
                label = fallback_label_from_target(target)
        return myst_external_doc_role(parsed["component"], parsed["module"], parsed["page"], label or None)

    href = normalize_docbook_href(target, current_doc)

    if auto_label:
        src = adoc_source_from_target(target, current_doc)
        if src:
            title = extract_adoc_title(src)
            if title:
                label = title
            else:
                label = fallback_label_from_target(target)
        else:
            label = fallback_label_from_target(target)

    label = escape_markdown_link_text(label)
    return f"[{label}]({href})"

def render_link(elem, current_doc):
    ulink = elem.find("ulink")
    if ulink is not None:
        url = ulink.attrib.get("url", "").strip()
        parsed = split_antora_target(url)
        label = append_tail_to_link_label(link_label_from_ulink(ulink), elem.tail)

        auto_label = (
            not label
            or label == url
            or label == os.path.basename(url)
            or label.endswith(".xml")
        )

        if parsed and parsed["kind"] == "cross_component_page":
            if auto_label:
                require_component_mapping_for_empty_cross_component_xref(url)
                src = adoc_source_from_target(url, current_doc)
                if src:
                    title = extract_adoc_title(src)
                    if title:
                        label = title
                    else:
                        label = fallback_label_from_target(url)
                else:
                    label = fallback_label_from_target(url)
            return myst_external_doc_role(parsed["component"], parsed["module"], parsed["page"], label or None)

        href = normalize_docbook_href(url, current_doc)

        if auto_label and (":" in url or url.endswith(".xml") or url.endswith(".adoc") or url.endswith(".md")):
            src = adoc_source_from_target(url, current_doc)
            if src:
                title = extract_adoc_title(src)
                if title:
                    label = title
                else:
                    label = fallback_label_from_target(url)
            else:
                label = fallback_label_from_target(url)

        label = escape_markdown_link_text(label)
        return f"[{label or href}]({href})"

    linkend = elem.attrib.get("linkend", "").strip()
    if linkend:
        parsed = split_antora_target(linkend)
        label = render_inline(elem, current_doc).strip()

        auto_label = (
            not label
            or label == linkend
            or label == os.path.basename(linkend)
            or label.endswith(".xml")
        )

        if parsed and parsed["kind"] == "cross_component_page":
            if auto_label:
                require_component_mapping_for_empty_cross_component_xref(linkend)
                src = adoc_source_from_target(linkend, current_doc)
                if src:
                    title = extract_adoc_title(src)
                    if title:
                        label = title
                    else:
                        label = fallback_label_from_target(linkend)
                else:
                    label = fallback_label_from_target(linkend)
            return myst_external_doc_role(parsed["component"], parsed["module"], parsed["page"], label or None)

        href = normalize_docbook_href(linkend, current_doc)

        if auto_label:
            src = adoc_source_from_target(linkend, current_doc)
            if src:
                title = extract_adoc_title(src)
                if title:
                    label = title
                else:
                    label = fallback_label_from_target(linkend)
            else:
                label = fallback_label_from_target(linkend)

        label = escape_markdown_link_text(label)
        return f"[{label}]({href})"

    return ""

def escape_markdown_link_text(text):
    """
    Escape characters that are significant inside Markdown link text.
    """
    if not text:
        return text
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")

def link_label_from_ulink(ulink):
    label = "".join(ulink.itertext()).strip()
    tail = (ulink.tail or "").strip()
    if tail and tail != label:
        label = (label + " " + tail).strip()
    return label

def append_tail_to_link_label(label, tail):
    tail = (tail or "").strip()
    if not tail or tail == label:
        return label
    if tail[0] in ".,;:!?)]":
        return (label + tail).strip()
    return (label + " " + tail).strip()

def render_inline(elem, current_doc):
    out = ""

    if elem.text:
        out += elem.text

    for child in elem:
        if child.tag == "emphasis":
            role = child.attrib.get("role", "")
            inner = render_inline(child, current_doc)
            if role == "strong":
                out += f"**{inner}**"
            else:
                out += f"*{inner}*"

        elif child.tag == "xref":
            out += render_xref(child, current_doc)

        elif child.tag == "ulink":
            url = child.attrib.get("url", "")

            url = normalize_docbook_href(url, current_doc)

            label = render_inline(child, current_doc) or url
            label = escape_markdown_link_text(label)
            out += f"[{label}]({url})"

        elif child.tag == "link":
            out += render_link(child, current_doc)

        else:
            out += render_inline(child, current_doc)

        if child.tail:
            if child.tag == "link" and child.tail.strip():
                pass
            else:
                out += child.tail

    return out.strip() if elem.tag in ("para", "simpara") else out

def render_cell_paragraphs(elem, current_doc):
    paras = []

    for child in elem:
        if child.tag in ("simpara", "para"):
            text = render_inline(child, current_doc)
            if text:
                paras.append(text)

    if paras:
        return paras

    text = render_inline(elem, current_doc)
    return [text] if text else [""]







def render_blocks(elem, current_doc, level=1):
    out = ""
    for child in elem:
        out += convert_element(child, current_doc, level)
    return out

def is_sidebar_subtitle_candidate(elem):
    if elem.tag not in ("para", "simpara"):
        return False

    if (elem.text or "").strip():
        return False

    children = list(elem)
    if len(children) != 1:
        return False

    child = children[0]
    if child.tag != "emphasis":
        return False

    if child.attrib.get("role", "") != "strong":
        return False

    if (child.tail or "").strip():
        return False

    return True

def convert_sidebar(elem, current_doc):
    title_elem = elem.find("title")
    title = render_inline(title_elem, current_doc).strip() if title_elem is not None else "Sidebar"

    subtitle = None
    body_children = []
    seen_title = False
    subtitle_consumed = False

    for child in elem:
        if child.tag == "title" and not seen_title:
            seen_title = True
            continue

        if not subtitle_consumed and is_sidebar_subtitle_candidate(child):
            subtitle = "".join(child.itertext()).strip()
            subtitle_consumed = True
            continue

        body_children.append(child)

    # Antora sidebars map more naturally to a single generic MyST admonition
    # than to a dropdown. If the sidebar only contains a single admonition-like
    # child (common in the generated DocBook), unwrap it so we do not create a
    # nested admonition inside another admonition.
    admonition_like_tags = {"note", "tip", "important", "warning", "caution"}
    if len(body_children) == 1 and body_children[0].tag in admonition_like_tags:
        body_source = list(body_children[0])
    else:
        body_source = body_children

    out = f":::{{admonition}} {title}\n\n"

    if subtitle:
        out += f"**{subtitle}**\n\n"

    for child in body_source:
        rendered = convert_element(child, current_doc)
        if rendered:
            out += rendered

    out += ":::\n\n"
    return out

def convert_blockquote(elem, current_doc):
    parts = []

    attribution = elem.find("attribution")
    if attribution is not None:
        attr_text = render_inline(attribution, current_doc).strip()
        if attr_text:
            parts.append(f"-- {attr_text}")

    for child in elem:
        if child.tag == "attribution":
            continue
        if child.tag in ("para", "simpara"):
            text = render_inline(child, current_doc).strip()
            if text:
                parts.append(text)
        else:
            rendered = convert_element(child, current_doc).rstrip()
            if rendered:
                parts.append(rendered)

    if not parts:
        return ""

    out = ""
    for i, part in enumerate(parts):
        for line in part.splitlines():
            out += f"> {line}\n" if line.strip() else ">\n"
        if i != len(parts) - 1:
            out += ">\n"

    out += "\n"
    return out

def convert_variablelist(elem, current_doc):
    out = ""

    for entry in elem.findall("varlistentry"):
        terms = []
        for term in entry.findall("term"):
            text = render_inline(term, current_doc).strip()
            if text:
                terms.append(text)

        listitem = entry.find("listitem")
        if listitem is None:
            continue

        paras = []
        other_blocks = []

        for child in listitem:
            if child.tag in ("para", "simpara"):
                text = render_inline(child, current_doc).strip()
                if text:
                    paras.append(text)
            else:
                rendered = convert_element(child, current_doc).rstrip()
                if rendered:
                    other_blocks.append(rendered)

        if not terms:
            continue

        for term in terms:
            out += f"{term}\n"

        if paras:
            out += f": {paras[0]}\n"
            for para in paras[1:]:
                out += "\n"
                out += f"  {para}\n"
        else:
            out += ": \n"

        for block in other_blocks:
            out += "\n"
            for line in block.splitlines():
                out += f"  {line}\n"

        out += "\n"

    return out

def convert_anchor(elem):
    anchor_id = elem.attrib.get("id", "").strip()
    if not anchor_id:
        return ""
    return f"({anchor_id})="

def convert_bibliography(elem, current_doc, level=1):
    out = ""

    title = elem.find("title")
    if title is not None:
        out += "#" * level + " " + render_inline(title, current_doc) + "\n\n"

    for child in elem:
        if child.tag == "title":
            continue
        rendered = convert_element(child, current_doc, level + 1)
        if rendered:
            out += rendered

    return out

def convert_bibliomixed(elem, current_doc):
    parts = []

    for child in elem:
        if child.tag == "anchor":
            rendered = convert_anchor(child)
            if rendered:
                parts.append(rendered)
        elif child.tag in ("bibliomisc", "simpara", "para"):
            text = render_inline(child, current_doc).strip()
            if text:
                parts.append(text)
        else:
            rendered = convert_element(child, current_doc).strip()
            if rendered:
                parts.append(rendered)

    if not parts:
        return ""

    return "\n\n".join(parts) + "\n\n"

def convert_bibliodiv(elem, current_doc, level=1):
    out = ""

    title = elem.find("title")
    if title is not None:
        out += "#" * level + " " + render_inline(title, current_doc) + "\n\n"

    for child in elem:
        if child.tag == "title":
            continue
        out += convert_element(child, current_doc, level)

    return out

def normalize_image_path(src, current_doc):
    src = (src or "").strip()
    if not src:
        return src

    if "://" in src or src.startswith("/"):
        return src

    current_doc = PurePosixPath(current_doc)
    source_root = current_doc.parent.parent
    parsed = split_antora_target(src)

    if parsed and parsed["kind"] == "same_component_asset":
        target_path = source_root / parsed["module"] / "images" / PurePosixPath(parsed["asset"])
    else:
        p = PurePosixPath(src)
        if p.parts and p.parts[0] in (".", ".."):
            target_path = current_doc.parent / p
        elif p.parts and p.parts[0] == "images":
            target_path = current_doc.parent / p
        elif len(p.parts) >= 2 and p.parts[1] == "images":
            target_path = source_root / p
        else:
            target_path = current_doc.parent / "images" / p

    rel = os.path.relpath(str(target_path), start=str(current_doc.parent))
    return rel.replace("\\", "/")

def convert_image(elem, current_doc):
    img = elem.find(".//imagedata")
    if img is None:
        return ""

    src = normalize_image_path(img.attrib.get("fileref", ""), current_doc)
    if not src:
        return ""

    title = elem.find(".//title")
    caption = render_inline(title, current_doc).strip() if title is not None else ""

    if caption:
        out = f"```{{figure}} {src}\n"
        out += ":class: antora-self-link\n\n"
        out += caption + "\n"
        out += "```\n\n"
    else:
        out = f"```{{image}} {src}\n"
        out += ":class: antora-self-link\n"
        out += "```\n\n"

    return out

def _first_listitem_text_node(item):
    for child in item:
        if child.tag in ("para", "simpara"):
            return child
    return None

def _convert_list(elem, current_doc, marker_func, indent=0):
    out = ""
    index = 1

    for item in elem.findall("listitem"):
        text_node = _first_listitem_text_node(item)
        marker = marker_func(index)
        line_prefix = " " * indent + marker + " "

        if text_node is not None:
            out += f"{line_prefix}{render_inline(text_node, current_doc)}\n"
        else:
            out += f"{line_prefix}\n"

        for child in item:
            if child is text_node:
                continue

            if child.tag == "itemizedlist":
                out += _convert_list(child, current_doc, lambda _: "-", indent + 2)
            elif child.tag == "orderedlist":
                out += _convert_list(child, current_doc, lambda n: f"{n}.", indent + 2)
            elif child.tag in ("para", "simpara"):
                text = render_inline(child, current_doc).strip()
                if text:
                    out += " " * (indent + 2) + text + "\n"
            else:
                rendered = convert_element(child, current_doc, level=1).rstrip()
                if rendered:
                    for line in rendered.splitlines():
                        out += " " * (indent + 2) + line + "\n"

        index += 1

    return out

def convert_itemizedlist(elem, current_doc):
    return _convert_list(elem, current_doc, lambda _: "-") + "\n"

def convert_orderedlist(elem, current_doc):
    return _convert_list(elem, current_doc, lambda n: f"{n}.") + "\n"



def convert_admonition(elem, current_doc):
    tag_to_name = {
        "note": "note",
        "tip": "tip",
        "important": "important",
        "warning": "warning",
        "caution": "caution",
    }

    admonition_type = tag_to_name.get(elem.tag)
    if not admonition_type:
        return ""

    out = f"```{{{admonition_type}}}\n"

    paras = []
    for child in elem:
        if child.tag in ("simpara", "para"):
            text = render_inline(child, current_doc)
            if text:
                paras.append(text)
        else:
            rendered = convert_element(child, current_doc)
            if rendered.strip():
                paras.append(rendered.strip())

    if paras:
        out += "\n\n".join(paras) + "\n"

    out += "```\n\n"
    return out

def get_rows(elem):
    rows = []
    for row in elem.findall(".//row"):
        cells = row.findall("entry")
        if cells:
            rows.append(cells)
    return rows





def emit_list_table_cell(paras, indent):
    out = ""

    first_lines = paras[0].splitlines() or [""]
    out += f"{indent}- {first_lines[0]}\n"
    for line in first_lines[1:]:
        out += f"{indent}  {line}\n"

    for para in paras[1:]:
        out += f"{indent}  \n"
        for line in (para.splitlines() or [""]):
            out += f"{indent}  {line}\n"

    return out






def header_rows_from_table(elem):
    """
    Return the number of header rows based on the DocBook table structure.

    For now, treat the presence of <thead> as one header row.
    If there is no <thead>, return 0.
    """
    thead = elem.find(".//thead")
    if thead is None:
        return 0

    rows = thead.findall("row")
    return len(rows) if rows else 1


def convert_simple_list_table(elem, current_doc):
    rows = get_rows(elem)
    if not rows:
        return ""

    out = "```{list-table}\n"

    header_rows = header_rows_from_table(elem)
    if header_rows > 0:
        out += f":header-rows: {header_rows}\n"

    out += "\n"

    for row in rows:
        first_paras = render_cell_paragraphs(row[0], current_doc)

        first_lines = first_paras[0].splitlines() or [""]
        out += f"* - {first_lines[0]}\n"
        for line in first_lines[1:]:
            out += f"    {line}\n"

        for para in first_paras[1:]:
            out += "    \n"
            for line in (para.splitlines() or [""]):
                out += f"    {line}\n"

        for cell in row[1:]:
            paras = render_cell_paragraphs(cell, current_doc)
            out += emit_list_table_cell(paras, "  ")

    out += "```\n\n"
    return out

def render_literallayout_text(elem, current_doc):
    out = elem.text or ""

    for child in elem:
        if child.tag == "phrase" and child.attrib.get("role", "") == "line-through":
            out += f"[struck-through: {render_inline(child, current_doc)}]"
        else:
            out += render_inline(child, current_doc)

        if child.tail:
            out += child.tail

    return out




def convert_table(elem, current_doc):
    title = elem.find("title")
    caption = render_inline(title, current_doc) if title is not None else ""

    out = convert_simple_list_table(elem, current_doc)

    if caption:
        return caption + "\n\n" + out
    return out

def convert_element(elem, current_doc, level=1):
    out = ""

    if elem.tag in ("section", "sect1", "sect2"):
        title = elem.find("title")
        if title is not None:
            out += "#" * level + " " + render_inline(title, current_doc) + "\n\n"

        for child in elem:
            if child.tag == "title":
                continue
            out += convert_element(child, current_doc, level + 1)

        return out

    if elem.tag == "formalpara":
        title = elem.find("title")
        if title is not None:
            title_text = render_inline(title, current_doc).strip()
            if title_text:
                out += title_text + "\n\n"

        for child in elem:
            if child.tag == "title":
                continue
            out += convert_element(child, current_doc, level)

        return out

    if elem.tag in ("para", "simpara"):
        literallayout = elem.find("literallayout")
        if literallayout is not None:
            return out + convert_element(literallayout, current_doc, level)

        return out + render_inline(elem, current_doc) + "\n\n"

    if elem.tag in ("table", "informaltable"):
        return out + convert_table(elem, current_doc)

    if elem.tag == "mediaobject":
        return out + convert_image(elem, current_doc)

    if elem.tag == "itemizedlist":
        return out + convert_itemizedlist(elem, current_doc)

    if elem.tag == "orderedlist":
        return out + convert_orderedlist(elem, current_doc)

    if elem.tag == "variablelist":
        return out + convert_variablelist(elem, current_doc)

    if elem.tag == "sidebar":
        return out + convert_sidebar(elem, current_doc)

    if elem.tag == "blockquote":
        return out + convert_blockquote(elem, current_doc)

    if elem.tag == "bibliography":
        return out + convert_bibliography(elem, current_doc, level)

    if elem.tag == "bibliodiv":
        return out + convert_bibliodiv(elem, current_doc, level + 1)

    if elem.tag == "bibliomixed":
        return out + convert_bibliomixed(elem, current_doc)

    if elem.tag == "bibliomisc":
        text = render_inline(elem, current_doc).strip()
        return out + (text + "\n\n" if text else "")

    if elem.tag == "anchor":
        return out + convert_anchor(elem) + "\n\n"

    if elem.tag in ("note", "tip", "important", "warning", "caution"):
        return out + convert_admonition(elem, current_doc)

    if elem.tag == "literallayout":
        text = render_literallayout_text(elem, current_doc)
        role = elem.attrib.get("role", "").strip()

        out += "```{code-block} text\n"
        if role:
            out += f":class: {role}\n"
        out += "\n"
        out += text.rstrip("\n")
        out += "\n```\n\n"
        return out

    for child in elem:
        out += convert_element(child, current_doc, level)

    return out


def convert(doc, current_doc):
    root = ET.parse(doc).getroot()
    out = ""

    title = root.find("title")
    if title is None:
        info = root.find("info")
        if info is not None:
            title = info.find("title")

    if title is not None:
        out += "# " + render_inline(title, current_doc) + "\n\n"

    for child in root:
        if child.tag in ("title", "info"):
            continue
        out += convert_element(child, current_doc, level=2)

    return out

