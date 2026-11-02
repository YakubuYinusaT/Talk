/* The Try it conversation. Plain script, no libraries. The server renders the steps as escaped HTML (steps_html); everything else is set as text.
   A visitor can type to Talk, or choose a ready-made conversation and send its sentences one at a time. */
(function () {
  var app = document.getElementById("try-app");
  if (!app) return;
  var log = document.getElementById("log");
  var form = document.getElementById("say-form");
  var input = document.getElementById("say");
  var sendBtn = document.getElementById("send");
  var restart = document.getElementById("restart");
  var status = document.getElementById("status");
  var inside = document.getElementById("inside");
  var picks = document.querySelectorAll("[data-script]");
  var panel = document.getElementById("script-panel");
  var panelName = document.getElementById("script-name");
  var panelLines = document.getElementById("script-lines");
  var nextBtn = document.getElementById("script-next");
  var note = document.getElementById("script-note");
  var emptyInside = inside.innerHTML;
  var scripts = [];
  try { scripts = JSON.parse(document.getElementById("scripts-data").textContent) || []; } catch (e) { scripts = []; }
  var session = null;
  var busy = false;
  var over = false;
  var current = null;   // the conversation being followed: { index: which one, next: the line to send next }

  function say(text, kind) { status.textContent = text; status.className = "status" + (kind ? " " + kind : ""); }

  /* A button that is waiting for an answer shows the standard spinner, and the rest of the controls wait with it. */
  function lock(on) {
    busy = on;
    var off = on || over || !session;
    input.disabled = off; sendBtn.disabled = off;
    Array.prototype.forEach.call(picks, function (b) { b.disabled = on; });
    nextBtn.disabled = off || !current || current.next >= scripts[current.index].lines.length;
    if (!on) { sendBtn.removeAttribute("aria-busy"); }
  }

  function bubble(who, text, stepsHtml) {
    var box = document.createElement("div");
    box.className = "msg " + (who === "Talk" ? "talk" : "you");
    var label = document.createElement("span"); label.className = "who"; label.textContent = who;
    var p = document.createElement("p"); p.textContent = text;
    box.appendChild(label); box.appendChild(p);
    if (stepsHtml) {
      var d = document.createElement("details");
      var s = document.createElement("summary"); s.textContent = "Steps";
      var body = document.createElement("div"); body.innerHTML = stepsHtml;
      d.appendChild(s); d.appendChild(body); box.appendChild(d);
    }
    log.appendChild(box);
    log.scrollTop = log.scrollHeight;
  }

  function post(path, body) {
    return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) { if (!r.ok) { throw new Error(data.error || "Something went wrong. Please try again."); } return data; });
    });
  }

  /* ---- the ready-made conversation: its sentences, which are done and which comes next ---- */

  function drawScript() {
    Array.prototype.forEach.call(picks, function (b) { b.setAttribute("aria-pressed", current && Number(b.getAttribute("data-script")) === current.index ? "true" : "false"); });
    if (!current) { panel.hidden = true; return; }
    var script = scripts[current.index];
    panel.hidden = false;
    panelName.textContent = script.title;
    panelLines.innerHTML = "";
    script.lines.forEach(function (line, i) {
      var li = document.createElement("li");
      li.textContent = line;
      li.className = i < current.next ? "done" : i === current.next ? "next" : "";
      if (i === current.next) { li.setAttribute("aria-current", "step"); }
      panelLines.appendChild(li);
    });
    var finished = current.next >= script.lines.length;
    note.textContent = finished ? "Done" : (current.next + 1) + " of " + script.lines.length;
  }

  function choose(index) {
    if (busy || !scripts[index]) return;
    current = { index: index, next: 0 };
    drawScript();
    start();   // every ready-made conversation begins with a fresh call, so nothing said earlier changes what Talk does
  }

  function sendNext() {
    if (!current || busy || over || !session) return;
    var lines = scripts[current.index].lines;
    if (current.next >= lines.length) return;
    send(lines[current.next], true);
  }

  /* ---- the call itself ---- */

  function start() {
    over = false; session = null; log.innerHTML = ""; inside.innerHTML = emptyInside;
    if (current) { current.next = 0; drawScript(); }
    lock(true); say("Connecting...");
    post("/try/start", {}).then(function (d) {
      session = d.session; bubble("Talk", d.greeting); say(""); lock(false); if (!current) { input.focus(); } else { nextBtn.focus(); }
    }).catch(function (e) { say(e.message, "err"); lock(false); });
  }

  function send(text, fromScript) {
    text = (text || "").trim();
    if (!text || busy || over || !session) return;
    bubble("You", text); input.value = ""; lock(true); sendBtn.setAttribute("aria-busy", "true"); say("Talk is replying...");
    post("/try/turn", { session: session, text: text }).then(function (d) {
      bubble("Talk", d.reply, d.steps_html);
      inside.innerHTML = d.steps_html;
      document.dispatchEvent(new CustomEvent("try:reply", { detail: d }));   // the onboarding wizard listens for this, to show a booking on the hospital's front desk at once
      if (fromScript && current) { current.next += 1; drawScript(); }
      if (d.ended) { over = true; say("Call ended. Start over to try again."); }
      else { say(d.turns_left <= 3 ? d.turns_left + (d.turns_left === 1 ? " message left." : " messages left.") : ""); }
      lock(false); if (!over) { (fromScript && current && current.next < scripts[current.index].lines.length ? nextBtn : input).focus(); }
    }).catch(function (e) {
      say(e.message, "err"); lock(false);
      if (/start over/i.test(e.message)) { over = true; lock(false); }   // the server says "start over" exactly when this conversation cannot go on
    });
  }

  form.addEventListener("submit", function (ev) { ev.preventDefault(); send(input.value, false); });
  Array.prototype.forEach.call(picks, function (b) { b.addEventListener("click", function () { choose(Number(b.getAttribute("data-script"))); }); });
  nextBtn.addEventListener("click", sendNext);
  restart.addEventListener("click", function () { start(); });
  if (app.getAttribute("data-autoselect") === "true" && scripts.length === 1) { current = { index: 0, next: 0 }; drawScript(); }   // one conversation, chosen for the visitor
  start();
})();
