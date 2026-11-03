// The Download page: the checksum in a form PowerShell prints (hex), copy buttons, and what
// happens when you press Download — the page turns into next steps while light races down the
// line, as if bringing your copy.
import { scene } from "./page.js";

const hex = (b64) => [...atob(b64)].map((c) => c.charCodeAt(0).toString(16).padStart(2, "0")).join("").toUpperCase();
let sha = "";
const showSha = (rel) => {
  if (!rel?.sha) return;
  sha = hex(rel.sha);
  document.querySelectorAll("[data-sha-hex]").forEach((el) => { el.textContent = sha; });
};
showSha(window.afhRelease); // layout.js may have read the release before this module loaded
document.addEventListener("afh:release", (e) => showSha(e.detail));

const copy = (btn, text) => navigator.clipboard.writeText(text).then(
  () => { btn.textContent = "Copied"; setTimeout(() => { btn.textContent = "Copy"; }, 1400); },
  () => { btn.textContent = "Select it"; },
);
document.querySelector("[data-copy-hash]")?.addEventListener("click", (e) => sha && copy(e.currentTarget, sha));
document.querySelector("[data-copy-cmd]")?.addEventListener("click", (e) => copy(e.currentTarget, e.currentTarget.previousElementSibling.textContent));

const main = document.querySelector(".dl-main");
document.querySelectorAll("[data-download]").forEach((a) => a.addEventListener("click", () => {
  main.classList.add("downloading");
  window.gsap.timeline().to(scene.state, { activity: 4, duration: 1.2, ease: "power2.out" }).to(scene.state, { activity: 0.3, duration: 2.4, ease: "power2.inOut" }, "+=2");
  scrollTo({ top: 0, behavior: "smooth" });
}));
