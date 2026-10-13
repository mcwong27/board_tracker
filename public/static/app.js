// Two small behaviours, no framework: the theme toggle and timeline hover cards.

(function theme() {
  var root = document.documentElement;
  var button = document.getElementById("theme-toggle");
  if (!button) return;
  var systemDark = window.matchMedia("(prefers-color-scheme: dark)");

  function current() {
    return root.getAttribute("data-theme") || (systemDark.matches ? "dark" : "light");
  }
  function label() {
    button.textContent = current() === "dark" ? "Light mode" : "Dark mode";
  }
  button.addEventListener("click", function () {
    var next = current() === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch (e) {}
    label();
  });
  systemDark.addEventListener("change", label);
  label();
})();

(function timelineTooltips() {
  var bars = document.querySelectorAll(".timeline-bar");
  if (!bars.length) return;

  // Lives on <body> so the timeline's horizontal scroll container can't clip it.
  var tip = document.createElement("div");
  tip.id = "tip";
  document.body.appendChild(tip);

  var GAP = 8;

  function show(bar) {
    var source = bar.querySelector(".tooltip");
    if (!source) return;
    tip.innerHTML = source.innerHTML;
    tip.classList.add("show");

    var barBox = bar.getBoundingClientRect();
    var tipBox = tip.getBoundingClientRect();
    var left = barBox.left + window.scrollX;
    var top = barBox.bottom + window.scrollY + GAP;

    // Keep it on screen: flip above the bar near the bottom, nudge in from the right.
    if (barBox.bottom + GAP + tipBox.height > window.innerHeight) {
      top = barBox.top + window.scrollY - tipBox.height - GAP;
    }
    var maxLeft = window.scrollX + document.documentElement.clientWidth - tipBox.width - GAP;
    tip.style.left = Math.max(window.scrollX + GAP, Math.min(left, maxLeft)) + "px";
    tip.style.top = Math.max(window.scrollY + GAP, top) + "px";
  }

  function hide() {
    tip.classList.remove("show");
  }

  bars.forEach(function (bar) {
    bar.addEventListener("mouseenter", function () { show(bar); });
    bar.addEventListener("focus", function () { show(bar); });
    bar.addEventListener("mouseleave", hide);
    bar.addEventListener("blur", hide);
  });
  window.addEventListener("scroll", hide, { passive: true });
})();
