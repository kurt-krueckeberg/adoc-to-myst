import xml.etree.ElementTree as ET
import re
from decimal import Decimal, InvalidOperation
from math import gcd
from functools import reduce

def render_link(elem):
    # External link wrapped in <link><ulink ...>...</ulink></link>
    ulink = elem.find("ulink")
    if ulink is not None:
        url = ulink.attrib.get("url", "")
        if url.endswith(".xml"):
            url = url[:-4] + ".md"

        label = "".join(ulink.itertext()).strip()
        label = escape_markdown_link_text(label)

        return f"[{label or url}]({url})"

    # Internal DocBook link: <link linkend="...">label</link>
    linkend = elem.attrib.get("linkend", "").strip()
    if linkend:
        label = render_inline(elem).strip() or linkend
        label = escape_markdown_link_text(label)
        return f"[{label}](#{linkend})"

    return ""

def escape_markdown_link_text(text):
    """
    Escape characters that are significant inside Markdown link text.
    """
    if not text:
        return text
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")

def render_inline(elem):
    out = ""

    if elem.text:
        out += elem.text

    for child in elem:
        if child.tag == "emphasis":
            role = child.attrib.get("role", "")
            inner = render_inline(child)
            if role == "strong":
                out += f"**{inner}**"
            else:
                out += f"*{inner}*"

        elif child.tag == "xref":
            target = child.attrib.get("linkend", "")
            out += f"{{ref}}`{target}`"

        elif child.tag == "ulink":
            url = child.attrib.get("url", "")

            if url.endswith(".xml"):
                url = url[:-4] + ".md"

            label = render_inline(child) or url
            label = escape_markdown_link_text(label)
            out += f"[{label}]({url})"
        
        elif child.tag == "link":
            out += render_link(child)

        else:
            out += render_inline(child)

        if child.tail:
            out += child.tail

    return out.strip() if elem.tag in ("para", "simpara") else out


def render_cell_paragraphs(elem):
    paras = []

    for child in elem:
        if child.tag in ("simpara", "para"):
            text = render_inline(child)
            if text:
                paras.append(text)

    if paras:
        return paras

    text = render_inline(elem)
    return [text] if text else [""]

def render_blocks(elem, level=1):
    out = ""
    for child in elem:
        out += convert_element(child, level)
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

def convert_sidebar(elem):
    title_elem = elem.find("title")
    title = render_inline(title_elem).strip() if title_elem is not None else ""

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
        rendered = convert_element(child)
        if rendered:
            out += rendered

    out += "::::\n\n"
    return out

def convert_blockquote(elem):
    parts = []

    attribution = elem.find("attribution")
    if attribution is not None:
        attr_text = render_inline(attribution).strip()
        if attr_text:
            parts.append(f"-- {attr_text}")

    for child in elem:
        if child.tag == "attribution":
            continue
        if child.tag in ("para", "simpara"):
            text = render_inline(child).strip()
            if text:
                parts.append(text)
        else:
            rendered = convert_element(child).rstrip()
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

def convert_variablelist(elem):
    out = ""

    for entry in elem.findall("varlistentry"):
        terms = []
        for term in entry.findall("term"):
            text = render_inline(term).strip()
            if text:
                terms.append(text)

        listitem = entry.find("listitem")
        if listitem is None:
            continue

        paras = []
        other_blocks = []

        for child in listitem:
            if child.tag in ("para", "simpara"):
                text = render_inline(child).strip()
                if text:
                    paras.append(text)
            else:
                rendered = convert_element(child).rstrip()
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

def convert_bibliography(elem, level=1):
    out = ""

    title = elem.find("title")
    if title is not None:
        out += "#" * level + " " + render_inline(title) + "\n\n"

    for child in elem:
        if child.tag == "title":
            continue
        rendered = convert_element(child, level + 1)
        if rendered:
            out += rendered

    return out

def convert_bibliomixed(elem):
    parts = []

    for child in elem:
        if child.tag == "anchor":
            rendered = convert_anchor(child)
            if rendered:
                parts.append(rendered)
        elif child.tag in ("bibliomisc", "simpara", "para"):
            text = render_inline(child).strip()
            if text:
                parts.append(text)
        else:
            rendered = convert_element(child).strip()
            if rendered:
                parts.append(rendered)

    if not parts:
        return ""

    return "\n\n".join(parts) + "\n\n"

def convert_bibliodiv(elem, level=1):
    out = ""

    title = elem.find("title")
    if title is not None:
        out += "#" * level + " " + render_inline(title) + "\n\n"

    for child in elem:
        if child.tag == "title":
            continue
        out += convert_element(child, level)

    return out

def convert_image(elem):
    img = elem.find(".//imagedata")
    if img is None:
        return ""

    src = img.attrib.get("fileref", "")
    title = elem.find(".//title")
    caption = render_inline(title) if title is not None else ""

    out = f"```{{figure}} {src}\n"
    if caption:
        out += caption + "\n"
    out += "```\n\n"
    return out

def _first_listitem_text_node(item):
    for child in item:
        if child.tag in ("para", "simpara"):
            return child
    return None

def _convert_list(elem, marker_func, indent=0):
    out = ""
    index = 1

    for item in elem.findall("listitem"):
        text_node = _first_listitem_text_node(item)
        marker = marker_func(index)
        line_prefix = " " * indent + marker + " "

        if text_node is not None:
            out += f"{line_prefix}{render_inline(text_node)}\n"
        else:
            out += f"{line_prefix}\n"

        for child in item:
            if child is text_node:
                continue

            if child.tag == "itemizedlist":
                out += _convert_list(child, lambda _: "-", indent + 2)
            elif child.tag == "orderedlist":
                out += _convert_list(child, lambda n: f"{n}.", indent + 2)
            elif child.tag in ("para", "simpara"):
                # extra paragraphs within the same list item
                text = render_inline(child).strip()
                if text:
                    out += " " * (indent + 2) + text + "\n"
            else:
                rendered = convert_element(child, level=1).rstrip()
                if rendered:
                    for line in rendered.splitlines():
                        out += " " * (indent + 2) + line + "\n"

        index += 1

    return out

def convert_itemizedlist(elem):
    return _convert_list(elem, lambda _: "-") + "\n"

def convert_orderedlist(elem):
    return _convert_list(elem, lambda n: f"{n}.") + "\n"

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

def convert_admonition(elem):
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
            text = render_inline(child)
            if text:
                paras.append(text)
        else:
            rendered = convert_element(child)
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

def emit_flat_table_cell(cell, indent):
    attrs = []

    if "morerows" in cell.attrib:
        try:
            attrs.append(f":rspan: {int(cell.attrib['morerows'])}")
        except ValueError:
            pass

    if "namest" in cell.attrib and "nameend" in cell.attrib:
        attrs.append(":cspan: 1")

    paras = render_cell_paragraphs(cell)
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

def convert_simple_list_table(elem):
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
        first_paras = render_cell_paragraphs(row[0])
        out += f"* - {first_paras[0]}\n"
        for para in first_paras[1:]:
            out += f"    \n"
            out += f"    {para}\n"

        for cell in row[1:]:
            paras = render_cell_paragraphs(cell)
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

def render_entry_blocks(entry, level=1):
    out = ""
    for child in entry:
        if isinstance(child.tag, str):
            out += convert_element(child, level)
    return out.strip()


def convert_image_layout_table(elem):
    rows = table_rows_direct(elem)
    if not rows:
        return ""

    out = "::::{grid} 1 1 2 2\n"
    out += ":gutter: 2\n\n"

    for row in rows:
        for cell in row:
            if is_empty_entry(cell):
                continue

            content = render_entry_blocks(cell).strip()
            if not content:
                continue

            out += ":::{grid-item}\n\n"
            out += content + "\n\n"
            out += ":::\n\n"

    out += "::::\n\n"
    return out

def convert_literal_parallel_table(elem):
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

    left = render_entry_blocks(left_cell).strip()
    right = render_entry_blocks(right_cell).strip()

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

def convert_table(elem):
    title = elem.find("title")
    caption = render_inline(title) if title is not None else ""

    if is_image_layout_table(elem):
        out = convert_image_layout_table(elem)
    elif is_literal_parallel_table(elem):
        out = convert_literal_parallel_table(elem)
    elif table_has_spans(elem):
        out = convert_flat_table(elem)
    else:
        out = convert_simple_list_table(elem)

    if caption:
        return caption + "\n\n" + out
    return out

def convert_flat_table(elem):
    rows = get_rows(elem)
    if not rows:
        return ""

    out = "```{eval-rst}\n"
    out += ".. flat-table::\n"
    out += "   :header-rows: 1\n\n"

    for row in rows:
        first_paras = render_cell_paragraphs(row[0])
        out += emit_flat_table_first_cell(first_paras)

        for cell in row[1:]:
            out += emit_flat_table_cell(cell, "     ")

    out += "```\n\n"
    return out

def convert_element(elem, level=1):
    out = ""

    if elem.tag in ("section", "sect1", "sect2"):
        title = elem.find("title")
        if title is not None:
            out += "#" * level + " " + render_inline(title) + "\n\n"

        for child in elem:
            if child.tag == "title":
                continue
            out += convert_element(child, level + 1)

        return out

    if elem.tag == "formalpara":
        title = elem.find("title")
        if title is not None:
            title_text = render_inline(title).strip()
            if title_text:
                out += title_text + "\n\n"

        for child in elem:
            if child.tag == "title":
                continue
            out += convert_element(child, level)

        return out

    if elem.tag in ("para", "simpara"):
        literallayout = elem.find("literallayout")
        if literallayout is not None:
            # Preserve block semantics instead of flattening through render_inline()
            return out + convert_element(literallayout, level)

        return out + render_inline(elem) + "\n\n"

    if elem.tag in ("table", "informaltable"):
        return out + convert_table(elem)

    if elem.tag == "mediaobject":
        return out + convert_image(elem)

    if elem.tag == "itemizedlist":
        return out + convert_itemizedlist(elem)

    if elem.tag == "orderedlist":
        return out + convert_orderedlist(elem)

    if elem.tag == "variablelist":
        return out + convert_variablelist(elem)

    if elem.tag == "sidebar":
        return out + convert_sidebar(elem)

    if elem.tag == "blockquote":
        return out + convert_blockquote(elem)

    if elem.tag == "bibliography":
        return out + convert_bibliography(elem, level)

    if elem.tag == "bibliodiv":
        return out + convert_bibliodiv(elem, level + 1)

    if elem.tag == "bibliomixed":
        return out + convert_bibliomixed(elem)

    if elem.tag == "bibliomisc":
        text = render_inline(elem).strip()
        return out + (text + "\n\n" if text else "")

    if elem.tag == "anchor":
        return out + convert_anchor(elem) + "\n\n"

    if elem.tag in ("note", "tip", "important", "warning", "caution"):
        return out + convert_admonition(elem)

    if elem.tag == "literallayout":
        text = elem.text or ""
        role = elem.attrib.get("role", "").strip()

        out += "```{code-block} text\n"
        if role:
            out += f":class: {role}\n"
        out += "\n"
        out += text.rstrip("\n")
        out += "\n```\n\n"
        return out

    for child in elem:
        out += convert_element(child, level)

    return out

def convert(doc):
    root = parse_docbook_with_table_widths(doc) 
    out = ""

    title = root.find("title")
    if title is None:
        info = root.find("info")
        if info is not None:
            title = info.find("title")

    if title is not None:
        out += "# " + render_inline(title) + "\n\n"

    for child in root:
        if child.tag in ("title", "info"):
            continue
        out += convert_element(child, level=2)

    return out


if __name__ == "__main__":
    import sys
    print(convert(sys.argv[1]))
