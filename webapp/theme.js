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
})();
