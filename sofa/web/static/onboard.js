/* The onboarding wizard. Every step works without this script, except the conversation with Talk (which says so) and the page that follows the first appointment.
   With it: a secret can be revealed, the preview of what Talk may say follows the information as it is typed, a button says that it is working, and step 7 follows the first
   appointment from the booking to the text message without a reload. Plain script, no libraries. Everything the server sends is set as text, never as markup,
   except the preview, which the server renders and escapes. */
(function () {
  /* ---- reveal a masked secret ---- */
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-reveal]");
    if (!button) return;
    var field = document.getElementById(button.getAttribute("data-reveal"));
    if (!field) return;
    var show = field.type === "password";
    field.type = show ? "text" : "password";
    button.textContent = show ? "Hide" : "Reveal";
    button.setAttribute("aria-pressed", show ? "true" : "false");
  });

  /* ---- a button that asks the server something slow says so, and cannot be pressed twice ---- */
  document.addEventListener("submit", function (event) {
    var button = event.target.querySelector("button[data-busy]");
    if (!button) return;
    window.setTimeout(function () { button.disabled = true; button.setAttribute("aria-busy", "true"); button.textContent = button.getAttribute("data-busy"); }, 0);
  });

  /* ---- step 4: the preview follows what is typed ---- */
  var form = document.getElementById("information-form");
  var preview = document.getElementById("preview");
  if (form && preview && window.fetch && window.URLSearchParams && window.FormData) {
    var timer = null;
    var latest = 0;
    var refresh = function () {
      var mine = ++latest;
      preview.setAttribute("aria-busy", "true");
      fetch(form.getAttribute("data-preview-url"), { method: "POST", body: new URLSearchParams(new FormData(form)), credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.text() : Promise.reject(new Error("no preview")); })
        .then(function (html) { if (mine === latest) { preview.innerHTML = html; } })
        .catch(function () { /* the preview stays as it was */ })
        .then(function () { if (mine === latest) { preview.setAttribute("aria-busy", "false"); } });
    };
    var later = function () { window.clearTimeout(timer); timer = window.setTimeout(refresh, 450); };
    form.addEventListener("input", later);
    form.addEventListener("change", later);
  }

  /* ---- step 7: from the booking to the text message ---- */
  var root = document.getElementById("journey");
  if (!root) return;
  var list = document.getElementById("progress-list");
  var note = document.getElementById("journey-note");
  var frame = document.getElementById("desk-frame");
  var card = document.getElementById("text-card");
  var stages = ["booked", "desk", "confirmed", "text"];
  var done = { booked: false, desk: false, confirmed: false, text: false };
  var seen = null;          // the first booking that came through Talk
  var polling = null;
  var tries = 0;

  function paint() {
    var next = true;
    Array.prototype.forEach.call(list.children, function (li) {
      var stage = li.getAttribute("data-stage");
      var dot = li.querySelector(".dot");
      var finished = done[stage];
      li.className = finished ? "done" : next ? "next" : "";
      dot.textContent = finished ? "✓" : String(stages.indexOf(stage) + 1);
      if (!finished) { next = false; }
    });
  }

  function tell(text) { if (note) { note.textContent = text; } }

  function deskHas(code) {
    try { return !!frame.contentDocument.getElementById("visit-" + code); } catch (e) { return false; }
  }

  function reloadDesk() {
    try { frame.contentWindow.location.reload(); } catch (e) { frame.src = frame.src; }
  }

  function apply(data) {
    var first = (data.appointments || [])[0];
    if (first && !done.booked) {
      done.booked = true; seen = first.code;
      tell("Booked " + first.code);
      reloadDesk();
    }
    if (first && done.booked && !done.desk) {
      if (deskHas(first.code)) { done.desk = true; tell("Press Confirm on the desk"); }
      else if (tries++ % 3 === 2) { reloadDesk(); }
    }
    if (first && first.status !== "booked") { done.desk = true; done.confirmed = true; }
    if (data.confirmed && data.confirmation) {
      done.desk = done.confirmed = done.text = true;
      document.getElementById("text-body").textContent = data.confirmation.text;
      document.getElementById("text-delivery").textContent = data.confirmation.words;
      card.hidden = false;
      tell("Done");
      document.getElementById("finish-link").hidden = false;
      document.getElementById("finish-link").removeAttribute("aria-disabled");
      document.getElementById("skip-link").hidden = true;
      window.clearInterval(polling);
    }
    paint();
  }

  function poll() {
    if (document.hidden && polling) { return; }
    fetch(root.getAttribute("data-journey-url"), { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) { apply(data); } })
      .catch(function () { /* try again at the next beat */ });
  }

  /* a booking made in the conversation is looked for at once, not at the next beat */
  document.addEventListener("try:reply", function (event) {
    var action = event.detail && event.detail.action;
    if (action === "health_booked" || action === "health_cancelled") { window.setTimeout(poll, 400); }
  });
  /* the Confirm button is pressed inside the desk, which is another page: the beat below notices it within a few seconds */
  paint();
  poll();
  polling = window.setInterval(poll, 2500);
})();
