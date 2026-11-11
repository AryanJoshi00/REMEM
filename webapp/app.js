/* REMEM student app (PWA). Plain JS, no build step. All server text is inserted with textContent (never innerHTML). */
"use strict";

const CONSENT_TEXT =
`REMEM pilot - what you agree to

- This is a university project (Aryan Joshi, final year). In all results you appear only as an account number such as user01.
- The name, contact, age and topic answers from the first form are private to the project owner, never shared, and used only for this project and a follow-up survey if needed.
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
function remount(nodes, focusSel) {           // same screen redrawn in place (the demo's what-if slider): keep the scroll position and the focus
  const y = window.scrollY, app = document.getElementById("app");
  app.replaceChildren(...nodes.flat()); window.scrollTo(0, y);
  const el = focusSel && app.querySelector(focusSel); if (el) el.focus({ preventScroll: true });
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
  setBadge(0); S.token = S.role = S.user = null;
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
// ---------------------------------------------------------------- add to home screen
let deferredInstall = null;                         // Chrome / Edge / Android: the browser's own install prompt, when it offers one
window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); deferredInstall = e; });
window.addEventListener("appinstalled", () => { deferredInstall = null; store.set("remem_installed", "1"); });

function env() {
  const ua = navigator.userAgent || "";
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  const ios = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const inApp = /FBAN|FBAV|Instagram|WhatsApp|Line\/|Snapchat|MicroMessenger|Twitter|LinkedInApp|GSA\//i.test(ua) || /; wv\)/.test(ua);
  return { standalone, ios, inApp, android: /Android/.test(ua), samsung: /SamsungBrowser/.test(ua), iosOtherBrowser: ios && /CriOS|FxiOS|EdgiOS|OPiOS/.test(ua) };
}
function installBannerHidden() { const t = Number(store.get("remem_install_hide") || 0); return Date.now() - t < 7 * 86400000; }
function setBadge(n) {                              // the number of concepts due, shown on the home-screen icon where the phone allows it
  try { if (n > 0 && navigator.setAppBadge) navigator.setAppBadge(n); else if (navigator.clearAppBadge) navigator.clearAppBadge(); } catch (e) { /* not supported */ }
}
function installBanner() {
  const e = env();
  if (e.standalone || installBannerHidden()) return null;
  return h("div", { class: "calm install" }, h("b", {}, "Keep REMEM one tap away"),
    h("p", { class: "muted" }, "Add it to your home screen. It opens like an app and the icon shows how many concepts are due."),
    h("div", { class: "actions" }, h("a", { class: "btn", href: "#/install" }, "Show how"),
      h("button", { class: "link", type: "button", onclick: () => { store.set("remem_install_hide", String(Date.now())); route(); } }, "Not now")));
}
function phoneArt() {
  const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 120 150"); svg.setAttribute("class", "phone-art"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "A phone with the REMEM icon on its home screen");
  const add = (tag, a) => { const el = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(a)) el.setAttribute(k, v); svg.append(el); return el; };
  add("rect", { x: 14, y: 6, width: 92, height: 138, rx: 16, class: "pa-body" });
  add("rect", { x: 22, y: 20, width: 76, height: 112, rx: 8, class: "pa-screen" });
  [0, 1, 2].forEach(r => [0, 1, 2].forEach(c => { if (!(r === 1 && c === 1)) add("rect", { x: 30 + c * 22, y: 30 + r * 26, width: 16, height: 16, rx: 5, class: "pa-app" }); }));
  add("rect", { x: 52, y: 56, width: 16, height: 16, rx: 5, class: "pa-remem" });
  add("circle", { cx: 70, cy: 56, r: 6, class: "pa-badge" });
  return svg;
}
function stepList(steps) {
  return h("ol", { class: "steps" }, steps.map((t, i) => h("li", {}, h("span", { class: "n", "aria-hidden": "true" }, String(i + 1)), h("span", { class: "t" }, t))));
}
function viewInstall() {
  const e = env();
  const back = h("a", { class: "btn block", href: S.token ? "#/" : "#/login" }, S.token ? "Back to today" : "Back to sign in");
  if (e.standalone) return mount(h("h1", {}, "Already on your home screen"), phoneArt(), h("p", { class: "muted" }, "You're using REMEM as an app. Nothing more to do."), back);
  const nodes = [h("h1", {}, "Keep REMEM one tap away"), phoneArt(), h("p", {}, "Put REMEM on your home screen. It opens full screen like an app, and the icon shows how many concepts are due.")];
  if (e.inApp) {
    const copy = h("button", { class: "block", onclick: async () => { try { await navigator.clipboard.writeText(location.origin + "/"); toast("Link copied. Paste it in Chrome or Safari."); } catch (x) { toast("Copy the address from the menu instead."); } } }, "Copy the link");
    nodes.push(h("div", { class: "panel" }, h("b", {}, "First, open it in your browser"), h("p", { class: "muted" }, "This page is open inside another app (such as WhatsApp or Instagram), and those can't add to the home screen. Tap the menu or the compass icon and choose Open in browser (Chrome or Safari), or copy the link and paste it there."), copy));
  }
  if (deferredInstall) {
    nodes.push(h("button", { class: "primary block", onclick: async () => { deferredInstall.prompt(); try { await deferredInstall.userChoice; } catch (x) { /* dismissed */ } deferredInstall = null; route(); } }, "Add to home screen"));
    nodes.push(h("p", { class: "muted small" }, "Prefer to do it yourself? The steps are below."));
  }
  let steps, title;
  if (e.ios) { title = e.iosOtherBrowser ? "On iPhone, in your browser" : "On iPhone, in Safari"; steps = [e.iosOtherBrowser ? "Tap the Share button (a square with an arrow) in the toolbar or the address bar." : "Tap the Share button (a square with an arrow) at the bottom of Safari.", "Scroll down in the sheet and tap Add to Home Screen.", "Tap Add in the top corner. REMEM appears on your home screen."]; }
  else if (e.samsung) { title = "On Samsung Internet"; steps = ["Tap the menu (three lines) at the bottom right.", "Tap Add page to, then Home screen.", "Tap Add."]; }
  else if (e.android) { title = "On Android, in Chrome"; steps = ["Tap the menu (three dots) at the top right.", "Tap Install app. If you see Add to Home screen instead, tap that.", "Tap Install or Add. REMEM appears on your home screen."]; }
  else { title = "On a computer"; steps = ["Look for the install icon at the right end of the address bar, or open the browser menu.", "Choose Install REMEM (Chrome and Edge).", "Confirm. REMEM opens in its own window."]; }
  nodes.push(h("h2", {}, title), stepList(steps));
  nodes.push(h("details", { class: "own" }, h("summary", {}, "Can't see the option?"),
    h("ul", { class: "muted" },
      h("li", {}, "Open the link in Chrome (Android) or Safari (iPhone). Links opened from WhatsApp, Instagram or similar usually can't be added."),
      h("li", {}, "On iPhone, other browsers can add it only on recent iOS versions; Safari always can."),
      h("li", {}, "Private or incognito tabs hide the option. Open a normal tab."),
      h("li", {}, "You can use REMEM in the browser without adding it. Nothing is lost."))));
  nodes.push(h("p", {}, back));
  mount(nodes);
}

// ---------------------------------------------------------------- nav
const SUBJECT_ICONS = {       // one glyph per ready-made topic subject
  Language: "M4 5h16v11H9l-5 4zM8 10h8",
  Photography: "M4 8h4l2-3h4l2 3h4v11H4zM12 16a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  Geography: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18",
  Psychology: "M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.5.4.5 1 .5 1.6h6c0-.6 0-1.2.5-1.6A6 6 0 0 0 12 3z",
  Technology: "M12 21s6-5.5 6-11a6 6 0 1 0-12 0c0 5.5 6 11 6 11zM12 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  Health: "M12 20s-8-4.6-8-10.5A4.5 4.5 0 0 1 12 7a4.5 4.5 0 0 1 8 2.5C20 15.4 12 20 12 20z",
};
const ICONS = {       // one drawn set: 24px grid, 1.8 stroke, round caps
  today: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4M8 14h3",
  notes: "M3 5h6a3 3 0 0 1 3 3v12a2 2 0 0 0-2-2H3zM21 5h-6a3 3 0 0 0-3 3v12a2 2 0 0 1 2-2h7z",
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
  const cur = (location.hash || "#/").split("?")[0], n = dueCount();
  if (!S.token || /^#\/(about|consent)$/.test(cur)) return;                   // no browsing before the intro form and consent
  [["#/", "Today", "today"], ["#/notes", "Topics", "notes"], ["#/concepts", "Concepts", "concepts"], ["#/me", "Me", "me"]].forEach(([href, label, ic]) => {
    const on = href === "#/" ? cur === "#/" : cur.startsWith(href);
    const badge = href === "#/" && n;
    nav.append(h("a", { href, class: on ? "on" : "", "aria-current": on ? "page" : false, "aria-label": badge ? label + ", " + pl(n, "concept") + " due" : false },
      icon(ic), label, badge ? h("span", { class: "badge", "aria-hidden": "true" }, String(n)) : null));
  });
}

// ---------------------------------------------------------------- views
const THETA_UI = 0.85;
function skeleton(n, hero) { return h("div", { "aria-busy": "true", "aria-label": "Loading" }, hero ? h("div", { class: "skel hero" }) : null, Array.from({ length: n }, () => h("div", { class: "skel" }))); }
function meter(R, fading) {            // the freshness bar: how much you still remember
  const pct = Math.round(R * 100);
  return h("div", { class: "meter" + (fading ? " fading" : ""), role: "meter", "aria-label": "Recall", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": pct, "aria-valuetext": pct + "% recall" }, h("i", { style: "--v:" + R }));
}
function aboutDays(d) { return d <= 0.5 ? "today" : "in about " + pl(Math.max(1, Math.round(d)), "day"); }      // Today and the memory curve round the same way
const daysText = aboutDays;

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
      location.hash = !r.profile_ok ? "#/about" : (r.consent_ok ? "#/" : "#/consent"); route();
    } catch (ex) { err.textContent = ex.message; go.disabled = false; }
  } }, h("div", {}, h("label", { for: "u" }, "Username"), u), h("div", {}, h("label", { for: "p" }, "Password"), h("div", { class: "pw" }, p, showBtn)), err, go);
  u.id = "u"; p.id = "p";
  mount(h("h1", {}, "Remember what you study"), h("p", { class: "muted" }, "REMEM tells you what to revise, and when. Your project owner gives you a username and password."), form,
    env().standalone ? null : h("p", {}, h("a", { href: "#/install" }, "Add REMEM to your home screen")));
}

async function viewAbout() {
  mount(h("h1", {}, "A quick intro"), skeleton(3));
  let f; try { f = await api("/auth/profile"); } catch (e) { return mount(h("h1", {}, "A quick intro"), h("div", { class: "err" }, e.message), h("p", {}, h("button", { class: "block", onclick: () => route() }, "Try again"))); }
  if (f.done) { location.hash = "#/consent"; return; }
  const name = h("input", { id: "pn", autocomplete: "name", maxlength: 80 });
  const contact = h("input", { id: "pc", autocomplete: "email", autocapitalize: "none", spellcheck: "false", maxlength: 120, placeholder: "Email or phone number" });
  const age = h("input", { id: "pa", type: "number", inputmode: "numeric", min: 10, max: 100 });
  const err = h("div", { class: "err", role: "alert" });
  const boxes = f.topics.map(t => ({ t, box: h("input", { type: "checkbox", value: t.id }) }));
  const go = h("button", { class: "primary block", type: "submit" }, "Continue");
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault(); err.textContent = "";
    if (!name.value.trim() || contact.value.trim().length < 3 || !(Number(age.value) >= 10)) { err.textContent = "Please fill in your name, contact and age."; return; }
    go.disabled = true;
    try {
      await api("/auth/profile", { method: "POST", body: { full_name: name.value.trim(), contact: contact.value.trim(), age: Number(age.value), known_topics: boxes.filter(b => b.box.checked).map(b => b.t.id) } });
      location.hash = "#/consent"; route();
    } catch (ex) { err.textContent = ex.message; go.disabled = false; }
  } },
    h("div", { class: "panel" }, "Your details stay with me, Aryan Joshi. They are not shared with anyone and are only for my final-year project (and a follow-up survey if I need one). In results you are just a number, never a name."),
    h("div", {}, h("label", { for: "pn" }, "Name"), name), h("div", {}, h("label", { for: "pc" }, "Email or phone"), contact), h("div", {}, h("label", { for: "pa" }, "Age"), age),
    h("h2", {}, "What do you already know well?"),
    h("p", { class: "muted" }, "Tick any topic you could already explain in detail. Please be honest: this is not a test, and it keeps my data fair. Tick nothing if none apply."),
    h("div", { class: "checks" }, boxes.map(b => h("label", { class: "check" }, b.box, h("span", {}, h("b", {}, b.t.title), h("span", { class: "muted small" }, " " + b.t.subject))))),
    err, go);
  mount(h("h1", {}, "A quick intro"), h("p", { class: "muted" }, "One short form before you start. It takes about a minute."), form);
}

function viewConsent() {
  const ok = h("button", { class: "primary block", onclick: async () => {
    try { await api("/auth/consent", { method: "POST" }); location.hash = "#/notes"; route(); } catch (e) { toast(e.message); }
  } }, "I agree");
  mount(h("h1", {}, "Before you start"), h("div", { class: "panel consent" }, CONSENT_TEXT), ok,
        h("p", {}, h("button", { class: "block", onclick: () => signOut() }, "No thanks, sign out")));
}

function renderHome(d) {
  setBadge(d.due.length);
  const nodes = [h("h1", {}, "Today")];
  const counts = [d.due.length ? d.due.length + " due" : "", d.new.length ? d.new.length + " new" : ""].filter(Boolean).join(", ");
  if (counts) nodes.push(h("p", { class: "muted" }, counts));
  if (S.offline) nodes.push(h("p", { class: "muted small offline", role: "status" }, "Offline. Showing what was saved on this phone."));
  const finalCard = d.final && d.final.open && d.final.remaining ? h("div", { class: "calm" }, h("b", {}, "Final check is open"),
    h("p", { class: "muted" }, pl(d.final.remaining, "question") + ", one per concept. It takes a few minutes and doesn't change your schedule."),
    h("a", { class: "btn primary block", href: "#/final" }, "Start the final check")) : null;
  const lead = d.due[0] || d.new[0];
  const row = (c, kind) => {
    const href = kind === "later" ? "#/curve/" + c.concept_id : "#/practice/" + c.concept_id;
    const kids = [h("span", { class: "name", dir: "auto" }, c.name)];
    if (c.new) kids.push(h("span", { class: "when" }, "not studied yet"), h("div", { class: "meter empty", "aria-hidden": "true" }));
    else {
      const late = kind === "due";
      kids.push(h("span", { class: "when" + (late ? " late" : "") }, late ? "review now" : daysText(c.due_in_days)), meter(c.R_now, late || c.R_now < THETA_UI));
    }
    return h("li", {}, h("a", { class: "item", href }, kids));
  };
  const section = (title, items, kind) => { if (items.length) nodes.push(h("h2", {}, title), h("ul", { class: "ledger" }, items.map(c => row(c, kind)))); };
  // order: the one thing to do next, then the final check, then the lists; the install banner (lowest value, dismissible) last
  if (lead) {
    nodes.push(h("div", { class: "next" }, h("h2", { dir: "auto" }, lead.name), h("p", {}, lead.new ? "New concept. Take the first quiz." : "Your recall has dropped to about " + Math.round(lead.R_now * 100) + "%. A quick review brings it back."),
      h("a", { class: "btn", href: "#/practice/" + lead.concept_id }, lead.new ? "Start the quiz" : "Review now")));
    if (finalCard) nodes.push(finalCard);
    section("Also due", d.due.slice(lead === d.due[0] ? 1 : 0), "due");
    section("New", d.new.slice(lead === d.new[0] && !d.due.length ? 1 : 0), "new");
  } else if (d.upcoming.length) {
    nodes.push(h("div", { class: "calm" }, h("b", {}, "You're all caught up"), h("p", { class: "muted" }, "Next review: " + d.upcoming[0].name + " " + daysText(d.upcoming[0].due_in_days) + ".")),
      h("a", { class: "btn block", href: "#/notes" }, "Pick another topic"));
    if (finalCard) nodes.push(finalCard);
  } else {
    nodes.push(h("div", { class: "calm" }, h("b", {}, "Welcome. Here is how it works"),
      stepList(["Pick a topic and read the short text once.", "Answer a few quiz questions on it.", "REMEM tells you when to come back, just before you would forget."])),
      h("a", { class: "btn primary block", href: "#/notes" }, "Pick a topic"));
    if (finalCard) nodes.push(finalCard);
  }
  section("Later", d.upcoming, "later");
  const ib = installBanner(); if (ib) nodes.push(ib);
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

const sess = { cid: null, n: 0, ok: 0 };           // this sitting only: how many questions answered, and how many right
async function viewPractice(cid) {
  if (sess.cid !== cid) { sess.cid = cid; sess.n = 0; sess.ok = 0; }
  mount(h("h1", {}, "Practice"), skeleton(2));
  let q; try { q = await api("/question/next?concept=" + cid); } catch (e) { return mount(h("h1", {}, "Practice"), h("div", { class: "err" }, e.message), h("a", { class: "btn", href: "#/" }, "Back to today")); }
  const t0 = performance.now();
  let answered = false;
  const fb = h("div", { class: "fb stack", role: "status" });
  const opts = q.options.map((text, i) => h("button", { class: "opt", onclick: async () => {
    if (answered) return; answered = true;
    opts.forEach(b => b.disabled = true);
    const body = { question_id: q.question_id, chosen_index: i, rt_ms: Math.round(performance.now() - t0), idem_key: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()) };
    opts[i].classList.add("picked");                                         // after rt_ms is taken: shows the tap registered while the answer is checked
    try {
      const r = await api("/respond", { method: "POST", body });
      sess.n++; if (r.correct) sess.ok++;
      const good = opts[r.correct_index]; good.classList.add("right"); good.querySelector(".key").replaceChildren(icon("M5 12.5l4.5 4.5L19 7.5")); good.querySelector(".txt").append(h("span", { class: "tag" }, "Correct answer"));
      if (!r.correct) { const bad = opts[i]; bad.classList.add("wrong"); bad.querySelector(".key").replaceChildren(icon("M6 6l12 12M18 6L6 18")); bad.querySelector(".txt").append(h("span", { class: "tag" }, "Your answer")); }
      fb.replaceChildren(h("div", {}, h("div", { class: "verdict " + (r.correct ? "ok" : "err") }, r.correct ? "Correct" : "Not quite"), h("div", { class: "muted" }, r.message), h("div", { class: "muted small sess" }, sess.ok + " of " + sess.n + " right this sitting"),
          r.source ? h("div", { class: "src" }, h("span", { class: "small" }, "From your notes"), h("q", { dir: "auto" }, r.source)) : null),
        h("button", { class: "primary block", onclick: () => viewPractice(cid) }, "Next question"),
        h("div", { class: "grid2" }, h("a", { class: "btn", href: "#/curve/" + cid }, "Memory curve"), h("a", { class: "btn", href: "#/" }, "Finish")));
      store.del("remem_due");
      opts[i].classList.remove("picked");
      fb.scrollIntoView({ block: "end", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      const next = fb.querySelector("button.primary"); if (next) next.focus({ preventScroll: true });
    } catch (e) {
      if (e instanceof TypeError) { const qd = queue(); qd.push(body); saveQueue(qd); fb.replaceChildren(h("div", { class: "panel" }, "You're offline. Your answer is saved and will sync when you reconnect."), h("a", { class: "btn block", href: "#/" }, "Back to today")); }
      else { answered = false; opts[i].classList.remove("picked"); opts.forEach(b => b.disabled = false); toast(e.message); }
    }
  } }, h("span", { class: "key", "aria-hidden": "true" }, "ABCD"[i]), h("span", { class: "txt", dir: "auto" }, text)));
  const flag = h("button", { class: "link flag", type: "button", onclick: async () => {
    try { await api("/flag", { method: "POST", body: { question_id: q.question_id } }); toast("Thanks, question flagged"); flag.textContent = "Reported, thank you"; flag.disabled = true; } catch (x) { toast(x.message); }
  } }, "Report a bad question");
  mount(h("div", { class: "bar" }, h("a", { class: "btn link", href: "#/", "aria-label": "Back to today" }, icon("M15 5l-7 7 7 7", "chev"), "Today"), h("span", { class: "where", dir: "auto" }, q.concept || "")), h("h1", { class: "q", dir: "auto" }, q.stem), h("div", { class: "opts" }, opts), fb,
        h("p", { class: "links" }, q.topic_id ? h("a", { class: "flag", href: "#/notes/" + q.topic_id + "?r=1" }, "Read the notes again") : null, flag));
}

async function viewFinal() {
  const back = h("a", { class: "btn block", href: "#/" }, "Back to today");
  mount(h("h1", {}, "Final check"), skeleton(2));
  let f; try { f = await api("/final"); } catch (e) { return mount(h("h1", {}, "Final check"), h("div", { class: "err" }, e.message), back); }
  if (!f.open || !f.items.length) {
    return mount(h("h1", {}, "Final check"), h("div", { class: "calm" }, h("b", {}, f.open ? "You've answered every question" : "The final check isn't open"),
      h("p", { class: "muted" }, f.open ? "Thank you. There is nothing more to do here." : "Your project owner will tell you when it opens.")), back);
  }
  const total = f.items.length; let right = 0;
  mount(h("h1", {}, "Final check"), h("p", {}, pl(total, "question") + ", one for each concept you studied. You won't see whether an answer is right until the end, and your review schedule stays as it is."),
    h("button", { class: "primary block", onclick: () => ask(0) }, "Begin"), h("p", {}, back));

  async function ask(i) {
    if (i >= total) {
      store.del("remem_due");
      return mount(h("h1", {}, "Final check done"), h("div", { class: "calm" }, h("b", {}, right + " of " + total + " correct"),
        h("p", { class: "muted" }, "Thank you. These answers show how well REMEM timed your reviews.")), back);
    }
    mount(h("h1", {}, "Final check"), skeleton(2));
    let q; try { q = await api("/question/next?concept=" + f.items[i].concept_id + "&final=1"); }
    catch (e) { return mount(h("h1", {}, "Final check"), h("div", { class: "err" }, e.message), h("button", { class: "block", onclick: () => ask(i) }, "Try again"), h("p", {}, back)); }
    const t0 = performance.now(); let sent = false;
    const opts = q.options.map((text, k) => h("button", { class: "opt", onclick: async () => {
      if (sent) return; sent = true; opts.forEach(b => { b.disabled = true; }); opts[k].classList.add("picked");
      try {
        const r = await api("/respond", { method: "POST", body: { question_id: q.question_id, chosen_index: k, rt_ms: Math.round(performance.now() - t0), idem_key: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()) } });
        if (r.correct) right++;
        ask(i + 1);
      } catch (e) { sent = false; opts.forEach(b => { b.disabled = false; }); opts[k].classList.remove("picked"); toast(e.message); }
    } }, h("span", { class: "key", "aria-hidden": "true" }, "ABCD"[k]), h("span", { class: "txt" }, text)));
    mount(h("div", { class: "bar" }, h("span", { class: "where" }, "Question " + (i + 1) + " of " + total), h("span", { class: "where" }, q.concept || "")),
      h("h1", { class: "q" }, q.stem), h("div", { class: "opts" }, opts));
  }
}

// ---- making a quiz: used by the reading page (ready-made topics) and by the paste-your-own-notes form
function quizReady(s) {
  store.del("remem_due");
  const first = s.concepts[0];
  mount(h("h1", {}, "Your quiz is ready"),
    h("p", { class: "muted" }, pl(s.concepts.length, "concept") + " to learn. Questions come one at a time. REMEM tells you when to come back."),
    h("ul", { class: "ledger" }, s.concepts.map(c => h("li", {}, h("a", { class: "item", href: "#/practice/" + c.concept_id }, h("span", { class: "name" }, c.name), h("span", { class: "when" }, "start"))))),
    h("p", {}, h("a", { class: "btn primary block", href: first ? "#/practice/" + first.concept_id : "#/" }, "Start the first quiz")),
    h("p", {}, h("a", { class: "btn block", href: "#/" }, "Go to Today")));
}
async function pollNote(id, msg, onFail) {
  const gen = routeGen;                                       // stop quietly if the student has gone to another page meanwhile
  msg.className = "muted"; msg.textContent = "Writing your questions. This can take up to a minute. You can leave this page; the quiz will be on Today when it is ready.";
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 2000));
    if (gen !== routeGen) return;
    let s; try { s = await api("/notes/" + id); } catch (e) { continue; }
    if (gen !== routeGen) return;
    if (s.status === "done") return quizReady(s);
    if (s.status === "failed") { msg.className = "err"; msg.textContent = s.error || "Could not create questions. Try again in a minute."; onFail(); return; }
  }
  msg.className = "err"; msg.textContent = "Still working. Check Today in a minute."; onFail();
}
async function startQuiz(path, body, msg, onFail) {
  msg.className = "muted"; msg.textContent = "Sending...";
  try { const r = await api(path, { method: "POST", body }); pollNote(r.note_id, msg, onFail); }
  catch (e) { msg.className = "err"; msg.textContent = e.message; onFail(); }
}

// ---- the reading page: ready-made topics are read once before any question is asked
function readingBlocks(text) {                                  // plain text -> headings, paragraphs and bullet lists (textContent only)
  const lines = text.split("\n").slice(1), out = [];            // the first line is the title, shown as the page heading
  let list = null, para = [];
  const flush = () => { if (para.length) { out.push(h("p", {}, para.join(" "))); para = []; } list = null; };
  lines.forEach((raw, i) => {
    const l = raw.trim();
    if (!l) { flush(); return; }
    if (l.startsWith("- ")) { if (!list) { flush(); list = h("ul", { class: "reading-list" }); out.push(list); } list.append(h("li", {}, l.slice(2))); return; }
    list = null;
    const next = (lines[i + 1] || "").trim();
    if (!para.length && next && l.length <= 60 && !/[.:;?!,]$/.test(l)) { out.push(h("h2", { class: "rh" }, l)); return; }
    para.push(l);
  });
  flush(); return out;
}
async function viewTopic(tid, review) {
  mount(h("h1", {}, "Reading"), skeleton(4));
  let t; try { t = await api("/topics/" + tid); } catch (e) { return mount(h("h1", {}, "Reading"), h("div", { class: "err" }, e.message), h("a", { class: "btn block", href: "#/notes" }, "Back to topics")); }
  const msg = h("div", { class: "muted", role: "status" });
  const sentinel = h("div", { class: "end", "aria-hidden": "true" });
  const hint = h("span", { class: "hint", id: "readhint", "aria-live": "polite" }, "Read to the end");
  const go = h("button", { class: "primary", disabled: true, onclick: () => {
    if (review) { history.length > 1 ? history.back() : (location.hash = "#/"); return; }
    go.disabled = true;
    mount(h("h1", {}, "Making your quiz"), msg, skeleton(3), h("p", {}, h("a", { class: "btn block", href: "#/notes/" + tid }, "Back to the notes")));
    startQuiz("/notes/topic", { topic_id: tid }, msg, () => {});
  }, "aria-describedby": "readhint" }, review ? "Back to the quiz" : "I've read it. Make my quiz");
  const unlock = () => { go.disabled = false; hint.textContent = review ? "" : "Ready when you are"; bar.classList.add("ready"); };
  const bar = h("div", { class: "readbar" }, h("div", { class: "inner" }, hint, go));
  const title = t.title.split(":")[0];
  mount(h("div", { class: "bar" }, h("a", { class: "btn link", href: "#/notes", "aria-label": "Back to topics" }, icon("M15 5l-7 7 7 7", "chev"), "Topics")),
    h("h1", {}, title), h("p", { class: "muted" }, t.subject + ", about " + t.minutes + " min read"),
    review ? null : h("div", { class: "panel hint-panel" }, h("b", {}, "Read this once before the quiz."), h("p", { class: "muted" }, "The questions come next and are based on this text. Take your time; nothing is timed while you read.")),
    h("article", { class: "reading" }, readingBlocks(t.text)), sentinel,
    review ? null : h("p", { class: "muted small" }, "Already know this well? You can say so on your profile form, and REMEM will stop suggesting it."), bar);
  const check = () => { if (sentinel.getBoundingClientRect().top < innerHeight) { unlock(); removeEventListener("scroll", check); removeEventListener("resize", check); } };    // the end of the text is on screen
  addEventListener("scroll", check, { passive: true }); addEventListener("resize", check); setTimeout(check, 300);
}

async function viewNotes() {
  const msg = h("div", { class: "muted", role: "status" });
  const title = h("input", { id: "nt", placeholder: "e.g. Roman roads" });
  const text = h("textarea", { id: "nx", placeholder: "Paste your study notes here (at least a few sentences)" });
  const own = h("button", { class: "primary block", onclick: () => { own.disabled = true; own.setAttribute("aria-busy", "true"); startQuiz("/notes", { title: title.value.trim(), text: text.value }, msg, () => { own.disabled = false; own.removeAttribute("aria-busy"); }); } }, "Make my quiz");
  const form = h("div", { class: "ownform", hidden: true },
    h("label", { for: "nt" }, "Title"), title, h("label", { for: "nx" }, "Notes"), text,
    h("p", { class: "muted small" }, "Your notes are sent to Google's Gemini AI, which writes the questions. Paste notes about one topic, and nothing personal or confidential."), h("p", {}, own), msg);
  const open = h("button", { class: "block", "aria-expanded": "false", onclick: () => { form.hidden = false; open.hidden = true; open.setAttribute("aria-expanded", "true"); title.focus(); } }, "Paste my own notes");
  const ownBox = h("div", { class: "panel own" }, h("h2", {}, "Or use your own notes"),
    h("p", { class: "muted" }, "Paste notes from your course and an AI (Google Gemini) turns them into quiz questions."), open, form);

  const slot = skeleton(3);
  mount(h("h1", {}, "Pick a topic"), h("p", { class: "muted" }, "Read a short text first, then answer questions on it."), slot, ownBox);
  let d; try { d = await api("/topics"); } catch (e) { slot.replaceWith(h("div", { class: "err" }, "Could not load topics: " + e.message)); return; }
  d.topics.sort((a, b) => (b.id === d.suggested) - (a.id === d.suggested));       // suggested topic first
  const mk = (t, label) => h("a", { class: "btn primary", href: "#/notes/" + t.id, "aria-label": label + ": " + t.title }, label);
  const meta = t => t.subject + ", " + t.minutes + " min read" + (t.done ? ", done before" : "") + (t.known ? ", you know this one" : "");
  const tile = (t, cls) => h("span", { class: "tile " + (cls || ""), "aria-hidden": "true" }, icon(SUBJECT_ICONS[t.subject] || "M5 5h14v14H5z"));
  const sug = d.topics.find(t => t.id === d.suggested);
  const rest = d.topics.filter(t => t !== sug);
  const out = [];
  if (sug) out.push(h("h2", {}, "Suggested for you"), h("div", { class: "panel sug" }, h("div", { class: "sug-head" }, tile(sug), h("h3", {}, sug.title)), h("p", { class: "muted" }, sug.blurb + " (" + meta(sug) + ")"), mk(sug, sug.done ? "Read again" : "Read and start")));
  if (rest.length) out.push(h("h2", {}, sug ? "Other topics" : "Topics"), h("ul", { class: "ledger topics" }, rest.map(t => {
    const label = t.done ? "Read again" : "Read";
    return h("li", {}, h("a", { class: "item row withtile", href: "#/notes/" + t.id, "aria-label": label + ": " + t.title }, tile(t),
      h("div", {}, h("span", { class: "name" }, t.title), h("div", { class: "muted" }, t.blurb), h("div", { class: "muted small" }, meta(t))),
      h("span", { class: "go", "aria-hidden": "true" }, label, icon("M9 5l7 7-7 7", "chev"))));
  })));
  slot.replaceWith(h("div", {}, out));
}

async function viewConcepts() {
  mount(h("h1", {}, "Concepts"), skeleton(4));
  let d; try { d = await api("/concepts"); } catch (e) { return mount(h("h1", {}, "Concepts"), h("div", { class: "err" }, e.message)); }
  const nodes = [h("h1", {}, "Concepts")];
  if (!d.concepts.length) nodes.push(h("div", { class: "calm" }, h("b", {}, "No concepts yet"), h("p", { class: "muted" }, "Pick a topic and they will appear here."), h("a", { class: "btn primary block", href: "#/notes" }, "Pick a topic")));
  nodes.push(h("ul", { class: "ledger" }, d.concepts.map(c => h("li", {}, h("a", { class: "item", href: c.new ? "#/practice/" + c.concept_id : "#/curve/" + c.concept_id },
    h("span", { class: "name" }, c.name),
    h("span", { class: "when" }, c.new ? "not studied yet" : "remembered ~" + pl(Math.round(c.stability_days), "day")),
    c.new ? h("div", { class: "meter empty", "aria-hidden": "true" }) : [meter(c.R_now, c.R_now < THETA_UI), h("span", { class: "note" }, "Mastery " + Math.round(c.mastery * 100) + "% · " + pl(c.n_responses, "answer"))])))));
  mount(nodes);
}

async function viewCurve(cid, theta, keep) {
  let r, ex;
  try { r = await api("/retention/" + cid + (theta ? "?theta=" + theta : "")); ex = await api("/explain/" + cid); }
  catch (e) { return mount(h("h1", {}, "Memory curve"), h("div", { class: "err" }, e.message), h("a", { class: "btn", href: "#/" }, "Back")); }
  // drawn in device pixels (1 unit = 1 px) so labels are the same size on a phone and a laptop
  const app = document.getElementById("app"), acs = getComputedStyle(app);
  const W = Math.round(Math.min(680, Math.max(280, app.clientWidth - parseFloat(acs.paddingLeft) - parseFloat(acs.paddingRight)))) || 328;
  const H = Math.round(Math.min(300, Math.max(200, W * 0.62))), L = 42, B = 28, T = 14, Rr = 12, FS = W >= 500 ? 14 : 13;
  const maxD = r.points[r.points.length - 1].day;
  const x = d => L + (d / maxD) * (W - L - Rr), y = v => T + (1 - v) * (H - T - B);
  const left = r.next_review_day - r.elapsed_days;                        // days from now, the same quantity as Today's rows
  const when = left <= 0 ? "review now" : "review " + aboutDays(left);
  const NS = "http://www.w3.org/2000/svg";
  const se = (t, a, txt) => { const e = document.createElementNS(NS, t); for (const [k, v] of Object.entries(a || {})) e.setAttribute(k, v); if (txt != null) e.textContent = txt; return e; };
  const svg = se("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart", style: "--fs:" + FS + "px", role: "img",
    "aria-label": "Predicted recall over the next " + maxD + " days. Recall now " + Math.round(r.R_now * 100) + "%, next review " + (left <= 0 ? "now" : aboutDays(left)) + "." });
  [0, 0.5, 1].forEach(v => { svg.append(se("line", { class: "grid", x1: L, x2: W - Rr, y1: y(v), y2: y(v) })); svg.append(se("text", { x: L - 6, y: y(v) + FS * 0.35, "text-anchor": "end" }, Math.round(v * 100) + "%")); });
  for (let i = 0; i <= 4; i++) { const d = (maxD * i) / 4; svg.append(se("text", { x: x(d), y: H - 8, "text-anchor": i === 0 ? "start" : i === 4 ? "end" : "middle" }, d.toFixed(0) + "d")); }
  const pts = r.points.map(p => x(p.day).toFixed(1) + "," + y(p.R).toFixed(1));
  svg.append(se("polygon", { class: "area", points: pts.join(" ") + " " + x(maxD) + "," + y(0) + " " + x(0) + "," + y(0) }));
  svg.append(se("line", { class: "target", x1: L, x2: W - Rr, y1: y(r.theta), y2: y(r.theta) }));
  svg.append(se("polyline", { class: "curve", points: pts.join(" ") }));
  svg.append(se("text", { class: "halo", x: L + 6, y: y(r.theta) + FS + 4, "text-anchor": "start" }, "target " + Math.round(r.theta * 100) + "%"));
  if (r.next_review_day <= maxD) {
    const rx = x(r.next_review_day), flip = rx > W - 140;
    svg.append(se("line", { class: "review", x1: rx, x2: rx, y1: T, y2: H - B }));
    svg.append(se("text", { class: "lab halo", x: flip ? rx - 6 : rx + 6, y: T + FS, "text-anchor": flip ? "end" : "start" }, when));
  }
  if (r.elapsed_days <= maxD) svg.append(se("circle", { class: "now", cx: x(r.elapsed_days), cy: y(r.R_now), r: 6 }));
  const nodes = [h("div", { class: "bar" }, h("a", { class: "btn link", href: "#/", "aria-label": "Back to today" }, icon("M15 5l-7 7 7 7", "chev"), "Today")),
    h("h1", { dir: "auto" }, r.concept), svg,
    h("p", { class: "muted" }, "The dot is you now, at " + Math.round(r.R_now * 100) + "% recall. REMEM asks you to review at the vertical line. Recall falls to about 90% after " + pl(Math.round(r.stability_days), "day") + ".")];
  if (S.role === "demo" || S.role === "admin") {
    const lab = h("b", {}, "target " + Math.round(r.theta * 100) + "%");
    const sl = h("input", { type: "range", min: 60, max: 97, value: Math.round(r.theta * 100), "aria-label": "What-if target retention", "aria-valuetext": Math.round(r.theta * 100) + "%",
      oninput: () => { lab.textContent = "target " + sl.value + "%"; sl.setAttribute("aria-valuetext", sl.value + "%"); }, onchange: () => viewCurve(cid, sl.value / 100, true) });
    nodes.push(h("div", { class: "panel" }, h("div", {}, "What-if target (demo only) ", lab), sl));
  }
  nodes.push(h("p", {}, rich(ex.explanation)), h("div", { class: "grid2" }, h("a", { class: "btn primary", href: "#/practice/" + cid }, "Practise now"), h("a", { class: "btn", href: "#/" }, "Back")));
  if (keep) remount(nodes, 'input[type="range"]'); else mount(nodes);
}

function viewMe() {
  const old = h("input", { id: "op", type: "password", autocomplete: "current-password" }), nw = h("input", { id: "np", type: "password", autocomplete: "new-password" });
  const msg = h("div", { class: "muted", role: "status" });
  mount(h("h1", {}, S.user || "Me"), S.role !== "student" ? h("p", { class: "muted" }, "Role: " + S.role) : null,
    h("h2", {}, "Change password"),
    h("form", { class: "stack", onsubmit: async (e) => { e.preventDefault(); try { await api("/auth/password", { method: "POST", body: { old_password: old.value, new_password: nw.value } }); msg.className = "ok"; msg.textContent = "Password changed."; old.value = nw.value = ""; } catch (ex) { msg.className = "err"; msg.textContent = ex.message; } } },
      h("input", { type: "text", autocomplete: "username", value: S.user || "", hidden: true, "aria-hidden": "true", tabindex: "-1" }),
      h("div", {}, h("label", { for: "op" }, "Current password"), old), h("div", {}, h("label", { for: "np" }, "New password (8 or more characters)"), nw), msg,
      h("button", { type: "submit" }, "Update password")),
    env().standalone ? null : h("p", {}, h("a", { class: "btn block", href: "#/install" }, "Add to home screen")),
    h("p", {}, h("button", { class: "block", onclick: () => signOut() }, "Sign out")));
}

// ---------------------------------------------------------------- router
let routeGen = 0;
function route() {
  routeGen++;
  const hash = location.hash || "#/";
  renderNav();
  if (hash.startsWith("#/install")) return viewInstall();
  if (!S.token) return viewLogin();
  const [path, query] = hash.split("?"), [, a, b] = path.split("/");
  if (a !== "practice") sess.cid = null;
  switch (a) {
    case "about": return viewAbout();
    case "consent": return viewConsent();
    case "notes": return b ? viewTopic(b, query === "r=1") : viewNotes();
    case "final": return viewFinal();
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
