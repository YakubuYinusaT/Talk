/* The front desk keeps itself up to date while it is open. Everything on the page can be read without this script; this only adds comfort for staff who keep the desk open all day:
   the figures, requests and visits are refreshed in place (the place you have scrolled to, the answer you are typing and the entries you have opened all stay as they are),
   marking a visit or sending a reply happens without leaving the page, and the long lists can be narrowed down. Short confirmations appear as toasts (see ci.js), and a toast is
   read out by assistive technology, so a refresh every ten seconds never speaks unless something needs attention. */
(function () {
  var live = document.getElementById("desk-live");
  if (!live) return;
  var box = document.getElementById("auto-refresh");
  var now = document.getElementById("refresh-now");
  var updated = document.getElementById("updated");
  var timer = null;
  var busy = false;
  var active = "overview";

  /* One section at a time. The address names the section (or something inside one, such as a request), so a link, the Back button and a reload all land in
     the right place. Without this script every section is shown, one under the other. */
  function sectionOf(id) {
    var el = id && document.getElementById(id);
    var panel = el && live.contains(el) ? (el.hasAttribute("data-panel") ? el : el.closest("[data-panel]")) : null;
    return panel ? panel.id : "overview";
  }

  function show(id, focusTarget) {
    active = id;
    Array.prototype.forEach.call(live.querySelectorAll("[data-panel]"), function (p) { p.hidden = p.id !== id; });
    Array.prototype.forEach.call(document.querySelectorAll("#desk-nav a[data-panel]"), function (a) {
      a.setAttribute("aria-current", a.getAttribute("data-panel") === id ? "true" : "false");
    });
    var crumb = document.getElementById("crumb");
    var label = document.querySelector('#desk-nav a[data-panel="' + id + '"] span');
    if (crumb) crumb.textContent = label ? label.textContent : "";
    if (focusTarget) {
      focusTarget.setAttribute("tabindex", "-1");
      focusTarget.focus({ preventScroll: true });
      focusTarget.scrollIntoView({ block: "start" });
    }
  }

  function follow() {
    var id = decodeURIComponent((location.hash || "").slice(1));
    var section = sectionOf(id);
    var target = id && id !== section ? document.getElementById(id) : null;
    show(section, target);
    if (!target) window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", follow);
  follow();

  function toast(text, tone) {
    if (window.toast) window.toast(text, tone || "info");
  }

  function clock() {
    var d = new Date();
    function two(n) { return (n < 10 ? "0" : "") + n; }
    return two(d.getHours()) + ":" + two(d.getMinutes()) + ":" + two(d.getSeconds());
  }

  /* The time of the last check is shown beside the refresh button. */
  function stamp() {
    if (updated) updated.textContent = "Updated " + clock();
  }

  /* What the visitor has done on the page and the page does not know: the entries opened, the text typed, the filters chosen and the place of the cursor. */
  function save() {
    var state = { y: window.scrollY, open: [], values: {}, focus: null };
    Array.prototype.forEach.call(live.querySelectorAll("details[id]"), function (d) { if (d.open) state.open.push(d.id); });
    Array.prototype.forEach.call(live.querySelectorAll("input[id]:not([type=hidden]):not([type=password]), select[id]"), function (el) { state.values[el.id] = el.value; });
    var a = document.activeElement;
    if (a && a.id && live.contains(a)) {
      state.focus = { id: a.id, start: a.selectionStart, end: a.selectionEnd };
    }
    return state;
  }

  function restore(state) {
    state.open.forEach(function (id) { var d = document.getElementById(id); if (d) d.open = true; });
    Object.keys(state.values).forEach(function (id) { var el = document.getElementById(id); if (el && state.values[id] !== "") el.value = state.values[id]; });
    narrow();
    if (state.focus) {
      var el = document.getElementById(state.focus.id);
      if (el) {
        el.focus({ preventScroll: true });
        try { if (state.focus.start !== null && state.focus.start !== undefined) el.setSelectionRange(state.focus.start, state.focus.end); } catch (e) { /* not a text field */ }
      }
    }
    window.scrollTo(0, state.y);
  }

  /* How many urgent requests a page shows, so that a new one can be announced the moment it arrives. */
  function urgent(root) {
    var list = root.querySelector("[data-urgent]");
    return list ? parseInt(list.getAttribute("data-urgent"), 10) || 0 : 0;
  }

  /* Put a freshly fetched page into the live part. Returns false when the page has no live part (for example a sign-in page in front of the desk). */
  function swap(text) {
    var fresh = new DOMParser().parseFromString(text, "text/html").getElementById("desk-live");
    if (!fresh) return false;
    var doc = fresh.ownerDocument;
    var menu = document.getElementById("desk-nav");
    var freshMenu = doc.getElementById("desk-nav");
    if (menu && freshMenu && menu.innerHTML !== freshMenu.innerHTML) {   // the counts in the menu follow the page
      menu.innerHTML = freshMenu.innerHTML;
    }
    if (fresh.innerHTML !== live.innerHTML) {
      var before = urgent(live);
      var state = save();
      live.innerHTML = fresh.innerHTML;
      show(active);
      restore(state);
      if (urgent(live) > before) toast("A new urgent request has arrived.", "danger");
    } else {
      show(active);
    }
    return true;
  }

  function load(quiet) {
    if (busy) return;
    busy = true;
    if (now && !quiet) now.setAttribute("aria-busy", "true");
    fetch(location.href, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.text() : ""; })
      .then(function (text) {
        if (swap(text)) stamp();
        else if (!quiet) toast("The desk could not be refreshed.", "warning");
      })
      .catch(function () { if (!quiet) toast("The desk could not be refreshed. Please check the connection.", "warning"); })
      .then(function () { busy = false; if (now) now.removeAttribute("aria-busy"); });
  }

  function schedule() {
    clearInterval(timer);
    if (box && box.checked) timer = setInterval(function () { if (!document.hidden) load(true); }, 10000);
  }

  if (box) box.addEventListener("change", function () {
    schedule();
    toast(box.checked ? "Auto refresh is on." : "Auto refresh is off.");
  });
  if (now) now.addEventListener("click", function () { load(false); });
  document.addEventListener("visibilitychange", function () { if (!document.hidden && box && box.checked) load(true); });
  schedule();
  stamp();

  /* What a button did, in a few words, for the toast that follows it. */
  function done(form, submitter) {
    if (form.querySelector("input[name=reply]")) return "Reply saved.";
    if (/desk\/confirm$/.test(form.getAttribute("action") || "")) return "Visit confirmed.";
    return submitter && submitter.value === "no_show" ? "Marked as did not come." : "Marked as attended.";
  }

  /* Marking a visit, confirming it or sending a reply: the form is sent in the background and the page is refreshed in place, so the place on the page is kept.
     If anything goes wrong the form is sent in the ordinary way, which always works. */
  live.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || (form.method || "").toLowerCase() !== "post" || !window.fetch || !window.URLSearchParams || !window.FormData) return;
    event.preventDefault();
    var fields = new FormData(form);
    if (event.submitter && event.submitter.name) fields.set(event.submitter.name, event.submitter.value);
    var item = form.closest(".visit, .request");
    var itemId = item ? item.id : "";
    var message = done(form, event.submitter);
    fetch(form.action, { method: "POST", body: new URLSearchParams(fields), credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error("refused"); return r.text(); })
      .then(function (text) {
        if (!swap(text)) throw new Error("not the desk");
        stamp();
        toast(message, "success");
        var again = itemId && document.getElementById(itemId);
        var target = again || document.getElementById("requests-title") || live;
        if (target) {
          target.setAttribute("tabindex", "-1");
          target.focus({ preventScroll: true });
        }
      })
      .catch(function () { form.submit(); });
  });

  /* Short answers that staff can put into the reply box with one click, and then change before sending. */
  live.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-fill]");
    if (!button) return;
    var holder = button.closest("[data-for]");
    var field = holder && document.getElementById(holder.getAttribute("data-for"));
    if (field) {
      field.value = button.getAttribute("data-fill");
      field.focus();
    }
  });

  /* Narrowing the long lists: the visits of one place, and the medicines whose name contains what was typed. */
  function narrow() {
    var place = document.getElementById("place-filter");
    var chosen = place ? place.value : "";
    Array.prototype.forEach.call(live.querySelectorAll(".visit"), function (li) { li.hidden = !!chosen && li.getAttribute("data-place") !== chosen; });
    Array.prototype.forEach.call(live.querySelectorAll(".day"), function (day) { day.hidden = !day.querySelector(".visit:not([hidden])"); });
    var search = document.getElementById("stock-filter");
    var typed = search ? search.value.trim().toLowerCase() : "";
    var shown = 0;
    Array.prototype.forEach.call(live.querySelectorAll(".drug"), function (row) {
      var match = !typed || row.getAttribute("data-name").indexOf(typed) !== -1;
      row.hidden = !match;
      if (match) shown += 1;
    });
    var none = document.getElementById("stock-none");
    if (none) none.hidden = !typed || shown > 0;
  }
  live.addEventListener("input", function (event) { if (event.target.id === "stock-filter") narrow(); });
  live.addEventListener("change", function (event) { if (event.target.id === "place-filter") narrow(); });
})();
