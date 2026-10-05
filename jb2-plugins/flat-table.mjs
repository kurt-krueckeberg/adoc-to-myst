// mystmd plugin: linuxdoc-compatible {flat-table} directive with {rspan} and
// {cspan} roles, so JB1 flat-tables with row/column spans work in JB2 and
// export to Typst/PDF.
//
// Like linuxdoc, {cspan}`N` / {rspan}`N` mean N *additional* columns / rows,
// and cells covered by a span are simply left out of the list.
//
//   ```{flat-table} Optional caption
//   :header-rows: 1
//   :class: no-zebra-rowspan-table
//
//   * - {cspan}`1` Spans two columns
//     - {rspan}`1` Spans two rows
//   * - a
//     - b
//   ```
//
// Enable in myst.yml:
//   project:
//     plugins:
//       - flat-table.mjs

const spanRole = (kind) => ({
  name: kind,
  body: { type: String, required: true },
  run(data) {
    return [{ type: 'flatTableSpan', kind, value: Number(data.body) }];
  },
});

// Remove span markers from a cell, recording them in `spans`. A marker may
// still be an unresolved mystRole node, depending on processing order.
function takeSpans(node, spans) {
  if (!node.children) return;
  node.children = node.children.filter((child) => {
    if (child.type === 'flatTableSpan') {
      spans[child.kind] = child.value;
      return false;
    }
    if (child.type === 'mystRole' && (child.name === 'rspan' || child.name === 'cspan')) {
      spans[child.name] = Number(child.value);
      return false;
    }
    takeSpans(child, spans);
    return true;
  });
  // Trim the space the role leaves behind.
  const first = node.children[0];
  if (first?.type === 'text') first.value = first.value.replace(/^\s+/, '');
}

// Warn when rows don't come out the same width once spans are applied;
// that means a span or a cell is missing and later cells have shifted.
function checkGrid(rows, vfile, node) {
  const covered = []; // covered[r] = Set of columns filled by rowspans from above
  const widths = rows.map((row, r) => {
    const taken = covered[r] ?? new Set();
    let col = 0;
    for (const cell of row.children) {
      while (taken.has(col)) col += 1;
      const colspan = cell.colspan ?? 1;
      for (let dr = 1; dr < (cell.rowspan ?? 1); dr += 1) {
        covered[r + dr] ??= new Set();
        for (let c = col; c < col + colspan; c += 1) covered[r + dr].add(c);
      }
      col += colspan;
    }
    while (taken.has(col)) col += 1;
    return col;
  });
  if (new Set(widths).size > 1) {
    vfile?.message?.(
      `flat-table rows have different widths after spans (${widths.join(', ')})`,
      node,
    );
  }
  if (covered.length > rows.length) {
    vfile?.message?.('flat-table {rspan} extends past the last row', node);
  }
}

const flatTable = {
  name: 'flat-table',
  arg: { type: 'myst' },
  options: {
    'header-rows': { type: Number },
    'stub-columns': { type: Number },
    widths: { type: String }, // accepted for compatibility; not applied
    'fill-cells': { type: Boolean }, // accepted for compatibility; not applied
    class: { type: String },
    name: { type: String },
    label: { type: String },
  },
  body: { type: 'myst', required: true },
  run(data, vfile) {
    const list = data.body?.find((n) => n.type === 'list');
    if (!list) {
      vfile?.message?.('flat-table body must be a bullet list of rows', data.node);
      return [];
    }
    const headerRows = data.options?.['header-rows'] ?? 0;
    const stubColumns = data.options?.['stub-columns'] ?? 0;

    const rows = list.children.map((rowItem, r) => {
      const cellList = rowItem.children?.find((n) => n.type === 'list');
      let col = 0;
      const cells = (cellList?.children ?? []).map((cellItem) => {
        const spans = {};
        takeSpans(cellItem, spans);
        const cell = { type: 'tableCell', children: cellItem.children ?? [] };
        if (r < headerRows || col < stubColumns) cell.header = true;
        if (spans.rspan > 0) cell.rowspan = spans.rspan + 1;
        if (spans.cspan > 0) cell.colspan = spans.cspan + 1;
        col += cell.colspan ?? 1;
        return cell;
      });
      return { type: 'tableRow', children: cells };
    });
    checkGrid(rows, vfile, data.node);

    const children = [];
    if (data.arg) children.push({ type: 'caption', children: [{ type: 'paragraph', children: data.arg }] });
    children.push({ type: 'table', children: rows });
    const container = { type: 'container', kind: 'table', children };
    const label = data.options?.label ?? data.options?.name;
    if (label) container.label = label;
    if (data.options?.class) container.class = data.options.class;
    return [container];
  },
};

export default {
  name: 'flat-table',
  directives: [flatTable],
  roles: [spanRole('rspan'), spanRole('cspan')],
};
