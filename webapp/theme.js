/* Light or dark, chosen on Me and remembered on this phone. Loaded in <head> before the page draws, so there is no flash.
   No choice saved: follow the phone's own setting. A file of its own because the server's CSP allows no inline script. */
(function () {
  "use strict";
  var KEY = "remem_theme", root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  var still = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  var PAPER = { light: "#f7f6f2", dark: "#121318" }, fadeTimer = 0;

  function saved() { try { var v = localStorage.getItem(KEY); return v === "dark" || v === "light" ? v : null; } catch (e) { return null; } }
  function effective() { return saved() || (mq && mq.matches ? "dark" : "light"); }
  function apply() {
    var s = saved();
    if (s) root.setAttribute("data-theme", s); else root.removeAttribute("data-theme");
    var metas = document.querySelectorAll('meta[name="theme-color"]');               // the phone's status bar follows the choice
    for (var i = 0; i < metas.length; i++) {
      var own = /dark/.test(metas[i].getAttribute("media") || "") ? "dark" : "light";
      metas[i].setAttribute("content", PAPER[s || own]);
    }
  }
  function change(write) {                // the whole page cross-fades as one image where the browser can; elsewhere colours fade
    write();                              // saved at once (the page reads it straight away); only the redraw is animated
    var go = apply;
    if (still && still.matches) return go();
    if (document.startViewTransition) { document.startViewTransition(go); return; }
    root.classList.add("theme-fade"); void root.offsetWidth; go();
    clearTimeout(fadeTimer); fadeTimer = setTimeout(function () { root.classList.remove("theme-fade"); }, 480);
  }
  function set(theme) { change(function () { try { localStorage.setItem(KEY, theme); } catch (e) {} }); }
  function clear() { change(function () { try { localStorage.removeItem(KEY); } catch (e) {} }); }

  apply();
  window.remTheme = { saved: saved, effective: effective, set: set, clear: clear, phone: mq };

  /* Launch screen: the logo draws itself (stem up, the branch splitting off, the dot lighting up), then hands over to the app.
     Full story on the first open of the day, a short dot pulse after that, a still logo with reduced motion. It never holds
     the app back: the app loads underneath, a tap skips it, and CSS hides it on its own if this script never finishes. */
  var DAY_KEY = "remem_splash_day", t0 = Date.now();
  var mode = "full";
  try {
    var today = new Date().toDateString();
    if (still && still.matches) mode = "still";
    else if (localStorage.getItem(DAY_KEY) === today) mode = "short";
    localStorage.setItem(DAY_KEY, today);
  } catch (e) { mode = still && still.matches ? "still" : "short"; }
  root.classList.add("sp-" + mode);
  var MIN = { full: 1250, short: 520, still: 220 }[mode], gone = false;
  function hide() {
    if (gone) return; gone = true;
    var el = document.getElementById("splash");
    if (!el) return;
    el.classList.add("sp-out");
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); root.classList.remove("sp-" + mode); }, 340);
  }
  window.remSplashDone = function () {                     // called by the app once its first screen is on the page
    setTimeout(hide, Math.max(0, MIN - (Date.now() - t0)));
  };
  document.addEventListener("DOMContentLoaded", function () {
    var el = document.getElementById("splash");
    if (el) el.addEventListener("pointerdown", hide);      // a tap skips it
  });
  setTimeout(hide, 2600);                                  // the app never got there: never keep the logo up longer than this
})();
