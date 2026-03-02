document.addEventListener("DOMContentLoaded", function () {
  // Convert pre.mermaid code blocks to div.mermaid for Mermaid.js
  document.querySelectorAll("pre.mermaid").forEach(function (pre) {
    var div = document.createElement("div");
    div.className = "mermaid";
    div.textContent = pre.textContent;
    pre.replaceWith(div);
  });

  if (document.querySelectorAll("div.mermaid").length === 0) return;

  var script = document.createElement("script");
  script.src = "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js";
  script.onload = function () {
    var isDark = document.documentElement.classList.contains("dark");
    mermaid.initialize({ startOnLoad: false, theme: isDark ? "dark" : "default" });
    mermaid.run();
  };
  document.head.appendChild(script);
});
