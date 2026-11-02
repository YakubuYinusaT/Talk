/* The script every page loads: the theme button, the toasts, and a small comfort for the menu on a phone. Everything else on the site works without it, except the Try it conversation,
   which says so on its own page. */
(function () {
  var root = document.documentElement;
  root.classList.add("js");

  /* The theme follows the visitor's system until the button is used, and then the choice is remembered on this device. */
  function dark() {
    var set = root.getAttribute("data-theme");
    if (set === "dark" || set === "light") return set === "dark";
    return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }

  function syncButtons() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-theme-toggle]"), function (b) { b.setAttribute("aria-pressed", dark() ? "true" : "false"); });
  }

  document.addEventListener("click", function (event) {
    var t = event.target.closest("[data-theme-toggle]");
    if (!t) return;
    var next = dark() ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("ci-theme", next); } catch (e) { /* storage is blocked, so the choice lasts only for this page */ }
    syncButtons();
  });

  /* A toast is a short confirmation at the foot of the window. Any page can call window.toast("Saved", "success"), where the tone is info, success, warning or danger,
     and an element that carries data-toast="..." shows its message once when the page opens. */
  function toast(message, tone) {
    var region = document.getElementById("toasts");
    if (!region || !message) return;
    var box = document.createElement("div");
    box.className = "toast" + (tone && tone !== "info" ? " is-" + tone : "");
    box.textContent = message;
    region.appendChild(box);
    setTimeout(function () { if (box.parentNode) box.parentNode.removeChild(box); }, tone === "danger" ? 8000 : 4500);
  }
  window.toast = toast;

  function ready() {
    syncButtons();
    Array.prototype.forEach.call(document.querySelectorAll("[data-toast]"), function (el) { toast(el.getAttribute("data-toast"), el.getAttribute("data-toast-tone") || "info"); });

    /* On a phone the menu scrolls sideways, so the page the visitor is on is brought into view instead of being left off the edge. */
    var here = document.querySelector(".nav a[aria-current='page']");
    var menu = here && here.parentNode;
    if (menu && menu.scrollWidth > menu.clientWidth) {
      menu.scrollLeft = Math.max(0, menu.scrollLeft + here.getBoundingClientRect().left - menu.getBoundingClientRect().left - 16);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready); else ready();
})();
