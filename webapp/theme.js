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
  function fade() {                       // every colour cross-fades while the switch moves, like the reference page's background
    if (still && still.matches) return;
    root.classList.add("theme-fade"); void root.offsetWidth;
    clearTimeout(fadeTimer); fadeTimer = setTimeout(function () { root.classList.remove("theme-fade"); }, 420);
  }
  function set(theme) { fade(); try { localStorage.setItem(KEY, theme); } catch (e) {} apply(); }
  function clear() { fade(); try { localStorage.removeItem(KEY); } catch (e) {} apply(); }

  apply();
  window.remTheme = { saved: saved, effective: effective, set: set, clear: clear, phone: mq };
})();
