/* Remem student app (PWA). Plain JS, no build step. All server text is inserted with textContent (never innerHTML). */
"use strict";

const CONSENT_TEXT =
`Remem pilot - what you agree to

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
let toastTimer = 0;
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), Math.max(4000, String(msg).length * 60));
}
const shown = nodes => nodes.flat(Infinity).filter(n => n != null && n !== false);     // an empty optional slot must not be drawn: replaceChildren(null) writes the word "null"
function mount(...nodes) {
  const app = document.getElementById("app"); app.replaceChildren(...shown(nodes)); window.scrollTo(0, 0);
  const h1 = app.querySelector("h1");
  document.title = (h1 ? h1.textContent + " - " : "") + "Remem";
  if (h1) { h1.tabIndex = -1; h1.focus({ preventScroll: true }); }          // a route change moves the reading position to the new heading
  if (window.remSplashDone) { window.remSplashDone(); window.remSplashDone = null; }   // the first screen is up: the launch logo can go
}
function markSvg(cls, size) {                       // the Remem mark, drawn in place so its parts can move (see .mk-* in styles.css)
  const NS = "http://www.w3.org/2000/svg", el = (tag, at) => { const e = document.createElementNS(NS, tag); for (const k in at) e.setAttribute(k, at[k]); return e; };
  const svg = el("svg", { viewBox: "0 0 512 512", width: size, height: size, class: "mk " + (cls || ""), "aria-hidden": "true" });
  svg.append(el("rect", { class: "mk-tile", width: 512, height: 512, rx: 112 }),
    el("path", { class: "mk-stem", pathLength: 1, d: "M164 366 L164 150" }), el("path", { class: "mk-branch", pathLength: 1, d: "M164 262 C164 206 210 170 274 170" }),
    el("circle", { class: "mk-ring", cx: 346, cy: 170, r: 30 }), el("circle", { class: "mk-ring mk-ring2", cx: 346, cy: 170, r: 30 }),
    el("circle", { class: "mk-dot", cx: 346, cy: 170, r: 30 }));
  return svg;
}
function remount(nodes, focusSel) {           // same screen redrawn in place (the demo's what-if slider): keep the scroll position and the focus
  const y = window.scrollY, app = document.getElementById("app");
  app.replaceChildren(...shown(nodes)); window.scrollTo(0, y);
  const el = focusSel && app.querySelector(focusSel); if (el) el.focus({ preventScroll: true });
}

// ---------------------------------------------------------------- API
async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (S.token) headers.Authorization = "Bearer " + S.token;
  const r = await fetch("api" + path, { method: opts.method || "GET", headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (r.status === 401 && S.token && path !== "/auth/password") { signOut(false); throw new Error("Please sign in again."); }   // a mistyped current password is not an expired session
  if (r.status === 403 && S.token && S.role !== "admin" && !/^#\/(about|consent)$/.test(location.hash)) {   // signed in but the intro form or consent is not done
    const d = await r.clone().json().catch(() => ({}));                     // (e.g. after going back from the consent screen):
    if (d.detail === "Consent required") { store.del("remem_consented"); location.replace("#/about"); const e = new Error("Finish signing up first."); e.status = 403; throw e; }
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;                                                   // a 422 sends a list of problems; show the first one in words
    const msg = (Array.isArray(d) ? fieldProblem(d[0]) : typeof d === "string" ? d : "").replace(/([^.!?])$/, "$1.");   // every message ends like a sentence
    const err = new Error(msg || ("Error " + r.status)); err.status = r.status;  // the status lets a not-found screen skip a retry that cannot work
    throw err;
  }
  return data;
}
const FIELD_NAMES = { title: "The title", text: "The notes text", old_password: "The current password", new_password: "The new password", full_name: "The name", contact: "The contact", age: "The age", username: "The username", password: "The password" };
function fieldProblem(p) {                                                  // one validation problem from the server, in plain words
  if (!p) return "Please check what you entered.";
  const field = FIELD_NAMES[(p.loc || []).slice(-1)[0]], type = String(p.type || ""), min = p.ctx && p.ctx.min_length;
  if (field && type.includes("too_short") && min === 1) return field + " is empty.";
  if (field && type.includes("too_short")) return field + " is too short" + (min ? " (at least " + pl(min, "character") + ")" : "") + ".";
  if (field && type.includes("too_long")) return field + " is too long.";
  if (field && type === "missing") return field + " is missing.";
  return p.msg ? String(p.msg).replace(/^Value error, /, "") : "Please check what you entered.";
}
const OFFLINE_MSG ="You're offline. Check your connection and try again.";
const isOffline = e => e instanceof TypeError || (e && e.message === "Offline");     // fetch failed, or the service worker's offline reply
function errText(e) { return isOffline(e) ? OFFLINE_MSG : e.message; }
function errScreen(title, e, back) {                                        // an error is never a dead end: say what happened, offer a retry and a way back
  const retry = e && (e.status === 404 || e.status === 422) ? null : h("button", { type: "button", onclick: () => route() }, "Try again");   // nothing to retry when the item does not exist
  return mount(h("h1", {}, title), h("div", { class: "err", role: "alert" }, errText(e)),
    h("div", { class: "actions" }, retry, back || null));
}
function signOut(call = true) {
  if (call && S.token) {
    const auth = { Authorization: "Bearer " + S.token, "Content-Type": "application/json" };
    (async () => {                                                           // this phone stops getting this account's reminders, then the session ends
      try { const sub = await currentSub(); if (sub) await fetch("api/push/unsubscribe", { method: "POST", headers: auth, body: JSON.stringify({ endpoint: sub.endpoint }) }); } catch (e) { /* best effort */ }
      fetch("api/auth/logout", { method: "POST", headers: auth }).catch(() => {});
    })();
  }
  setBadge(0); S.token = S.role = S.user = null;
  ["remem_token", "remem_role", "remem_user", "remem_queue", "remem_due", "remem_consented", "remem_name"].forEach(store.del);
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
const HANGUL = /([ᄀ-ᇿ㄰-㆏가-힯]+(?:[\sᄀ-ᇿ㄰-㆏가-힯]*[ᄀ-ᇿ㄰-㆏가-힯])?)/;
function ko(text) {                                  // Korean letters inside English text get lang="ko", so screen readers say them in Korean
  const parts = String(text).split(HANGUL);
  return parts.length === 1 ? String(text) : parts.map((p, i) => i % 2 ? h("span", { lang: "ko" }, p) : p).filter(p => p !== "");
}
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
// ---------------------------------------------------------------- sounds: original tones built in the browser (no files, nothing to download)
const SND = { ctx: null, out: null };
function soundOn() { return store.get("remem_sound") !== "0"; }
function audioReady() {                              // called inside the tap itself: phones only allow sound that starts from a tap
  if (!soundOn()) return null;
  try {
    if (!SND.ctx) {
      const C = window.AudioContext || window.webkitAudioContext; if (!C) return null;
      SND.ctx = new C(); const comp = SND.ctx.createDynamicsCompressor(); SND.out = SND.ctx.createGain(); SND.out.gain.value = 0.55;
      SND.out.connect(comp); comp.connect(SND.ctx.destination);
    }
    if (SND.ctx.state === "suspended") SND.ctx.resume();
    return SND.ctx;
  } catch (e) { return null; }
}
function tone(t, f, dur, o = {}) {
  const c = SND.ctx, g = c.createGain(), peak = o.gain ?? 0.35;
  g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + (o.attack ?? 0.006)); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  let out = g; if (o.lp) { const lp = c.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = o.lp; lp.Q.value = 0.7; g.connect(lp); out = lp; }
  out.connect(SND.out);
  (o.parts || [[1, 1, o.type || "sine"]]).forEach(([m, a, ty]) => {
    const os = c.createOscillator(), og = c.createGain(); os.type = ty || "sine"; os.frequency.setValueAtTime(f * m, t);
    if (o.glide) os.frequency.exponentialRampToValueAtTime(o.glide * m, t + (o.glideT ?? dur * 0.8));
    og.gain.value = a; os.connect(og); og.connect(g); os.start(t); os.stop(t + dur + 0.05);
  });
}
const PLUCK = [[1, 1, "sine"], [2, 0.35, "sine"], [3, 0.12, "triangle"]], BELL = [[1, 1, "triangle"], [2, 0.5, "sine"], [4.01, 0.12, "sine"]];
const SOUNDS = {
  right: t => { tone(t, 520, 0.07, { glide: 900, glideT: 0.05, gain: 0.18 }); tone(t + 0.06, 880, 0.32, { parts: PLUCK, gain: 0.3 }); tone(t + 0.14, 1318.5, 0.5, { parts: PLUCK, gain: 0.32 }); },   // Bubbly
  wrong: t => { tone(t, 392, 0.17, { type: "square", lp: 1800, gain: 0.30 }); tone(t + 0.13, 311.1, 0.32, { type: "square", lp: 1500, gain: 0.30 }); },   // Soft bonk: G4 down to E-flat 4, high enough for phone speakers and as loud as the right-answer sound
  end: t => { const n = [523.3, 659.3, 784, 1046.5]; n.forEach((f, i) => tone(t + i * 0.09, f, 0.3, { parts: PLUCK, gain: 0.24 })); n.forEach(f => tone(t + 0.4, f, 1.1, { parts: BELL, gain: 0.11, attack: 0.03 })); },   // Fanfare
};
function play(name) { const c = audioReady(); if (!c) return; try { SOUNDS[name](c.currentTime + 0.02); } catch (e) { /* no sound is fine */ } }

// ---------------------------------------------------------------- review reminders (web push)
const PUSH = { key: null, synced: false };
function swReady() {                                 // the service worker, or an error rather than waiting forever
  if (!("serviceWorker" in navigator)) return Promise.reject(new Error("This browser can't show reminders."));
  return Promise.race([navigator.serviceWorker.ready, new Promise((_, no) => setTimeout(() => no(new Error("The app is still loading. Try again in a moment.")), 8000))]);
}
async function currentSub() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return null;
  try { return await (await swReady()).pushManager.getSubscription(); } catch (e) { return null; }
}
function b64bytes(s) { const raw = atob((s + "=".repeat((4 - s.length % 4) % 4)).replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from(raw, c => c.charCodeAt(0)); }
async function pushKey() { if (!PUSH.key) PUSH.key = await api("/push/key"); return PUSH.key; }
async function reminderState() {                     // on | off | blocked | needs-install | unsupported | unavailable
  const e = env();
  if (e.ios && !e.standalone) return "needs-install";
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return "unsupported";
  try { if (!(await pushKey()).enabled) return "unavailable"; } catch (x) { return "unavailable"; }
  if (Notification.permission === "denied") return "blocked";
  return Notification.permission === "granted" && await currentSub() ? "on" : "off";
}
async function turnOnReminders() {
  const perm = await Notification.requestPermission();                       // first, while the tap still counts: phones only show the prompt after a tap
  if (perm !== "granted") throw new Error(perm === "denied" ? "Notifications are blocked. Allow them for Remem in your phone's settings." : "Reminders are still off.");
  const k = await pushKey();
  if (!k.enabled) throw new Error("Reminders aren't available yet.");
  const reg = await swReady();
  const sub = (await reg.pushManager.getSubscription()) || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64bytes(k.public_key) });
  await api("/push/subscribe", { method: "POST", body: sub.toJSON() });
  store.set("remem_push", "1");
}
async function turnOffReminders() {
  const sub = await currentSub();
  if (sub) { await api("/push/unsubscribe", { method: "POST", body: { endpoint: sub.endpoint } }); await sub.unsubscribe().catch(() => {}); }
  store.del("remem_push");
}
async function syncReminders() {                     // once per visit: keep the server's copy current (new phone, signed in as someone else, or a renewed address)
  if (PUSH.synced || !S.token || !("Notification" in window) || Notification.permission !== "granted") return;
  PUSH.synced = true;
  try {
    let sub = await currentSub();
    if (!sub && store.get("remem_push") === "1") { const k = await pushKey(); if (k.enabled) sub = await (await swReady()).pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64bytes(k.public_key) }); }
    if (sub) await api("/push/subscribe", { method: "POST", body: sub.toJSON() });
  } catch (e) { /* tried again on the next visit */ }
}
function clearShownReminders() {                     // opening Today answers the reminder: take it off the lock screen
  swReady().then(r => r.getNotifications({ tag: "remem-due" })).then(ns => ns.forEach(n => n.close())).catch(() => {});
}
function remindersHidden() { const t = Number(store.get("remem_remind_hide") || 0); return Date.now() - t < 7 * 86400000; }
async function fillReminderCard(slot) {              // Today: offer reminders once the person has studied something
  if (remindersHidden() || await reminderState() !== "off") return;
  const go = h("button", { class: "btn outline", type: "button", onclick: async () => {     // secondary: the next quiz stays the one solid button
    go.disabled = true; go.setAttribute("aria-busy", "true");
    try { await turnOnReminders(); slot.replaceChildren(h("div", { class: "calm" }, h("b", {}, "Reminders are on"), h("p", { class: "muted" }, "You'll get one on days a concept is due, between 9 am and 9 pm."))); }
    catch (e) { go.disabled = false; go.removeAttribute("aria-busy"); toast(errText(e)); }
  } }, "Turn on reminders");
  slot.replaceChildren(h("div", { class: "calm" }, h("b", {}, "Get a reminder when it's time"),
    h("p", { class: "muted" }, "Remem can tell you when a concept is due to review: at most once a day, and never at night."),
    h("div", { class: "actions" }, go, h("button", { class: "link", type: "button", onclick: () => { store.set("remem_remind_hide", String(Date.now())); slot.replaceChildren(); } }, "Not now"))));
}
async function fillReminderSettings(slot) {          // Me: the current state in words, and the one action that fits it
  const st = await reminderState();
  const msg = h("div", { class: "muted", role: "status" });
  const redo = () => fillReminderSettings(slot);
  const btn = (label, fn, cls) => { const b = h("button", { class: cls || "", type: "button", onclick: async () => { b.disabled = true; try { await fn(); } catch (e) { msg.className = "err"; msg.textContent = errText(e); } b.disabled = false; } }, label); return b; };
  const text = {
    on: "On. Remem sends one reminder on days a concept is due, between 9 am and 9 pm.",
    off: "Off. Turn them on to hear when a concept is due to review.",
    blocked: "Notifications are blocked for Remem. Allow them in your phone's settings (Notifications), then come back here.",
    "needs-install": "On iPhone, reminders work once Remem is on your home screen. Add it, open it from the home screen, and turn reminders on here.",
    unsupported: "This browser can't show reminders. Use Chrome on Android, or add Remem to your home screen on iPhone.",
    unavailable: "Reminders aren't available right now.",
  }[st];
  const acts = [];
  if (st === "off") acts.push(btn("Turn on reminders", async () => { await turnOnReminders(); redo(); }, "primary"));
  if (st === "on") acts.push(btn("Send a test reminder", async () => { const r = await api("/push/test", { method: "POST" }); msg.className = r.sent ? "ok" : "err"; msg.textContent = r.sent ? "Sent. It should appear in a few seconds." : "It couldn't reach this phone. Turn reminders off and on again."; }),
                             btn("Turn off", async () => { await turnOffReminders(); redo(); }));
  if (st === "needs-install") acts.push(h("a", { class: "btn", href: "#/install" }, "Show how"));
  slot.replaceChildren(...shown([h("p", {}, text), acts.length ? h("div", { class: "actions" }, acts) : null, msg]));
}
function installBanner() {
  const e = env();
  if (e.standalone || installBannerHidden()) return null;
  return h("div", { class: "calm install" }, h("b", {}, "Add Remem to your home screen"),
    h("p", { class: "muted" }, "It opens like an app, and it can remind you when concepts are due."),
    h("div", { class: "actions" }, h("a", { class: "btn", href: "#/install" }, "Show how"),
      h("button", { class: "link", type: "button", onclick: () => { store.set("remem_install_hide", String(Date.now())); route(); } }, "Not now")));
}
function phoneArt() {
  const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 120 150"); svg.setAttribute("class", "phone-art"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "A phone with the Remem icon on its home screen");
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
  if (e.standalone) return mount(h("h1", {}, "Already on your home screen"), phoneArt(), h("p", { class: "muted" }, "You're using Remem as an app. Nothing more to do."), back);
  const nodes = [h("h1", {}, "Add Remem to your home screen"), phoneArt(), h("p", {}, "It opens full screen like an app, and the icon shows how many questions are waiting.")];
  if (e.inApp) {
    const copy = h("button", { class: "block", onclick: async () => { try { await navigator.clipboard.writeText(location.origin + "/"); toast("Link copied. Paste it in Chrome or Safari."); } catch (x) { toast("Copy the address from the menu instead."); } } }, "Copy the link");
    nodes.push(h("div", { class: "panel" }, h("b", {}, "First, open it in your browser"), h("p", { class: "muted" }, "This page is open inside another app (such as WhatsApp or Instagram), and those can't add to the home screen. Tap the menu or the compass icon and choose Open in browser (Chrome or Safari), or copy the link and paste it there."), copy));
  }
  if (deferredInstall) {
    nodes.push(h("button", { class: "primary block", onclick: async () => { deferredInstall.prompt(); try { await deferredInstall.userChoice; } catch (x) { /* dismissed */ } deferredInstall = null; route(); } }, "Add to home screen"));
    nodes.push(h("p", { class: "muted small" }, "Prefer to do it yourself? The steps are below."));
  }
  let steps, title;
  if (e.ios) { title = e.iosOtherBrowser ? "On iPhone, in your browser" : "On iPhone, in Safari"; steps = [e.iosOtherBrowser ? "Tap the Share button (a square with an arrow) in the toolbar or the address bar." : "Tap the Share button (a square with an arrow) at the bottom of Safari.", "Scroll down in the sheet and tap Add to Home Screen.", "Tap Add in the top corner. Remem appears on your home screen."]; }
  else if (e.samsung) { title = "On Samsung Internet"; steps = ["Tap the menu (three lines) at the bottom right.", "Tap Add page to, then Home screen.", "Tap Add."]; }
  else if (e.android) { title = "On Android, in Chrome"; steps = ["Tap the menu (three dots) at the top right.", "Tap Install app. If you see Add to Home screen instead, tap that.", "Tap Install or Add. Remem appears on your home screen."]; }
  else { title = "On a computer"; steps = ["Look for the install icon at the right end of the address bar, or open the browser menu.", "Choose Install Remem (Chrome and Edge).", "Confirm. Remem opens in its own window."]; }
  nodes.push(h("h2", {}, title), stepList(steps));
  nodes.push(h("details", { class: "own" }, h("summary", {}, "Can't see the option?"),
    h("ul", { class: "muted" },
      h("li", {}, "Open the link in Chrome (Android) or Safari (iPhone). Links opened from WhatsApp, Instagram or similar usually can't be added."),
      h("li", {}, "On iPhone, other browsers can add it only on recent iOS versions; Safari always can."),
      h("li", {}, "Private or incognito tabs hide the option. Open a normal tab."),
      h("li", {}, "You can use Remem in the browser without adding it. Nothing is lost."))));
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
function dueCount() { try { const d = JSON.parse(store.get("remem_due") || "null"); return d && d.test ? d.test.questions : 0; } catch (e) { return 0; } }
function renderNav() {
  const nav = document.getElementById("nav"), who = document.getElementById("who");
  nav.replaceChildren(); who.textContent = S.token ? S.user : "";
  const cur = (location.hash || "#/").split("?")[0], n = dueCount();
  if (S.token && S.role === "admin") {                                   // the owner's tabs
    [["#/", "Pilot", "today"], ["#/admin/test", "Remem Test", "concepts"], ["#/me", "Me", "me"]].forEach(([href, label, ic]) => {
      const on = href === "#/" ? (cur === "#/" || cur.startsWith("#/admin/p") || cur.startsWith("#/admin/notify")) : href === "#/admin/test" ? (cur.startsWith("#/admin/test") || cur.startsWith("#/admin/try")) : cur.startsWith(href);
      nav.append(h("a", { href, class: on ? "on" : "", "aria-current": on ? "page" : false }, icon(ic), label));
    });
    return;
  }
  if (!S.token || /^#\/(about|consent)$/.test(cur) || store.get("remem_consented") !== "1") return;   // no browsing before the intro form and consent
  [["#/", "Today", "today"], ["#/notes", "Topics", "notes"], ["#/concepts", "Concepts", "concepts"], ["#/me", "Me", "me"]].forEach(([href, label, ic]) => {
    const on = href === "#/" ? cur === "#/" : cur.startsWith(href);
    const badge = href === "#/" && n;
    nav.append(h("a", { href, class: on ? "on" : "", "aria-current": on ? "page" : false, "aria-label": badge ? label + ", " + pl(n, "question") + " waiting" : false },
      icon(ic), label, badge ? h("span", { class: "badge", "aria-hidden": "true" }, String(n)) : null));
  });
}

// ---------------------------------------------------------------- views
const THETA_UI = 0.85;
function skeleton(n, hero) { return h("div", { "aria-busy": "true", "aria-label": "Loading" }, h("div", { class: "mk-wait" }, markSvg("mk-breathe", 28)), hero ? h("div", { class: "skel hero" }) : null, Array.from({ length: n }, () => h("div", { class: "skel" }))); }
function meter(R, fading, name) {      // the freshness bar: how much you still remember
  const pct = Math.round(R * 100);
  return h("div", { class: "meter" + (fading ? " fading" : ""), role: "meter", "aria-label": name ? name + ", recall" : "Recall", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": pct, "aria-valuetext": pct + "% recall" }, h("i", { style: "--v:" + R }));
}
function aboutDays(d) { return d <= 0.5 ? "today" : "in about " + pl(Math.max(1, Math.round(d)), "day"); }      // Today and the memory curve round the same way

function viewLogin() {
  const err = h("div", { class: "err", role: "alert" });
  const u = h("input", { autocomplete: "username", autocapitalize: "none", spellcheck: "false", placeholder: "e.g. user01" });
  const p = h("input", { type: "password", autocomplete: "current-password" });
  const showBtn = h("button", { type: "button", "aria-pressed": "false", onclick: () => { const on = p.type === "password"; p.type = on ? "text" : "password"; showBtn.textContent = on ? "Hide" : "Show"; showBtn.setAttribute("aria-pressed", String(on)); } }, "Show");
  const go = h("button", { class: "primary block", type: "submit" }, "Sign in");
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault(); err.textContent = ""; u.removeAttribute("aria-invalid"); p.removeAttribute("aria-invalid");
    const empty = !u.value.trim() ? [u, "Enter your username."] : !p.value ? [p, "Enter your password."] : null;   // said at once, at the field
    if (empty) { err.textContent = empty[1]; empty[0].setAttribute("aria-invalid", "true"); empty[0].focus(); return; }
    go.disabled = true;
    try {
      const r = await api("/auth/login", { method: "POST", body: { username: u.value.trim(), password: p.value } });
      S.token = r.token; S.role = r.role; S.user = r.username;
      if (r.consent_ok) store.set("remem_consented", "1"); else store.del("remem_consented");
      store.set("remem_token", r.token); store.set("remem_role", r.role); store.set("remem_user", r.username);
      const to = !r.profile_ok ? "#/about" : (r.consent_ok ? "#/" : "#/consent");
      if (location.hash === to || (!location.hash && to === "#/")) route(); else location.replace(to);   // replace: back never returns to the sign-in form
    } catch (ex) { err.textContent = errText(ex); go.disabled = false; if (!isOffline(ex)) { p.focus(); p.select(); } }
  } }, h("div", {}, h("label", { for: "u" }, "Username"), u), h("div", {}, h("label", { for: "p" }, "Password"), h("div", { class: "pw" }, p, showBtn)), err, go);
  u.id = "u"; p.id = "p";
  mount(h("h1", {}, "Remember what you study"), h("p", { class: "muted" }, "Remem quizzes you just before you'd forget, so what you study actually stays. You get a username and password when you join the study."), form,
    env().standalone ? null : h("p", {}, h("a", { href: "#/install" }, "Add Remem to your home screen")));
}

async function viewAbout() {
  mount(h("h1", {}, "A quick intro"), skeleton(3));
  let f; try { f = await api("/auth/profile"); } catch (e) { return errScreen("A quick intro", e); }
  if (f.done) { location.replace("#/consent"); return; }
  const name = h("input", { id: "pn", autocomplete: "name", maxlength: 80 });
  const contact = h("input", { id: "pc", autocomplete: "email", autocapitalize: "none", spellcheck: "false", maxlength: 120, placeholder: "Email or phone number" });
  const age = h("input", { id: "pa", type: "number", inputmode: "numeric", min: 10, max: 100 });
  const err = h("div", { class: "err", role: "alert" });
  const fe = { pn: h("div", { class: "field-err", id: "e-pn" }), pc: h("div", { class: "field-err", id: "e-pc" }), pa: h("div", { class: "field-err", id: "e-pa" }) };
  const mark = (input, text) => { fe[input.id].textContent = text; if (text) { input.setAttribute("aria-invalid", "true"); input.setAttribute("aria-describedby", "e-" + input.id); } else { input.removeAttribute("aria-invalid"); input.removeAttribute("aria-describedby"); } return !text; };
  const boxes = f.topics.map(t => ({ t, box: h("input", { type: "checkbox", value: t.id }) }));
  const go = h("button", { class: "primary block", type: "submit" }, "Continue");
  const form = h("form", { class: "stack", novalidate: true, onsubmit: async (e) => {
    e.preventDefault(); err.textContent = "";
    const ok = [mark(name, name.value.trim() ? "" : "Enter your name."),
                mark(contact, contact.value.trim().length >= 3 ? "" : "Enter an email address or phone number."),
                mark(age, Number(age.value) >= 10 && Number(age.value) <= 100 ? "" : "Enter your age as a number from 10 to 100.")];
    const bad = [name, contact, age][ok.indexOf(false)];
    if (bad) { bad.focus({ preventScroll: true }); bad.scrollIntoView({ block: "center" }); return; }
    go.disabled = true;
    try {
      await api("/auth/profile", { method: "POST", body: { full_name: name.value.trim(), contact: contact.value.trim(), age: Number(age.value), known_topics: boxes.filter(b => b.box.checked).map(b => b.t.id) } });
      location.replace("#/consent");                                     // the form is done: back skips it
    } catch (ex) { err.textContent = errText(ex); go.disabled = false; }
  } },
    h("div", { class: "panel" }, "Your details stay private: only the project owner, Aryan Joshi, can see them. They are not shared with anyone and are used only for this final-year project (and a follow-up survey if one is needed). In results you are just a number, never a name."),
    h("div", {}, h("label", { for: "pn" }, "Name"), name, fe.pn), h("div", {}, h("label", { for: "pc" }, "Email or phone"), contact, fe.pc), h("div", {}, h("label", { for: "pa" }, "Age"), age, fe.pa),
    h("h2", {}, "What do you already know well?"),
    h("p", { class: "muted" }, "Tick any topic you could already explain in detail. Please be honest: this is not a test, and it keeps the study fair. Tick nothing if none apply."),
    h("div", { class: "checks" }, boxes.map(b => h("label", { class: "check" }, b.box, h("span", {}, h("b", {}, b.t.title), h("span", { class: "muted small" }, " " + b.t.subject))))),
    err, go);
  mount(h("h1", {}, "A quick intro"), h("p", { class: "muted" }, "One short form before you start. It takes about a minute."), form);
}

async function viewConsent() {
  if (store.get("remem_consented") === "1") { location.replace("#/"); return; }   // already agreed (e.g. came back here with the back button)
  try { if ((await api("/auth/profile")).consent_ok) { store.set("remem_consented", "1"); location.replace("#/"); return; } } catch (e) { /* show the screen */ }
  const ok = h("button", { class: "primary block", onclick: async () => {
    try { await api("/auth/consent", { method: "POST" }); store.set("remem_consented", "1"); location.replace("#/notes"); } catch (e) { toast(errText(e)); }
  } }, "I agree");
  const [head, ...lines] = CONSENT_TEXT.split("\n").filter(l => l.trim());              // the fixed text, drawn as a heading and a real list
  mount(h("h1", {}, "Before you start"), h("div", { class: "panel consent" }, h("p", { class: "consent-head" }, head),
        h("ul", {}, lines.map(l => h("li", {}, l.replace(/^- /, ""))))), ok,
        h("p", {}, h("button", { class: "block", onclick: () => signOut() }, "No thanks, sign out")));
}

function renderHome(d) {
  const t = d.test || { questions: 0, answered: 0, concepts: 0 };
  setBadge(t.questions);
  const nodes = [h("h1", {}, "Today")];
  if (S.offline) nodes.push(h("p", { class: "muted small offline", role: "status" }, "Offline. Showing what was saved on this phone."));
  const mins = n => "About " + pl(Math.max(1, Math.round(n * 15 / 60)), "minute") + ".";          // about 15 seconds a question
  const first = d.first || [];
  let hero = false;
  if (t.questions > 0) {                    // one card, no concept names: the test checks what you remember, not what you can guess
    hero = true;
    nodes.push(h("div", { class: "next" }, h("h2", {}, t.answered ? "Finish today's test" : "Today's test"),
      h("p", {}, (t.answered ? pl(t.questions, "question") + " left" : pl(t.questions, "question") + " from " + pl(t.concepts, "concept")) + ". " + mins(t.questions)),
      h("a", { class: "btn", href: "#/test" }, t.answered ? "Continue the test" : "Start the test")));
  }
  const fin = d.final || {};
  const remOpen = fin.open && fin.remaining > 0;
  if (remOpen) {                            // the study's last check comes first while it is open (after a test already in progress)
    const line = "One last check on everything you've studied: " + pl(fin.remaining, "question") + (fin.answered ? " left" : "") + ", no hints. It doesn't change your schedule.";
    const go = fin.answered ? "Continue the Remem Test" : "Start the Remem Test";
    if (!hero) { hero = true; nodes.push(h("div", { class: "next" }, h("h2", {}, "The Remem Test is open"), h("p", {}, line), h("a", { class: "btn", href: "#/final" }, go))); }
    else nodes.push(h("div", { class: "calm" }, h("b", {}, "The Remem Test is open"), h("p", { class: "muted" }, line), h("a", { class: "btn outline block", href: "#/final" }, go)));
  }
  first.forEach(f => {                      // a topic just read: its first quiz, kept apart from the reviews
    const card = [h("h2", {}, "First quiz: " + f.title), h("p", {}, pl(f.questions, "question") + " on what you just read. " + mins(f.questions))];
    const label = "Start the first quiz: " + f.title;
    if (!hero) { hero = true; nodes.push(h("div", { class: "next" }, card, h("a", { class: "btn", href: "#/test?note=" + f.note_id, "aria-label": label }, "Start the first quiz"))); }
    else nodes.push(h("div", { class: "calm" }, h("b", {}, "First quiz: " + f.title), h("p", { class: "muted" }, card[1].textContent), h("a", { class: "btn outline block", href: "#/test?note=" + f.note_id, "aria-label": label }, "Start the first quiz")));
  });
  if (!remOpen && fin.finished) {
    nodes.push(h("div", { class: "calm" }, h("b", {}, "You finished the Remem Test"), h("p", { class: "muted" }, "Thank you. Your notes are unlocked again, so you can re-read any topic.")));
  }
  if (!hero && d.studied) {
    const nextP = h("p", { class: "muted" }, d.next_test_in_days == null ? "Your next test will appear here." : "Your next test is " + aboutDays(d.next_test_in_days) + ".");
    if (d.next_test_in_days != null && !S.offline) reminderState().then(s => { if (s === "on") nextP.append(" Remem will remind you."); }).catch(() => {});   // promised only when reminders are on
    nodes.push(h("div", { class: "calm" }, h("b", {}, "You're all caught up"), nextP,
      h("a", { class: "btn block", href: "#/notes" }, "Pick another topic")));
  } else if (!hero && !d.studied) {
    nodes.push(h("div", { class: "calm" }, h("b", {}, "How Remem works"),
      stepList(["Pick a topic and read it once. Just understand it, no need to memorise.", "Take a short quiz.", "Remem works out when you're about to forget and sends you a quick test then."])),
      h("a", { class: "btn primary block", href: "#/notes" }, "Pick a topic"));
  }
  if (!S.offline && d.studied) { const slot = h("div", { class: "remind-slot" }); nodes.push(slot); fillReminderCard(slot); }   // offered once something has been studied
  const ib = installBanner(); if (ib) nodes.push(ib);
  mount(nodes);
  if (d.whats_new && !S.offline) showWhatsNew(d);
}
let whatsNewShown = false;
function showWhatsNew(d) {                 // once, only for people who had answered questions before these changes went live
  if (whatsNewShown || !window.HTMLDialogElement) return;
  whatsNewShown = true;
  const seen = () => api("/whats-new/seen", { method: "POST" }).catch(() => {});
  const close = () => { dlg.close(); dlg.remove(); };
  const reads = d.last_read || [];
  const item = (title, text) => h("li", {}, h("b", {}, title), " " + text);
  const dlg = h("dialog", { class: "sheet", "aria-labelledby": "wn-title" },
    h("h2", { id: "wn-title" }, "Thank you for testing Remem"),
    h("p", {}, "A few things went wrong in the first days, and your feedback helped fix them. Here's what's new:"),
    h("ol", { class: "wn" },
      item("No more repeated questions.", "Each question comes up once per test. The schedule is fixed too, so nothing gets pushed 348 days away any more."),
      item("One test a day.", "Everything due is mixed into one short test, without telling you the topic. That way it checks what you remember, not what you can guess. You see the right answers at the end."),
      item("Reminders.", "Turn them on, and Remem tells you when your test is ready."),
      item("Notes lock after one read.", "If you could re-read, Remem couldn't tell what you remembered from what you just read. You get one last read now; after that, your notes open again once you finish the Remem Test.")),
    h("p", { class: "muted" }, "Thanks for your help."),
    h("div", { class: "stack" },
      reads.length ? h("button", { class: "primary block", type: "button", onclick: () => { seen(); close(); location.hash = reads.length === 1 ? "#/notes/" + reads[0].topic_id : "#/notes"; } }, "Read my notes one last time") : null,
      h("button", { class: reads.length ? "block" : "primary block", type: "button", onclick: () => { seen(); close(); } }, "Got it")));
  dlg.addEventListener("cancel", () => { seen(); setTimeout(() => dlg.remove(), 0); });   // Esc or the back gesture counts as seen
  document.body.append(dlg); dlg.showModal();
}
function confirmSheet(title, text, yes, no) {     // a small native sheet; resolves true for the first button
  return new Promise(resolve => {
    if (!window.HTMLDialogElement) { resolve(window.confirm(title + "\n\n" + text)); return; }
    const done = v => { dlg.close(); dlg.remove(); resolve(v); };
    const dlg = h("dialog", { class: "sheet", "aria-labelledby": "cs-title" }, h("h2", { id: "cs-title" }, title), h("p", {}, text),
      h("div", { class: "stack" }, h("button", { class: "primary block", type: "button", onclick: () => done(true) }, yes), h("button", { class: "block", type: "button", onclick: () => done(false) }, no)));
    dlg.addEventListener("cancel", e => { e.preventDefault(); done(false); });
    document.body.append(dlg); dlg.showModal();
  });
}
async function viewHome() {
  syncReminders(); clearShownReminders();
  let cached = null; try { cached = JSON.parse(store.get("remem_due") || "null"); } catch (e) { /* ignore */ }
  if (cached && !cached.test) cached = null;                                         // saved by an older version of the app: not drawn
  if (cached) renderHome(cached); else mount(h("h1", {}, "Today"), skeleton(3, true));     // show last known state instantly, refresh underneath
  let d;
  try { d = await api("/due"); }
  catch (e) {
    if (!cached) return errScreen("Today", e);
    if (isOffline(e) && (location.hash === "" || location.hash === "#/")) { S.offline = true; renderHome(cached); S.offline = false; }
    return;
  }
  const fresh = JSON.stringify(d);
  const same = cached && fresh === JSON.stringify(cached);
  store.set("remem_due", fresh);
  renderNav();                                                                      // refresh the due badge
  if (!same && (location.hash === "" || location.hash === "#/")) renderHome(d);     // no second render (and no second bar animation) when nothing changed
}

function progress(done, total) {          // the progress bar: grows smoothly as each answer is given
  const fill = h("i", { style: "width:" + (total ? 100 * done / total : 0) + "%" });
  const bar = h("div", { class: "progress", role: "progressbar", "aria-label": "Progress", "aria-valuemin": 0, "aria-valuemax": total, "aria-valuenow": done, "aria-valuetext": done + " of " + total + " answered" }, fill);
  bar.step = n => { fill.style.width = (total ? 100 * n / total : 0) + "%"; bar.setAttribute("aria-valuenow", n); bar.setAttribute("aria-valuetext", n + " of " + total + " answered"); };
  return bar;
}
function testHeader(prog, pos, total) {
  return h("div", { class: "testbar" }, h("a", { class: "btn link close", href: "#/", "aria-label": "Close the test. Your answers are saved." }, icon("M6 6l12 12M18 6L6 18")),
    prog, h("span", { class: "count", "aria-hidden": "true" }, pos + " of " + total));
}
function newKey() { return crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random(); }

async function viewTest(note) {           // today's test (all due concepts, mixed) or one topic's first quiz; no concept names until the end
  const title = note ? "First quiz" : "Today's test", back = h("a", { class: "btn", href: "#/" }, "Back to today");
  mount(h("h1", {}, title), skeleton(2));
  let q; try { q = await api("/test/next" + (note ? "?note=" + note : "")); } catch (e) {
    if (e.status === 404 && note) return mount(h("h1", {}, "This quiz isn't here any more"), h("p", { class: "muted" }, "It may have finished already. Today shows everything that is waiting for you."), h("p", {}, h("a", { class: "btn primary block", href: "#/" }, "Back to today")));   // an old link
    return errScreen(title, e, back);
  }
  if (q.done) return testDone(q, note);
  const prog = progress(q.position - 1, q.total), last = q.position >= q.total;
  const t0 = performance.now();
  let answered = false;
  const fb = h("div", { class: "fb stack", role: "status" });
  const opts = q.options.map((text, i) => h("button", { class: "opt", onclick: async () => {
    if (answered) return; answered = true;
    audioReady();                                                            // unlock sound inside the tap; it plays when the answer comes back
    opts.forEach(b => b.disabled = true);
    const body = { question_id: q.question_id, chosen_index: i, shuffled: q.shuffled === true, rt_ms: Math.round(performance.now() - t0), idem_key: newKey() };
    opts[i].classList.add("picked");
    try {
      const r = await api("/respond", { method: "POST", body });
      play(r.correct ? "right" : "wrong");
      prog.step(q.position);
      const mine = opts[i];                                                 // only your own pick is marked: the right answers come at the end,
      mine.classList.add(r.correct ? "right" : "wrong");                    // so every answer in the test is a clean test of memory
      mine.querySelector(".key").replaceChildren(icon(r.correct ? "M5 12.5l4.5 4.5L19 7.5" : "M6 6l12 12M18 6L6 18"));
      fb.replaceChildren(...shown([h("div", { class: "verdict " + (r.correct ? "ok" : "err") }, r.correct ? "Correct" : "Not quite"),
        r.correct ? null : h("p", { class: "muted small" }, "You'll see the right answer at the end of the test."),
        h("button", { class: "primary block", onclick: () => viewTest(note) }, last ? "See how you did" : "Next question")]));
      store.del("remem_due");
      opts[i].classList.remove("picked");
      fb.scrollIntoView({ block: "end", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      const next = fb.querySelector("button.primary"); if (next) next.focus({ preventScroll: true });
    } catch (e) {
      if (e instanceof TypeError) { const qd = queue(); qd.push(body); saveQueue(qd); fb.replaceChildren(h("div", { class: "panel" }, "You're offline. Your answer is saved and will sync when you reconnect."), h("a", { class: "btn block", href: "#/" }, "Back to today")); }
      else { answered = false; opts[i].classList.remove("picked"); opts.forEach(b => b.disabled = false); toast(errText(e)); if (e.status === 409) viewTest(note); }
    }
  } }, h("span", { class: "key", "aria-hidden": "true" }, "ABCD"[i]), h("span", { class: "txt", dir: "auto" }, ko(text))));
  const flag = h("button", { class: "link flag", type: "button", onclick: async () => {
    try { await api("/flag", { method: "POST", body: { question_id: q.question_id } }); toast("Thanks, question flagged"); flag.textContent = "Reported, thank you"; flag.disabled = true; } catch (x) { toast(errText(x)); }
  } }, "Report a bad question");
  mount(testHeader(prog, q.position, q.total), h("h1", { class: "q", dir: "auto" }, ko(q.stem)), h("div", { class: "opts" }, opts), fb, h("p", { class: "links" }, flag));
}

function testDone(s, note) {               // the score, then each concept by name: how it went and when it comes back
  store.del("remem_due");
  const back = h("p", {}, h("a", { class: "btn primary block", href: "#/" }, "Back to today"));
  if (!s.total) return mount(h("h1", {}, "Nothing to answer right now"), h("p", { class: "muted" }, "There's no test waiting. Remem will bring your next one when it's time."), back);
  play("end");
  const rows = s.concepts.filter(c => c.marks.length).map(c => h("li", {},      // no per-concept return date: side by side, those would show which method schedules each concept
    h("span", { class: "name", dir: "auto" }, ko(c.name)),
    h("span", { class: "dots", role: "img", "aria-label": c.marks.filter(Boolean).length + " of " + c.marks.length + " right" }, c.marks.map(m => h("i", { class: m ? "on" : "" })))));
  const missed = (s.missed || []).map(m => h("li", { class: "miss" },
    h("p", { class: "q", dir: "auto" }, ko(m.stem)),
    m.chosen_index == null || m.chosen_index === m.correct_index ? null
      : h("p", { class: "ans bad", dir: "auto" }, h("span", { class: "lab" }, "Your answer"), ko(m.options[m.chosen_index])),
    h("p", { class: "ans good", dir: "auto" }, h("span", { class: "lab" }, "Right answer"), ko(m.options[m.correct_index]))));
  mount(h("div", { class: "mk-done" }, markSvg("mk-burst", 56)), h("h1", {}, note ? "First quiz done" : "Test done"),
    h("div", { class: "score" }, h("b", {}, s.right + " of " + s.total), h("span", {}, " right")),
    h("ul", { class: "ledger summary" }, rows),
    h("p", { class: "muted" }, "Remem brings each concept back in a later test when it's time."),
    h("h2", {}, missed.length ? "Your mistakes" : "No mistakes this time"),
    missed.length ? h("ul", { class: "misses" }, missed) : null, back);
}

async function viewFinal() {               // the Remem Test: three unseen questions per concept, shuffled, no names, no right or wrong until the end
  const back = h("p", {}, h("a", { class: "btn block", href: "#/" }, "Back to today")), title = "The Remem Test";
  mount(h("h1", {}, title), skeleton(2));
  let d; try { d = await api("/due"); } catch (e) { return errScreen(title, e, back); }
  const fin = d.final || {};
  if (!fin.open) return mount(h("h1", {}, title), h("div", { class: "calm" }, h("b", {}, "The Remem Test isn't open yet"), h("p", { class: "muted" }, "You'll hear when it opens.")), back);
  if (!fin.total) return mount(h("h1", {}, title), h("div", { class: "calm" }, h("b", {}, "Nothing to answer"), h("p", { class: "muted" }, "Study a topic first, then come back for the Remem Test.")), back);
  if (fin.remaining > 0) {
    mount(h("h1", {}, title), h("p", {}, "Do you still remember? " + pl(fin.total, "question") + " on the concepts you've studied, mixed together, with no hints. You'll see your score at the end, and your review schedule stays as it is."),
      h("button", { class: "primary block", onclick: () => ask() }, fin.answered ? "Continue (" + fin.remaining + " left)" : "Begin"), back);
  } else ask();

  async function ask() {
    mount(h("h1", {}, title), skeleton(2));
    let q; try { q = await api("/final/next"); }
    catch (e) { return mount(h("h1", {}, title), h("div", { class: "err", role: "alert" }, errText(e)), h("button", { class: "block", onclick: () => ask() }, "Try again"), back); }
    if (q.done) {
      play("end"); store.del("remem_due");
      return mount(h("div", { class: "mk-done" }, markSvg("mk-burst", 56)), h("h1", {}, "Remem Test done"), h("div", { class: "score" }, h("b", {}, q.right + " of " + q.total), h("span", {}, " right")),
        h("p", { class: "muted" }, "Thank you. Your notes are unlocked again, so you can re-read any topic."), h("p", {}, h("a", { class: "btn primary block", href: "#/" }, "Back to today")));
    }
    const prog = progress(q.position - 1, q.total), t0 = performance.now(); let sent = false;
    const opts = q.options.map((text, k) => h("button", { class: "opt", onclick: async () => {
      if (sent) return; sent = true; audioReady(); opts.forEach(b => { b.disabled = true; }); opts[k].classList.add("picked");
      try {
        await api("/respond", { method: "POST", body: { question_id: q.question_id, chosen_index: k, shuffled: q.shuffled === true, rt_ms: Math.round(performance.now() - t0), idem_key: newKey() } });
        prog.step(q.position);
        setTimeout(ask, matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 380);    // let the bar finish its step
      } catch (e) { sent = false; opts.forEach(b => { b.disabled = false; }); opts[k].classList.remove("picked"); toast(errText(e)); if (e.status === 409) ask(); }
    } }, h("span", { class: "key", "aria-hidden": "true" }, "ABCD"[k]), h("span", { class: "txt", dir: "auto" }, ko(text))));
    mount(testHeader(prog, q.position, q.total), h("h1", { class: "q", dir: "auto" }, ko(q.stem)), h("div", { class: "opts" }, opts));
  }
}

// ---- making a quiz: used by the reading page (ready-made topics) and by the paste-your-own-notes form
function quizReady(s) {                    // no concept names here: the quiz itself is the first test of what was read
  store.del("remem_due");
  mount(h("h1", {}, "Your quiz is ready"),
    h("p", { class: "muted" }, "Questions on what you just read, one at a time, mixed together."),
    h("p", {}, h("a", { class: "btn primary block", href: "#/test?note=" + s.note_id }, "Start the first quiz")),
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
  catch (e) { msg.className = "err"; msg.textContent = errText(e); onFail(); }
}

// ---- the reading page: ready-made topics are read once before any question is asked
function readingBlocks(text) {                                  // plain text -> headings, paragraphs and bullet lists (textContent only)
  const lines = text.split("\n").slice(1), out = [];            // the first line is the title, shown as the page heading
  let list = null, para = [];
  const flush = () => { if (para.length) { out.push(h("p", {}, ko(para.join(" ")))); para = []; } list = null; };
  lines.forEach((raw, i) => {
    const l = raw.trim();
    if (!l) { flush(); return; }
    if (l.startsWith("- ")) { if (!list) { flush(); list = h("ul", { class: "reading-list" }); out.push(list); } list.append(h("li", {}, ko(l.slice(2)))); return; }
    list = null;
    const next = (lines[i + 1] || "").trim();
    if (!para.length && next && l.length <= 60 && !/[.:;?!,]$/.test(l)) { out.push(h("h2", { class: "rh" }, ko(l))); return; }
    para.push(l);
  });
  flush(); return out;
}
async function viewTopic(tid) {
  mount(h("h1", {}, "Reading"), skeleton(4));
  const toTopics = h("a", { class: "btn", href: "#/notes" }, "Back to topics");
  let t; try { t = await api("/topics/" + tid); }
  catch (e) {
    if (e.status === 403) return mount(h("div", { class: "bar" }, h("a", { class: "btn link", href: "#/notes", "aria-label": "Back to topics" }, icon("M15 5l-7 7 7 7", "chev"), "Topics")),
      h("h1", {}, "Notes locked"), h("div", { class: "calm" }, h("b", {}, "You've read these notes once"),
        h("p", { class: "muted" }, "They stay locked until you finish the Remem Test, so Remem measures what you remember, not what you just re-read.")),
        h("div", { class: "actions" }, h("a", { class: "btn primary", href: "#/" }, "Go to Today"), toTopics));     // a waiting first quiz is on Today
    return errScreen("Reading", e, toTopics);
  }
  const msg = h("div", { class: "muted", role: "status" });
  const sentinel = h("div", { class: "end", "aria-hidden": "true" });
  const hint = h("span", { class: "hint", id: "readhint", "aria-live": "polite" }, "Read to the end");
  const go = h("button", { class: "primary", disabled: true, onclick: async () => {
    if (t.done) { location.hash = t.last_read ? "#/" : "#/notes"; return; }
    if (!(await confirmSheet("Ready for the quiz?", "Your notes will lock until the Remem Test, a short final check near the end of the study.", "Start the quiz", "Keep reading"))) return;
    go.disabled = true;
    const wait = skeleton(3);
    mount(h("h1", {}, "Making your quiz"), msg, wait);
    startQuiz("/notes/topic", { topic_id: tid }, msg, () => wait.replaceWith(h("div", { class: "actions" },   // never a dead end: a way back when it fails
      h("a", { class: "btn", href: "#/notes" }, "Back to topics"), h("a", { class: "btn", href: "#/" }, "Go to Today"))));
  }, "aria-describedby": "readhint" }, t.done ? "Done reading" : "I've read it. Make my quiz");
  const unlock = () => { go.disabled = false; hint.textContent = t.done ? "" : "Ready when you are"; bar.classList.add("ready"); };
  const bar = h("div", { class: "readbar" }, h("div", { class: "inner" }, hint, go));
  const title = t.title.split(":")[0];
  const note = t.last_read
    ? h("div", { class: "panel hint-panel" }, h("b", {}, "This is your last read."), h("p", { class: "muted" }, "When you leave this page, these notes lock until you finish the Remem Test."))
    : t.done ? null
    : h("div", { class: "panel hint-panel" }, h("b", {}, "Read to understand, not to memorise."),
        h("p", { class: "muted" }, "Go at your own pace. Remembering is Remem's job: it will test you at the right times. You can read this once. When you start the quiz, the notes lock until the Remem Test, a short final check near the end of the study."));
  mount(h("div", { class: "bar" }, h("a", { class: "btn link", href: "#/notes", "aria-label": "Back to topics" }, icon("M15 5l-7 7 7 7", "chev"), "Topics")),
    h("h1", {}, title), h("p", { class: "muted" }, t.subject + ", about " + t.minutes + " min read"), note,
    h("article", { class: "reading" }, readingBlocks(t.text)), sentinel, bar);
  const check = () => { if (sentinel.getBoundingClientRect().top < innerHeight) { unlock(); removeEventListener("scroll", check); removeEventListener("resize", check); } };    // the end of the text is on screen
  addEventListener("scroll", check, { passive: true }); addEventListener("resize", check); setTimeout(check, 300);
}

async function viewNotes() {
  const msg = h("div", { class: "muted", role: "status" });
  const title = h("input", { id: "nt", placeholder: "e.g. Roman roads" });
  const text = h("textarea", { id: "nx", placeholder: "Paste your study notes here (at least a few sentences)", "aria-describedby": "nx-help" });
  const other = h("p", { hidden: true }, h("a", { href: "#/notes", onclick: (e) => { e.preventDefault(); window.scrollTo(0, 0); const h1 = document.querySelector("#app h1"); if (h1) h1.focus({ preventScroll: true }); } }, "Or pick a ready-made topic"));
  const failed = () => { own.disabled = false; own.removeAttribute("aria-busy"); other.hidden = false; msg.scrollIntoView({ block: "center" }); };
  const own = h("button", { class: "primary block", onclick: () => { own.disabled = true; own.setAttribute("aria-busy", "true"); other.hidden = true; startQuiz("/notes", { title: title.value.trim(), text: text.value }, msg, failed); } }, "Make my quiz");
  const form = h("div", { class: "ownform", hidden: true },
    h("label", { for: "nt" }, "Title"), title, h("label", { for: "nx" }, "Notes"), text, h("p", { class: "muted small", id: "nx-help" }, "At least a few sentences, about one topic."),
    h("p", { class: "muted small" }, "Your notes are sent to Google's Gemini AI, which writes the questions. Paste notes about one topic, and nothing personal or confidential."), h("p", {}, own), msg, other);
  const open = h("button", { class: "block", "aria-expanded": "false", onclick: () => { form.hidden = false; open.hidden = true; open.setAttribute("aria-expanded", "true"); title.focus(); } }, "Paste my own notes");
  const ownBox = h("div", { class: "panel own" }, h("h2", {}, "Or use your own notes"),
    h("p", { class: "muted" }, "Paste notes from your course and an AI (Google Gemini) turns them into quiz questions."), open, form);

  const slot = skeleton(3);
  mount(h("h1", {}, "Pick a topic"), h("p", { class: "muted" }, "Read a short text first, then answer questions on it."), slot, ownBox);
  let d; try { d = await api("/topics"); } catch (e) { slot.replaceWith(h("div", {}, h("div", { class: "err", role: "alert" }, "Could not load topics: " + errText(e)), h("button", { type: "button", onclick: () => route() }, "Try again"))); return; }
  d.topics.sort((a, b) => (b.id === d.suggested) - (a.id === d.suggested));       // suggested topic first
  const mk = (t, label) => h("a", { class: "btn primary", href: "#/notes/" + t.id, "aria-label": label + ": " + t.title }, label);
  const lock = t => !t.done ? "" : t.reading === "locked" ? ", locked until the Remem Test" : t.reading === "last" ? ", one last read left" : ", done before";
  const meta = t => t.subject + ", " + t.minutes + " min read" + lock(t) + (t.known ? ", you know this one" : "");
  const tile = (t, cls) => h("span", { class: "tile " + (cls || ""), "aria-hidden": "true" }, icon(SUBJECT_ICONS[t.subject] || "M5 5h14v14H5z"));
  const sug = d.topics.find(t => t.id === d.suggested);
  const rest = d.topics.filter(t => t !== sug);
  const out = [];
  if (sug) out.push(h("h2", {}, "Suggested for you"), h("div", { class: "panel sug" }, h("div", { class: "sug-head" }, tile(sug), h("h3", {}, sug.title)), h("p", { class: "muted" }, sug.blurb), h("p", { class: "muted small meta-line" }, meta(sug)), mk(sug, sug.done ? "Read again" : "Read and start")));
  if (rest.length) out.push(sug ? h("h2", {}, "Other topics") : null, h("ul", { class: "ledger topics" }, rest.map(t => {   // no suggestion: the h1 already says it
    const label = !t.done ? "Read" : t.reading === "locked" ? "Locked" : t.reading === "last" ? "Read one last time" : "Read again";
    return h("li", {}, h("a", { class: "item row withtile", href: "#/notes/" + t.id, "aria-label": label + ": " + t.title }, tile(t),
      h("div", {}, h("span", { class: "name" }, t.title), h("div", { class: "muted" }, t.blurb), h("div", { class: "muted small" }, meta(t))),
      h("span", { class: "go" + (t.done ? " quiet" : ""), "aria-hidden": "true" }, t.done ? null : label, icon("M9 5l7 7-7 7", "chev"))));   // done rows: chevron only, the label stays in aria-label
  })));
  slot.replaceWith(h("div", {}, out));
}

async function viewConcepts() {
  mount(h("h1", {}, "Concepts"), skeleton(4));
  let d; try { d = await api("/concepts"); } catch (e) { return errScreen("Concepts", e); }
  const nodes = [h("h1", {}, "Concepts")];
  if (!d.concepts.length) nodes.push(h("div", { class: "calm" }, h("b", {}, "No concepts yet"), h("p", { class: "muted" }, "Pick a topic and they will appear here."), h("a", { class: "btn primary block", href: "#/notes" }, "Pick a topic")));
  else if (d.concepts.some(c => !c.new)) nodes.push(h("p", { class: "muted" }, "The bar is how much you're likely to recall now. Mastery is how well you've answered so far."));
  const row = c => h("li", {}, h(c.new ? "div" : "a", { class: "item", href: c.new ? false : "#/curve/" + c.concept_id },
    h("span", { class: "name" }, ko(c.name)),
    h("span", { class: "when" }, c.new ? "not studied yet" : ""),
    c.new ? h("div", { class: "meter empty", "aria-hidden": "true" }) : [meter(c.R_now, c.R_now < THETA_UI, c.name),
      h("span", { class: "note" }, "Mastery " + Math.round(c.mastery * 100) + "% · " + pl(c.n_responses, "answer") + " · recall above 90% for about " + pl(Math.round(c.stability_days), "day"))]));
  const groups = [];                                                       // one list per topic, in the order the topics were added
  d.concepts.forEach(c => { const k = c.topic || "Your notes"; let g = groups.find(x => x.k === k); if (!g) groups.push(g = { k, items: [] }); g.items.push(c); });
  groups.forEach(g => nodes.push(groups.length > 1 ? h("h2", {}, ko(g.k)) : null, h("ul", { class: "ledger" }, g.items.map(row))));
  mount(nodes);
}

let curveSeq = 0;
async function viewCurve(cid, theta, keep) {
  const gen = routeGen, seq = ++curveSeq;                                   // a late answer (an older slider value, or a page already left) must not redraw
  let r, ex;
  try { r = await api("/retention/" + cid + (theta ? "?theta=" + theta : "")); ex = await api("/explain/" + cid); }
  catch (e) { if (gen !== routeGen || seq !== curveSeq) return; return errScreen("Memory curve", e, h("a", { class: "btn", href: "#/" }, "Back")); }
  if (gen !== routeGen || seq !== curveSeq) return;
  // drawn in device pixels (1 unit = 1 px) so labels are the same size on a phone and a laptop
  const app = document.getElementById("app"), acs = getComputedStyle(app);
  const W = Math.round(Math.min(680, Math.max(280, app.clientWidth - parseFloat(acs.paddingLeft) - parseFloat(acs.paddingRight)))) || 328;
  const FS = Math.round((W >= 500 ? 14 : 13) * Math.max(1, parseFloat(getComputedStyle(document.documentElement).fontSize) / 17));   // labels follow the phone's text size
  const H = Math.max(Math.round(Math.min(300, Math.max(200, W * 0.62))), Math.round(FS * 15)), L = Math.round(FS * 2.6) + 8, B = FS + 15, T = Math.max(14, Math.round(FS * 0.7)), Rr = 12;   // H and T grow at large text so labels neither collide nor clip
  const maxD = r.points[r.points.length - 1].day;
  const x = d => L + (d / maxD) * (W - L - Rr), y = v => T + (1 - v) * (H - T - B);
  // No review-day marker: the review day comes from the concept's scheduling method, and drawing it against the target
  // would show the student which method that is. The curve, the target and "now" are the same for every concept.
  const NS = "http://www.w3.org/2000/svg";
  const se = (t, a, txt) => { const e = document.createElementNS(NS, t); for (const [k, v] of Object.entries(a || {})) e.setAttribute(k, v); if (txt != null) e.textContent = txt; return e; };
  const svg = se("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart", style: "--fs:" + FS + "px", role: "img",
    "aria-label": "Predicted recall over the next " + maxD + " days, with the " + Math.round(r.theta * 100) + "% target. Recall now " + Math.round(r.R_now * 100) + "%." });
  [0, 0.5, 1].forEach(v => { svg.append(se("line", { class: "grid", x1: L, x2: W - Rr, y1: y(v), y2: y(v) })); svg.append(se("text", { x: L - 6, y: y(v) + FS * 0.35, "text-anchor": "end" }, Math.round(v * 100) + "%")); });
  for (let i = 0; i <= 4; i++) { const d = (maxD * i) / 4; svg.append(se("text", { x: x(d), y: H - 8, "text-anchor": i === 0 ? "start" : i === 4 ? "end" : "middle" }, d.toFixed(0) + "d")); }
  const pts = r.points.map(p => x(p.day).toFixed(1) + "," + y(p.R).toFixed(1));
  svg.append(se("polygon", { class: "area", points: pts.join(" ") + " " + x(maxD) + "," + y(0) + " " + x(0) + "," + y(0) }));
  svg.append(se("line", { class: "target", x1: L, x2: W - Rr, y1: y(r.theta), y2: y(r.theta) }));
  svg.append(se("polyline", { class: "curve", points: pts.join(" ") }));
  svg.append(se("text", { class: "halo", x: L + 6, y: y(r.theta) + FS + 4, "text-anchor": "start" }, "target " + Math.round(r.theta * 100) + "%"));
  if (r.elapsed_days <= maxD) {                                              // "now N%" goes where it collides with nothing already drawn
    const cx = x(r.elapsed_days), cy = y(r.R_now), nowTxt = "now " + Math.round(r.R_now * 100) + "%", nw = nowTxt.length * FS * 0.64;
    const tgtTxt = "target " + Math.round(r.theta * 100) + "%", busy = [
      [L + 2, y(r.theta), L + 12 + tgtTxt.length * FS * 0.62, y(r.theta) + FS + 10],                       // target label
      [cx - 8, cy - 8, cx + 8, cy + 8]];                                                                         // the dot itself
    const fits = ([x0, y0, x1, y1]) => x0 >= L && x1 <= W - Rr && y0 >= 0 && y1 <= H - B && !busy.some(([a, b, c, d]) => x0 < c && a < x1 && y0 < d && b < y1);
    const spots = [[cx - 10 - nw, cy - FS / 2], [cx + 10, cy - FS / 2], [cx + 10, cy + 8], [cx - 10 - nw, cy + 8], [cx + 10, cy - FS - 10], [cx - nw / 2, cy + FS + 10]];
    const spot = spots.find(([a, b]) => fits([a, b, a + nw, b + FS + 2]));
    svg.append(se("circle", { class: "now", cx, cy, r: 6 }));
    if (spot) svg.append(se("text", { class: "lab halo", x: spot[0], y: spot[1] + FS * 0.85, "text-anchor": "start" }, nowTxt));   // no room (large text): the sentence under the chart already says it
  }
  const nodes = [h("div", { class: "bar" }, h("a", { class: "btn link", href: "#/concepts", "aria-label": "Back to concepts" }, icon("M15 5l-7 7 7 7", "chev"), "Concepts")),
    h("h1", { dir: "auto" }, ko(r.concept)), svg, h("p", { class: "muted small axis-cap" }, "days since you last practised"),
    h("p", { class: "muted" }, "The dot is you now, at " + Math.round(r.R_now * 100) + "% recall. The dashed line is the " + Math.round(r.theta * 100) + "% target. Recall falls to about 90% after " + pl(Math.round(r.stability_days), "day") + ".")];
  if (S.role === "demo" || S.role === "admin") {
    const lab = h("b", {}, "target " + Math.round(r.theta * 100) + "%");
    const sl = h("input", { type: "range", min: 60, max: 97, value: Math.round(r.theta * 100), "aria-label": "What-if target retention", "aria-valuetext": Math.round(r.theta * 100) + "%",
      oninput: () => { lab.textContent = "target " + sl.value + "%"; sl.setAttribute("aria-valuetext", sl.value + "%"); }, onchange: () => viewCurve(cid, sl.value / 100, true) });
    nodes.push(h("div", { class: "panel" }, h("div", {}, "What-if target (demo only) ", lab), sl));
  }
  nodes.push(h("p", {}, rich(ex.explanation)), h("p", {}, h("a", { class: "btn block", href: "#/concepts" }, "Back to concepts")));        // no practising early: the schedule decides when
  if (keep) remount(nodes, 'input[type="range"]'); else mount(nodes);
}

// ---------------------------------------------------------------- theme switch (owner's reference design, ported 1:1)
// The motion is the reference's own: values sampled frame by frame from its animation (25 fps source, played at 34 fps),
// Catmull-Rom between frames, the exit replays the first frames backwards, and a 50 ms blend smooths a reversal mid-way.
const TS = (() => {
  const F0 = 48, N = 23, END = N - 1, SETTLE = 10, FPS = 34, BLEND = 0.05;
  function track(sp) {
    const keys = Object.keys(sp).map(Number).sort((a, b) => a - b), out = [];
    for (let i = 0; i < N; i++) {
      const f = F0 + i; let v;
      if (f <= keys[0]) v = sp[keys[0]];
      else if (f >= keys[keys.length - 1]) v = sp[keys[keys.length - 1]];
      else for (let k = 0; k < keys.length - 1; k++) if (f >= keys[k] && f <= keys[k + 1]) { const t = (f - keys[k]) / (keys[k + 1] - keys[k]); v = sp[keys[k]] + (sp[keys[k + 1]] - sp[keys[k]]) * t; break; }
      out.push(v);
    }
    return out;
  }
  const F = {
    b: track({48:0,49:.005,50:.03,51:.08,52:.19,53:.5,54:.81,55:.92,56:.97,57:.995,58:1}),
    pd: track({48:0,49:0,50:.01,51:.055,52:.15,53:.55,54:.9,55:.97,56:.995,57:1}),
    xc: track({48:388,49:389.2,50:392.3,51:396.75,52:399.5,53:405.7,54:412.5,55:419.75,56:427.2,57:434.75,58:441.5,59:445.7,60:446.1,61:444.9,62:443.3,63:442.15,64:441.5}),
    ad: track({48:1,50:1,51:.85,52:.65,53:.36,54:.11,55:0}),
    ac: track({48:0,51:0,52:.34,53:.64,54:.89,55:1}),
    bx: track({48:0,49:-.5,50:-1.5,51:-3.5,52:-8.2,53:-16,54:-24}),
    ba: track({48:1,50:1,51:.85,52:.65,53:0}),
    xd: track({48:0,51:0,52:2.7,53:2.65,54:2.76,55:2.8}),
    yd: track({48:0}),
    sx: track({48:0,49:-.2,50:-.8,51:-2.6,52:-14,53:-25.7,54:-35}),
    sa: track({48:1,50:1,51:.85,52:.65,53:.4,54:0}),
    Ax: track({56:58,57:36,58:15.3,59:0,60:-13,61:-14.2,62:-10.4,63:-5.6,64:-2,65:0,66:.9,67:.9,68:.6,69:.4,70:0}),
    Ay: track({56:9,57:5.8,58:2.4,59:0,60:-1.9,61:-2.1,62:-1.5,63:-.9,64:-.1,65:0}),
    Aa: track({55:0,56:0,57:1}),
    Bx: track({56:0,57:0,58:-11,59:-12.1,60:-8.7,61:-4.7,62:-1.6,63:0,64:.9,65:.9,66:.8,67:.4,68:.2,69:0}),
    By: track({57:0,58:3.9,59:4.2,60:3.1,61:1.7,62:.6,63:0,64:-.1,65:-.1,66:-.1,67:0}),
    Ba: track({55:0,56:0,57:1}),
    D1x: track({56:0,57:-9.1,58:-9.8,59:-7.2,60:-4,61:-1.3,62:0,63:.7,64:.7,65:.7,66:.6,67:.4,68:0}),
    D1y: track({56:.3,57:-3.2,58:-3.2,59:-2.3,60:-1.2,61:-.4,62:0,63:.3,64:.3,65:.3,66:.2,67:.1,68:0}),
    D1a: track({55:0,56:.75,57:1}),
    D2x: track({56:46,57:34.2,58:24.1,59:9.5,60:0,61:-8.7,62:-9.7,63:-6.9,64:-3.9,65:-1.7,66:0,67:.3,68:0}),
    D2y: track({56:2,57:1.4,58:1.1,59:.7,60:0,61:-.1,62:-.1,63:-.1,64:.1,65:.1,66:0}),
    D2a: track({55:0,56:0,57:1}),
    D3x: track({55:65,56:45.1,57:20.1,58:0,59:-16.7,60:-18.1,61:-13.2,62:-7.2,63:-2.9,64:0,65:.9,66:1,67:.9,68:.3,69:0}),
    D3y: track({56:-5.1,57:-2.1,58:0,59:1.9,60:1.9,61:1.6,62:.9,63:.1,64:0,65:-.1,66:-.2,67:-.1,68:0}),
    D3a: track({55:0,56:1}),
  };
  const R = Object.assign({}, F, { Bx: track({48:0}), By: track({48:0}), D1x: track({48:0}), D1y: track({48:0}) });   // on the way out star B and dot 1 stay put
  const KEYS = Object.keys(F);
  function sample(arr, u) {
    if (u <= 0) return arr[0];
    if (u >= END) return arr[END];
    const i = Math.floor(u), t = u - i, p0 = arr[Math.max(i - 1, 0)], p1 = arr[i], p2 = arr[i + 1], p3 = arr[Math.min(i + 2, END)], t2 = t * t, t3 = t2 * t;
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3);
  }
  function values(u, mode) {
    const src = mode === "R" ? R : F, uu = mode === "R" ? Math.min(u, SETTLE) : u, v = {};
    for (const k of KEYS) v[k] = sample(src[k], uu);
    return v;
  }
  return { END, SETTLE, FPS, BLEND, KEYS, values };
})();

let tsCount = 0;
function themeSwitch(startDark, onToggle, width) {
  const NS = "http://www.w3.org/2000/svg", id = "ts" + (++tsCount);   // own ids, so several switches can share a page
  const s = (tag, attrs, ...kids) => { const el = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v); el.append(...kids); return el; };
  const grad = (id, stops) => s("linearGradient", { id, x1: 0, y1: 0, x2: 0, y2: 1 }, ...stops.map(([o, c]) => s("stop", { offset: o, "stop-color": c })));
  // day pill: the reference's sky blue moved into Remem's indigo; night pill: the reference's near-black navy (close to the app's dark paper)
  const day = [[0, "rgb(84,89,226)"], [.1, "rgb(98,103,231)"], [.2, "rgb(114,119,236)"], [.3, "rgb(124,129,240)"], [.4, "rgb(121,126,239)"], [.6, "rgb(117,122,238)"],
               [.7, "rgb(113,118,236)"], [.8, "rgb(103,108,233)"], [.9, "rgb(93,98,229)"], [1, "rgb(84,89,226)"]];
  const night = [[0, "rgb(3,4,6)"], [.11, "rgb(9,11,17)"], [.19, "rgb(12,16,25)"], [.29, "rgb(18,22,36)"], [.41, "rgb(19,24,38)"], [.56, "rgb(20,25,40)"],
                 [.66, "rgb(19,24,38)"], [.71, "rgb(16,21,32)"], [.76, "rgb(12,16,25)"], [.84, "rgb(9,11,17)"], [.91, "rgb(4,5,7)"], [1, "rgb(3,4,6)"]];
  const star = "M0,-1 L.2245,-.309 .951,-.309 .363,.118 .588,.809 0,.382 -.588,.809 -.363,.118 -.951,-.309 -.2245,-.309Z";
  const pill = fill => s("rect", { x: 0, y: .45, width: 139, height: 79.55, rx: 39.775, fill });
  const pillDark = pill("url(#" + id + "-night)"); pillDark.setAttribute("opacity", 0);
  const g = (...kids) => s("g", {}, ...kids);
  const bigDot = g(s("circle", { cx: 102.55, cy: 20.4, r: 6.8, fill: "#fff" })), smDot = g(s("circle", { cx: 86.68, cy: 36.24, r: 2.78, fill: "#fff" }));
  const starAt = (x, y, k, w) => g(s("path", { d: star, transform: "translate(" + x + " " + y + ") scale(" + k + ")", fill: "#fff", stroke: "#fff", "stroke-width": w, "stroke-linejoin": "round" }));
  const gA = starAt(34, 25.55, 5.35, .57), gB = starAt(56.19, 54.78, 3.93, .61);
  const dot = (cx, cy, r) => g(s("circle", { cx, cy, r, fill: "#fff" }));
  const g1 = dot(69.39, 22.3, 2.17), g2 = dot(53.6, 34.24, 2.16), g3 = dot(21.81, 46.08, 2.19);
  const disc = s("circle", { cx: 43, cy: 40.18, r: 26.74, fill: "#fff" });
  const moon = s("g", { opacity: 0, transform: "translate(96.24 40.4)" }, s("circle", { r: 27.12, fill: "#fff", mask: "url(#" + id + "-moon)" }));
  const svg = s("svg", { viewBox: "0 0 139 80", "aria-hidden": "true", focusable: "false" },
    s("defs", {}, grad(id + "-day", day), grad(id + "-night", night),
      s("clipPath", { id: id + "-clip" }, s("rect", { x: 0, y: .45, width: 139, height: 79.55, rx: 39.775 })),
      s("mask", { id: id + "-moon", maskUnits: "userSpaceOnUse", x: -60, y: -60, width: 120, height: 120 },
        s("rect", { x: -60, y: -60, width: 120, height: 120, fill: "#fff" }), s("circle", { cx: -14.64, cy: -7.63, r: 19.96, fill: "#000" }))),
    s("g", { "clip-path": "url(#" + id + "-clip)" }, pill("url(#" + id + "-day)"), pillDark, bigDot, smDot, gA, gB, g1, g2, g3, disc, moon));
  const btn = h("button", { class: "theme-switch", type: "button", role: "switch", "aria-checked": String(!!startDark), "aria-label": "Theme: dark mode" }, svg);
  if (width) btn.style.setProperty("--tsw", width + "px");
  const el = btn;                         // no Light / Dark words: the sun and moon say it (the owner's call); the name "Dark mode" stays for screen readers

  const tr = (dx, dy) => "translate(" + dx.toFixed(2) + " " + dy.toFixed(2) + ")";
  const mixSh = b => "rgba(" + Math.round(84 * (1 - b)) + "," + Math.round(89 * (1 - b)) + "," + Math.round(226 * (1 - b)) + "," + (0.45 + 0.1 * b).toFixed(2) + ")";
  let last = null;
  function paint(v) {
    pillDark.setAttribute("opacity", v.pd.toFixed(3));
    disc.setAttribute("cx", (v.xc + v.xd - 345).toFixed(2)); disc.setAttribute("cy", (40.18 + v.yd).toFixed(2)); disc.setAttribute("opacity", v.ad.toFixed(3));
    moon.setAttribute("transform", "translate(" + (v.xc - 345.26).toFixed(2) + " 40.4)"); moon.setAttribute("opacity", v.ac.toFixed(3));
    bigDot.setAttribute("transform", tr(v.bx, 0)); bigDot.setAttribute("opacity", v.ba.toFixed(3));
    smDot.setAttribute("transform", tr(v.sx, 0)); smDot.setAttribute("opacity", v.sa.toFixed(3));
    gA.setAttribute("transform", tr(v.Ax, v.Ay)); gA.setAttribute("opacity", v.Aa.toFixed(3));
    gB.setAttribute("transform", tr(v.Bx, v.By)); gB.setAttribute("opacity", v.Ba.toFixed(3));
    g1.setAttribute("transform", tr(v.D1x, v.D1y)); g1.setAttribute("opacity", v.D1a.toFixed(3));
    g2.setAttribute("transform", tr(v.D2x, v.D2y)); g2.setAttribute("opacity", v.D2a.toFixed(3));
    g3.setAttribute("transform", tr(v.D3x, v.D3y)); g3.setAttribute("opacity", v.D3a.toFixed(3));
    btn.style.setProperty("--sh", mixSh(v.b));
    last = v;
  }
  // state machine, as in the reference: u runs 0..END forwards (to dark) or back (to light); a reversal blends from where it was
  let dark = !!startDark, u = dark ? TS.END : 0, mode = dark ? "F" : "R", snap = null, blendT = 1, raf = 0, prev = 0;
  const still = matchMedia("(prefers-reduced-motion: reduce)");
  function render() {
    let v = TS.values(u, mode);
    if (snap && blendT < 1) { const o = {}; for (const k of TS.KEYS) o[k] = snap[k] + (v[k] - snap[k]) * blendT; v = o; }
    paint(v);
  }
  function frame(now) {
    const dt = Math.min((now - prev) / 1000, 0.1); prev = now;
    let moving = false;
    if (dark) { if (u < TS.END) { u = Math.min(TS.END, u + TS.FPS * dt); moving = true; } }
    else if (u > 0) { u = Math.max(0, u - TS.FPS * dt); moving = true; }
    if (blendT < 1) { blendT = Math.min(1, blendT + dt / TS.BLEND); moving = true; }
    render();
    raf = moving && btn.isConnected ? requestAnimationFrame(frame) : 0;
  }
  function set(next, user) {
    if (next === dark) return;
    snap = last; blendT = 0; dark = next;
    if (dark) mode = "F"; else { mode = "R"; if (u > TS.SETTLE) u = TS.SETTLE; }
    btn.setAttribute("aria-checked", String(dark));
    if (user) onToggle(dark);
    if (still.matches) { u = dark ? TS.END : 0; snap = null; blendT = 1; render(); return; }
    if (!raf) { prev = performance.now(); raf = requestAnimationFrame(frame); }
  }
  btn.addEventListener("click", () => set(!dark, true));
  render();
  return { el, set: next => set(next, false) };
}

function firstName(full) {                           // "JATIN ASHOK GUPTA" -> "Jatin", "aryan joshi" -> "Aryan"
  const w = String(full || "").trim().split(/\s+/)[0] || "";
  return w ? w.charAt(0).toLocaleUpperCase() + w.slice(1).toLocaleLowerCase() : "";
}
function viewMe() {
  const old = h("input", { id: "op", type: "password", autocomplete: "current-password" }), nw = h("input", { id: "np", type: "password", autocomplete: "new-password" });
  const msg = h("div", { class: "muted", role: "status" });
  const reminders = h("div", { class: "stack" }, h("p", { class: "muted" }, "Checking..."));
  fillReminderSettings(reminders);
  const T = window.remTheme;
  const switches = [];
  const toggle = dark => { T.set(dark ? "dark" : "light"); switches.forEach(x => x.set(dark)); showState(); };
  const make = w => { const x = themeSwitch(T.effective() === "dark", toggle, w); switches.push(x); return x; };
  const sw = make(60);                    // 60 x 35: next to the 51 x 31 sound switch, so the two read as one family
  const sub = h("span", { class: "sub" });
  const matchRow = h("button", { class: "me-act", type: "button", onclick: () => { T.clear(); switches.forEach(x => x.set(T.effective() === "dark")); showState(); } }, "Match my phone");
  function showState() {                 // say what is in use; once overridden, offer the way back to the phone's own setting
    sub.textContent = T.saved() ? "Set on this phone" : "Same as your phone";
    matchRow.hidden = !T.saved();
  }
  showState();
  if (T.phone) {                          // the phone switches light/dark (e.g. at sunset) while Me is open
    const follow = () => { if (!sw.el.isConnected) return T.phone.removeEventListener("change", follow); if (!T.saved()) switches.forEach(x => x.set(T.phone.matches)); };
    T.phone.addEventListener("change", follow);
  }
  const chev = () => icon("M9 5l7 7-7 7", "chev");
  const nameEl = h("b", { class: "me-name" }, store.get("remem_name") || "");
  api("/auth/profile").then(f => { const n = firstName(f.name); nameEl.textContent = n; if (n) store.set("remem_name", n); else store.del("remem_name"); }).catch(() => {});
  mount(h("h1", {}, "Me"), h("p", { class: "me-who" }, nameEl, " ", h("span", { class: "me-user" }, S.user || ""), S.role !== "student" ? h("span", { class: "me-user" }, " (" + S.role + ")") : null),
    h("h2", {}, "Reminders"), h("div", { class: "me-group" }, reminders),
    h("h2", {}, "Sound"),
    h("div", { class: "me-group" }, h("label", { class: "switch" }, h("span", {}, "Sounds for right and wrong answers"),
      h("input", { type: "checkbox", role: "switch", checked: soundOn(), onchange: e => { store.set("remem_sound", e.target.checked ? "1" : "0"); if (e.target.checked) play("right"); } }))),
    h("h2", {}, "Appearance"),
    h("div", { class: "me-group" }, h("div", { class: "me-theme" }, h("span", {}, "Theme", sub), sw.el), matchRow),
    h("h2", {}, "Account"),
    h("div", { class: "me-group" },
      h("details", {}, h("summary", {}, h("span", {}, "Change password"), chev()),
        h("form", { class: "stack", onsubmit: async (e) => { e.preventDefault(); try { await api("/auth/password", { method: "POST", body: { old_password: old.value, new_password: nw.value } }); msg.className = "ok"; msg.textContent = "Password changed."; old.value = nw.value = ""; } catch (ex) { msg.className = "err"; msg.textContent = errText(ex); } } },
          h("input", { type: "text", autocomplete: "username", value: S.user || "", hidden: true, "aria-hidden": "true", tabindex: "-1" }),
          h("div", {}, h("label", { for: "op" }, "Current password"), old), h("div", {}, h("label", { for: "np" }, "New password (8 or more characters)"), nw), msg,
          h("button", { type: "submit" }, "Update password"))),
      env().standalone ? null : h("a", { class: "me-row", href: "#/install" }, h("span", {}, "Add to home screen"), chev())),
    h("p", { class: "me-signout" }, h("button", { class: "block", onclick: () => signOut() }, "Sign out")));
}

// ---------------------------------------------------------------- owner's view (admin account only): the pilot at a glance
const ARM_NAMES = { remem: "REMEM", sm2: "SM-2", fixed: "Fixed 3-day" };
const pct = v => v == null ? "–" : Math.round(v * 100) + "%";
const clock = ms => new Date(ms).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const dayName = ms => new Date(ms).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
function since(ms) {
  if (!ms) return "never";
  const day = t => { const x = new Date(t); return Date.UTC(x.getFullYear(), x.getMonth(), x.getDate()) / 86400000; };   // calendar days on this phone
  const d = day(Date.now()) - day(ms);
  return d <= 0 ? "today, " + clock(ms) : d === 1 ? "yesterday, " + clock(ms) : d + " days ago";
}
function personState(p) {                          // one short label and a tone for a person's line
  if (!p.signed_up) return ["Not signed up", "off"];
  if (p.status === "never") return ["Not started", "bad"];
  if (p.status === "today") return ["Done today", "good"];
  if (p.days_away >= 3) return ["Quiet " + p.days_away + " days", "bad"];
  if (p.waiting) return [pl(p.waiting, "question") + " waiting", "warn"];
  return ["Nothing due", "off"];
}
const dots = days => h("span", { class: "ad-dots", role: "img", "aria-label": days.filter(Boolean).length + " of the last 7 days active" },
  days.map(on => h("i", { class: on ? "on" : "" })));
function adminCards(nums) { return h("div", { class: "ad-cards" }, nums.map(([v, label]) => h("div", { class: "ad-card" }, h("b", {}, String(v)), h("span", {}, label)))); }
function personLine(p, finalOpen) {
  const [label, tone] = personState(p);
  const meta = [pl(p.topics.length, "topic"), pl(p.answers, "answer"), pl(p.days_active, "active day"), p.reminders_on ? "reminders on" : "reminders off"];
  if (finalOpen && p.final.total) meta.unshift("Remem Test " + (p.final.finished ? "done" : p.final.answered + "/" + p.final.total));
  return h("a", { class: "ad-person", href: "#/admin/p/" + p.user_id },
    h("div", { class: "ad-top" }, h("span", {}, h("b", {}, p.name ? firstName(p.name) : "—"), " ", h("span", { class: "muted" }, p.username + (p.role !== "student" ? " · " + p.role : "") + (p.active ? "" : " · disabled"))),
      h("span", { class: "ad-pill " + tone }, label)),
    p.topics.length ? h("div", { class: "small" }, p.topics.join(", ")) : null,
    h("div", { class: "ad-mid" }, dots(p.last_7), h("span", { class: "muted small" }, "last active " + since(p.last_ts))),
    h("div", { class: "muted small" }, meta.join(" · ")));
}
function finalCard(o, redo) {
  const f = o.final;
  const flip = async open => {
    const ok = await confirmSheet(open ? "Open the Remem Test?" : "Close the Remem Test?",
      open ? "Everyone who has studied a topic can take it from now on, and everyone with reminders on gets a notification right away. Do this once, near the end of the pilot."
           : "Nobody can answer more Remem Test questions until you open it again. Answers already given are kept.",
      open ? "Open it" : "Close it", "Cancel");
    if (!ok) return;
    try { await api("/admin/final-test", { method: "POST", body: { open } }); toast(open ? "The Remem Test is open." : "The Remem Test is closed."); redo(); } catch (e) { toast(errText(e)); }
  };
  return h("div", { class: "panel" },
    h("div", { class: "ad-top" }, h("b", {}, "The Remem Test"), h("span", { class: "ad-pill " + (f.open ? "good" : "off") }, f.open ? "Open" : "Closed")),
    h("p", { class: "muted small" }, f.open ? f.finished + " of " + f.eligible + " finished, " + f.started + " part-way through." : f.eligible + (f.eligible === 1 ? " person has" : " people have") + " questions ready. Preview them before you open it."),
    h("div", { class: "actions" }, location.hash.startsWith("#/admin/test") ? null : h("a", { class: "btn outline", href: "#/admin/test" }, f.open ? "Progress and questions" : "Preview questions"),
      h("button", { class: f.open ? "" : "primary", type: "button", onclick: () => flip(!f.open) }, f.open ? "Close it" : "Open it")));
}
function experimentBlock(x) {
  return [h("h2", {}, "The experiment"),
    h("p", { class: "muted small" }, x.reviews
      ? pl(x.reviews, "review") + " (" + pl(x.answers, "answer") + ") from " + x.people_reviewing + (x.people_reviewing === 1 ? " person" : " people") + ". A review is a concept coming back after a gap." +
        (x.predicted == null ? "" : " Overall, REMEM predicted " + pct(x.predicted) + " and people got " + pct(x.observed) + " right.")
      : "No reviews yet. A review is a concept coming back after a gap."),
    h("div", { class: "ad-table", role: "table" }, h("div", { class: "ad-tr head", role: "row" }, ["Method", "Concepts", "Reviews", "Correct", "Avg gap"].map(t => h("span", { role: "columnheader" }, t))),
      x.arms.map(a => h("div", { class: "ad-tr", role: "row" }, [ARM_NAMES[a.arm], String(a.concepts), String(a.reviews), pct(a.accuracy), a.mean_gap_days == null ? "–" : a.mean_gap_days.toFixed(1) + "d"].map(t => h("span", { role: "cell" }, t))))),
    h("p", { class: "muted small" }, "Balance check, first-quiz accuracy (should be similar): " + x.arms.map(a => ARM_NAMES[a.arm] + " " + pct(a.first_quiz_accuracy)).join(", ") + "."),
    h("h3", {}, "Predicted vs actual, by days since last review"),
    x.by_gap.length ? h("div", { class: "ad-cal" }, x.by_gap.map(g => h("div", { class: "ad-calrow" },
      h("span", { class: "small" }, g.label, h("span", { class: "muted" }, " · " + pl(g.reviews, "review"))),
      h("div", { class: "ad-bars", "aria-hidden": "true" }, h("i", { class: "pred", style: "--v:" + g.predicted }), h("i", { class: "obs", style: "--v:" + g.observed })),
      h("span", { class: "small" }, pct(g.predicted) + " → " + pct(g.observed))))) : h("p", { class: "muted" }, "No reviews yet."),
    h("p", { class: "muted small" }, h("i", { class: "ad-key pred" }), " predicted   ", h("i", { class: "ad-key obs" }), " actually right. Small numbers: read it as a trend, not a result.")];
}
async function viewAdmin() {
  const gen = routeGen;
  mount(h("h1", {}, "Pilot today"), skeleton(4, true));
  let o; try { o = await api("/admin/overview"); } catch (e) { if (gen === routeGen) errScreen("Pilot today", e); return; }
  if (gen !== routeGen) return;
  const showAll = store.get("remem_admin_all") === "1";
  const people = o.people.filter(p => showAll || p.role === "student");
  const t = o.today;
  const toggle = h("label", { class: "switch" }, h("span", {}, "Show test and admin accounts"),
    h("input", { type: "checkbox", role: "switch", checked: showAll, onchange: e => { store.set("remem_admin_all", e.target.checked ? "1" : "0"); viewAdmin(); } }));
  mount(h("h1", {}, "Pilot today"),
    h("p", { class: "muted small" }, dayName(o.now) + " · updated " + clock(o.now) + " · ", h("button", { class: "link", type: "button", onclick: () => viewAdmin() }, "Refresh")),
    adminCards([[t.people + "/" + t.started, "answered today"], [t.answers, "questions today"], [t.active_3d + "/" + t.started, "active in last 3 days"], [t.waiting, "have questions waiting"]]),
    h("p", { class: "muted small" }, t.started + " of " + pl(t.students, "account") + " started · " + t.two_topics + " have 2+ topics · " + t.reminders_on + " have reminders on"),
    finalCard(o, viewAdmin),
    h("a", { class: "panel ad-row", href: "#/admin/notify" }, h("span", {}, h("b", {}, "Notifications"), h("span", { class: "muted small" }, " · see every message, send one to your phone")), icon("M9 5l7 7-7 7", "chev")),
    h("h2", {}, "People"), h("div", { class: "me-group" }, toggle),
    h("div", { class: "ad-list" }, people.map(p => personLine(p, o.final.open))),
    ...experimentBlock(o.experiment));
}
async function viewAdminPerson(id) {
  const gen = routeGen;
  const back = h("a", { class: "btn", href: "#/" }, "Back");
  mount(h("h1", {}, "Person"), skeleton(4));
  let p; try { p = await api("/admin/person/" + id); } catch (e) { if (gen === routeGen) errScreen("Person", e, back); return; }
  if (gen !== routeGen) return;
  const [label, tone] = personState(p);
  const max = Math.max(1, ...p.days.map(d => d.answers));
  mount(h("p", {}, h("a", { href: "#/" }, "← Pilot today")),
    h("h1", {}, p.name || p.username),
    h("p", { class: "muted" }, p.username + " · " + p.role + (p.age ? " · age " + p.age : "") + (p.active ? "" : " · disabled") + " ", h("span", { class: "ad-pill " + tone }, label)),
    adminCards([[p.days_active, "active days"], [p.answers, "answers"], [p.concepts, "concepts"], [p.waiting, "waiting now"]]),
    h("p", { class: "muted small" }, "Last active " + since(p.last_ts) + " · reminders " + (p.reminders_on ? "on" : "off") +
      (p.final.total ? " · Remem Test " + (p.final.finished ? "finished, " + p.final.right + "/" + p.final.total + " right" : p.final.answered + "/" + p.final.total + " answered") : "")),
    h("h2", {}, "Last 14 days"),
    h("div", { class: "ad-chart", role: "img", "aria-label": "Answers per day over the last 14 days: " + p.days.map(d => d.answers).join(", ") },
      p.days.map(d => h("div", { class: "ad-col" }, h("small", {}, d.answers ? String(d.answers) : ""), h("i", { style: "--v:" + (d.answers / max) }), h("span", {}, String(new Date(d.day_ms).getDate()))))),
    h("h2", {}, "Topics"),
    p.topic_list.length ? h("div", { class: "me-group" }, p.topic_list.map(t => h("div", {}, h("b", {}, t.title), h("div", { class: "muted small" },
      (t.own_notes ? "own notes · " : "") + pl(t.concepts, "concept") + " (" + Object.entries(t.arms).map(([a, n]) => ARM_NAMES[a] + " " + n).join(", ") + ") · added " + dayName(t.added))))) : h("p", { class: "muted" }, "No topics yet."),
    p.known_topics.length ? h("p", { class: "muted small" }, "Said they already know: " + p.known_topics.join(", ")) : null,
    h("h2", {}, "Recent reviews"),
    p.reviews.length ? h("div", { class: "me-group" }, p.reviews.map(r => h("div", {}, h("div", { class: "ad-top" }, h("span", {}, r.concept), h("b", {}, r.right + "/" + r.n)),
      h("div", { class: "muted small" }, dayName(r.ts) + " · " + ARM_NAMES[r.arm] + " · after " + r.gap_days.toFixed(1) + " days · predicted " + pct(r.predicted))))) : h("p", { class: "muted" }, "No reviews yet."),
    h("h2", {}, "Reminders sent"),
    p.reminders.length ? h("div", { class: "me-group ad-rems" }, p.reminders.map(r => h("details", {},
      h("summary", {}, h("span", {}, h("span", { class: "small" }, dayName(r.ts) + ", " + clock(r.ts) + (r.reached ? "" : " · not delivered")), h("br"), h("b", { class: "small" }, r.title)), icon("M9 5l7 7-7 7", "chev")),
      h("div", { class: "ad-notif" }, h("b", {}, r.title), h("p", {}, r.body)),
      h("p", { class: "muted small" }, ({ due: "Daily reminder", final: "Remem Test opened", done: "Remem Test finished", test: "Reminders-on check", owner: "Sent to yourself" }[r.kind] || r.kind) +
        (r.template ? " · line " + r.template : "") + (r.exact ? "" : " · an older reminder: its exact words weren't saved, so [blanks] mark where their topic and numbers went"))))) : h("p", { class: "muted" }, "None yet."),
    h("p", {}, back));
}
async function viewAdminTest() {
  const gen = routeGen;
  const back = h("a", { class: "btn", href: "#/" }, "Back");
  mount(h("h1", {}, "The Remem Test"), skeleton(4));
  let o, q; try { [o, q] = await Promise.all([api("/admin/overview"), api("/admin/final-questions")]); } catch (e) { if (gen === routeGen) errScreen("The Remem Test", e, back); return; }
  if (gen !== routeGen) return;
  const letters = "ABCDEF";
  const takers = o.people.filter(p => p.role === "student" && p.final.total);
  mount(h("h1", {}, "The Remem Test"),
    finalCard(o, viewAdminTest),
    h("h2", {}, "Progress"),
    takers.length ? h("div", { class: "me-group" }, takers.map(p => h("a", { class: "ad-top ad-link", href: "#/admin/p/" + p.user_id },
      h("span", {}, h("b", {}, p.name ? firstName(p.name) : p.username), " ", h("span", { class: "muted small" }, p.username)),
      h("span", { class: "ad-pill " + (p.final.finished ? "good" : p.final.answered ? "warn" : "off") },
        p.final.finished ? "Done · " + p.final.right + "/" + p.final.total : p.final.answered ? p.final.answered + "/" + p.final.total : "Not started")))) : h("p", { class: "muted" }, "Nobody has questions yet."),
    h("h2", {}, "Questions"),
    h("p", { class: "muted small" }, "Each person gets three unseen questions for every concept they studied, shuffled, without concept names. The right answer is marked ✓."),
    q.people.map(person => h("details", { class: "ad-q" },
      h("summary", {}, h("span", {}, h("b", {}, person.name ? firstName(person.name) : person.username), " ", h("span", { class: "muted small" }, person.username + " · " + pl(person.concepts.length, "concept") + " · " + pl(person.concepts.reduce((n, c) => n + c.questions.length, 0), "question")))),
      h("div", { class: "ad-concept" }, h("a", { class: "btn outline", href: "#/admin/try/" + person.user_id }, "Take this test yourself")),
      person.concepts.map(c => h("div", { class: "ad-concept" }, h("div", { class: "muted small" }, c.topic), h("b", {}, c.concept),
        c.questions.map(x => h("div", { class: "ad-qa" }, h("p", {}, x.stem),
          h("ol", {}, x.options.map((op, i) => h("li", { class: i === x.correct ? "ok" : "" }, h("span", { class: "muted" }, letters[i] + ". "), op, i === x.correct ? " ✓" : ""))))))))),
    h("p", {}, back));
}

async function notifySelf(tpl, extra) {               // send one message to the owner's own phone; true when it went
  try {
    const r = await api("/admin/notify-self", { method: "POST", body: Object.assign({ tpl }, extra || {}) });
    if (!r.sent) { toast("Couldn't reach your phone. Check that notifications are allowed."); return false; }
    toast("Sent: " + r.title); return true;
  } catch (e) { toast(errText(e)); return false; }
}
async function viewAdminNotify() {
  const gen = routeGen;
  const back = h("a", { class: "btn", href: "#/" }, "Back");
  mount(h("h1", {}, "Notifications"), skeleton(4));
  let c; try { c = await api("/admin/notify-catalog"); } catch (e) { if (gen === routeGen) errScreen("Notifications", e, back); return; }
  if (gen !== routeGen) return;
  const turnOn = h("button", { class: "primary", type: "button", onclick: async () => {
    turnOn.disabled = true;
    try { await turnOnReminders(); toast("Notifications are on for this phone."); viewAdminNotify(); } catch (e) { turnOn.disabled = false; toast(errText(e)); }
  } }, "Turn on notifications");
  const groups = [];
  c.messages.forEach(m => { const g = groups.find(x => x.name === m.group); if (g) g.items.push(m); else groups.push({ name: m.group, items: [m] }); });
  mount(h("p", {}, h("a", { href: "#/" }, "← Pilot today")), h("h1", {}, "Notifications"),
    h("p", { class: "muted" }, "Every message people can get, filled with sample words. Tap Send to see exactly how it looks on your phone. Sending to yourself never counts in the pilot."),
    c.reminders_on ? null : h("div", { class: "calm" }, h("b", {}, "Notifications are off on this phone"),
      h("p", { class: "muted" }, "Turn them on once, then you can send any message to yourself."), h("div", { class: "actions" }, turnOn)),
    groups.map(g => [h("h2", {}, g.name), h("div", { class: "me-group" }, g.items.map(m => {
      const send = h("button", { class: "btn outline", type: "button", disabled: !c.reminders_on, onclick: async () => { send.disabled = true; await notifySelf(m.tpl); send.disabled = false; } }, "Send");
      return h("div", { class: "ad-msg" }, h("div", {}, h("b", {}, m.title), h("div", { class: "muted small" }, m.body)), send);
    }))]),
    h("p", {}, back));
}
function shuffled(list, seed) {                       // a fixed shuffle for one practice run
  let x = seed || 1; const rnd = () => (x = (x * 1103515245 + 12345) % 2147483648) / 2147483648;
  const a = list.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a;
}
async function viewAdminTry(uid) {
  const gen = routeGen;
  const back = h("a", { class: "btn", href: "#/admin/test" }, "Back");
  mount(h("h1", {}, "Practice Remem Test"), skeleton(3));
  let q; try { q = await api("/admin/final-questions"); } catch (e) { if (gen === routeGen) errScreen("Practice Remem Test", e, back); return; }
  if (gen !== routeGen) return;
  const person = q.people.find(p => p.user_id === uid);
  if (!person) return errScreen("Practice Remem Test", Object.assign(new Error("No Remem Test questions for this account."), { status: 404 }), back);
  const all = shuffled(person.concepts.flatMap(c => c.questions.map(x => ({ ...x, concept: c.concept }))), Date.now() % 100000 + 7);
  const who = person.name ? firstName(person.name) : person.username;
  const picks = [];
  const finish = () => {
    if (gen !== routeGen) return;
    const right = picks.filter((p, i) => p === all[i].correct).length;
    notifySelf("fd1", { n: all.length, right });
    const wrong = all.map((x, i) => ({ x, p: picks[i] })).filter(r => r.p !== r.x.correct);
    mount(h("div", { class: "mk-done" }, markSvg("mk-burst", 56)), h("h1", {}, "You got " + right + " of " + all.length),
      h("p", { class: "muted" }, "Practice run on " + who + "'s questions. Nothing was saved. If notifications are on for this phone, \"Mogambo khush hua\" is on its way."),
      wrong.length ? h("h2", {}, "The ones you missed") : h("p", {}, "Perfect score."),
      wrong.map(r => h("div", { class: "panel" }, h("div", { class: "muted small" }, r.x.concept), h("p", {}, r.x.stem),
        h("p", { class: "small" }, "You chose: " + r.x.options[r.p]), h("p", { class: "small ok" }, "Right answer: " + r.x.options[r.x.correct]))),
      h("div", { class: "actions" }, h("button", { class: "primary", type: "button", onclick: () => viewAdminTry(uid) }, "Try again"), back));
  };
  const ask = i => {
    if (gen !== routeGen) return;
    if (i >= all.length) return finish();
    const x = all[i];
    mount(h("p", { class: "muted small" }, "Practice run · " + who + "'s questions · nothing is saved"),
      h("h1", {}, "Question " + (i + 1) + " of " + all.length),
      h("div", { class: "meter" }, h("i", { style: "--v:" + (i / all.length) })),
      h("p", { class: "ad-stem" }, x.stem),
      h("div", { class: "stack" }, x.options.map((op, k) => h("button", { class: "block ad-opt", type: "button", onclick: () => { picks[i] = k; ask(i + 1); } }, op))),
      h("p", {}, h("button", { class: "link", type: "button", onclick: () => { location.hash = "#/admin/test"; } }, "Stop")));
  };
  mount(h("p", {}, h("a", { href: "#/admin/test" }, "← The Remem Test")), h("h1", {}, "Practice Remem Test"),
    h("p", {}, "You'll answer " + who + "'s " + all.length + " Remem Test questions, shuffled and without concept names, just as they will see them. Right answers show at the end."),
    h("div", { class: "calm" }, h("b", {}, "Nothing is saved"), h("p", { class: "muted" }, "Your answers don't count anywhere. You'll get the \"Kaabil bano\" notification when you start and \"Mogambo khush hua\" with your score when you finish (if notifications are on for this phone).")),
    h("div", { class: "actions" }, h("button", { class: "primary", type: "button", onclick: () => { notifySelf("fl1", { n: all.length }); ask(0); } }, "Start"), back));
}

// ---------------------------------------------------------------- router
let routeGen = 0;
async function signUpGate() {                        // asked once per sign-in (sessions from before this check have no flag yet)
  mount(skeleton(2));
  let f; try { f = await api("/auth/profile"); } catch (e) { return errScreen("Remem", e); }
  if (f.consent_ok) { store.set("remem_consented", "1"); return route(); }
  location.replace(f.done ? "#/consent" : "#/about");
}
function route() {
  routeGen++;
  const hash = location.hash || "#/";
  renderNav();
  if (hash.startsWith("#/install")) return viewInstall();
  if (!S.token) return viewLogin();
  const [path, query] = hash.split("?"), [, a, b, c] = path.split("/");
  if (S.role === "admin") {                                              // the owner's account: the pilot view, not the student app
    if (a === "admin" && b === "p" && /^\d+$/.test(c || "")) return viewAdminPerson(Number(c));
    if (a === "admin" && b === "test") return viewAdminTest();
    if (a === "admin" && b === "notify") return viewAdminNotify();
    if (a === "admin" && b === "try" && /^\d+$/.test(c || "")) return viewAdminTry(Number(c));
    if (a === "me") return viewMe();
    if (a) { location.replace("#/"); return; }
    return viewAdmin();
  }
  if (a !== "about" && a !== "consent" && store.get("remem_consented") !== "1") return signUpGate();   // no screen before the intro form and consent
  switch (a) {
    case "about": return viewAbout();
    case "consent": return viewConsent();
    case "notes": return b ? viewTopic(b) : viewNotes();
    case "final": return viewFinal();
    case "concepts": return viewConcepts();
    case "test": return viewTest(new URLSearchParams(query || "").get("note"));
    case "practice": location.replace("#/test"); return;                  // old links: practice now happens only in the daily test
    case "curve": return /^\d+$/.test(b || "") ? viewCurve(Number(b)) : errScreen("Memory curve", Object.assign(new Error("Unknown concept"), { status: 404 }), h("a", { class: "btn", href: "#/concepts" }, "Back"));
    case "me": return viewMe();
    case "login": location.replace("#/"); return;                          // already signed in: go to Today
    case undefined: case "": flushQueue(); return viewHome();
    default: location.replace("#/"); return;                               // an unknown address: go to Today (and show it in the address)
  }
}
window.addEventListener("hashchange", route);
window.addEventListener("load", () => {
  route();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
});
