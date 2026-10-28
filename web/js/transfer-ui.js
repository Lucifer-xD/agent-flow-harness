// Export a thread to a file; import threads from files or other harnesses (Zadloop, OpenCode).

import { api, native } from "./api.js";
import { ago, basename, el, ico, icon, modal, toast } from "./ui.js";

export async function exportThread(id, title) {
  try {
    const payload = await api.get(`/api/sessions/${id}/export`);
    const name = `${(title || id).replace(/[^\w.-]+/g, "-").slice(0, 60)}.afh-session.json`;
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const a = el("a", { href: URL.createObjectURL(blob), download: name });
    document.body.append(a);
    a.click();
    a.remove();
    toast(`Exported ${name}`, "ok");
  } catch (e) {
    toast(e.message, "err");
  }
}

/** Import dialog: a file (.afh-session.json / OpenCode export) or a Zadloop session. */
export function openImportDialog(ctx, onImported) {
  const directory = ctx.project();
  const body = el("div.m-body", { style: { padding: "22px 24px 26px" } });
  const tabs = el("div.seg", { style: { marginBottom: "14px" } });
  const panel = el("div");
  const m = modal(body, { small: true });
  const importPayload = async (req, label) => {
    const btns = panel.querySelectorAll("button");
    btns.forEach((b) => (b.disabled = true));
    try {
      const session = await api.post(req.url, req.body);
      toast(`Imported “${session.title || label}”`, "ok");
      m.close();
      onImported?.(session);
    } catch (e) {
      toast(e.message, "err", 6000);
      btns.forEach((b) => (b.disabled = false));
    }
  };
  const preview = async (req) => {
    try {
      const s = await api.post(req.url, { ...req.body, preview: true });
      return el("div.note", el("b", s.title || "Untitled"), ` · ${s.messages} messages · ${s.created ? new Date(s.created).toLocaleString() : ""}`, s.firstUserText ? el("div", { style: { marginTop: "4px", color: "var(--text-2)" } }, s.firstUserText.slice(0, 160)) : null);
    } catch (e) {
      return el("div.error-card", ico("alert"), el("div", e.message));
    }
  };

  const fileTab = async () => {
    panel.replaceChildren();
    const paste = el("textarea.ta.code", { rows: 6, placeholder: 'Paste the contents of an .afh-session.json file (or an OpenCode export: {"info": …, "messages": […]})' });
    const previewBox = el("div");
    const pickBtn = native.available() ? el("button.btn", { on: { click: async () => {
      const files = (await native.pickFiles()) || [];
      if (!files[0]) return;
      const req = { url: "/api/sessions/import", body: { path: files[0], directory } };
      previewBox.replaceChildren(await preview(req), el("div.actions", el("button.btn.primary", { on: { click: () => importPayload(req, basename(files[0])) } }, "Import this thread")));
    } } }, ico("file"), "Choose a file…") : el("div.help", "Run the desktop app to pick a file; here you can paste the JSON instead.");
    panel.append(pickBtn, el("div", { style: { margin: "12px 0 6px", color: "var(--text-3)", fontSize: "12.5px" } }, "or paste it:"), paste, previewBox,
      el("div.actions", el("button.btn.primary", { on: { click: async () => {
        let payload;
        try { payload = JSON.parse(paste.value); } catch { return toast("That isn't valid JSON", "err"); }
        importPayload({ url: "/api/sessions/import", body: { payload, directory } }, "pasted thread");
      } } }, "Import pasted JSON")));
  };

  const zadTab = async () => {
    panel.replaceChildren(el("div.empty-row", el("span.spinner")));
    let list = [];
    try { list = await api.get("/api/import/zadloop"); } catch (e) { panel.replaceChildren(el("div.empty-row", e.message)); return; }
    panel.replaceChildren();
    if (!list.length) return panel.append(el("div.empty-row", "No Zadloop (DeepSeek Harness) sessions found in ~/.dsh/sessions."));
    panel.append(el("div.help", { style: { marginBottom: "8px", color: "var(--text-3)", fontSize: "12.5px" } }, `${list.length} sessions found. Each imports as a new thread in ${basename(directory)}.`));
    const box = el("div", { style: { maxHeight: "340px", overflowY: "auto", border: "1px solid var(--border)", borderRadius: "10px" } });
    for (const s of list) {
      box.append(el("div.list-item", ico("branch"),
        el("div.li-main", el("div.li-title", s.title || s.id), el("div.li-sub", `${s.messages} messages · ${basename(s.cwd || s.workspace || "")} · ${s.createdAt ? ago(s.createdAt) : ""}`)),
        el("button.btn.sm", { on: { click: () => importPayload({ url: "/api/import/zadloop", body: { path: s.path, directory } }, s.title) } }, ico("arrow-down"), "Import")));
    }
    panel.append(box);
  };

  for (const [id, label, fn] of [["file", "From a file", fileTab], ["zadloop", "From Zadloop", zadTab]]) {
    tabs.append(el(`button${id === "file" ? ".on" : ""}`, { type: "button", on: { click: (e) => { tabs.querySelectorAll("button").forEach((b) => b.classList.remove("on")); e.currentTarget.classList.add("on"); fn(); } } }, label));
  }
  body.append(el("h2", "Import a thread"), el("p.lead", directory ? `Into ${basename(directory)}. OpenCode exports and AFH files keep tool calls, diffs and reasoning; Zadloop sessions are converted.` : "Open a project folder first."), tabs, panel);
  fileTab();
  return m;
}
