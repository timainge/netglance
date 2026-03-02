// Three-state theme toggle: light → dark → auto (system)
(function () {
  var icons = {
    light: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="size-4.5"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>',
    dark: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="size-4.5"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>',
    auto: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="size-4.5"><rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/></svg>'
  };

  var titles = {
    light: "Theme: light",
    dark: "Theme: dark",
    auto: "Theme: auto"
  };

  var cycle = { light: "dark", dark: "auto", auto: "light" };

  function getState() {
    var s = localStorage.getItem("theme");
    return s === "dark" || s === "light" ? s : "auto";
  }

  function apply(state) {
    var root = document.documentElement;
    if (state === "dark") {
      root.classList.add("dark");
      localStorage.setItem("theme", "dark");
    } else if (state === "light") {
      root.classList.remove("dark");
      localStorage.setItem("theme", "light");
    } else {
      localStorage.removeItem("theme");
      if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
        root.classList.add("dark");
      } else {
        root.classList.remove("dark");
      }
    }
    updateButton(state);
    if (typeof updatePygmentsStylesheet === "function") updatePygmentsStylesheet();
  }

  function updateButton(state) {
    var btn = document.querySelector('[title="Toggle theme"], [title^="Theme:"]');
    if (!btn) return;
    btn.title = titles[state];
    var span = btn.querySelector(".sr-only");
    var svg = btn.querySelector("svg");
    if (svg) svg.outerHTML = icons[state];
    if (span) span.textContent = titles[state];
  }

  // Replace the button's inline onclick since the theme's const can't be overridden
  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.querySelector('[title="Toggle theme"], [title^="Theme:"]');
    if (btn) {
      btn.removeAttribute("onclick");
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        apply(cycle[getState()]);
      });
    }
    updateButton(getState());
  });
})();
