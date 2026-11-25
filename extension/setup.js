// The page AFH opens in your browser to help you add the extension. It runs from the folder itself, as a file.
const edge = /Edg\//.test(navigator.userAgent);
const page = document.getElementById("page");
if (edge) page.textContent = "edge://extensions";
else if (navigator.brave) page.textContent = "brave://extensions";

const path = decodeURIComponent(new URL(".", location.href).pathname).replace(/\/$/, "");
document.getElementById("folder").textContent = /^\/[A-Za-z]:/.test(path) ? path.slice(1).replace(/\//g, "\\") : path;

for (const b of document.querySelectorAll("[data-copy]")) {
  b.addEventListener("click", async () => {
    const code = document.getElementById(b.dataset.copy);
    try {
      await navigator.clipboard.writeText(code.textContent);
      b.textContent = "Copied";
      setTimeout(() => (b.textContent = "Copy"), 1600);
    } catch (e) {
      getSelection().selectAllChildren(code); // the browser keeps the clipboard from local files: Ctrl+C works
    }
  });
}
