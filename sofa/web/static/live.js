/* Live calls: an optional refresh, off until the visitor switches it on. Only the figures and calls are swapped, so the place you have scrolled to and the steps you have opened stay as they are. */
(function () {
  var box = document.getElementById("auto-refresh");
  var live = document.getElementById("live");
  if (!box || !live) return;
  var timer = null;

  function swap() {
    if (document.hidden || !box.checked) return;
    var open = Array.prototype.map.call(live.querySelectorAll("details"), function (d) { return d.open; });
    fetch(location.href, { credentials: "same-origin", cache: "no-store" }).then(function (r) { return r.ok ? r.text() : ""; }).then(function (text) {
      var fresh = new DOMParser().parseFromString(text, "text/html").getElementById("live");
      if (!fresh || fresh.innerHTML === live.innerHTML || !box.checked) return;
      var y = window.scrollY;
      live.innerHTML = fresh.innerHTML;
      Array.prototype.forEach.call(live.querySelectorAll("details"), function (d, i) { if (open[i]) d.open = true; });
      window.scrollTo(0, y);
    }).catch(function () { /* offline for a moment: try again next time */ });
  }

  box.addEventListener("change", function () {
    clearInterval(timer);
    if (box.checked) { timer = setInterval(swap, 10000); }
  });
})();
