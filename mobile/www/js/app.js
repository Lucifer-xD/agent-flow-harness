// AFH for Android and iPhone: a small native-style app over the AFH account. Screens are custom
// elements pushed on an Ionic nav stack: sign in → computers → threads → chat (+ account).
import { auth, whenSignedOut } from "./api.js";
import { nav } from "./nav.js";

await Promise.all(["ion-nav", "ion-content", "ion-toolbar"].map((t) => customElements.whenDefined(t)));
await Promise.all(["signin", "computers", "threads", "chat", "account"].map((s) => import(`./screens/${s}.js`)));

whenSignedOut(() => nav().setRoot("afh-signin", {}, { animated: true, direction: "back" }));
await nav().setRoot(auth.token ? "afh-computers" : "afh-signin");
document.documentElement.classList.add("ready");

// Android back button (MainActivity asks this before leaving the app): close a sheet, then go back a screen.
window.afhBack = () => {
  const overlay = [...document.querySelectorAll("ion-modal, ion-action-sheet, ion-alert, ion-select-popover")].filter((o) => o.isConnected && !o.classList.contains("overlay-hidden")).pop();
  if (overlay) { overlay.dismiss?.(); return true; }
  const n = nav();
  if (n && n.querySelectorAll(":scope > .ion-page").length > 1) { n.pop(); return true; }
  return false;
};
