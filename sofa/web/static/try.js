/* The Try it conversation. Plain script, no libraries. The server renders the steps as escaped HTML (steps_html); everything else is set as text.
   A visitor can call Talk from the browser, or type to it. Typing also offers ready-made conversations whose sentences are sent one at a time.
   A call is hands free: Talk speaks, then listens, and the visitor's turn ends by itself when they pause, as it does on the telephone. */
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

  // ---- the two ways in: a call or a chat ----
  var hasModes = app.getAttribute("data-modes") === "true";
  var mode = hasModes ? "call" : "chat";
  var tabCall = document.getElementById("tab-call");
  var tabChat = document.getElementById("tab-chat");
  var callPane = document.getElementById("call-mode");
  var chatPane = document.getElementById("chat-mode");
  var callStart = document.getElementById("call-start");
  var callLive = document.getElementById("call-live");
  var mic = document.getElementById("mic");
  var callEnd = document.getElementById("call-end");

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

  /* ---- the typed conversation ---- */

  function start() {
    over = false; session = null; log.innerHTML = ""; inside.innerHTML = emptyInside;
    if (current) { current.next = 0; drawScript(); }
    lock(true); say("Connecting...");
    post("/try/start", {}).then(function (d) {
      session = d.session; bubble("Talk", d.greeting); say(""); lock(false); if (!current) { input.focus(); } else { nextBtn.focus(); }
    }).catch(function (e) { say(e.message, "err"); lock(false); });
  }

  function shown(d) {
    inside.innerHTML = d.steps_html;
    document.dispatchEvent(new CustomEvent("try:reply", { detail: d }));   // the onboarding wizard listens for this, to show a booking on the hospital's front desk at once
  }

  function send(text, fromScript) {
    text = (text || "").trim();
    if (!text || busy || over || !session) return;
    bubble("You", text); input.value = ""; lock(true); sendBtn.setAttribute("aria-busy", "true"); say("Talk is replying...");
    post("/try/turn", { session: session, text: text }).then(function (d) {
      bubble("Talk", d.reply, d.steps_html);
      shown(d);
      if (fromScript && current) { current.next += 1; drawScript(); }
      if (d.ended) { over = true; say("Call ended. Start over to try again."); }
      else { say(d.turns_left <= 3 ? d.turns_left + (d.turns_left === 1 ? " message left." : " messages left.") : ""); }
      lock(false); if (!over) { (fromScript && current && current.next < scripts[current.index].lines.length ? nextBtn : input).focus(); }
    }).catch(function (e) {
      say(e.message, "err"); lock(false);
      if (/start over/i.test(e.message)) { over = true; lock(false); }   // the server says "start over" exactly when this conversation cannot go on
    });
  }

  /* ---- the call from the browser ---- */

  var call = null;   // { stream, ctx, voice, live } while a call is open

  function pressMic(on, label) { if (!mic) return; mic.setAttribute("aria-pressed", on ? "true" : "false"); mic.textContent = label; mic.classList.toggle("on", on); }

  /* The visitor's speech as a 16 kHz, 16-bit WAV file in base64: the same sound a telephone line gives the recogniser, only clearer. */
  function wavBase64(chunks, rate) {
    var length = 0; chunks.forEach(function (c) { length += c.length; });
    var all = new Float32Array(length), at = 0;
    chunks.forEach(function (c) { all.set(c, at); at += c.length; });
    var ratio = rate / 16000, n = Math.floor(all.length / ratio), pcm = new Int16Array(n);
    for (var i = 0; i < n; i++) {
      var from = Math.floor(i * ratio), to = Math.min(all.length, Math.floor((i + 1) * ratio)), sum = 0;
      for (var j = from; j < to; j++) { sum += all[j]; }
      var v = Math.max(-1, Math.min(1, sum / Math.max(1, to - from)));
      pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
    }
    var buf = new ArrayBuffer(44 + pcm.length * 2), dv = new DataView(buf);
    function text(o, s) { for (var k = 0; k < s.length; k++) { dv.setUint8(o + k, s.charCodeAt(k)); } }
    text(0, "RIFF"); dv.setUint32(4, 36 + pcm.length * 2, true); text(8, "WAVE"); text(12, "fmt "); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true);
    dv.setUint16(22, 1, true); dv.setUint32(24, 16000, true); dv.setUint32(28, 32000, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true);
    text(36, "data"); dv.setUint32(40, pcm.length * 2, true);
    new Int16Array(buf, 44).set(pcm);
    var bytes = new Uint8Array(buf), out = "";
    for (var b = 0; b < bytes.length; b += 0x8000) { out += String.fromCharCode.apply(null, bytes.subarray(b, b + 0x8000)); }
    return btoa(out);
  }

  /* Plays Talk's reply. When the server has no real voice (a fresh checkout), the browser's own voice reads the words instead, so the call still works. */
  function play(urls, text) {
    return new Promise(function (done) {
      if (!call) { done(); return; }
      if ((!urls || !urls.length || call.voice === "stand-in") && window.speechSynthesis) {
        var u = new SpeechSynthesisUtterance(text); u.lang = "en-NG"; u.onend = done; u.onerror = done; speechSynthesis.speak(u); return;
      }
      var i = 0;
      (function next() {
        if (!call || i >= urls.length) { done(); return; }
        var a = new Audio(urls[i++]); call.player = a;
        a.onended = next; a.onerror = next; a.play().catch(next);
      })();
    });
  }

  /* Listens until the visitor has spoken and then paused, as a telephone line does. A visitor who says nothing for eight seconds is asked again. */
  function listen() {
    if (!call || over) return;
    var chunks = [], began = Date.now(), lastVoice = 0, spoke = false, floor = 0, frames = 0, ended = false;
    pressMic(true, "Listening");
    say("Listening...");
    call.finish = function () {
      if (ended) return;
      ended = true; call.proc.onaudioprocess = null; call.finish = null; pressMic(false, "Speak");
      if (!spoke) { say("I did not hear anything. Press Speak to try again."); return; }
      turn(wavBase64(chunks, call.ctx.sampleRate));
    };
    call.proc.onaudioprocess = function (e) {
      var data = e.inputBuffer.getChannelData(0), copy = new Float32Array(data.length), sum = 0;
      for (var i = 0; i < data.length; i++) { copy[i] = data[i]; sum += data[i] * data[i]; }
      var rms = Math.sqrt(sum / data.length), t = Date.now();
      frames += 1;
      if (frames <= 4) { floor = Math.max(floor, rms); }   // the first moment sets how loud the room is
      var threshold = Math.max(0.012, floor * 2.5);
      if (rms > threshold) { spoke = true; lastVoice = t; }
      if (spoke || chunks.length < 6) { chunks.push(copy); } else { chunks = chunks.slice(-5).concat([copy]); }   // a moment before the first word is kept
      if ((spoke && t - lastVoice > 1000) || t - began > 15000 || (!spoke && t - began > 8000)) { call.finish(); }
    };
  }

  function turn(audio) {
    lock(true); say("Talk is replying..."); mic.disabled = true;
    post("/try/speak", { session: session, audio: audio }).then(function (d) {
      if (d.heard) { bubble("You", d.heard); }
      bubble("Talk", d.reply, d.steps_html);
      shown(d);
      if (d.ended) { over = true; }
      lock(false); say("Talk is speaking..."); mic.disabled = false;
      return play(d.audio, d.reply).then(function () {
        if (over) { hangUp("Call ended."); } else { listen(); }
      });
    }).catch(function (e) {
      lock(false); mic.disabled = false; say(e.message, "err");
      if (/start over/i.test(e.message)) { hangUp(e.message); }
    });
  }

  function startCall() {
    if (busy) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { say("This browser cannot use a microphone. Please use Chat.", "err"); return; }
    callStart.disabled = true; say("Connecting...");
    navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }).then(function (stream) {
      var Ctx = window.AudioContext || window.webkitAudioContext, ctx = new Ctx();
      var source = ctx.createMediaStreamSource(stream), proc = ctx.createScriptProcessor(4096, 1, 1), mute = ctx.createGain();
      mute.gain.value = 0; source.connect(proc); proc.connect(mute); mute.connect(ctx.destination);
      call = { stream: stream, ctx: ctx, proc: proc, voice: "", player: null, finish: null };
      over = false; session = null; log.innerHTML = ""; inside.innerHTML = emptyInside;
      lock(true);
      return post("/try/start", { mode: "call" }).then(function (d) {
        session = d.session; call.voice = d.voice || ""; lock(false);
        callStart.hidden = true; callLive.hidden = false; callStart.disabled = false;
        bubble("Talk", d.greeting); say("Talk is speaking...");
        return play(d.audio, d.greeting).then(listen);
      });
    }).catch(function (e) {
      callStart.disabled = false; lock(false);
      say(e && e.name === "NotAllowedError" ? "Please allow the microphone to call, or use Chat." : (e.message || "The call could not start."), "err");
      hangUp(null);
    });
  }

  function hangUp(message) {
    if (call) {
      if (call.player) { call.player.pause(); }
      if (window.speechSynthesis) { speechSynthesis.cancel(); }
      if (call.proc) { call.proc.onaudioprocess = null; }
      call.stream.getTracks().forEach(function (t) { t.stop(); });
      call.ctx.close();
      call = null;
    }
    over = true; session = null; pressMic(false, "Speak");
    callLive.hidden = true; callStart.hidden = false;
    if (message) { say(message); }
  }


  function setMode(next) {
    if (!hasModes || next === mode) return;
    if (call) { hangUp(null); }
    mode = next;
    tabCall.setAttribute("aria-selected", mode === "call" ? "true" : "false"); tabCall.tabIndex = mode === "call" ? 0 : -1;
    tabChat.setAttribute("aria-selected", mode === "chat" ? "true" : "false"); tabChat.tabIndex = mode === "chat" ? 0 : -1;
    callPane.hidden = mode !== "call"; chatPane.hidden = mode !== "chat"; form.hidden = mode !== "chat";
    log.innerHTML = ""; inside.innerHTML = emptyInside; say("");
    if (mode === "chat") { start(); }
  }

  if (hasModes) {
    tabCall.addEventListener("click", function () { setMode("call"); });
    tabChat.addEventListener("click", function () { setMode("chat"); });
    [tabCall, tabChat].forEach(function (tab) {
      tab.addEventListener("keydown", function (ev) {
        if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") { ev.preventDefault(); var other = tab === tabCall ? tabChat : tabCall; other.focus(); other.click(); }
      });
    });
    callStart.addEventListener("click", startCall);
    mic.addEventListener("click", function () {
      if (!call || busy) return;
      if (call.finish) { call.finish(); return; }   // pressed while listening: the visitor has finished speaking
      if (call.player) { call.player.pause(); }
      if (window.speechSynthesis) { speechSynthesis.cancel(); }
      listen();
    });
    callEnd.addEventListener("click", function () { hangUp("Call ended."); });
  }

  form.addEventListener("submit", function (ev) { ev.preventDefault(); send(input.value, false); });
  Array.prototype.forEach.call(picks, function (b) { b.addEventListener("click", function () { choose(Number(b.getAttribute("data-script"))); }); });
  nextBtn.addEventListener("click", sendNext);
  restart.addEventListener("click", function () { if (mode === "call") { hangUp(null); log.innerHTML = ""; inside.innerHTML = emptyInside; say(""); } else { start(); } });
  if (app.getAttribute("data-autoselect") === "true" && scripts.length === 1) { current = { index: 0, next: 0 }; drawScript(); }   // one conversation, chosen for the visitor
  if (mode === "chat") { start(); }
})();
