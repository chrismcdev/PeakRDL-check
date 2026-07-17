/* PeakRDL-check viewer.
 *
 * Deliberately framework-free: one file, no build step, fully offline.
 * Invariants:
 *  - No API response ever contains the full hierarchy; everything is paginated.
 *  - Browser state is proportional to what the user has actually expanded or
 *    requested (rows array = visible/expanded entries only).
 *  - All untrusted text (names, paths, descriptions) is set via textContent.
 */
"use strict";

const ROW_H = 28;
const SVG_NS = "http://www.w3.org/2000/svg";
const MAX_DIAGRAM_BITS = 256;
const ADDRESS_MAP_LIMIT = 200;
const FIELD_COLORS = [
  "var(--field-1)", "var(--field-2)", "var(--field-3)", "var(--field-4)",
  "var(--field-5)", "var(--field-6)", "var(--field-7)", "var(--field-8)",
];
const perf = { queries: [] };
window.__peakrdlCheckPerf = perf;

async function api(url) {
  const t0 = performance.now();
  const res = await fetch(url);
  const ms = performance.now() - t0;
  perf.queries.push({ url, ms: Math.round(ms * 100) / 100, ok: res.ok });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { msg = (await res.json()).error || msg; } catch (e) { /* ignore */ }
    throw new Error(msg);
  }
  return res.json();
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function svgEl(tag, attrs = {}, text) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs))
    if (value !== null && value !== undefined) e.setAttribute(name, String(value));
  if (text !== undefined) e.textContent = text;
  return e;
}

function fmtAddr(hex) { return "0x" + (hex || "0"); }

// ---------------------------------------------------------------------------
// Virtualized list over a flat row model
// ---------------------------------------------------------------------------
const listEl = document.getElementById("list");
const spacer = listEl.querySelector(".spacer");
const state = {
  mode: "overview",       // overview | tree | results | changes
  rows: [],               // flat visible rows
  selected: -1,
  severityFilter: null,   // set of enabled classifications (changes mode)
  resultsQuery: null,
  detailPath: null,
};

// ---------------------------------------------------------------------------
// Resizable split view
// ---------------------------------------------------------------------------
const mainEl = document.querySelector("main");
const leftEl = document.getElementById("left");
const splitterEl = document.getElementById("splitter");
const PANEL_WIDTH_KEY = "peakrdl-check:left-panel-ratio";
const DEFAULT_PANEL_RATIO = 0.46;
const MIN_LEFT_WIDTH = 280;
const MIN_DETAIL_WIDTH = 320;

function panelWidthBounds() {
  const mainWidth = mainEl.getBoundingClientRect().width;
  const max = Math.max(MIN_LEFT_WIDTH, mainWidth - MIN_DETAIL_WIDTH - splitterEl.offsetWidth);
  return { mainWidth, min: MIN_LEFT_WIDTH, max };
}

function setLeftPanelWidth(width, persist = false) {
  const bounds = panelWidthBounds();
  const clamped = Math.max(bounds.min, Math.min(bounds.max, width));
  leftEl.style.width = clamped + "px";
  const percent = bounds.mainWidth ? Math.round(clamped / bounds.mainWidth * 100) : 46;
  splitterEl.setAttribute("aria-valuenow", String(percent));
  splitterEl.setAttribute("aria-valuetext", `${percent}% navigation panel`);
  if (persist && bounds.mainWidth) {
    try { localStorage.setItem(PANEL_WIDTH_KEY, String(clamped / bounds.mainWidth)); }
    catch (error) { /* storage may be unavailable */ }
  }
}

function restoreLeftPanelWidth() {
  let ratio = DEFAULT_PANEL_RATIO;
  try {
    const saved = Number(localStorage.getItem(PANEL_WIDTH_KEY));
    if (Number.isFinite(saved) && saved > 0) ratio = saved;
  } catch (error) { /* storage may be unavailable */ }
  setLeftPanelWidth(panelWidthBounds().mainWidth * ratio);
}

let panelDrag = null;
splitterEl.addEventListener("pointerdown", event => {
  if (event.button !== 0) return;
  event.preventDefault();
  panelDrag = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startWidth: leftEl.getBoundingClientRect().width,
  };
  splitterEl.setPointerCapture(event.pointerId);
  document.body.classList.add("resizing");
});
splitterEl.addEventListener("pointermove", event => {
  if (panelDrag?.pointerId === event.pointerId)
    setLeftPanelWidth(panelDrag.startWidth + event.clientX - panelDrag.startX);
});
function finishPanelResize(event) {
  if (panelDrag?.pointerId !== event.pointerId) return;
  if (splitterEl.hasPointerCapture(event.pointerId)) splitterEl.releasePointerCapture(event.pointerId);
  panelDrag = null;
  document.body.classList.remove("resizing");
  setLeftPanelWidth(leftEl.getBoundingClientRect().width, true);
}
splitterEl.addEventListener("pointerup", finishPanelResize);
splitterEl.addEventListener("pointercancel", finishPanelResize);
splitterEl.addEventListener("dblclick", () => {
  setLeftPanelWidth(panelWidthBounds().mainWidth * DEFAULT_PANEL_RATIO, true);
});
splitterEl.addEventListener("keydown", event => {
  const bounds = panelWidthBounds();
  const step = event.shiftKey ? 48 : 16;
  let width = leftEl.getBoundingClientRect().width;
  if (event.key === "ArrowLeft") width -= step;
  else if (event.key === "ArrowRight") width += step;
  else if (event.key === "Home") width = bounds.min;
  else if (event.key === "End") width = bounds.max;
  else return;
  event.preventDefault();
  event.stopPropagation();
  setLeftPanelWidth(width, true);
});
new ResizeObserver(() => setLeftPanelWidth(leftEl.getBoundingClientRect().width)).observe(mainEl);
restoreLeftPanelWidth();

function setRows(rows) {
  state.rows = rows;
  state.selected = Math.min(state.selected, rows.length - 1);
  spacer.style.height = rows.length * ROW_H + "px";
  renderWindow();
}

function renderWindow() {
  const top = listEl.scrollTop;
  const first = Math.max(0, Math.floor(top / ROW_H) - 5);
  const last = Math.min(state.rows.length, Math.ceil((top + listEl.clientHeight) / ROW_H) + 5);
  spacer.replaceChildren();
  for (let i = first; i < last; i++) spacer.appendChild(renderRow(state.rows[i], i));
}

function renderRow(row, i) {
  if (row.type === "more") {
    const d = el("div", "loadmore", row.loading ? "loading…" : "Load more…");
    d.style.top = i * ROW_H + "px";
    d.onclick = () => row.load();
    return d;
  }
  const n = row.node;
  const d = el("div", "row" + (i === state.selected ? " selected" : ""));
  d.style.top = i * ROW_H + "px";
  d.style.paddingLeft = 10 + (row.level || 0) * 16 + "px";
  d.setAttribute("role", "option");
  if (row.change) {
    const sev = el("span", "sev", row.change.classification);
    sev.style.background = `var(--${row.change.classification}, #6b7280)`;
    d.appendChild(sev);
    d.appendChild(el("span", "name", row.change.entityKey));
    d.appendChild(el("span", "addr", row.change.ruleId));
  } else {
    const expandable = n.kind !== "reg";
    d.appendChild(el("span", "twisty", expandable ? (row.expanded ? "▼" : "▶") : ""));
    d.appendChild(el("span", "kind", n.kind));
    const label = n.name + (n.array_dims ? `[${n.array_dims.join("][")}]` : "");
    d.appendChild(el("span", "name", label));
    const impact = changeImpactForPath(n.path);
    if (impact) {
      const direct = impact.direct > 0;
      const badge = el("span", "impact" + (direct ? "" : " descendant"), String(impact.total));
      badge.style.background = `var(--${impact.classification}, #6b7280)`;
      badge.style.color = direct ? "#fff" : `var(--${impact.classification}, #6b7280)`;
      badge.title = direct
        ? `${impact.total} change${impact.total === 1 ? "" : "s"} on or below this entity`
        : `${impact.total} change${impact.total === 1 ? "" : "s"} below this entity`;
      d.appendChild(badge);
    }
    d.appendChild(el("span", "addr", fmtAddr(n.addr)));
  }
  d.onclick = () => { select(i); if (row.node && row.node.kind !== "reg") toggle(i); };
  return d;
}

listEl.addEventListener("scroll", renderWindow);
new ResizeObserver(renderWindow).observe(listEl);

function select(i) {
  state.selected = i;
  renderWindow();
  const row = state.rows[i];
  if (!row) return;
  if (row.change) showChangeDetail(row.change);
  else if (row.node) showDetail(row.node.path, row.node);
}

// ---------------------------------------------------------------------------
// Tree mode (lazy, paginated)
// ---------------------------------------------------------------------------
async function loadTreeRoots() {
  const res = await api("/api/children?parent=root&limit=200");
  const rows = res.items.map(n => ({ node: n, level: 0, expanded: false }));
  if (res.nextCursor !== null) rows.push(moreRow(null, res.nextCursor, 0, rows.length));
  setRows(rows);
}

function moreRow(parentId, cursor, level, insertAt) {
  const row = {
    type: "more", level,
    load: async () => {
      row.loading = true; renderWindow();
      const p = parentId === null ? "root" : parentId;
      const res = await api(`/api/children?parent=${p}&cursor=${cursor}&limit=200`);
      const idx = state.rows.indexOf(row);
      const newRows = res.items.map(n => ({ node: n, level, expanded: false }));
      if (res.nextCursor !== null) newRows.push(moreRow(parentId, res.nextCursor, level, 0));
      state.rows.splice(idx, 1, ...newRows);
      setRows(state.rows);
    },
  };
  return row;
}

async function childRowsThrough(parentId, targetPath, level) {
  const rows = [];
  let cursor = -1;
  while (true) {
    const p = parentId === null ? "root" : parentId;
    const res = await api(`/api/children?parent=${p}&cursor=${cursor}&limit=200`);
    rows.push(...res.items.map(n => ({ node: n, level, expanded: false })));
    if (res.items.some(n => n.path === targetPath)) {
      if (res.nextCursor !== null)
        rows.push(moreRow(parentId, res.nextCursor, level, rows.length));
      return rows;
    }
    if (res.nextCursor === null) return rows;
    cursor = res.nextCursor;
  }
}

async function revealInHierarchy(path) {
  let node, fieldName = null;
  try {
    node = await api("/api/entities/" + encodeURIComponent(path));
  } catch (error) {
    // Field-level change keys (reg.field) are not entities; reveal the
    // register instead and highlight the field once its detail renders.
    const dot = path.lastIndexOf(".");
    if (dot < 0) throw error;
    fieldName = path.slice(dot + 1);
    path = path.slice(0, dot);
    node = await api("/api/entities/" + encodeURIComponent(path));
  }
  const parts = node.path.split(".");
  const prefixes = parts.map((_, i) => parts.slice(0, i + 1).join("."));

  setMode("tree");
  let rows = await childRowsThrough(null, prefixes[0], 0);
  let selected = rows.findIndex(r => r.node && r.node.path === prefixes[0]);
  if (selected < 0) throw new Error(`Could not reveal ${path} in the hierarchy`);

  for (let level = 1; level < prefixes.length; level++) {
    const parent = rows[selected];
    parent.expanded = true;
    const children = await childRowsThrough(parent.node.node_id, prefixes[level], level);
    rows.splice(selected + 1, 0, ...children);
    const childOffset = children.findIndex(r => r.node && r.node.path === prefixes[level]);
    if (childOffset < 0) throw new Error(`Could not reveal ${path} in the hierarchy`);
    selected += childOffset + 1;
  }

  setRows(rows);
  state.selected = selected;
  listEl.scrollTop = Math.max(0, selected * ROW_H - listEl.clientHeight / 2);
  renderWindow();
  await showDetail(path, node);
  if (fieldName) focusField(fieldName);
}

async function toggle(i) {
  const row = state.rows[i];
  if (!row.node || row.node.kind === "reg") return;
  if (row.expanded) {
    // collapse: remove deeper rows until level <= row.level
    let j = i + 1;
    while (j < state.rows.length && (state.rows[j].level || 0) > row.level) j++;
    state.rows.splice(i + 1, j - i - 1);
    row.expanded = false;
    setRows(state.rows);
    return;
  }
  row.expanded = true;
  const res = await api(`/api/children?parent=${row.node.node_id}&limit=200`);
  const children = res.items.map(n => ({ node: n, level: row.level + 1, expanded: false }));
  if (res.nextCursor !== null)
    children.push(moreRow(row.node.node_id, res.nextCursor, row.level + 1, 0));
  state.rows.splice(i + 1, 0, ...children);
  setRows(state.rows);
}

// ---------------------------------------------------------------------------
// Search / address-range results
// ---------------------------------------------------------------------------
const searchEl = document.getElementById("search");
const addrEl = document.getElementById("addr-filter");
let searchTimer = null;

searchEl.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, 200);
});
addrEl.addEventListener("change", runAddrFilter);

async function runSearch() {
  const q = searchEl.value.trim();
  if (!q) {
    setMode("results");
    updateViewUrl("results");
    setRows([]);
    statusDetail("Enter a search term to find registers, fields, and descriptions.");
    return;
  }
  switchMode("results");
  try {
    const res = await api(`/api/search?q=${encodeURIComponent(q)}&limit=100`);
    const rows = res.items.map(n => ({ node: n, level: 0 }));
    if (res.nextCursor !== null) {
      const more = {
        type: "more", level: 0,
        load: async () => {
          const r2 = await api(`/api/search?q=${encodeURIComponent(q)}&cursor=${res.nextCursor}&limit=100`);
          const idx = state.rows.indexOf(more);
          state.rows.splice(idx, 1, ...r2.items.map(n => ({ node: n, level: 0 })));
          setRows(state.rows);
        },
      };
      rows.push(more);
    }
    setRows(rows);
    statusDetail(rows.length ? `${rows.length}${res.nextCursor ? "+" : ""} results for “${q}”` : `No results for “${q}”`);
  } catch (e) { statusDetail("Search failed: " + e.message, true); }
}

async function runAddrFilter() {
  const v = addrEl.value.trim();
  if (!v) { switchMode("tree"); return; }
  const m = v.match(/^([0-9a-fx]+)\s*[:\-]\s*([0-9a-fx]+)$/i);
  if (!m) { statusDetail("Address filter format: start:end (e.g. 0x1000:0x2fff)", true); return; }
  switchMode("results");
  try {
    const res = await api(`/api/address-range?start=${m[1]}&end=${m[2]}&limit=500`);
    setRows(res.items.map(n => ({ node: n, level: 0 })));
    statusDetail(`${res.items.length}${res.nextCursor ? "+" : ""} registers in ${m[1]}…${m[2]}`);
  } catch (e) { statusDetail("Address query failed: " + e.message, true); }
}

// ---------------------------------------------------------------------------
// Changes mode
// ---------------------------------------------------------------------------
const CLASSES = ["breaking", "behavioural", "compatible", "documentation", "informational", "uncertain"];
let changesCache = null;
let changesPromise = null;
let changeImpactIndex = new Map();

function hierarchyEntityForChange(change) {
  const path = change.entityKey || "";
  if (change.entityType === "field") return path.slice(0, path.lastIndexOf("."));
  return path;
}

function buildChangeImpactIndex(items) {
  const index = new Map();
  for (const change of items) {
    const entityPath = hierarchyEntityForChange(change);
    if (!entityPath) continue;
    const parts = entityPath.split(".");
    for (let depth = 1; depth <= parts.length; depth++) {
      const path = parts.slice(0, depth).join(".");
      const entry = index.get(path) || { total: 0, direct: 0, classification: "uncertain" };
      entry.total++;
      if (path === entityPath) entry.direct++;
      if (entry.total === 1 || CLASSES.indexOf(change.classification) < CLASSES.indexOf(entry.classification))
        entry.classification = change.classification;
      index.set(path, entry);
    }
  }
  changeImpactIndex = index;
  return index;
}

function changeImpactForPath(path) {
  return changeImpactIndex.get(path) || null;
}

let changesProgress = null; // set by views that want per-page load feedback

async function getChanges() {
  if (changesCache) return changesCache;
  if (!changesPromise) {
    changesPromise = (async () => {
      const pages = [];
      let cursor = 0;
      let summary = {};
      // 50 pages × 10k caps browser memory on pathological diffs; `truncated`
      // lets views say so instead of silently under-reporting.
      for (let guard = 0; guard < 50 && cursor !== null; guard++) {
        const res = await api(`/api/changes?cursor=${cursor}&limit=10000`);
        pages.push(...res.items);
        summary = res.summary || {};
        cursor = res.nextCursor;
        if (changesProgress) changesProgress(pages.length);
      }
      // Cache is only ever set on a complete load: a failed page must not
      // leave a partial list that every later view silently reuses.
      changesCache = { items: pages, summary, truncated: cursor !== null };
      buildChangeImpactIndex(pages);
      if (state.mode === "tree") renderWindow();
      return changesCache;
    })();
    changesPromise.catch(() => { changesPromise = null; });
  }
  return changesPromise;
}

async function loadChanges() {
  const filters = document.getElementById("filters");
  if (!changesCache) {
    const loading = el("div", "status", "loading changes…");
    document.getElementById("detail").replaceChildren(loading);
    changesProgress = n => {
      loading.textContent = `loading changes… (${n.toLocaleString()} so far)`;
    };
  }
  try { await getChanges(); }
  finally { changesProgress = null; }
  if (!state.severityFilter) state.severityFilter = new Set(CLASSES);
  filters.style.display = "flex";
  filters.replaceChildren();
  for (const c of CLASSES) {
    const count = changesCache.items.filter(ch => ch.classification === c).length;
    const lab = el("label");
    const cb = el("input"); cb.type = "checkbox"; cb.checked = state.severityFilter.has(c);
    cb.onchange = () => {
      cb.checked ? state.severityFilter.add(c) : state.severityFilter.delete(c);
      renderChanges();
    };
    lab.appendChild(cb);
    lab.appendChild(el("span", "", `${c} (${count})`));
    filters.appendChild(lab);
  }
  renderChanges();
}

function renderChanges() {
  const items = changesCache.items.filter(c => state.severityFilter.has(c.classification));
  setRows(items.map(c => ({ change: c, level: 0 })));
  statusDetail(`${items.length} changes shown (${changesCache.items.length}${changesCache.truncated ? "+" : ""} total)`);
}

function countsBy(items, keyFn) {
  const counts = new Map();
  for (const item of items) {
    const key = keyFn(item) || "unknown";
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

function appendSummaryRows(parent, entries, emptyText = "None") {
  if (!entries.length) {
    parent.appendChild(el("div", "desc", emptyText));
    return;
  }
  for (const [label, count] of entries) {
    const row = el("div", "summary-row");
    row.appendChild(el("span", "summary-label", label));
    row.appendChild(el("span", "summary-count", String(count)));
    parent.appendChild(row);
  }
}

function openChangesWithFilter(classification) {
  state.severityFilter = new Set(classification ? [classification] : CLASSES);
  switchMode("changes");
}

function appendMetric(card, value, label, color) {
  card.style.setProperty("--metric-color", color);
  card.appendChild(el("span", "metric-value", String(value)));
  card.appendChild(el("span", "metric-label", label));
}

async function renderOverview() {
  const d = document.getElementById("detail");
  const loading = el("div", "status", "loading overview…");
  d.replaceChildren(loading);
  changesProgress = n => {
    loading.textContent = `loading overview… (${n.toLocaleString()} changes)`;
  };
  let data;
  try { data = await getChanges(); }
  finally { changesProgress = null; }
  const items = data.items;
  setRows(items.map(change => ({ change, level: 0 })));
  d.replaceChildren();

  // The server-side summary holds the true totals even when the loaded list
  // is truncated.
  const severityCounts = new Map(countsBy(items, item => item.classification));
  for (const [cls, count] of Object.entries(data.summary || {}))
    if (Number(count) > (severityCounts.get(cls) || 0)) severityCounts.set(cls, Number(count));
  const totalCount = [...severityCounts.values()].reduce((a, b) => a + b, 0);

  const head = el("div", "overview-head");
  head.appendChild(el("h2", "", "Change overview"));
  head.appendChild(el("span", "desc", !items.length
    ? "No semantic changes detected"
    : data.truncated
      ? `Loaded the first ${items.length.toLocaleString()} of ${totalCount.toLocaleString()} changes`
      : "Select a change to view its details"));
  d.appendChild(head);

  const cards = el("div", "overview-grid");
  const total = el("button", "metric-card");
  total.type = "button";
  appendMetric(total, totalCount, "total changes", "var(--accent)");
  total.onclick = () => openChangesWithFilter(null);
  cards.appendChild(total);
  for (const classification of CLASSES) {
    const count = severityCounts.get(classification) || 0;
    if (!count) continue;
    const card = el("button", "metric-card");
    card.type = "button";
    appendMetric(card, count, classification, `var(--${classification})`);
    card.onclick = () => openChangesWithFilter(classification);
    cards.appendChild(card);
  }
  d.appendChild(cards);

  if (!items.length) return;

  const compositionCounts = new Map(countsBy(items, changeState));
  const compositionPanel = el("section", "overview-panel");
  compositionPanel.appendChild(el("h3", "", "Change composition"));
  const composition = el("div", "composition");
  for (const kind of ["added", "removed", "modified"]) {
    const count = compositionCounts.get(kind) || 0;
    if (!count) continue;
    const segment = el("span");
    segment.style.flex = String(count);
    segment.style.background = `var(--change-${kind})`;
    segment.title = `${count} ${kind}`;
    composition.appendChild(segment);
  }
  compositionPanel.appendChild(composition);
  appendSummaryRows(compositionPanel, ["added", "removed", "modified"]
    .map(kind => [kind, compositionCounts.get(kind) || 0]).filter(([, count]) => count));

  const entityPanel = el("section", "overview-panel");
  entityPanel.appendChild(el("h3", "", "Affected entity types"));
  appendSummaryRows(entityPanel, countsBy(items, item => item.entityType).slice(0, 6));

  const rulesPanel = el("section", "overview-panel");
  rulesPanel.appendChild(el("h3", "", "Top rules"));
  appendSummaryRows(rulesPanel, countsBy(items, item => item.ruleId).slice(0, 6));

  const scopesPanel = el("section", "overview-panel");
  scopesPanel.appendChild(el("h3", "", "Most affected hierarchy scopes"));
  const scopes = [...changeImpactIndex.entries()]
    .filter(([, impact]) => impact.total > impact.direct)
    .sort((a, b) => b[1].total - a[1].total || a[0].localeCompare(b[0]))
    .slice(0, 6)
    .map(([path, impact]) => [path, impact.total]);
  appendSummaryRows(scopesPanel, scopes, "Changes only affect top-level entities");

  const columns = el("div", "overview-columns");
  for (const panel of [compositionPanel, entityPanel, rulesPanel, scopesPanel]) columns.appendChild(panel);
  d.appendChild(columns);
}

function showChangeDetail(c) {
  const d = document.getElementById("detail");
  d.replaceChildren();
  d.appendChild(el("h2", "", c.entityKey));
  const sev = el("span", "sev", c.classification);
  sev.style.background = `var(--${c.classification}, #6b7280)`;
  sev.style.padding = "2px 10px";
  d.appendChild(sev);
  d.appendChild(el("p", "", c.message));
  const t = el("table");
  const rows = [
    ["Rule", c.ruleId], ["Confidence", c.confidence],
    ["Before", c.before === null ? "—" : String(c.before)],
    ["After", c.after === null ? "—" : String(c.after)],
    ["Entity type", c.entityType],
    ["Base location", c.baseLocation ? `${c.baseLocation.file}:${c.baseLocation.line ?? "?"}` : "—"],
    ["Head location", c.headLocation ? `${c.headLocation.file}:${c.headLocation.line ?? "?"}` : "—"],
  ];
  for (const [k, v] of rows) {
    const tr = el("tr"); tr.appendChild(el("th", "", k)); tr.appendChild(el("td", "mono", v ?? "—"));
    t.appendChild(tr);
  }
  d.appendChild(t);
  const link = el("a", "", "Open entity in hierarchy →");
  link.href = "/r/" + encodeURIComponent(c.entityKey);
  link.onclick = (e) => {
    e.preventDefault();
    revealInHierarchy(c.entityKey).catch(err =>
      statusDetail(`Could not reveal ${c.entityKey}: ${err.message}`, true));
  };
  d.appendChild(link);
}

function changeState(c) {
  const rule = c.ruleId || "";
  if (rule.startsWith("FIELD-ADDED-") || rule.startsWith("REG-ADDED-")) return "added";
  if (rule === "FIELD-REMOVED" || rule === "REG-REMOVED") return "removed";
  return "modified";
}

function fieldNameForChange(c, registerPath) {
  const prefix = registerPath + ".";
  return c.entityType === "field" && c.entityKey.startsWith(prefix)
    ? c.entityKey.slice(prefix.length)
    : null;
}

function changesForRegister(items, registerPath) {
  const prefix = registerPath + ".";
  return items.filter(c =>
    (c.entityType === "reg" && c.entityKey === registerPath) ||
    (c.entityType === "field" && c.entityKey.startsWith(prefix)));
}

function parseBitRange(value) {
  const m = String(value || "").match(/\[(\d+)(?::(\d+))?\]/);
  if (!m) return null;
  const a = Number(m[1]);
  const b = m[2] === undefined ? a : Number(m[2]);
  return { msb: Math.max(a, b), lsb: Math.min(a, b) };
}

function fieldAnchor(name) {
  return "field-" + encodeURIComponent(name).replaceAll("%", "_");
}

function focusField(name) {
  const target = document.getElementById(fieldAnchor(name));
  if (!target) return;
  target.scrollIntoView({ block: "nearest", behavior: "smooth" });
  target.classList.add("field-focus");
  setTimeout(() => target.classList.remove("field-focus"), 900);
}

function segmentLabel(name, width) {
  const maxChars = Math.max(1, Math.floor((width - 7) / 6.5));
  if (name.length <= maxChars) return name;
  if (maxChars === 1) return name.slice(0, 1);
  return name.slice(0, maxChars - 1) + "…";
}

function renderChangeItem(c) {
  const item = el("div", "change-item");
  item.appendChild(el("span", "change-badge " + changeState(c), changeState(c)));
  const message = el("div", "change-message");
  message.appendChild(el("div", "", c.message));
  const values = [c.classification, c.ruleId];
  if (c.before !== null || c.after !== null)
    values.push(`${c.before ?? "—"} → ${c.after ?? "—"}`);
  message.appendChild(el("div", "change-values", values.join(" · ")));
  item.appendChild(message);
  return item;
}

function appendChangeSummary(parent, changes) {
  if (!changes.length) return;
  const box = el("section", "change-summary");
  box.appendChild(el("div", "change-summary-title",
    `${changes.length} semantic change${changes.length === 1 ? "" : "s"} in this register`));
  for (const c of changes) box.appendChild(renderChangeItem(c));
  parent.appendChild(box);
}

function renderBitfield(registerPath, body, relatedChanges) {
  const size = Math.max(1, Number(body.regwidth) || 1);
  const visibleSize = Math.min(size, MAX_DIAGRAM_BITS);
  const laneBits = Math.min(32, visibleSize);
  const lanes = Math.ceil(visibleSize / laneBits);
  const CELL = 26, LANE_H = 36, RULER_H = 15, LANE_GAP = 12, PAD = 5;
  const laneBlock = RULER_H + LANE_H + LANE_GAP;
  const width = laneBits * CELL + PAD * 2;
  const height = lanes * laneBlock + PAD;
  const laneY = lane => PAD + (lanes - 1 - lane) * laneBlock + RULER_H;
  const bitX = (lane, bit) => PAD + (laneBits - 1 - (bit - lane * laneBits)) * CELL;

  const fieldChanges = relatedChanges.filter(c => c.entityType === "field");
  const currentNames = new Set(body.fields.map(f => f.name));
  const entries = body.fields.map((field, index) => {
    const changes = fieldChanges.filter(c => fieldNameForChange(c, registerPath) === field.name);
    return { field, index, changes, state: changes.length ? changeState(changes[0]) : null, ghost: false };
  });

  const ghosts = new Map();
  for (const c of fieldChanges) {
    const name = fieldNameForChange(c, registerPath);
    if (!name || currentNames.has(name) || ghosts.has(name)) continue;
    const state = changeState(c);
    const range = parseBitRange(state === "removed" ? c.before : c.after);
    if (!range) continue;
    ghosts.set(name, {
      field: { name, lsb: range.lsb, msb: range.msb, width: range.msb - range.lsb + 1 },
      index: entries.length + ghosts.size,
      changes: fieldChanges.filter(other => fieldNameForChange(other, registerPath) === name),
      state,
      ghost: true,
    });
  }
  entries.push(...ghosts.values());

  const occupancy = new Array(visibleSize).fill(0);
  for (const { field, ghost } of entries) {
    if (ghost) continue;
    for (let bit = Math.max(0, field.lsb); bit <= Math.min(field.msb, visibleSize - 1); bit++) occupancy[bit]++;
  }

  const wrap = el("div", "bitfield");
  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": `Bit layout of register ${registerPath}`,
  });
  const defs = svgEl("defs");
  const pattern = svgEl("pattern", { id: "reserved-hatch", width: 7, height: 7, patternUnits: "userSpaceOnUse" });
  pattern.appendChild(svgEl("rect", { width: 7, height: 7, fill: "var(--accent-bg)" }));
  pattern.appendChild(svgEl("path", { d: "M-1 1 L1 -1 M0 7 L7 0 M6 8 L8 6", stroke: "var(--line)", "stroke-width": 1 }));
  defs.appendChild(pattern);
  svg.appendChild(defs);

  for (let lane = lanes - 1; lane >= 0; lane--) {
    const lo = lane * laneBits;
    const hi = Math.min(lo + laneBits - 1, visibleSize - 1);
    const y = laneY(lane);
    const laneWidth = (hi - lo + 1) * CELL;
    const x = bitX(lane, hi);
    const ticks = [];
    for (let bit = lo; bit <= hi; bit++)
      if (bit === lo || bit === hi || bit % 8 === 0) ticks.push(bit);
    for (const bit of [...new Set(ticks)])
      svg.appendChild(svgEl("text", {
        x: bitX(lane, bit) + CELL / 2, y: y - 4,
        class: "bit-tick", "text-anchor": "middle",
      }, bit));
    svg.appendChild(svgEl("rect", {
      x, y, width: laneWidth, height: LANE_H, rx: 4,
      fill: "url(#reserved-hatch)", class: "bit-lane",
    }));
  }

  for (const entry of entries) {
    const f = entry.field;
    const lo = Math.max(0, f.lsb);
    const hi = Math.min(f.msb, visibleSize - 1);
    if (lo > hi) continue;
    for (let lane = Math.floor(lo / laneBits); lane <= Math.floor(hi / laneBits); lane++) {
      const segLo = Math.max(lo, lane * laneBits);
      const segHi = Math.min(hi, lane * laneBits + laneBits - 1);
      const x = bitX(lane, segHi);
      const w = (segHi - segLo + 1) * CELL;
      const trouble = f.msb >= size || occupancy.slice(segLo, segHi + 1).some(count => count > 1);
      const group = svgEl("g", {
        class: `bit-segment${entry.state ? " " + entry.state : ""}${entry.ghost ? " ghost" : ""}${trouble ? " trouble" : ""}`,
        tabindex: 0,
      });
      const bits = f.msb === f.lsb ? `${f.lsb}` : `${f.msb}:${f.lsb}`;
      const titleParts = [`${f.name} [${bits}]`];
      if (f.sw) titleParts.push(`SW ${f.sw}`);
      if (f.hw) titleParts.push(`HW ${f.hw}`);
      if (f.reset !== null && f.reset !== undefined) titleParts.push(`reset 0x${f.reset}`);
      for (const c of entry.changes) titleParts.push(c.message);
      group.appendChild(svgEl("title", {}, titleParts.join(" · ")));
      group.appendChild(svgEl("rect", {
        x: x + 1, y: laneY(lane) + 1, width: Math.max(1, w - 2), height: LANE_H - 2, rx: 4,
        fill: FIELD_COLORS[entry.index % FIELD_COLORS.length],
      }));
      if (!(entry.ghost && entry.state === "removed"))
        group.appendChild(svgEl("text", {
          x: x + w / 2, y: laneY(lane) + LANE_H / 2 + 4,
          class: "bit-label", "text-anchor": "middle",
        }, segmentLabel(entry.ghost ? `${f.name} (${entry.state})` : f.name, w)));
      group.addEventListener("click", () => focusField(f.name));
      group.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); focusField(f.name); }
      });
      svg.appendChild(group);
    }
  }

  wrap.appendChild(svg);
  if (fieldChanges.length) {
    const legend = el("div", "bitfield-legend");
    for (const [state, label] of [["added", "Added"], ["removed", "Removed"], ["modified", "Modified"]]) {
      const key = el("span", "legend-key");
      const swatch = el("span", `legend-swatch ${state}`);
      swatch.style.background = `var(--change-${state})`;
      key.appendChild(swatch); key.appendChild(document.createTextNode(label)); legend.appendChild(key);
    }
    wrap.appendChild(legend);
  }
  if (size > MAX_DIAGRAM_BITS)
    wrap.appendChild(el("p", "bitfield-note", `Showing the lowest ${MAX_DIAGRAM_BITS} of ${size} bits.`));
  return wrap;
}

function nextPowerOfTwo(value) {
  let power = 1n;
  while (power < value) power <<= 1n;
  return power;
}

function bigHex(value) {
  return "0x" + value.toString(16);
}

async function renderAddressMap(node) {
  const section = el("section", "address-map");
  section.appendChild(el("h3", "", "Address map"));
  const start = BigInt("0x" + (node.addr || "0"));
  const end = BigInt("0x" + (node.addr_end || node.addr || "0"));
  let result;
  try {
    result = await api(`/api/address-range?start=${bigHex(start)}&end=${bigHex(end)}&limit=${ADDRESS_MAP_LIMIT}`);
  } catch (error) {
    section.appendChild(el("p", "address-map-note error", "Could not load address map: " + error.message));
    return section;
  }
  if (!result.items.length) {
    section.appendChild(el("p", "address-map-note", "No registers in this container."));
    return section;
  }

  const registers = result.items;
  const pageStart = BigInt("0x" + registers[0].addr);
  const pageEnd = registers.reduce((max, register) => {
    const registerEnd = BigInt("0x" + (register.addr_end || register.addr));
    return registerEnd > max ? registerEnd : max;
  }, pageStart);
  const span = pageEnd - pageStart + 1n;
  const targetLanes = 8n;
  const minLaneBytes = 32n;
  const laneBytes = nextPowerOfTwo((span + targetLanes - 1n) / targetLanes > minLaneBytes
    ? (span + targetLanes - 1n) / targetLanes : minLaneBytes);
  const laneCount = Number((span + laneBytes - 1n) / laneBytes);
  const WIDTH = 900, LABEL_W = 88, TRACK_W = WIDTH - LABEL_W - 8;
  const LANE_H = 28, LANE_GAP = 12, TOP = 4;
  const height = TOP + laneCount * (LANE_H + LANE_GAP);
  const svg = svgEl("svg", {
    viewBox: `0 0 ${WIDTH} ${height}`,
    role: "img",
    "aria-label": `Address map for ${node.path}`,
  });

  for (let lane = 0; lane < laneCount; lane++) {
    const laneStart = pageStart + BigInt(lane) * laneBytes;
    const laneEnd = laneStart + laneBytes - 1n;
    const y = TOP + lane * (LANE_H + LANE_GAP);
    svg.appendChild(svgEl("text", { x: 0, y: y + 17, class: "address-label" }, bigHex(laneStart)));
    svg.appendChild(svgEl("rect", {
      x: LABEL_W, y, width: TRACK_W, height: LANE_H, rx: 4, class: "address-lane",
    }));
    svg.appendChild(svgEl("text", {
      x: WIDTH - 8, y: y + LANE_H + 10, class: "address-label", "text-anchor": "end",
    }, bigHex(laneEnd)));
  }

  for (const register of registers) {
    const registerStart = BigInt("0x" + register.addr);
    const registerEnd = BigInt("0x" + (register.addr_end || register.addr));
    const firstLane = Math.max(0, Number((registerStart - pageStart) / laneBytes));
    const lastLane = Math.min(laneCount - 1, Number((registerEnd - pageStart) / laneBytes));
    for (let lane = firstLane; lane <= lastLane; lane++) {
      const laneStart = pageStart + BigInt(lane) * laneBytes;
      const laneEnd = laneStart + laneBytes - 1n;
      const segmentStart = registerStart > laneStart ? registerStart : laneStart;
      const segmentEnd = registerEnd < laneEnd ? registerEnd : laneEnd;
      const xRatio = Number(segmentStart - laneStart) / Number(laneBytes);
      const widthRatio = Number(segmentEnd - segmentStart + 1n) / Number(laneBytes);
      const x = LABEL_W + xRatio * TRACK_W;
      const width = Math.max(2, widthRatio * TRACK_W);
      const drawWidth = Math.min(width, LABEL_W + TRACK_W - x);
      const y = TOP + lane * (LANE_H + LANE_GAP);
      const impact = changeImpactForPath(register.path);
      const group = svgEl("g", {
        tabindex: 0, role: "button",
        "aria-label": `${register.path}, ${fmtAddr(register.addr)}`,
      });
      const title = `${register.path} · ${fmtAddr(register.addr)}…${fmtAddr(register.addr_end || register.addr)}` +
        (impact ? ` · ${impact.total} change${impact.total === 1 ? "" : "s"}` : "");
      group.appendChild(svgEl("title", {}, title));
      const rect = svgEl("rect", {
        x, y: y + 1, width: drawWidth, height: LANE_H - 2, rx: 3,
        class: "address-register",
      });
      if (impact) rect.style.fill = `var(--${impact.classification})`;
      group.appendChild(rect);
      if (drawWidth >= 46) {
        group.appendChild(svgEl("text", {
          x: x + drawWidth / 2, y: y + 18, class: "address-register-label", "text-anchor": "middle",
        }, segmentLabel(register.name || register.path.split(".").slice(-1)[0], drawWidth)));
      }
      const reveal = () => revealInHierarchy(register.path).catch(error => statusDetail(error.message, true));
      group.addEventListener("click", reveal);
      group.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); reveal(); }
      });
      svg.appendChild(group);
    }
  }

  section.appendChild(svg);
  const range = `${bigHex(start)}…${bigHex(end)}`;
  const shown = `${registers.length.toLocaleString()} register${registers.length === 1 ? "" : "s"} shown`;
  const truncated = result.nextCursor !== null ? `; capped at the first ${ADDRESS_MAP_LIMIT.toLocaleString()}` : "";
  section.appendChild(el("p", "address-map-note",
    `${shown}${truncated} · container range ${range} · ${laneCount} lane${laneCount === 1 ? "" : "s"} × ${bigHex(laneBytes)} bytes`));
  return section;
}

// ---------------------------------------------------------------------------
// Detail panel + deep links
// ---------------------------------------------------------------------------
function statusDetail(msg, isError) {
  const d = document.getElementById("detail");
  d.replaceChildren(el("div", "status" + (isError ? " error" : ""), msg));
}

async function showDetail(path, preloaded) {
  const d = document.getElementById("detail");
  d.replaceChildren(el("div", "status", "loading…"));
  let node = preloaded && preloaded.definition ? preloaded : null;
  try {
    if (!node) node = await api("/api/entities/" + encodeURIComponent(path));
  } catch (e) {
    return statusDetail(`Could not load ${path}: ${e.message}`, true);
  }
  let relatedChanges = [];
  if (node.kind === "reg") {
    try {
      const changeData = await getChanges();
      relatedChanges = changesForRegister(changeData.items, node.path);
    } catch (e) {
      perf.queries.push({ url: "/api/changes", ok: false, error: e.message });
    }
  }
  history.replaceState(null, "", "/r/" + encodeURIComponent(node.resolved_path || node.path));
  state.detailPath = path;
  d.replaceChildren();
  d.appendChild(el("h2", "", node.resolved_path || node.path));
  const sub = el("div", "sub");
  sub.appendChild(el("span", "chip", node.kind));
  if (node.type_name) sub.appendChild(el("span", "chip", node.type_name));
  sub.appendChild(el("span", "chip", "addr " + fmtAddr(node.addr)));
  sub.appendChild(el("span", "chip", "size 0x" + node.size));
  if (node.array_dims)
    sub.appendChild(el("span", "chip",
      `array [${node.array_dims.join("][")}] stride 0x${node.array_stride}`));
  if (node.reg_count > 1) sub.appendChild(el("span", "chip", node.reg_count + " regs in subtree"));
  if (node.src_file)
    sub.appendChild(el("span", "chip",
      `${node.src_file.split("/").pop()}${node.src_line ? ":" + node.src_line : ""}`));
  d.appendChild(sub);

  appendChangeSummary(d, relatedChanges);

  const body = node.definition || {};
  if (body.desc) d.appendChild(el("p", "desc", body.desc));

  if (node.kind === "reg" && body.fields) {
    d.appendChild(el("h3", "", "Bit layout"));
    d.appendChild(renderBitfield(node.path, body, relatedChanges));
    d.appendChild(el("h3", "", "Fields"));
    const t = el("table");
    const hd = el("tr");
    for (const h of ["Bits", "Field", "SW", "HW", "Reset", "Enum", "Description"])
      hd.appendChild(el("th", "", h));
    t.appendChild(hd);
    const fieldChanges = relatedChanges.filter(c => c.entityType === "field");
    const currentNames = new Set(body.fields.map(f => f.name));
    for (const f of [...body.fields].reverse()) {
      const tr = el("tr");
      tr.id = fieldAnchor(f.name);
      const changes = fieldChanges.filter(c => fieldNameForChange(c, node.path) === f.name);
      if (changes.length) tr.className = "changed-field";
      tr.appendChild(el("td", "mono bits", f.msb === f.lsb ? `[${f.lsb}]` : `[${f.msb}:${f.lsb}]`));
      const nameTd = el("td", "mono");
      if (changes.length) nameTd.appendChild(el("span", "field-state " + changeState(changes[0])));
      nameTd.appendChild(document.createTextNode(f.name));
      tr.appendChild(nameTd);
      tr.appendChild(el("td", "mono", f.sw || "—"));
      tr.appendChild(el("td", "mono", f.hw || "—"));
      tr.appendChild(el("td", "mono", f.reset !== null && f.reset !== undefined ? "0x" + f.reset : "—"));
      const enumTd = el("td", "mono");
      if (f.encode) {
        for (const [name, val] of f.encode) enumTd.appendChild(el("div", "", `${name}=0x${val}`));
      } else enumTd.textContent = "—";
      tr.appendChild(enumTd);
      tr.appendChild(el("td", "desc", f.desc || ""));
      t.appendChild(tr);
      if (changes.length) {
        const note = el("tr", "field-change-row");
        const td = el("td"); td.colSpan = 7;
        for (const c of changes) td.appendChild(renderChangeItem(c));
        note.appendChild(td); t.appendChild(note);
      }
    }
    const missing = new Map();
    for (const c of fieldChanges) {
      const name = fieldNameForChange(c, node.path);
      if (!name || currentNames.has(name)) continue;
      if (!missing.has(name)) missing.set(name, []);
      missing.get(name).push(c);
    }
    const missingRows = [...missing.entries()].map(([name, changes]) => {
      const state = changeState(changes[0]);
      const range = parseBitRange(state === "removed" ? changes[0].before : changes[0].after);
      return { name, changes, state, range };
    }).sort((a, b) => (b.range?.msb ?? -1) - (a.range?.msb ?? -1));
    for (const item of missingRows) {
      const tr = el("tr", "changed-field"); tr.id = fieldAnchor(item.name);
      tr.appendChild(el("td", "mono bits", item.range
        ? (item.range.msb === item.range.lsb ? `[${item.range.lsb}]` : `[${item.range.msb}:${item.range.lsb}]`)
        : "—"));
      const nameTd = el("td", "mono");
      nameTd.appendChild(el("span", "field-state " + item.state));
      nameTd.appendChild(document.createTextNode(`${item.name} (${item.state})`));
      tr.appendChild(nameTd);
      for (let i = 0; i < 5; i++) tr.appendChild(el("td", i === 4 ? "desc" : "mono", "—"));
      t.appendChild(tr);
      const note = el("tr", "field-change-row");
      const td = el("td"); td.colSpan = 7;
      for (const c of item.changes) td.appendChild(renderChangeItem(c));
      note.appendChild(td); t.appendChild(note);
    }
    d.appendChild(t);
  } else if (node.kind !== "reg") {
    const p = el("p", "desc", "Container with " + (node.reg_count || 0) + " registers. Expand it in the hierarchy panel.");
    d.appendChild(p);
    d.appendChild(await renderAddressMap(node));
  }
}

// ---------------------------------------------------------------------------
// Tabs, keyboard, boot
// ---------------------------------------------------------------------------
function updateViewUrl(mode) {
  if (mode === "overview") {
    history.replaceState(null, "", "/");
    return;
  }
  const params = new URLSearchParams({ view: mode });
  if (mode === "results") {
    const query = searchEl.value.trim();
    const range = addrEl.value.trim();
    if (query) params.set("q", query);
    else if (range) params.set("range", range);
  }
  history.replaceState(null, "", "/?" + params.toString());
}

function setMode(mode) {
  state.mode = mode;
  // Entering the tree directly (?view=hierarchy, /r/ deep link) must still
  // load changes, or the impact badges never appear; getChanges re-renders
  // the tree when it completes.
  if (mode === "tree" && !changesCache) getChanges().catch(() => {});
  document.getElementById("filters").style.display = mode === "changes" ? "flex" : "none";
  for (const [id, m] of [["tab-overview", "overview"], ["tab-tree", "tree"], ["tab-results", "results"], ["tab-changes", "changes"]])
    document.getElementById(id).classList.toggle("active", m === mode);
}

function switchMode(mode, updateUrl = true) {
  setMode(mode);
  if (updateUrl) updateViewUrl(mode);
  if (mode === "overview") return renderOverview().catch(e => statusDetail(e.message, true));
  if (mode === "tree") return loadTreeRoots();
  if (mode === "changes") return loadChanges().catch(e => statusDetail(e.message, true));
  setRows([]);
}
document.getElementById("tab-overview").onclick = () => switchMode("overview");
document.getElementById("tab-tree").onclick = () => switchMode("tree");
document.getElementById("tab-results").onclick = () => { switchMode("results"); runSearch(); };
document.getElementById("tab-changes").onclick = () => switchMode("changes");

document.addEventListener("keydown", (e) => {
  if (e.key === "/" && document.activeElement !== searchEl) {
    e.preventDefault(); searchEl.focus(); searchEl.select(); return;
  }
  if (document.activeElement === searchEl || document.activeElement === addrEl) {
    if (e.key === "Escape") { searchEl.blur(); addrEl.blur(); }
    return;
  }
  if (e.key === "ArrowDown") { e.preventDefault(); moveSel(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); moveSel(-1); }
  else if (e.key === "ArrowRight") { const r = state.rows[state.selected]; if (r && r.node && !r.expanded) toggle(state.selected); }
  else if (e.key === "ArrowLeft") { const r = state.rows[state.selected]; if (r && r.node && r.expanded) toggle(state.selected); }
  else if (e.key === "Enter") select(state.selected);
});

function moveSel(delta) {
  const i = Math.max(0, Math.min(state.rows.length - 1, state.selected + delta));
  state.selected = i;
  const y = i * ROW_H;
  if (y < listEl.scrollTop) listEl.scrollTop = y;
  else if (y + ROW_H > listEl.scrollTop + listEl.clientHeight)
    listEl.scrollTop = y + ROW_H - listEl.clientHeight;
  renderWindow();
  const row = state.rows[i];
  if (row && row.node) showDetail(row.node.path, row.node);
}

async function boot() {
  try {
    const meta = await api("/api/metadata");
    const c = meta.counts || {};
    document.getElementById("meta-line").textContent =
      `${meta.top_name} · ${(c.registers ?? 0).toLocaleString()} regs · ` +
      `${(c.definitions ?? 0).toLocaleString()} defs · ` +
      `${(meta.db_bytes / 1048576).toFixed(1)} MB`;
  } catch (e) {
    document.getElementById("meta-line").textContent = "metadata unavailable: " + e.message;
  }
  // Deep link: /r/<entity path>
  if (location.pathname.startsWith("/r/")) {
    const path = decodeURIComponent(location.pathname.slice(3));
    if (path) {
      try { return await revealInHierarchy(path); }
      catch (error) { return statusDetail(`Could not reveal ${path}: ${error.message}`, true); }
    }
  }
  const params = new URLSearchParams(location.search);
  const view = params.get("view");
  if (view === "changes") return switchMode("changes");
  if (view === "hierarchy") return switchMode("tree");
  if (view === "results") {
    searchEl.value = params.get("q") || "";
    addrEl.value = params.get("range") || "";
    if (searchEl.value) return runSearch();
    if (addrEl.value) return runAddrFilter();
    return switchMode("results");
  }
  return switchMode("overview");
}
boot();
