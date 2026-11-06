"use strict";
// ---------- Demo data (used when URL has ?demo=1) ----------
const DEMO = {
  "GET /api/health": { jobs: [{ job: "aos-night-school", last_run: "2026-11-01T22:00:12", ok: true, detail: "ok" }, { job: "aos-bridge", last_run: null, ok: true, detail: "running" }] },
  "GET /api/status": { tts_voice: "Jamie (Premium)", tiers: { t1: { state: "up" }, jev: { state: "up" }, t2: { state: "up" }, t3: { state: "up" }, t4: { state: "degraded" }, t5: { state: "off" } } },
  // null = unknown value (UI shows "—" with a tooltip)
  "GET /api/usage": {
    claude: { session_pct: 42, week_pct: 74, session_resets_at: "2026-11-01T17:00:00", week_resets_at: "2026-11-05T09:00:00", source: "statusline" },
    tokens_today: [{ model: "opus", tokens: 182000 }, { model: "sonnet", tokens: 96400 }, { model: "haiku", tokens: 12100 }],
    jev_usd_month: 0.38, groq_remaining: 11840, openrouter_remaining: null, ollama_calls_today: 27,
    brightdata_pct: 12, apify_pct: 3,
    unknown_reasons: { openrouter_remaining: "No OPENROUTER_API_KEY set, so no rate-limit headers to read." }
  },
  "GET /api/widgets/plan": {
    directives: [{ text: "Ship dashboard front-end", done: false }, { text: "Review Jev threshold results", done: true }, { text: "Reply to landlord", done: false }],
    calendar: "ok", events: [{ time: "10:30", title: "Standup" }, { time: "14:00", title: "Dentist" }]
  },
  "GET /api/widgets/inbox": { configured: true, need_action: 3, items: [{ title: "Reply to landlord about rent", from: "" }, { title: "Confirm dentist appointment", from: "" }, { title: "Renew car insurance", from: "" }] },
  "GET /api/widgets/weekly": { asked_by_tier: { T1: 12, T2: 30, T3: 6, T4: 4, T5: 0 }, asked_total: 52, skills_run: [{ name: "plan-today", count: 5 }, { name: "inbox-brief", count: 3 }], briefs: 14, night_learned: 9 },
  "GET /api/widgets/system": { ollama: { up: true, models: 3 }, last_backup: "2026-11-01T23:30:00+00:00", keys: { groq: true, openrouter: false },
    jobs: [{ job: "aos-bridge", last_run: null, ok: true, detail: "running" }, { job: "aos-night-school", last_run: "2026-11-01T22:00:12", ok: true, detail: "ok" }] },
  "GET /api/widgets/intel": { last_run: "06:30", path: "~/vault/outputs/intel/2026-11-01.md",
    headlines: [{ title: "New open-weights model tops coding benchmark", url: "https://example.com/a", source: "Lab Blog" }, { title: "Cheaper routing for LLM cascades", url: "https://example.com/b", source: "Preprints cs.AI" }, { title: "Show: a local-first agent shell", url: "", source: "Tech Forum" }] },
  "GET /api/night": { last_run: "22:00", learned: 12,
    pending: [{ id: "p1", summary: "Rulebook: route 'summarise' requests to T2" }, { id: "p2", summary: "Shortcut: 'what's on today' answered by T1 calendar" }] },
  "POST /api/ask": { id: "r1", answer: "Short answer: use the T2 local model.\nSecond line shows line breaks are kept. https://example.com stays plain text.",
    final_tier: 2, provider: "ollama", model: "qwen3.5:9b", ms: 2100,
    path: [{ tier: 2, provider: "jev", p: 0.94, step: "jev" }, { tier: 2, provider: "ollama", ok: true, verdict: "pass", ms: 2100 }], saved: true },
  "POST /api/feedback": { ok: true },
  "POST /api/skills/run": { job_id: "demo-job" },
  "GET /api/jobs/demo-job": { state: "done", started: 0, finished: 1, report_path: "~/vault/outputs/plans/2026-11-01.md", error: null },
  "POST /api/night/approve": { ok: true },
  "GET /api/library": {
    total: 6, duplicates: [],
    review: [{ id: 21, original_name: "IMG_4021.jpeg", status: "review", fields: { reason: "low confidence 0.42", category: null } }],
    upcoming: [{ id: 3, title: "Car insurance - Acme", kind: "renews", date: "2026-11-20", days: 18 },
               { id: 4, title: "Passport", kind: "expires", date: "2026-10-28", days: -5 }],
    recent: [{ id: 5, original_name: "a.pdf", note_path: "~/vault/library/Car/2026-10-30 Car insurance.md", fields: { category: "Car", title: "Car insurance - Acme" } },
             { id: 6, original_name: "b.png", note_path: "~/vault/library/Home/2026-10-20 Electricity bill.md", fields: { category: "Home", title: "Electricity bill" } },
             { id: 7, original_name: "c.txt", note_path: "~/vault/library/Health/2026-10-12 GP letter.md", fields: { category: "Health", title: "GP letter" } }] },
  "POST /api/library/file": { id: 21, status: "filed" },
  "POST /api/library/remind": { id: 9, type: "calendar_add", summary: "Calendar: add 'Renew: Car insurance - Acme' Fri 06 Nov 09:00–09:15" },
  "GET /api/actions": { recent: [], pending: [
    { id: 7, type: "email_draft", summary: "Draft: email to jo@example.com — 'Re: rent' (saved, not sent)", created: "2026-11-02T09:12:00",
      payload: { to: "jo@example.com", subject: "Re: rent", body: "Hi Jo,\nThanks — I'll transfer it on Friday.\nFilip" } },
    { id: 8, type: "calendar_add", summary: "Calendar: add 'Dentist' Tue 03 Nov 14:00–14:30", created: "2026-11-02T09:13:00",
      payload: { title: "Dentist", start: "2026-11-03T14:00", end: "2026-11-03T14:30" } }] },
  "POST /api/actions/approve": { id: 7, type: "email_draft", status: "done", decided: "2026-11-02T09:15:00", summary: "",
    result: { path: "~/vault/outputs/drafts/2026-11-02-re-rent.md", mailto: "mailto:jo@example.com?subject=Re%3A%20rent&body=Hi%20Jo" } },
  "POST /api/actions/reject": { id: 8, type: "calendar_add", status: "rejected", decided: "2026-11-02T09:15:00", summary: "", result: null }
};

// ---------- helpers ----------
const DEMO_MODE = new URLSearchParams(location.search).get("demo") === "1";
const $ = (id) => document.getElementById(id);
function el(tag, props, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") n.className = v; else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v);
  }
  for (const c of kids) if (c != null) n.append(c);
  return n;
}
const clear = (n) => { while (n.firstChild) n.removeChild(n.firstChild); };
const TIER_COLOR = { 1: "#5ad1a0", 2: "#63b3ff", 3: "#c4a3ff", 4: "#f2c46d", 5: "#ff7a7a" };

async function api(method, path, body) {
  if (DEMO_MODE) {
    await new Promise((r) => setTimeout(r, 400));
    const act = path.match(/^\/api\/actions\/\d+\/(approve|reject)$/);
    const key = path.startsWith("/api/library/") ? `${method} ` + path.replace(/\/\d+\//, "/") : path.startsWith("/api/skills/") ? "POST /api/skills/run" : act ? "POST /api/actions/" + act[1] : `${method} ${path}`;
    if (!(key in DEMO)) throw new Error("no demo data for " + key);
    return DEMO[key];
  }
  const opt = { method, credentials: "same-origin", headers: {} };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const res = await fetch(path, opt);
  if (res.status === 401) { $("banner").hidden = false; throw new Error("unauthorised"); }
  if (!res.ok) throw new Error(`${path} failed (${res.status})`);
  return res.json();
}
const get = (p) => api("GET", p);
const post = (p, b) => api("POST", p, b);
const msg = (e) => (e && e.message) || String(e);
const hhmm = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); };
const dayTime = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" }); };

// ---------- header ----------
function tickClock() {
  const d = new Date();
  $("clock").textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  $("date").textContent = d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
}
const TIER_CHIPS = [["t1", "T1"], ["jev", "JEV"], ["t2", "T2"], ["t3", "T3"], ["t4", "T4"], ["t5", "T5"]];
async function loadStatus() {
  const ul = $("health");
  try {
    const s = await get("/api/status");
    const tiers = s.tiers || {};
    voice.name = s.tts_voice || null;
    clear(ul);
    for (const [k, label] of TIER_CHIPS) {
      const t = tiers[k] || {};
      const state = t.state === "up" || t.up === true ? "up" : t.state === "degraded" ? "degraded" : "off";
      const word = state === "up" ? "up" : state === "degraded" ? "no key or degraded" : "off";
      ul.append(el("li", { class: "chip " + state, title: t.note || word }, el("span", { class: "dot", "aria-hidden": "true" }), `${label}`, el("span", { class: "sr", text: ": " + word })));
    }
  } catch (e) { clear(ul); ul.append(el("li", { class: "chip", text: "status unavailable" })); }
}

async function loadHealth() {
  try {
    const h = await get("/api/health");
    const bad = (h.jobs || []).filter((j) => !j.ok), dot = $("health-dot");
    if (!bad.length) { dot.hidden = true; dot.removeAttribute("aria-label"); dot.removeAttribute("title"); return; }
    const msg = "Background job problem: " + bad.map((j) => `${j.job} — ${j.detail}`).join("; ");
    dot.setAttribute("aria-label", msg); dot.setAttribute("title", msg); dot.hidden = false;
  } catch (e) { /* leave the dot unchanged */ }
}

// ---------- usage ----------
function setMeter(id, pct, reset) {
  const num = $("u-" + id), bar = $("b-" + id), r = $("r-" + id);
  if (pct == null) { num.textContent = "—"; bar.style.width = "0"; r.textContent = ""; return; }
  num.textContent = Math.round(pct) + "%";
  bar.style.width = Math.min(100, pct) + "%";
  bar.className = pct >= 90 ? "crit" : pct >= 70 ? "warn" : "";
  r.textContent = reset ? "resets " + (id === "session" ? hhmm(reset) : dayTime(reset)) : "";
}
const shortModel = (m) => String(m).replace(/^claude-/, "").replace(/-\d+(-\d+)?(-\d{8})?$/, "");
async function loadUsage() {
  const dl = $("usage-list");
  try {
    const u = await get("/api/usage");
    const c = u.claude || {};
    setMeter("session", c.session_pct, c.session_resets_at);
    setMeter("week", c.week_pct, c.week_resets_at);
    const why = u.unknown_reasons || {};
    const rows = [];
    const add = (name, key, val, fmt) => rows.push([name, val == null ? null : fmt(val), why[key] || "Not available from the source yet."]);
    const tok = u.tokens_today;
    rows.push(["Claude tokens today", tok && tok.length ? tok.map((t) => `${shortModel(t.model)} ${Math.round(t.tokens / 1000)}k`).join(" · ") : null, "ccusage data not available."]);
    add("Jev this month", "jev_usd_month", u.jev_usd_month, (v) => "$" + v.toFixed(v < 0.01 ? 4 : 2));
    add("Groq requests left", "groq_remaining", u.groq_remaining, (v) => v.toLocaleString());
    add("OpenRouter requests left", "openrouter_remaining", u.openrouter_remaining, (v) => v.toLocaleString());
    add("Ollama calls today", "ollama_calls_today", u.ollama_calls_today, String);
    add("Bright Data of free cap", "brightdata_pct", u.brightdata_pct, (v) => v + "%");
    add("Apify of free cap", "apify_pct", u.apify_pct, (v) => v + "%");
    clear(dl);
    for (const [name, val, tip] of rows) {
      const wide = name === "Claude tokens today" && val != null ? " wide" : "";
      dl.append(el("dt", { text: name, class: wide.trim() }), val == null ? el("dd", { text: "—", title: tip, tabindex: "0", "aria-label": "unknown: " + tip }) : el("dd", { text: val, class: wide.trim() }));
    }
  } catch (e) { clear(dl); dl.append(el("dt", { text: "Usage unavailable" }), el("dd", { text: "—", title: msg(e) })); }
}

// ---------- plan ----------
async function loadPlan() {
  const d = $("directives"), ev = $("events");
  try {
    const p = await get("/api/widgets/plan");
    clear(d); clear(ev);
    const dirs = (p.directives || []).slice(0, 3);
    if (!dirs.length) d.append(el("li", { class: "empty", text: "No directives yet." }));
    dirs.forEach((x, i) => {
      const cb = el("input", { type: "checkbox", id: "dir" + i, disabled: "", "aria-label": x.text });
      cb.checked = !!x.done;
      d.append(el("li", { class: x.done ? "done" : "" }, cb, el("span", { text: x.text })));
    });
    if (p.calendar === "denied" || p.calendar_permission === false) ev.append(el("li", { class: "empty", text: "Open KeystoneCalendar in ~/Applications once and allow access" }));
    else if (!(p.events || []).length) ev.append(el("li", { class: "empty", text: "Nothing scheduled." }));
    else for (const e of p.events) ev.append(el("li", {}, el("span", { class: "time", text: e.time || "" }), el("span", { text: e.title || "" })));
  } catch (e) { clear(d); d.append(el("li", { class: "empty", text: "Couldn't load plan: " + msg(e) })); }
}

// ---------- system ----------
function ago(iso) {
  const d = new Date(iso), h = (Date.now() - d) / 36e5;
  if (isNaN(d)) return "";
  if (h < 1) return "just now";
  if (h < 24) return Math.floor(h) + " h ago";
  const day = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  return h < 48 ? "yesterday " + day : Math.floor(h / 24) + " days ago";
}
async function loadSystem() {
  const dl = $("system");
  try {
    const r = await get("/api/widgets/system");
    clear(dl);
    const dot = (cls) => el("span", { class: "sdot " + cls, "aria-hidden": "true" });
    const row = (k, ...kids) => dl.append(el("dt", { text: k }), el("dd", {}, ...kids));
    const o = r.ollama || {};
    row("Local model", dot(o.up ? "ok" : "bad"), o.up ? `up · ${o.models} model${o.models === 1 ? "" : "s"}` : "down");
    if (r.last_backup) dl.append(el("dt", { text: "Last backup" }), el("dd", { text: ago(r.last_backup), title: new Date(r.last_backup).toLocaleString() }));
    else dl.append(el("dt", { text: "Last backup" }), el("dd", { class: "warn", text: "never" }));
    for (const j of r.jobs || []) {
      const name = String(j.job).replace(/^aos-/, "");
      if (j.ok) dl.append(el("dt", { text: name }), el("dd", { class: "dim", text: "ok" }));
      else dl.append(el("dt", { text: name }), el("dd", { class: "bad", title: j.detail }, dot("bad"), j.detail));
    }
    const k = r.keys || {};
    row("Cloud keys", `Groq ${k.groq ? "✓" : "—"} · OpenRouter ${k.openrouter ? "✓" : "—"}`);
  } catch (e) { clear(dl); dl.append(el("dt", { text: "System unavailable" }), el("dd", { text: "—", title: msg(e) })); }
}

// ---------- weekly review ----------
async function loadWeekly() {
  const box = $("weekly");
  try {
    const r = await get("/api/widgets/weekly");
    clear(box);
    box.append(el("div", { class: "big mono", text: String(r.asked_total) }), el("div", { class: "faint small", text: "asks this week" }));
    const tiers = r.asked_by_tier || {}, total = Object.values(tiers).reduce((a, b) => a + b, 0);
    const bar = el("div", { class: "tierbar", "aria-hidden": "true" });
    if (total) for (const t of ["T1", "T2", "T3", "T4", "T5"]) if (tiers[t]) { const seg = el("i"); seg.style.width = (tiers[t] / total * 100) + "%"; seg.style.background = `var(--t${t[1]})`; bar.append(seg); }
    box.append(bar, el("p", { class: "legend", text: ["T1", "T2", "T3", "T4", "T5"].map((t) => `${t} ${tiers[t] || 0}`).join(" · ") }));
    const skills = (r.skills_run || []).reduce((a, b) => a + b.count, 0);
    const dl = el("dl", { class: "kv" });
    const row = (k, v, tip) => dl.append(el("dt", { text: k }), el("dd", { text: String(v), title: tip || "" }));
    row("Skills run", skills, (r.skills_run || []).map((s) => `${s.name} ${s.count}`).join(", "));
    row("Briefs written", r.briefs);
    row("Night-school learned", r.night_learned);
    box.append(dl);
  } catch (e) { clear(box); box.append(el("p", { class: "empty", text: "Couldn't load weekly stats: " + msg(e) })); }
}

// ---------- right column ----------
async function loadInbox() {
  const box = $("inbox");
  try {
    const r = await get("/api/widgets/inbox");
    clear(box);
    if (r.configured === false) {
      box.append(el("p", { class: "empty", text: "Connect Notion to show your inbox" }), el("p", { class: "faint small", text: "Add NOTION_TOKEN to .env, then restart the bridge." }));
      return;
    }
    const items = (r.items || []).slice(0, 5);
    box.append(el("p", { class: "n-need", text: `${r.need_action ?? items.length} need action` }));
    const ul = el("ul", { class: "items" });
    for (const i of items) ul.append(el("li", {}, i.title || "", i.from ? el("span", { class: "sub", text: i.from }) : null));
    box.append(ul);
  } catch (e) { clear(box); box.append(el("p", { class: "empty", text: "Couldn't load inbox: " + msg(e) })); }
}
async function loadIntel() {
  const box = $("intel");
  try {
    const r = await get("/api/widgets/intel");
    clear(box);
    const hs = (r.headlines || []).slice(0, 5);
    if (!hs.length) { box.append(el("p", { class: "empty", text: "Runs daily at 06:30" })); return; }
    const ul = el("ul", { class: "items" });
    for (const h of hs) {
      const title = h.title || String(h);
      ul.append(el("li", {}, /^https?:\/\//i.test(h.url || "") ? el("a", { href: h.url, target: "_blank", rel: "noopener", text: title }) : document.createTextNode(title)));
    }
    box.append(ul, el("p", { class: "faint small", text: r.last_run ? "Last run " + r.last_run : "" }));
  } catch (e) { clear(box); box.append(el("p", { class: "empty", text: "Runs daily at 06:30" })); }
}
async function loadNight() {
  const sec = $("night"), box = $("night-body");
  try {
    const r = await get("/api/night");
    clear(box);
    const pend = r.pending || [];
    sec.classList.toggle("pending", pend.length > 0);
    if (!pend.length) { box.append(el("p", { class: "empty", text: `Last run ${r.last_run || "—"} · nothing pending` })); return; }
    box.append(el("p", { text: `Learned ${r.learned ?? 0} routes · ${pend.length} changes need your OK` }));
    const list = el("div", { hidden: "" });
    const btn = el("button", { type: "button", class: "review", "aria-expanded": "false", text: "Review", onclick: () => {
      list.hidden = !list.hidden; btn.setAttribute("aria-expanded", String(!list.hidden));
    } });
    for (const p of pend) {
      const row = el("div", { class: "prop" }, el("span", { text: p.summary || p.id }));
      row.append(el("button", { type: "button", "aria-label": "Approve: " + (p.summary || p.id), text: "Approve", onclick: async (ev) => {
        ev.target.disabled = true;
        try { await post("/api/night/approve", { proposal_id: p.id }); loadNight(); } catch (e) { ev.target.disabled = false; row.append(el("span", { class: "small", style: "color:var(--t5)", text: msg(e) })); }
      } }));
      list.append(row);
    }
    box.append(btn, list);
  } catch (e) { clear(box); box.append(el("p", { class: "empty", text: "Couldn't load: " + msg(e) })); }
}

// ---------- pending actions ----------
const ACTION_CHIP = { notion_task_update: "NOTION", calendar_add: "CALENDAR", email_draft: "DRAFT" };
const decidedActions = new Map(); // id -> {action, outcome}; decided this session, kept on screen
function actionStatus(a, outcome) {
  if (outcome.error) return el("p", { class: "act-status err", text: "Failed: " + outcome.error });
  const r = outcome.result || {};
  if (r.status === "rejected") return el("p", { class: "act-status", text: "Rejected" });
  if (r.status === "failed") return el("p", { class: "act-status err", text: "Failed: " + (r.result || "unknown error") });
  const line = el("p", { class: "act-status", text: "Done" });
  const res = r.result || {};
  if (a.type === "email_draft" && typeof res === "object") {
    if (/^mailto:/i.test(res.mailto || "")) line.append(el("a", { href: res.mailto, rel: "noopener", text: "Open in mail app" }));
    if (res.path) line.append(el("span", { class: "act-path", text: res.path }));
  }
  return line;
}
function actionItem(a) {
  const item = el("div", { class: "act" },
    el("div", { class: "act-head" }, el("span", { class: "achip", text: ACTION_CHIP[a.type] || String(a.type).toUpperCase() }), el("span", { class: "act-sum", text: a.summary || "" })),
    el("pre", { text: JSON.stringify(a.payload || {}, null, 2) }));
  const done = decidedActions.get(a.id);
  if (done) { item.append(actionStatus(a, done)); return item; }
  const btns = el("div", { class: "act-btns" });
  const decide = async (verb) => {
    for (const b of btns.querySelectorAll("button")) b.disabled = true;
    let outcome;
    try { outcome = { result: await post(`/api/actions/${encodeURIComponent(a.id)}/${verb}`, {}) }; }
    catch (e) { outcome = { error: msg(e) }; }
    decidedActions.set(a.id, { action: a, ...outcome });
    btns.replaceWith(actionStatus(a, outcome));
    loadActions();
  };
  btns.append(el("button", { type: "button", class: "approve", "aria-label": "Approve: " + (a.summary || a.type), text: "Approve", onclick: () => decide("approve") }),
    el("button", { type: "button", class: "tbtn", "aria-label": "Reject: " + (a.summary || a.type), text: "Reject", onclick: () => decide("reject") }));
  item.append(btns);
  return item;
}
async function loadActions() {
  const sec = $("actions"), box = $("actions-body");
  try {
    const r = await get("/api/actions");
    const pend = (r.pending || []).filter((a) => !decidedActions.has(a.id));
    $("actions-n").textContent = String(pend.length);
    sec.hidden = !pend.length && !decidedActions.size;
    // keep focus stable: only rebuild when something changed
    const sig = JSON.stringify([pend.map((a) => a.id), [...decidedActions.keys()]]);
    if (box.dataset.sig === sig) return;
    box.dataset.sig = sig; clear(box);
    for (const a of pend) box.append(actionItem(a));
    for (const d of [...decidedActions.values()].reverse()) box.append(actionItem(d.action));
  } catch (e) { /* keep the last rendered state */ }
}

// ---------- library ----------
const LIB_CATEGORIES = ["Insurance", "Contracts", "Payments", "Health", "ID", "Home", "Car", "Work", "Other"];
const reminded = new Set(); // "id:kind" proposed this session
let libSig = "";
function libSelect(label, ph, opts, cur) {
  const sel = el("select", { "aria-label": label }, el("option", { value: "", text: ph }));
  for (const o of opts) sel.append(el("option", { value: o, text: o }));
  sel.value = opts.includes(cur) ? cur : "";
  return sel;
}
function reviewItem(r) {
  const f = r.fields || {};
  const category = libSelect("Category for " + r.original_name, "Category…", LIB_CATEGORIES, f.category);
  const err = el("p", { class: "lib-err", role: "alert", hidden: "" });
  const btn = el("button", { type: "button", class: "lib-file", "aria-label": "File " + r.original_name, text: "File" });
  btn.addEventListener("click", async () => {
    err.hidden = true;
    if (!category.value) { err.textContent = "Pick a category first."; err.hidden = false; return; }
    btn.disabled = true;
    try { await post(`/api/library/${encodeURIComponent(r.id)}/file`, { category: category.value }); libSig = ""; await loadLibrary(); }
    catch (e) { err.textContent = "Couldn't file it: " + msg(e); err.hidden = false; btn.disabled = false; }
  });
  return el("li", { class: "lib-item" }, el("span", { class: "lib-name", text: r.original_name }),
    el("span", { class: "lib-reason", text: f.reason || "needs a look" }), el("div", { class: "lib-pick" }, category, btn, err));
}
function upcomingItem(u) {
  const key = u.id + ":" + u.kind, late = u.days < 0;
  const row = el("li", { class: "lib-up" + (late ? " late" : "") }, el("span", { class: "d", text: u.date }),
    el("span", { class: "k", text: (u.kind === "renews" ? "Renews" : "Expires") + (late ? " (overdue)" : "") }),
    el("span", { class: "t", text: u.title || "Untitled" }));
  if (reminded.has(key)) { row.append(el("span", { class: "done", text: "Reminder proposed" })); return row; }
  const b = el("button", { type: "button", class: "tbtn", "aria-label": `Remind me: ${u.title || "document"}`, text: "Remind me" });
  b.addEventListener("click", async () => {
    b.disabled = true;
    try { await post(`/api/library/${encodeURIComponent(u.id)}/remind`, { kind: u.kind }); reminded.add(key); b.replaceWith(el("span", { class: "done", text: "Reminder proposed" })); loadActions(); }
    catch (e) { b.disabled = false; b.textContent = "Retry"; b.title = msg(e); }
  });
  row.append(b);
  return row;
}
function renderLibrary(r) {
  const box = $("lib-body"); clear(box);
  const chips = el("div", { class: "chips" });
  chips.append(el("span", { class: "stagechip" }, "Documents", el("b", { text: String(r.total || 0) })));
  box.append(chips);
  const review = (r.review || []).filter((x) => (x.fields || {}).reason !== "processing");
  if (review.length) {
    box.append(el("h3", { class: "label lib-need", text: "Needs a look · " + review.length }));
    const ul = el("ul"); for (const x of review) ul.append(reviewItem(x)); box.append(ul);
  }
  if ((r.upcoming || []).length) {
    box.append(el("h3", { class: "label faint-label", text: "Coming up" }));
    const ul = el("ul"); for (const u of r.upcoming) ul.append(upcomingItem(u)); box.append(ul);
  }
  const recent = (r.recent || []).slice(0, 5);
  if (recent.length) {
    box.append(el("h3", { class: "label faint-label", text: "Recently filed" }));
    const ul = el("ul", {});
    for (const x of recent) {
      const f = x.fields || {};
      const a = el("a", { class: "lib-rec", href: "obsidian://open?path=" + encodeURIComponent(x.note_path || ""), "aria-label": `Open note: ${f.title || x.original_name}` },
        el("span", { class: "sub", text: `${f.category} · ` }), f.title || x.original_name);
      ul.append(el("li", {}, a));
    }
    box.append(ul);
  } else if (!review.length) box.append(el("p", { class: "empty", text: "Nothing filed yet." }));
}
async function loadLibrary() {
  try {
    const r = await get("/api/library");
    const sig = JSON.stringify(r);
    if (sig !== libSig) { libSig = sig; renderLibrary(r); }
    return r;
  } catch (e) { clear($("lib-body")); $("lib-body").append(el("p", { class: "empty", text: "Couldn't load library: " + msg(e) })); libSig = ""; return null; }
}
const LIB_ERR = { 413: "is over 25 MB. Split or compress it, then try again.", 415: "isn't a supported type. Use pdf, an image, txt, md, csv, doc, docx, rtf or odt." };
async function sendFile(f, desc) {
  if (DEMO_MODE) { await new Promise((r) => setTimeout(r, 400)); return f.name; }
  const headers = { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(f.name) };
  if (desc) headers["X-Description"] = encodeURIComponent(desc);
  const res = await fetch("/api/library/upload", { method: "POST", credentials: "same-origin", headers, body: f });
  if (res.status === 401) { $("banner").hidden = false; throw new Error("unauthorised. Reload the page."); }
  if (!res.ok) throw new Error(LIB_ERR[res.status] || `failed (${res.status}). Try again.`);
  return (await res.json()).name;
}
let libBusy = false;
async function uploadFiles(files) {
  files = [...files];
  const st = $("lib-status");
  if (!files.length || libBusy) return;
  libBusy = true; st.className = "lib-status mono";
  const desc = $("lib-desc").value.trim().slice(0, 500);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    const base = await get("/api/library");
    const maxId = Math.max(0, ...[...(base.recent || []), ...(base.review || []), ...(base.duplicates || [])].map((x) => x.id));
    st.textContent = `Reading ${files.length} document${files.length > 1 ? "s" : ""}…`;
    const names = new Set(), errs = [];
    for (const f of files) {
      try { names.add(await sendFile(f, desc)); } catch (e) { errs.push(`${f.name} ${msg(e)}`); }
    }
    const fail = () => { if (!errs.length) return; st.className = "lib-status mono err"; for (const e of errs) st.append(el("span", { class: "e", text: e })); };
    if (!names.size) { st.textContent = ""; fail(); return; }
    $("lib-desc").value = "";
    let filed = 0, look = 0, dup = 0;
    for (let i = 0; i < 60; i++) {
      await sleep(DEMO_MODE ? 800 : 3000);
      const r = await loadLibrary(); if (!r) continue;
      const rows = [...(r.recent || []).map((x) => [x, "f"]), ...(r.review || []).filter((x) => (x.fields || {}).reason !== "processing").map((x) => [x, "r"]),
        ...(r.duplicates || []).map((x) => [x, "d"])].filter(([x]) => x.id > maxId && (DEMO_MODE || names.has(x.original_name)));
      filed = rows.filter(([, k]) => k === "f").length; look = rows.filter(([, k]) => k === "r").length; dup = rows.filter(([, k]) => k === "d").length;
      if (DEMO_MODE) { filed = names.size; look = 0; }
      if (filed + look + dup >= names.size) break;
    }
    const total = filed + look + dup;
    st.textContent = total >= names.size ? ["Filed " + filed, look ? `${look} needs a look` : "", dup ? `${dup} duplicate${dup > 1 ? "s" : ""}` : ""].filter(Boolean).join(" · ")
      : `Still reading ${names.size - total} — check back soon.`;
    fail();
    if (!errs.length) setTimeout(() => { if (!libBusy) st.textContent = ""; }, 8000);
  } catch (e) { st.className = "lib-status mono err"; st.textContent = "Upload failed: " + msg(e); }
  finally { libBusy = false; }
}
function wireLibrary() {
  const drop = $("lib-drop"), input = $("lib-file");
  for (const ev of ["dragenter", "dragover"]) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); });
  for (const ev of ["dragleave", "drop"]) drop.addEventListener(ev, () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); uploadFiles(e.dataTransfer.files); });
  input.addEventListener("change", () => { uploadFiles(input.files); input.value = ""; });
  // a miss must not make the browser navigate to the dropped file
  for (const ev of ["dragover", "drop"]) window.addEventListener(ev, (e) => { if (!drop.contains(e.target)) e.preventDefault(); });
}

// ---------- skills ----------
function wireSkills() {
  document.querySelectorAll("[data-skill]").forEach((b) => b.addEventListener("click", async () => {
    const name = b.dataset.skill, orig = b.textContent;
    b.disabled = true; clear(b); b.append(el("span", { class: "spin", "aria-hidden": "true" }), "Running…");
    const done = (node) => { b.disabled = false; b.textContent = orig; const box = $("skill-notes"); clear(box); if (node) box.append(node); };
    try {
      const { job_id } = await post(`/api/skills/${encodeURIComponent(name)}/run`, {});
      for (;;) {
        await new Promise((r) => setTimeout(r, DEMO_MODE ? 800 : 3000));
        const j = await get("/api/jobs/" + encodeURIComponent(job_id));
        if (j.state === "done") {
          done(j.report_path ? el("a", { class: "report", href: "obsidian://open?path=" + encodeURIComponent(j.report_path), text: "Report ready" }) : el("span", { class: "skillnote", text: "Done" }));
          if (name === "plan-today") loadPlan(); else if (name === "inbox-brief") loadInbox(); else if (name === "morning-intel") loadIntel(); else if (name === "weekly-review") loadWeekly();
          return;
        }
        if (j.state === "error" || j.state === "failed") { done(el("span", { class: "skillnote", style: "color:var(--t5)", text: "Failed: " + (j.error || "unknown error") + ". Check the bridge log, then retry." })); return; }
      }
    } catch (e) { done(el("span", { class: "skillnote", style: "color:var(--t5)", text: "Couldn't run: " + msg(e) })); }
  }));
}

// ---------- ask + answers ----------
const core = { tint: null, tintUntil: 0, busy: false };
const answers = []; // newest first, max 10
function tierOf(a) { return Number(a.final_tier) || 0; }
function pathLine(a) {
  const steps = (a.path || []).map((s) => {
    if (s.provider === "jev" || s.step === "jev") return `jev T${s.tier} ${s.p != null ? Number(s.p).toFixed(2) : ""}`.trim();
    const bits = [`T${s.tier}`, s.ok === false ? "failed" : "answered"];
    if (s.verdict) bits.push("check " + s.verdict);
    return bits.join(" → ").replace(/^T(\d) → /, "");
  });
  const head = steps.join(" → ");
  return `${head}${head ? " · " : ""}${(a.ms / 1000).toFixed(1)}s`;
}
function renderAnswers() {
  const box = $("answers"); clear(box);
  answers.forEach((a, i) => {
    const t = tierOf(a), color = TIER_COLOR[t] || "var(--muted)";
    const chip = el("span", { class: "tchip", style: "color:" + color, text: a.error ? "Error" : `T${t} · ${a.model || a.provider}` });
    if (i > 0) {
      const old = el("div", { class: "card old", tabindex: "0", role: "button", "aria-label": "Expand previous answer" }, chip,
        el("span", { class: "line", text: (a.error || a.answer || "").replace(/\s+/g, " ") }));
      const open = () => { answers.splice(0, 0, answers.splice(i, 1)[0]); renderAnswers(); };
      old.addEventListener("click", open); old.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
      box.append(old); return;
    }
    const card = el("article", { class: "card" }, chip);
    if (a.error) { card.append(el("p", { class: "text err", text: a.error + " — check the bridge is running and try again." })); box.append(card); return; }
    card.append(el("div", { class: "path", text: pathLine(a) }), el("p", { class: "text", text: a.answer }));
    const nAct = (a.actions || []).length;
    if (nAct) card.append(el("p", { class: "proposed", text: `Proposed ${nAct} action${nAct === 1 ? "" : "s"} — review above` }));
    const foot = el("div", { class: "foot" });
    for (const [icon, verdict, label] of [["up", "up", "Good answer"], ["down", "down", "Bad answer"], ["Escalate", "escalate", "Escalate to the next tier"]]) {
      const b = el("button", { type: "button", class: "ibtn", "aria-label": label, onclick: async () => {
        b.disabled = true;
        try {
          const r = await post("/api/feedback", { id: a.id, verdict });
          if (verdict === "escalate" && r && r.answer) { answers.unshift(r); answers.length = Math.min(answers.length, 10); renderAnswers(); flash(r); speakAnswer(r); loadActions(); }
          else b.classList.add("on");
        } catch (e) { b.disabled = false; foot.append(el("span", { class: "small err", text: msg(e) })); }
      } });
      if (icon === "Escalate") b.textContent = icon; else b.append(thumb(icon === "up"));
      foot.append(b);
    }
    if (a.saved !== false) foot.append(el("span", { class: "saved", text: "Saved to vault" }));
    card.append(foot); box.append(card);
  });
}
function thumb(up) {
  const NS = "http://www.w3.org/2000/svg", s = document.createElementNS(NS, "svg"), p = document.createElementNS(NS, "path");
  s.setAttribute("viewBox", "0 0 16 16"); s.setAttribute("aria-hidden", "true");
  p.setAttribute("d", up ? "M5 7v7H2V7zM5 7l3-5c1.5 0 2 1 1.700 2.200L9.300 6H13a1 1 0 0 1 1 1.200l-1 5A1.500 1.500 0 0 1 11.500 14H5" : "M5 9V2H2v7zM5 9l3 5c1.500 0 2-1 1.700-2.200L9.300 10H13a1 1 0 0 0 1-1.200l-1-5A1.500 1.500 0 0 0 11.500 2H5");
  s.append(p); return s;
}
function flash(a) {
  const t = tierOf(a);
  core.tint = TIER_COLOR[t] || null; core.tintUntil = performance.now() + 3000;
  $("core-label").textContent = a.error ? "error" : `${(a.path || []).length ? pathLine(a) : "T" + t} `;
}
function wireAsk() {
  const mode = $("ask-mode"), model = $("ask-model"), text = $("ask-text"), form = $("ask");
  mode.addEventListener("change", () => { model.hidden = mode.value !== "model"; });
  // Esc priority (speaking > countdown > clear text) lives in wireVoice's document handler.
  wireVoice(form, text);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const t = text.value.trim();
    if (!t || core.busy) return;
    const body = { text: t, mode: "auto" };
    if (mode.value.startsWith("tier:")) { body.mode = "tier"; body.tier = Number(mode.value.slice(5)); }
    else if (mode.value === "model") { if (!model.value.trim()) { model.focus(); return; } body.mode = "model"; body.model = model.value.trim(); }
    core.busy = true; form.classList.add("busy"); form.setAttribute("aria-busy", "true");
    core.tint = body.tier ? TIER_COLOR[body.tier] : null; core.tintUntil = Infinity;
    $("core-label").textContent = "Thinking…";
    try {
      const a = await post("/api/ask", body);
      answers.unshift(a); answers.length = Math.min(answers.length, 10); text.value = ""; flash(a); speakAnswer(a);
    } catch (err) {
      answers.unshift({ error: msg(err), ms: 0 }); answers.length = Math.min(answers.length, 10);
      core.tint = null; $("core-label").textContent = "error";
    }
    core.busy = false; form.classList.remove("busy"); form.removeAttribute("aria-busy");
    renderAnswers(); loadActions();
  });
}

// ---------- voice out + pause-to-send ----------
const voice = { name: null, on: false, speaking: false, gen: 0 };
const store = {
  get(k) { try { return localStorage.getItem(k) === "1"; } catch (e) { return false; } },
  set(k, v) { try { localStorage.setItem(k, v ? "1" : "0"); } catch (e) { /* ignore */ } },
};
function pickVoice() {
  const vs = speechSynthesis.getVoices(), gb = vs.filter((v) => /^en[-_]GB$/i.test(v.lang));
  return vs.find((v) => voice.name && v.name === voice.name)
    || gb.find((v) => /premium|enhanced/i.test(v.name))
    || gb.find((v) => /^Daniel\b/.test(v.name))
    || gb.find((v) => v.localService) || gb[0] || null;
}
function speechText(raw) {
  let t = String(raw).replace(/```[\s\S]*?(```|$)/g, " code block on screen. ")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/[#*_`>]/g, "").replace(/\s+/g, " ").trim();
  if (t.length > 600) {
    const cut = t.slice(0, 600), i = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("! "), cut.lastIndexOf("? "));
    t = (i > 0 ? cut.slice(0, i + 1) : cut) + " Full answer on screen.";
  }
  return t;
}
let setStatus = () => {};
function speakAnswer(a) {
  if (!voice.on || !window.speechSynthesis || !a || a.error || !a.answer) return;
  speechSynthesis.cancel();
  const gen = ++voice.gen; // a cancelled earlier answer's onend must not clear this one's state
  const sentences = speechText(a.answer).match(/[^.!?]+[.!?]*\s*/g) || [];
  const v = pickVoice();
  sentences.forEach((s, i) => {
    if (!s.trim()) return;
    const u = new SpeechSynthesisUtterance(s);
    if (v) { u.voice = v; u.lang = v.lang; }
    if (i === sentences.length - 1) u.onend = u.onerror = () => { if (gen === voice.gen) { voice.speaking = false; setStatus(""); } };
    speechSynthesis.speak(u);
  });
  voice.speaking = true; setStatus("Speaking · Esc to stop");
}
function wireVoice(form, text) {
  const vt = $("voice-toggle"), pt = $("pause-toggle"), status = $("ask-status"), live = $("ask-live");
  let timer = null, tick = null;
  setStatus = (s) => { status.textContent = s; };
  const stopCount = () => { clearTimeout(timer); clearInterval(tick); timer = tick = null; setStatus(voice.speaking ? "Speaking · Esc to stop" : ""); };
  const startCount = () => {
    stopCount();
    const end = performance.now() + 2500;
    setStatus("Sending in 2.5s · any key cancels"); live.textContent = "Sending in 2.5 seconds. Any key cancels.";
    tick = setInterval(() => setStatus(`Sending in ${Math.max(0, (end - performance.now()) / 1000).toFixed(1)}s · any key cancels`), 100);
    timer = setTimeout(() => { stopCount(); live.textContent = ""; if (!core.busy && text.value.trim()) form.requestSubmit(); }, 2500);
  };
  const bind = (btn, key, on) => {
    const set = (v) => { btn.setAttribute("aria-pressed", String(v)); store.set(key, v); on(v); };
    btn.addEventListener("click", () => set(btn.getAttribute("aria-pressed") !== "true"));
    const v = store.get(key); btn.setAttribute("aria-pressed", String(v)); on(v);
  };
  if (!window.speechSynthesis) vt.hidden = true;
  else {
    const refresh = () => { const v = pickVoice(); if (v) vt.title = "Voice: " + v.name; };
    speechSynthesis.addEventListener("voiceschanged", refresh); refresh();
  }
  bind(vt, "aos.voice", (v) => { voice.on = v && !!window.speechSynthesis; if (!v && window.speechSynthesis) { speechSynthesis.cancel(); voice.speaking = false; setStatus(""); } });
  bind(pt, "aos.pauseSend", (v) => { if (!v) stopCount(); });
  text.addEventListener("keydown", (e) => { if (timer && e.key !== "Escape") stopCount(); });
  text.addEventListener("input", () => { if (pt.getAttribute("aria-pressed") === "true" && text.value.trim() && !core.busy) startCount(); else stopCount(); });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (voice.speaking || (window.speechSynthesis && speechSynthesis.speaking)) { speechSynthesis.cancel(); voice.speaking = false; setStatus(""); }
    else if (timer) stopCount();
    else if (document.activeElement === text) text.value = "";
  });
}

// ---------- core canvas ----------
function startCore() {
  const cv = $("core"), ctx = cv.getContext("2d");
  const N = 500, pts = [];
  for (let i = 0; i < N; i++) {
    const u = Math.random() * 2 - 1, th = Math.random() * Math.PI * 2, r = Math.sqrt(1 - u * u);
    pts.push({ x: r * Math.cos(th), y: u, z: r * Math.sin(th), ph: Math.random() * 6.28 });
  }
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  let W = 0, H = 260, dpr = 1, angle = 0.6, raf = 0, last = 0, tintMix = 0;
  const ACCENT = [124, 140, 255];
  const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  function size() {
    dpr = window.devicePixelRatio || 1; W = cv.clientWidth; H = 260;
    cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (reduce.matches || document.hidden) draw(0);
  }
  function draw(t) {
    const now = performance.now();
    const wantTint = core.tint && now < core.tintUntil ? 1 : 0;
    tintMix += (wantTint - tintMix) * 0.06;
    const tc = core.tint ? rgb(core.tint) : ACCENT;
    const c = ACCENT.map((v, i) => Math.round(v + (tc[i] - v) * tintMix));
    const pulse = core.busy ? 0.5 + 0.5 * Math.sin(t / 220) : 0;
    const Rx = Math.min(W * 0.3, H * 0.4) * (1 + pulse * 0.04), Ry = Rx, cx = W / 2, cy = H / 2;
    ctx.clearRect(0, 0, W, H);
    const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.min(H / 2, Rx * 1.35));
    g.addColorStop(0, `rgba(${c},${0.16 + pulse * 0.14})`); g.addColorStop(1, `rgba(${c},0)`);
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    const ca = Math.cos(angle), sa = Math.sin(angle), tilt = 0.35, ct = Math.cos(tilt), st = Math.sin(tilt);
    const P = pts.map((p) => {
      const x = p.x * ca - p.z * sa, z0 = p.x * sa + p.z * ca;
      const y = p.y * ct - z0 * st, z = p.y * st + z0 * ct;
      const w = 1 + 0.03 * Math.sin(t / 900 + p.ph);
      return { x: cx + x * Rx * w, y: cy + y * Ry * w, z };
    });
    ctx.lineWidth = 1;
    for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
      const dx = P[i].x - P[j].x; if (dx > 46 || dx < -46) continue;
      const dy = P[i].y - P[j].y; if (dy > 46 || dy < -46) continue;
      const d = Math.hypot(dx, dy);
      if (d < 46) { ctx.strokeStyle = `rgba(${c},${(1 - d / 46) * 0.16 * (0.4 + (P[i].z + 1) * 0.3)})`; ctx.beginPath(); ctx.moveTo(P[i].x, P[i].y); ctx.lineTo(P[j].x, P[j].y); ctx.stroke(); }
    }
    for (const p of P) { ctx.fillStyle = `rgba(${c},${0.35 + (p.z + 1) * 0.3})`; ctx.fillRect(p.x - 1, p.y - 1, 2, 2); }
  }
  function frame(t) {
    const dt = last ? Math.min(t - last, 50) : 16; last = t;
    angle += dt * 0.00012 * (core.busy ? 3 : 1);
    draw(t); raf = requestAnimationFrame(frame);
  }
  function run() {
    cancelAnimationFrame(raf); raf = 0; last = 0;
    if (reduce.matches || document.hidden) { draw(0); return; }
    raf = requestAnimationFrame(frame);
  }
  window.addEventListener("resize", size);
  document.addEventListener("visibilitychange", run);
  reduce.addEventListener("change", run);
  size(); run();
}

// ---------- boot ----------
tickClock(); setInterval(tickClock, 15000);
wireAsk(); wireSkills(); wireLibrary(); startCore();
if (DEMO_MODE) $("core-label").textContent = "demo data · idle";
loadStatus(); loadHealth(); loadUsage(); loadPlan(); loadInbox(); loadIntel(); loadNight(); loadActions(); loadSystem(); loadWeekly(); loadLibrary();
setInterval(() => { loadStatus(); loadHealth(); loadUsage(); loadSystem(); }, 60000);
