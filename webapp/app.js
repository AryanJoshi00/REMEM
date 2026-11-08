/* REMEM student app (PWA). Plain JS, no build step. All server text is inserted with textContent (never innerHTML). */
"use strict";

const CONSENT_TEXT =
`REMEM pilot - what you agree to

- This is a university project. You are using an anonymous account; no name or email is stored.
- Your answers, response times and review history are recorded to evaluate the scheduling model.
- Notes you paste are sent to an external AI service (Google Gemini) to create quiz questions. Free-tier AI services may allow the provider to use submitted content. Do NOT paste personal, confidential or exam-restricted material.
- Participation is voluntary. You may stop at any time and ask the project owner to delete your data.
- The app gives study suggestions only; it does not prove that it improves learning.`;

const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage blocked: keep going */ } },
  del(k) { try { localStorage.removeItem(k); } catch (e) {} },
};
const S = { token: store.get("remem_token"), role: store.get("remem_role"), user: store.get("remem_user") };

// ---------------------------------------------------------------- DOM helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}
function rich(text) {            // **bold** -> <b>, everything else plain text
  const span = h("span");
  String(text).split("**").forEach((p, i) => span.append(i % 2 ? h("b", {}, p) : document.createTextNode(p)));
  return span;
}
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2600);
}
function mount(...nodes) {
  const app = document.getElementById("app"); app.replaceChildren(...nodes.flat()); window.scrollTo(0, 0);
  const h1 = app.querySelector("h1");
  document.title = (h1 ? h1.textContent + " - " : "") + "REMEM";
  if (h1) { h1.tabIndex = -1; h1.focus({ preventScroll: true }); }          // a route change moves the reading position to the new heading
}

// ---------------------------------------------------------------- API
async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (S.token) headers.Authorization = "Bearer " + S.token;
  const r = await fetch("api" + path, { method: opts.method || "GET", headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (r.status === 401 && S.token) { signOut(false); throw new Error("Please sign in again."); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || ("Error " + r.status));
  return data;
}
function signOut(call = true) {
  if (call && S.token) fetch("api/auth/logout", { method: "POST", headers: { Authorization: "Bearer " + S.token } }).catch(() => {});
  S.token = S.role = S.user = null;
  ["remem_token", "remem_role", "remem_user", "remem_queue", "remem_due"].forEach(store.del);
  if ("caches" in window) caches.delete("remem-api").catch(() => {});
  location.hash = "#/login"; route();
}

// ---------------------------------------------------------------- offline answer queue (replayed once thanks to idempotency keys)
function queue() { try { return JSON.parse(store.get("remem_queue") || "[]"); } catch (e) { return []; } }
function saveQueue(q) { store.set("remem_queue", JSON.stringify(q)); }
async function flushQueue() {
  const q = queue(); if (!q.length || !S.token) return;
  const rest = [];
  for (const item of q) {
    try { await api("/respond", { method: "POST", body: item }); }
    catch (e) { if (e instanceof TypeError || /Failed to fetch|NetworkError/i.test(e.message)) rest.push(item); }
  }
  saveQueue(rest);
  if (rest.length < q.length) toast("Synced " + pl(q.length - rest.length, "saved answer"));
}
window.addEventListener("online", flushQueue);

const pl = (n, w) => n + " " + w + (Number(n) === 1 ? "" : "s");     // 1 day, 2 days
// ---------------------------------------------------------------- nav
const ICONS = {       // one drawn set: 24px grid, 1.8 stroke, round caps
  today: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM8 12.5l3 3 5-6",
  notes: "M6 3h8l4 4v14H6zM14 3v4h4M12 11v6M9 14h6",
  concepts: "M4 6h16M4 12h16M4 18h10",
  me: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 3.6-6 8-6s8 2 8 6",
};
function icon(name, cls) {
  const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); if (cls) svg.setAttribute("class", cls);
  const path = document.createElementNS(NS, "path"); path.setAttribute("d", name.startsWith("M") ? name : ICONS[name]); svg.append(path); return svg;
}
function dueCount() { try { const d = JSON.parse(store.get("remem_due") || "null"); return d ? d.due.length : 0; } catch (e) { return 0; } }
function renderNav() {
  const nav = document.getElementById("nav"), who = document.getElementById("who");
  nav.replaceChildren(); who.textContent = S.token ? S.user : "";
  if (!S.token) return;
  const cur = location.hash || "#/", n = dueCount();
  [["#/", "Today", "today"], ["#/notes", "Notes", "notes"], ["#/concepts", "Concepts", "concepts"], ["#/me", "Me", "me"]].forEach(([href, label, ic]) =>
    nav.append(h("a", { href, class: cur === href ? "on" : "", "aria-current": cur === href ? "page" : false },
      icon(ic), label, href === "#/" && n ? h("span", { class: "badge", "aria-label": pl(n, "concept") + " due" }, String(n)) : null)));
}

// ---------------------------------------------------------------- views
const THETA_UI = 0.85;
function skeleton(n, hero) { return h("div", { "aria-busy": "true", "aria-label": "Loading" }, hero ? h("div", { class: "skel hero" }) : null, Array.from({ length: n }, () => h("div", { class: "skel" }))); }
function meter(R, fading) {            // the freshness bar: how much you still remember
  const pct = Math.round(R * 100);
  return h("div", { class: "meter" + (fading ? " fading" : ""), role: "meter", "aria-label": "Recall", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": pct, "aria-valuetext": pct + "% recall" }, h("i", { style: "--v:" + R }));
}
function daysText(d) { d = Number(d.toFixed(1)); return d < 0.05 ? "today" : "in " + pl(d, "day"); }

function viewLogin() {
  const err = h("div", { class: "err", role: "alert" });
  const u = h("input", { autocomplete: "username", autocapitalize: "none", spellcheck: "false", placeholder: "e.g. user01" });
  const p = h("input", { type: "password", autocomplete: "current-password" });
  const showBtn = h("button", { type: "button", "aria-pressed": "false", onclick: () => { const on = p.type === "password"; p.type = on ? "text" : "password"; showBtn.textContent = on ? "Hide" : "Show"; showBtn.setAttribute("aria-pressed", String(on)); } }, "Show");
  const go = h("button", { class: "primary block", type: "submit" }, "Sign in");
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault(); err.textContent = ""; go.disabled = true;
    try {
      const r = await api("/auth/login", { method: "POST", body: { username: u.value.trim(), password: p.value } });
      S.token = r.token; S.role = r.role; S.user = r.username;
      store.set("remem_token", r.token); store.set("remem_role", r.role); store.set("remem_user", r.username);
      location.hash = r.consent_ok ? "#/" : "#/consent"; route();
    } catch (ex) { err.textContent = ex.message; go.disabled = false; }
  } }, h("div", {}, h("label", { for: "u" }, "Username"), u), h("div", {}, h("label", { for: "p" }, "Password"), h("div", { class: "pw" }, p, showBtn)), err, go);
  u.id = "u"; p.id = "p";
  mount(h("h1", {}, "Remember what you study"), h("p", { class: "muted" }, "REMEM tells you what to revise, and when. Your project owner gives you a username and password."), form);
}

function viewConsent() {
  const ok = h("button", { class: "primary block", onclick: async () => {
    try { await api("/auth/consent", { method: "POST" }); location.hash = "#/"; route(); } catch (e) { toast(e.message); }
  } }, "I agree");
  mount(h("h1", {}, "Before you start"), h("div", { class: "panel consent" }, CONSENT_TEXT), ok,
        h("p", {}, h("button", { class: "block", onclick: () => signOut() }, "No thanks, sign out")));
}

function renderHome(d) {
  const nodes = [h("h1", {}, "Today")];
  const counts = [d.due.length ? d.due.length + " due" : "", d.new.length ? d.new.length + " new" : ""].filter(Boolean).join(", ");
  if (counts) nodes.push(h("p", { class: "muted" }, counts));
  const lead = d.due[0] || d.new[0];
  const row = (c, kind) => {
    const href = kind === "later" ? "#/curve/" + c.concept_id : "#/practice/" + c.concept_id;
    const kids = [h("span", { class: "name" }, c.name)];
    if (c.new) kids.push(h("span", { class: "when" }, "not studied yet"), h("div", { class: "meter empty", "aria-hidden": "true" }));
    else {
      const late = kind === "due";
      kids.push(h("span", { class: "when" + (late ? " late" : "") }, late ? "review now" : daysText(c.due_in_days)), meter(c.R_now, late || c.R_now < THETA_UI));
    }
    return h("li", {}, h("a", { class: "item", href }, kids));
  };
  const section = (title, items, kind) => { if (items.length) nodes.push(h("h2", {}, title), h("ul", { class: "ledger" }, items.map(c => row(c, kind)))); };
  if (lead) {
    nodes.push(h("div", { class: "next" }, h("h2", {}, lead.name), h("p", {}, lead.new ? "New concept. Take the first quiz." : "Your recall has dropped to about " + Math.round(lead.R_now * 100) + "%. A quick review brings it back."),
      h("a", { class: "btn", href: "#/practice/" + lead.concept_id }, lead.new ? "Start the quiz" : "Review now")));
    section("Also due", d.due.slice(lead === d.due[0] ? 1 : 0), "due");
    section("New", d.new.slice(lead === d.new[0] && !d.due.length ? 1 : 0), "new");
  } else if (d.upcoming.length) {
    nodes.push(h("div", { class: "calm" }, h("b", {}, "You're all caught up"), h("p", { class: "muted" }, "Next review: " + d.upcoming[0].name + " " + daysText(d.upcoming[0].due_in_days) + ".")),
      h("a", { class: "btn block", href: "#/notes" }, "Add a topic"));
  } else {
    nodes.push(h("div", { class: "calm" }, h("b", {}, "Nothing to study yet"), h("p", { class: "muted" }, "Pick a topic or paste your notes. REMEM turns them into quiz questions.")),
      h("a", { class: "btn primary block", href: "#/notes" }, "Add notes"));
  }
  section("Later", d.upcoming, "later");
  mount(nodes);
}

async function viewHome() {
  let cached = null; try { cached = JSON.parse(store.get("remem_due") || "null"); } catch (e) { /* ignore */ }
  if (cached) renderHome(cached); else mount(h("h1", {}, "Today"), skeleton(3, true));     // show last known state instantly, refresh underneath
  let d;
  try { d = await api("/due"); } catch (e) { if (!cached) mount(h("h1", {}, "Today"), h("div", { class: "err" }, e.message)); return; }
  const fresh = JSON.stringify(d);
  const same = cached && fresh === JSON.stringify(cached);
  store.set("remem_due", fresh);
  renderNav();                                                                      // refresh the due badge
  if (!same && (location.hash === "" || location.hash === "#/")) renderHome(d);     // no second render (and no second bar animation) when nothing changed
}

async function viewPractice(cid) {
  mount(h("h1", {}, "Practice"), skeleton(2));
  let q; try { q = await api("/question/next?concept=" + cid); } catch (e) { return mount(h("h1", {}, "Practice"), h("div", { class: "err" }, e.message), h("a", { class: "btn", href: "#/" }, "Back to today")); }
  const t0 = performance.now();
  let answered = false;
  const fb = h("div", { class: "fb stack", role: "status" });
  const opts = q.options.map((text, i) => h("button", { class: "opt", onclick: async () => {
    if (answered) return; answered = true;
    opts.forEach(b => b.disabled = true);
    const body = { question_id: q.question_id, chosen_index: i, rt_ms: Math.round(performance.now() - t0), idem_key: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()) };
    try {
      const r = await api("/respond", { method: "POST", body });
      const good = opts[r.correct_index]; good.classList.add("right"); good.querySelector(".key").replaceChildren(icon("M5 12.5l4.5 4.5L19 7.5")); good.querySelector(".txt").append(h("span", { class: "tag" }, "Correct answer"));
      if (!r.correct) { const bad = opts[i]; bad.classList.add("wrong"); bad.querySelector(".key").replaceChildren(icon("M6 6l12 12M18 6L6 18")); bad.querySelector(".txt").append(h("span", { class: "tag" }, "Your answer")); }
      fb.replaceChildren(h("div", {}, h("div", { class: "verdict " + (r.correct ? "ok" : "err") }, r.correct ? "Correct" : "Not quite"), h("div", { class: "muted" }, r.message),
          r.source ? h("div", { class: "src" }, h("span", { class: "small" }, "From your notes"), "“" + r.source + "”") : null),
        h("button", { class: "primary block", onclick: () => viewPractice(cid) }, "Next question"),
        h("div", { class: "grid2" }, h("a", { class: "btn", href: "#/curve/" + cid }, "Memory curve"), h("a", { class: "btn", href: "#/" }, "Finish")));
      store.del("remem_due");
      fb.scrollIntoView({ block: "end", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    } catch (e) {
      if (e instanceof TypeError) { const qd = queue(); qd.push(body); saveQueue(qd); fb.replaceChildren(h("div", { class: "panel" }, "You're offline. Your answer is saved and will sync when you reconnect."), h("a", { class: "btn block", href: "#/" }, "Back to today")); }
      else { answered = false; opts.forEach(b => b.disabled = false); toast(e.message); }
    }
  } }, h("span", { class: "key", "aria-hidden": "true" }, "ABCD"[i]), h("span", { class: "txt" }, text)));
  mount(h("div", { class: "bar" }, h("a", { class: "btn link", href: "#/", "aria-label": "Back to today" }, icon("M15 5l-7 7 7 7", "chev"), "Today"), h("span", { class: "where" }, q.concept || "")), h("h1", { class: "q" }, q.stem), h("div", { class: "opts" }, opts), fb,
        h("p", { class: "muted small" }, h("a", { class: "flag", href: "#/", onclick: async (e) => { e.preventDefault(); try { await api("/flag", { method: "POST", body: { question_id: q.question_id } }); toast("Thanks, question flagged"); } catch (x) { toast(x.message); } } }, "Report a bad question")));
}

async function viewNotes() {
  const msg = h("div", { class: "muted", role: "status" });
  const title = h("input", { id: "nt", placeholder: "e.g. Photosynthesis" });
  const text = h("textarea", { id: "nx", placeholder: "Paste your study notes here (at least a few sentences)" });
  const busy = [];   // buttons to lock while a quiz is being made
  const lock = (on) => busy.forEach(b => { b.disabled = on; if (on) b.setAttribute("aria-busy", "true"); else b.removeAttribute("aria-busy"); });

  async function poll(id) {
    msg.className = "muted"; msg.textContent = "Reading the notes and writing questions. This can take up to a minute.";
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 2000));
      let s; try { s = await api("/notes/" + id); } catch (e) { continue; }
      if (s.status === "done") { store.del("remem_due"); mount(h("h1", {}, "Quiz ready"), h("p", { class: "muted" }, pl(s.concepts.length, "concept") + " added."), h("ul", { class: "ledger" }, s.concepts.map(c => h("li", {}, h("div", { class: "item" }, h("span", { class: "name" }, c.name))))), h("p", {}, h("a", { class: "btn primary block", href: "#/" }, "Start practising"))); return; }
      if (s.status === "failed") { msg.className = "err"; msg.textContent = s.error || "Could not create questions. Try again in a minute."; lock(false); return; }
    }
    msg.className = "err"; msg.textContent = "Still working. Check Today in a minute."; lock(false);
  }
  async function start(path, body) {
    lock(true); msg.className = "muted"; msg.textContent = "Sending...";
    try { const r = await api(path, { method: "POST", body }); poll(r.note_id); }
    catch (e) { msg.className = "err"; msg.textContent = e.message; lock(false); }
  }

  const own = h("button", { class: "primary block", onclick: () => start("/notes", { title: title.value.trim(), text: text.value }) }, "Make my quiz");
  busy.push(own);
  const ownBox = h("details", { class: "own" }, h("summary", {}, "Use your own notes instead"),
    h("p", { class: "muted" }, "Notes about one topic. Don't paste personal or confidential text."),
    h("label", { for: "nt" }, "Title"), title, h("label", { for: "nx" }, "Notes"), text, h("p", {}, own));

  const slot = skeleton(3);
  mount(h("h1", {}, "Add notes"), h("p", { class: "muted" }, "Pick a topic to start in one tap."), msg, slot, ownBox);
  let d; try { d = await api("/topics"); } catch (e) { slot.replaceWith(h("div", { class: "err" }, "Could not load topics: " + e.message)); return; }
  d.topics.sort((a, b) => (b.id === d.suggested) - (a.id === d.suggested));       // suggested topic first
  const mk = (t, label) => { const btn = h("button", { onclick: () => start("/notes/topic", { topic_id: t.id }), "aria-label": label + ": " + t.title }, label); busy.push(btn); return btn; };
  const meta = t => t.subject + ", " + t.minutes + " min read" + (t.done ? ", done before" : "");
  const sug = d.topics.find(t => t.id === d.suggested);
  const rest = d.topics.filter(t => t !== sug);
  const out = [];
  if (sug) {
    const btn = mk(sug, sug.done ? "Study again" : "Start");
    out.push(h("h2", {}, "Suggested for you"), h("div", { class: "next" }, h("h2", {}, sug.title), h("p", {}, sug.blurb + " (" + meta(sug) + ")"), btn));
  }
  if (rest.length) out.push(h("h2", {}, sug ? "Other topics" : "Topics"), h("ul", { class: "ledger" }, rest.map(t =>
    h("li", {}, h("div", { class: "item row" }, h("div", {}, h("span", { class: "name" }, t.title), h("div", { class: "muted" }, t.blurb), h("div", { class: "muted small" }, meta(t))), mk(t, t.done ? "Study again" : "Start"))))));
  slot.replaceWith(h("div", {}, out));
}

async function viewConcepts() {
  mount(h("h1", {}, "Concepts"), skeleton(4));
  let d; try { d = await api("/concepts"); } catch (e) { return mount(h("h1", {}, "Concepts"), h("div", { class: "err" }, e.message)); }
  const nodes = [h("h1", {}, "Concepts")];
  if (!d.concepts.length) nodes.push(h("div", { class: "calm" }, h("b", {}, "No concepts yet"), h("p", { class: "muted" }, "Add a topic and they will appear here."), h("a", { class: "btn primary block", href: "#/notes" }, "Add notes")));
  nodes.push(h("ul", { class: "ledger" }, d.concepts.map(c => h("li", {}, h("a", { class: "item", href: c.new ? "#/practice/" + c.concept_id : "#/curve/" + c.concept_id },
    h("span", { class: "name" }, c.name),
    h("span", { class: "when" }, c.new ? "not studied yet" : "remembered ~" + pl(Math.round(c.stability_days), "day")),
    c.new ? h("div", { class: "meter empty", "aria-hidden": "true" }) : [meter(c.R_now, c.R_now < THETA_UI), h("span", { class: "note" }, "Mastery " + Math.round(c.mastery * 100) + "% · " + pl(c.n_responses, "answer"))])))));
  mount(nodes);
}

async function viewCurve(cid, theta) {
  let r, ex;
  try { r = await api("/retention/" + cid + (theta ? "?theta=" + theta : "")); ex = await api("/explain/" + cid); }
  catch (e) { return mount(h("h1", {}, "Memory curve"), h("div", { class: "err" }, e.message), h("a", { class: "btn", href: "#/" }, "Back")); }
  const W = 640, H = 340, L = 74, B = 44, T = 18, Rr = 16;
  const maxD = r.points[r.points.length - 1].day;
  const x = d => L + (d / maxD) * (W - L - Rr), y = v => T + (1 - v) * (H - T - B);
  const NS = "http://www.w3.org/2000/svg";
  const se = (t, a, txt) => { const e = document.createElementNS(NS, t); for (const [k, v] of Object.entries(a || {})) e.setAttribute(k, v); if (txt != null) e.textContent = txt; return e; };
  const svg = se("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Predicted recall over the next " + maxD + " days. Recall now " + Math.round(r.R_now * 100) + "%, next review in " + pl(Number(r.next_review_day.toFixed(1)), "day") + "." });
  [0, 0.25, 0.5, 0.75, 1].forEach(v => { svg.append(se("line", { class: "grid", x1: L, x2: W - Rr, y1: y(v), y2: y(v) })); svg.append(se("text", { x: 4, y: y(v) + 7 }, Math.round(v * 100) + "%")); });
  for (let i = 0; i <= 4; i++) { const d = (maxD * i) / 4; svg.append(se("text", { x: Math.min(x(d) - 10, W - 40), y: H - 12 }, d.toFixed(0) + "d")); }
  const pts = r.points.map(p => x(p.day) + "," + y(p.R));
  svg.append(se("polygon", { class: "area", points: pts.join(" ") + " " + x(maxD) + "," + y(0) + " " + x(0) + "," + y(0) }));
  svg.append(se("line", { class: "target", x1: L, x2: W - Rr, y1: y(r.theta), y2: y(r.theta) }));
  svg.append(se("text", { x: W - Rr - 150, y: y(r.theta) - 8 }, "target " + Math.round(r.theta * 100) + "%"));
  svg.append(se("polyline", { class: "curve", points: pts.join(" ") }));
  if (r.next_review_day <= maxD) { svg.append(se("line", { class: "review", x1: x(r.next_review_day), x2: x(r.next_review_day), y1: T, y2: H - B })); svg.append(se("text", { class: "lab", x: Math.min(x(r.next_review_day) + 6, W - 170), y: T + 22 }, "review day " + r.next_review_day.toFixed(1))); }
  if (r.elapsed_days <= maxD) svg.append(se("circle", { class: "now", cx: x(r.elapsed_days), cy: y(r.R_now), r: 8 }));
  const nodes = [h("h1", {}, r.concept), svg,
    h("p", { class: "muted" }, "The dot is you now, at " + Math.round(r.R_now * 100) + "% recall. REMEM asks you to review at the vertical line. Recall falls to about 90% after " + pl(Math.round(r.stability_days), "day") + ".")];
  if (S.role === "demo" || S.role === "admin") {
    const lab = h("b", {}, "target " + Math.round(r.theta * 100) + "%");
    const sl = h("input", { type: "range", min: 60, max: 97, value: Math.round(r.theta * 100), "aria-label": "What-if target retention", oninput: () => { lab.textContent = "target " + sl.value + "%"; }, onchange: () => viewCurve(cid, sl.value / 100) });
    nodes.push(h("div", { class: "panel" }, h("div", {}, "What-if target (demo only) ", lab), sl));
  }
  nodes.push(h("p", {}, rich(ex.explanation)), h("div", { class: "grid2" }, h("a", { class: "btn primary", href: "#/practice/" + cid }, "Practise now"), h("a", { class: "btn", href: "#/" }, "Back")));
  mount(nodes);
}

function viewMe() {
  const old = h("input", { id: "op", type: "password", autocomplete: "current-password" }), nw = h("input", { id: "np", type: "password", autocomplete: "new-password" });
  const msg = h("div", { class: "muted", role: "status" });
  mount(h("h1", {}, S.user || "Me"), S.role !== "student" ? h("p", { class: "muted" }, "Role: " + S.role) : null,
    h("h2", {}, "Change password"),
    h("div", { class: "stack" }, h("div", {}, h("label", { for: "op" }, "Current password"), old), h("div", {}, h("label", { for: "np" }, "New password (8 or more characters)"), nw), msg,
      h("button", { onclick: async () => { try { await api("/auth/password", { method: "POST", body: { old_password: old.value, new_password: nw.value } }); msg.className = "ok"; msg.textContent = "Password changed."; old.value = nw.value = ""; } catch (e) { msg.className = "err"; msg.textContent = e.message; } } }, "Update password")),
    h("p", {}, h("button", { class: "block", onclick: () => signOut() }, "Sign out")));
}

// ---------------------------------------------------------------- router
function route() {
  const hash = location.hash || "#/";
  renderNav();
  if (!S.token) return viewLogin();
  const [, a, b] = hash.split("/");
  switch (a) {
    case "consent": return viewConsent();
    case "notes": return viewNotes();
    case "concepts": return viewConcepts();
    case "practice": return viewPractice(Number(b));
    case "curve": return viewCurve(Number(b));
    case "me": return viewMe();
    case "login": return viewLogin();
    default: flushQueue(); return viewHome();
  }
}
window.addEventListener("hashchange", route);
window.addEventListener("load", () => {
  route();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
});
