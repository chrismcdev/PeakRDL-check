/* RegReview viewer.
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
const perf = { queries: [] };
window.__regreviewPerf = perf;

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

function fmtAddr(hex) { return "0x" + (hex || "0"); }

// ---------------------------------------------------------------------------
// Virtualized list over a flat row model
// ---------------------------------------------------------------------------
const listEl = document.getElementById("list");
const spacer = listEl.querySelector(".spacer");
const state = {
  mode: "tree",           // tree | results | changes
  rows: [],               // flat visible rows
  selected: -1,
  severityFilter: null,   // set of enabled classifications (changes mode)
  resultsQuery: null,
  detailPath: null,
};

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
  if (!q) { switchMode("tree"); return; }
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

async function loadChanges() {
  const filters = document.getElementById("filters");
  if (!changesCache) {
    const pages = [];
    let cursor = 0;
    for (let guard = 0; guard < 50 && cursor !== null; guard++) {
      const res = await api(`/api/changes?cursor=${cursor}&limit=1000`);
      pages.push(...res.items);
      cursor = res.nextCursor;
      changesCache = { items: pages, summary: res.summary };
    }
  }
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
  statusDetail(`${items.length} changes shown (${changesCache.items.length} total)`);
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
  link.onclick = (e) => { e.preventDefault(); showDetail(c.entityKey); };
  d.appendChild(link);
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
  let node;
  try {
    node = await api("/api/entities/" + encodeURIComponent(path));
  } catch (e) {
    return statusDetail(`Could not load ${path}: ${e.message}`, true);
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

  const body = node.definition || {};
  if (body.desc) d.appendChild(el("p", "desc", body.desc));

  if (node.kind === "reg" && body.fields) {
    const t = el("table");
    const hd = el("tr");
    for (const h of ["Bits", "Field", "SW", "HW", "Reset", "Enum", "Description"])
      hd.appendChild(el("th", "", h));
    t.appendChild(hd);
    for (const f of [...body.fields].reverse()) {
      const tr = el("tr");
      tr.appendChild(el("td", "mono bits", f.msb === f.lsb ? `[${f.lsb}]` : `[${f.msb}:${f.lsb}]`));
      tr.appendChild(el("td", "mono", f.name));
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
    }
    d.appendChild(t);
  } else if (node.kind !== "reg") {
    const p = el("p", "desc", "Container with " + (node.reg_count || 0) + " registers. Expand it in the hierarchy panel.");
    d.appendChild(p);
  }
}

// ---------------------------------------------------------------------------
// Tabs, keyboard, boot
// ---------------------------------------------------------------------------
function switchMode(mode) {
  state.mode = mode;
  document.getElementById("filters").style.display = mode === "changes" ? "flex" : "none";
  for (const [id, m] of [["tab-tree", "tree"], ["tab-results", "results"], ["tab-changes", "changes"]])
    document.getElementById(id).classList.toggle("active", m === mode);
  if (mode === "tree") loadTreeRoots();
  else if (mode === "changes") loadChanges().catch(e => statusDetail(e.message, true));
  else setRows([]);
}
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
  await loadTreeRoots();
  // Deep link: /r/<entity path>
  if (location.pathname.startsWith("/r/")) {
    const path = decodeURIComponent(location.pathname.slice(3));
    if (path) showDetail(path);
  }
}
boot();
