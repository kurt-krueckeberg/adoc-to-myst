import xml.etree.ElementTree as ET
import re
import os
from decimal import Decimal, InvalidOperation
from math import gcd
from functools import reduce
from pathlib import PurePosixPath, Path

def normalize_docbook_href(target, current_doc):
    target = (target or "").strip()
    if not target:
        return target

    if "://" in target or target.startswith("#"):
        return target

    fragment = ""
    if "#" in target:
        target, frag = target.split("#", 1)
        fragment = "#" + frag

    if target.endswith(".xml"):
        target = target[:-4] + ".md"
    elif target.endswith(".adoc"):
        target = target[:-5] + ".md"

    current_doc = PurePosixPath(current_doc)
    source_root = current_doc.parent.parent

    if ":" in target:
        module, page = target.split(":", 1)
        target_path = source_root / module / page
    else:
        p = PurePosixPath(target)

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
    target = target.replace("\\", "/")

    if ":" in target:
        module, page = target.split(":", 1)
        page = normalize_docbook_href(page, "dummy.md")
        stem = PurePosixPath(page).stem

        if stem == "index":
            return module
        return f"{module}:{stem}"

    target = normalize_docbook_href(target, "dummy.md")
    return PurePosixPath(target).stem

SOURCE_ROOT = None

def adoc_source_from_target(target):
    target = (target or "").strip()
    if not target or SOURCE_ROOT is None:
        return None

    target = target.rsplit("#", 1)[0]

    if target.endswith(".xml"):
        target = target[:-4] + ".adoc"
    elif target.endswith(".md"):
        target = target[:-3] + ".adoc"

    if ":" in target:
        module, page = target.split(":", 1)
        return SOURCE_ROOT / module / "pages" / page

    return None

def extract_adoc_title(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if s.startswith("="):
                    return s.lstrip("=").strip()
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

    href = normalize_docbook_href(target, current_doc)

    label = render_inline(elem, current_doc).strip()
    if not label:
        src = adoc_source_from_target(target)
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
    # External link wrapped in <link><ulink ...>...</ulink></link>
    ulink = elem.find("ulink")
    if ulink is not None:
        url = ulink.attrib.get("url", "")

        url = normalize_docbook_href(url, current_doc)

        label = "".join(ulink.itertext()).strip()
        label = escape_markdown_link_text(label)

        return f"[{label or url}]({url})"

    # Internal DocBook link: <link linkend="...">label</link>
    linkend = elem.attrib.get("linkend", "").strip()
    if linkend:
        href = normalize_docbook_href(linkend, current_doc)

        label = render_inline(elem, current_doc).strip()
        if not label:
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
    title = render_inline(title_elem, current_doc).strip() if title_elem is not None else ""

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

    out = f"::::{{sidebar}} {title}\n"
    if subtitle:
        out += f":subtitle: {subtitle}\n"
    out += "\n"

    for child in body_children:
        rendered = convert_element(child, current_doc)
        if rendered:
            out += rendered

    out += "::::\n\n"
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

def normalize_image_path(src):
    src = (src or "").strip()
    if not src:
        return src

    # Leave absolute URLs and already-qualified paths alone.
    if "://" in src or src.startswith("/") or "/" in src:
        return src

    return f"images/{src}"

def convert_image(elem, current_doc):
    img = elem.find(".//imagedata")
    if img is None:
        return ""

    src = normalize_image_path(img.attrib.get("fileref", ""))
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

def cell_has_span(entry):
    return (
        "namest" in entry.attrib
        or "nameend" in entry.attrib
        or "morerows" in entry.attrib
    )

def table_has_spans(elem):
    for entry in elem.findall(".//entry"):
        if cell_has_span(entry):
            return True
    return False

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

def parse_colwidth_value(colwidth):
    """
    Parse DocBook colwidth values like:
      17*
      72.25*
      42.5*
    Return Decimal or None.
    """
    if not colwidth:
        return None

    value = colwidth.strip()

    m = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\*', value)
    if m:
        try:
            return Decimal(m.group(1))
        except InvalidOperation:
            return None

    m = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)', value)
    if m:
        try:
            return Decimal(m.group(1))
        except InvalidOperation:
            return None

    return None

def decimals_to_scaled_ints(values):
    """
    Convert Decimals to integers by scaling to the maximum number
    of decimal places present.
    Example: [42.5, 85, 297.5] -> [425, 850, 2975]
    """
    exponents = [abs(v.as_tuple().exponent) for v in values]
    scale = max(exponents) if exponents else 0
    factor = Decimal(10) ** scale
    return [int(v * factor) for v in values]

def reduce_ratio(ints):
    """
    Reduce a list of integers to lowest whole-number ratio.
    Example: [425, 850, 2975] -> [1, 2, 7]
    """
    g = reduce(gcd, ints)
    if g == 0:
        return ints
    return [n // g for n in ints]

def widths_from_colspecs(elem, prefer_ratio=True):
    """
    Read <colspec colwidth="..."> and return a MyST widths string.

    If prefer_ratio is True, return a simple whole-number ratio by
    normalizing against the smallest column width and rounding.

    Examples:
      8.3333*,25*,16.6666*,8.3333*,25*,16.6668* -> '1 3 2 1 3 2'
      85*,42.5*,42.5*,42.5* -> '2 1 1 1'

    Otherwise return integer percentages.
    """
    tgroup = elem.find("tgroup")
    if tgroup is None:
        return None

    colspecs = tgroup.findall("colspec")
    if not colspecs:
        return None

    raw = []
    for colspec in colspecs:
        w = parse_colwidth_value(colspec.attrib.get("colwidth", ""))
        if w is None:
            return None
        raw.append(w)

    if not raw:
        return None

    if prefer_ratio:
        smallest = min(raw)
        if smallest == 0:
            return None

        ratio = []
        for w in raw:
            n = int((w / smallest).to_integral_value(rounding="ROUND_HALF_UP"))
            ratio.append(max(1, n))

        return " ".join(str(x) for x in ratio)

    total = sum(raw)
    if total == 0:
        return None

    exact = [(w * Decimal("100")) / total for w in raw]
    rounded = [int(x.to_integral_value(rounding="ROUND_HALF_UP")) for x in exact]

    diff = 100 - sum(rounded)
    if diff != 0:
        rounded[-1] += diff

    rounded = [max(1, x) for x in rounded]
    return " ".join(str(x) for x in rounded)

def emit_list_table_cell(paras, indent):
    out = f"{indent}- {paras[0]}\n"
    for para in paras[1:]:
        out += f"{indent}  \n"
        out += f"{indent}  {para}\n"
    return out

def emit_flat_table_first_cell(paras):
    out = ""
    first_lines = paras[0].splitlines() or [""]
    out += f"   * - {first_lines[0]}\n"
    for line in first_lines[1:]:
        out += f"       {line}\n"

    for para in paras[1:]:
        out += "       \n"
        for line in para.splitlines():
            out += f"       {line}\n"

    return out

def emit_flat_table_cell(cell, current_doc, indent):
    attrs = []

    if "morerows" in cell.attrib:
        try:
            attrs.append(f":rspan: {int(cell.attrib['morerows'])}")
        except ValueError:
            pass

    if "namest" in cell.attrib and "nameend" in cell.attrib:
        attrs.append(":cspan: 1")

    paras = render_cell_paragraphs(cell, current_doc)
    out = ""

    first_lines = paras[0].splitlines() or [""]

    out += f"{indent}- {first_lines[0]}\n"
    for line in first_lines[1:]:
        out += f"{indent}  {line}\n"

    for para in paras[1:]:
        out += f"{indent}  \n"
        for line in para.splitlines():
            out += f"{indent}  {line}\n"

    for attr in attrs:
        out += f"{indent}  {attr}\n"

    return out

def parse_docbook_with_table_widths(doc):
    """
    Parse the DocBook file while preserving table-width processing instructions
    like <?dbhtml table-width="100%"?> by attaching the discovered width to
    the currently open table/informaltable element as a synthetic attribute
    named _table_width.
    """
    root = None
    table_stack = []

    for event, node in ET.iterparse(doc, events=("start", "end", "pi")):
        if event == "start":
            if root is None:
                root = node

            if node.tag in ("table", "informaltable"):
                table_stack.append(node)

        elif event == "pi":
            text = getattr(node, "text", "") or ""
            m = re.search(r'table-width="([^"]+)"', text)
            if m and table_stack:
                table_stack[-1].attrib["_table_width"] = m.group(1)

        elif event == "end":
            if node.tag in ("table", "informaltable"):
                if table_stack and table_stack[-1] is node:
                    table_stack.pop()

    return root

def table_width_from_pi(elem):
    """
    Return a table width such as '100%' if one was attached during parsing.
    """
    return elem.attrib.get("_table_width")

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

    out = "::: {list-table}\n"

    table_width = table_width_from_pi(elem)
    if table_width:
        out += f":width: {table_width}\n"

    widths = widths_from_colspecs(elem, prefer_ratio=True)
    if widths:
        out += f":widths: {widths}\n"

    header_rows = header_rows_from_table(elem)
    if header_rows > 0:
        out += f":header-rows: {header_rows}\n"

    out += "\n"

    for row in rows:
        first_paras = render_cell_paragraphs(row[0], current_doc)
        out += f"* - {first_paras[0]}\n"
        for para in first_paras[1:]:
            out += f"    \n"
            out += f"    {para}\n"

        for cell in row[1:]:
            paras = render_cell_paragraphs(cell, current_doc)
            out += emit_list_table_cell(paras, "  ")

    out += ":::\n\n"
    return out

def entry_children(elem):
    return [child for child in elem if isinstance(child.tag, str)]

def is_empty_entry(entry):
    if (entry.text or "").strip():
        return False
    for child in entry:
        if isinstance(child.tag, str):
            return False
        if (child.tail or "").strip():
            return False
    return True

def entry_is_image_only(entry):
    children = entry_children(entry)
    if not children:
        return False
    return all(child.tag in ("mediaobject", "figure", "informalfigure") for child in children)

def entry_is_literal_only(entry):
    children = entry_children(entry)
    if not children:
        return False
    return all(child.tag == "literallayout" for child in children)

def table_rows_direct(elem):
    rows = []
    for row in elem.findall(".//row"):
        cells = row.findall("entry")
        if cells:
            rows.append(cells)
    return rows

def is_image_layout_table(elem):
    if header_rows_from_table(elem) != 0:
        return False
    if table_has_spans(elem):
        return False

    rows = table_rows_direct(elem)
    if not rows:
        return False

    saw_nonempty = False
    for row in rows:
        for cell in row:
            if is_empty_entry(cell):
                continue
            saw_nonempty = True
            if not entry_is_image_only(cell):
                return False

    return saw_nonempty

def is_literal_parallel_table(elem):
    if table_has_spans(elem):
        return False

    header_rows = header_rows_from_table(elem)
    rows = table_rows_direct(elem)
    if not rows:
        return False

    if header_rows == 0:
        body_rows = rows
    elif header_rows == 1:
        if len(rows) < 2:
            return False
        body_rows = rows[1:]
    else:
        return False

    if len(body_rows) != 1:
        return False

    row = body_rows[0]
    if len(row) != 2:
        return False

    return entry_is_literal_only(row[0]) and entry_is_literal_only(row[1])

def render_entry_blocks(entry, current_doc, level=1):
    out = ""
    for child in entry:
        if isinstance(child.tag, str):
            out += convert_element(child, current_doc, level)
    return out.strip()

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

def convert_image_layout_table(elem, current_doc):
    rows = table_rows_direct(elem)
    if not rows:
        return ""

    out = "::::{grid} 1 1 2 2\n"
    out += ":gutter: 2\n\n"

    for row in rows:
        for cell in row:
            if is_empty_entry(cell):
                continue

            content = render_entry_blocks(cell, current_doc).strip()
            if not content:
                continue

            out += ":::{grid-item}\n\n"
            out += content + "\n\n"
            out += ":::\n\n"

    out += "::::\n\n"
    return out

def convert_literal_parallel_table(elem, current_doc):
    rows = table_rows_direct(elem)
    if not rows:
        return ""

    header_rows = header_rows_from_table(elem)
    if header_rows == 0:
        body_rows = rows
    elif header_rows == 1:
        if len(rows) < 2:
            return ""
        body_rows = rows[1:]
    else:
        return ""

    if len(body_rows) != 1:
        return ""

    row = body_rows[0]
    if len(row) != 2:
        return ""

    left_cell, right_cell = row

    left = render_entry_blocks(left_cell, current_doc).strip()
    right = render_entry_blocks(right_cell, current_doc).strip()

    out = "::::{grid} 1 1 2 2\n"
    out += ":gutter: 2\n\n"

    out += ":::{grid-item}\n\n"
    if left:
        out += left + "\n\n"
    out += ":::\n\n"

    out += ":::{grid-item}\n\n"
    if right:
        out += right + "\n\n"
    out += ":::\n\n"

    out += "::::\n\n"
    return out

def convert_table(elem, current_doc):
    title = elem.find("title")
    caption = render_inline(title, current_doc) if title is not None else ""

    if is_image_layout_table(elem):
        out = convert_image_layout_table(elem, current_doc)
    elif is_literal_parallel_table(elem):
        out = convert_literal_parallel_table(elem, current_doc)
    elif table_has_spans(elem):
        out = convert_flat_table(elem, current_doc)
    else:
        out = convert_simple_list_table(elem, current_doc)

    if caption:
        return caption + "\n\n" + out
    return out

def convert_flat_table(elem, current_doc):
    rows = get_rows(elem)
    if not rows:
        return ""

    out = "```{eval-rst}\n"
    out += ".. flat-table::\n"
    out += "   :header-rows: 1\n\n"

    for row in rows:
        first_paras = render_cell_paragraphs(row[0], current_doc)
        out += emit_flat_table_first_cell(first_paras)

        for cell in row[1:]:
            out += emit_flat_table_cell(cell, current_doc, "     ")

    out += "```\n\n"
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
    root = parse_docbook_with_table_widths(doc)
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

if __name__ == "__main__":
    import sys

    SOURCE_ROOT = Path(sys.argv[3])

    print(convert(sys.argv[1], sys.argv[2]))
