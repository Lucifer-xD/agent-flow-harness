// Context viewer/editor: everything the model sees, editable. The model reads from the latest
// compaction summary on, so that is what is shown; older messages stay in the thread untouched.
// Very long threads are drawn a page at a time so opening the editor never freezes the app.

import { api } from "./api.js";
import { confirmDialog, el, ico, icon, modal, toast } from "./ui.js";

const TYPES = { user: "You", assistant: "Model", system: "System notice", idle: "Run ended", compaction: "Compaction summary", shell: "Shell", synthetic: "Injected", skill: "Skill" };
const PAGE = 60;

export async function openContextEditor(ctx, thread, { onSaved }) {
  const body = el("div.m-body");
  const m = modal([el("div.ctx-side"), body]);
  m.box.classList.add("ctx-modal");
  body.append(el("button.icon-btn.m-close", { title: "Close", html: icon("x"), on: { click: () => m.close() } }));
  const loading = el("div.drawer-empty", el("span.spinner"));
  body.append(loading);
  let messages;
  try {
    messages = await api.get(`/api/sessions/${thread.id}/context`);
  } catch (e) {
    loading.replaceWith(el("div.error-card", ico("alert"), el("div", e.message)));
    return;
  }
  loading.remove();
  let start = 0;
  for (let i = messages.length - 1; i >= 0; i--) if (messages[i].type === "compaction") { start = i; break; }
  const before = messages.slice(0, start); // replaced by the summary for the model; saved back as they are
  const work = messages.slice(start).map((msg) => ({ msg, deleted: false, copied: false }));
  const own = (w) => { if (!w.copied) { w.msg = JSON.parse(JSON.stringify(w.msg)); w.copied = true; } return w.msg; };
  let dirty = false;
  const saveBtn = el("button.btn.primary", { disabled: true }, "Save & apply");
  const counter = el("span.h-muted", { style: { fontStyle: "normal" } });
  const sizeOf = (w) => (w.msg.text?.length || 0) + JSON.stringify(w.msg.content || "").length;
  const count = () => {
    const live = work.filter((w) => !w.deleted);
    counter.textContent = `${live.length} of ${work.length} messages · ~${Math.round(live.reduce((a, w) => a + sizeOf(w), 0) / 4000)}k tokens (rough)`;
  };
  let countTimer = 0;
  const markDirty = () => { dirty = true; saveBtn.disabled = false; clearTimeout(countTimer); countTimer = setTimeout(count, 400); };
  count();

  const side = m.box.querySelector(".ctx-side");
  side.append(el("h3", "Context"), el("p.lead", { style: { fontSize: "12.5px" } }, "What the model sees, in order. Edit any text — your requests, the model's replies, tool inputs and outputs, the compaction summary — or delete messages, then Save."),
    before.length ? el("div.note", el("b", `${before.length} earlier messages `), "are summarised by the compaction at the top. They stay in the thread for you to read; the model reads the summary instead.") : null,
    el("div.note", el("b", "Saving rewrites history. "), "Files on disk are not touched."),
    counter);

  const list = el("div.ctx-list");
  body.append(el("h2", thread.session.title || "Thread context"), list, el("div.actions", { style: { marginTop: "16px", position: "sticky", bottom: 0, background: "var(--bg)", padding: "10px 0" } }, el("span", { style: { flex: 1 } }), el("button.btn.ghost", { on: { click: () => m.close() } }, "Cancel"), saveBtn));

  const ta = (get, set, cls = "") => {
    const t = el(`textarea.ta.ctx-ta${cls}`, { value: get() ?? "", on: { input: (e) => { set(e.target.value); markDirty(); autosize(e.target); } } });
    requestAnimationFrame(() => autosize(t));
    return t;
  };
  const autosize = (t) => { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight + 2, 420) + "px"; };

  const block = (w) => {
    const msg = w.msg;
    const box = el(`div.ctx-msg.${msg.type}${w.deleted ? ".deleted" : ""}`);
    const head = el("div.ctx-head", el("span.ctx-type", TYPES[msg.type] || msg.type), msg.model ? el("span.pill-tag", `${msg.model.providerID}/${msg.model.id}`) : null, msg.agent ? el("span.pill-tag", msg.agent) : null,
      msg.time?.created ? el("span.h-muted", { style: { fontStyle: "normal", fontSize: "11.5px" } }, new Date(msg.time.created).toLocaleTimeString()) : null,
      el("span", { style: { flex: 1 } }),
      el("button.btn.ghost.sm", { title: "Delete this message", on: { click: () => { w.deleted = !w.deleted; box.classList.toggle("deleted", w.deleted); markDirty(); } } }, ico("trash")));
    box.append(head);
    if (msg.type === "user") box.append(ta(() => msg.text, (v) => (own(w).text = v)));
    else if (msg.type === "assistant") {
      (msg.content || []).forEach((p, j) => {
        const part = () => own(w).content[j];
        if (p.type === "text") box.append(el("div.ctx-part", el("div.tool-section-label", "reply"), ta(() => p.text, (v) => (part().text = v))));
        else if (p.type === "reasoning") box.append(el("details.ctx-part", el("summary", "thinking"), ta(() => p.text, (v) => (part().text = v), ".dim")));
        else if (p.type === "tool") {
          const st = p.state || {};
          const out = (st.content || []).filter((c) => c.type === "text");
          box.append(el("div.ctx-part.tool",
            el("div.tool-section-label", `tool · ${p.name} · ${st.status || ""}`),
            el("div.ctx-sub", "input (JSON)"), ta(() => JSON.stringify(st.input ?? {}, null, 2), (v) => { try { (part().state ||= {}).input = JSON.parse(v); box.classList.remove("bad-json"); } catch { box.classList.add("bad-json"); } }, ".mono"),
            out.length ? [el("div.ctx-sub", "output"), ta(() => out.map((c) => c.text).join("\n"), (v) => { (part().state ||= {}).content = [{ type: "text", text: v }]; }, ".mono")] : null,
            st.error ? el("div.ctx-sub", { style: { color: "var(--bad)" } }, `error: ${st.error.message || ""}`) : null));
        }
      });
    } else if (["system", "synthetic", "compaction"].includes(msg.type)) box.append(ta(() => msg.text, (v) => (own(w).text = v), msg.type === "compaction" ? "" : ".dim"));
    else box.append(el("div.ctx-sub", JSON.stringify({ ...msg, id: undefined, type: undefined, time: undefined }).slice(0, 200)));
    return box;
  };

  // Newest page first; "Show earlier" adds a page above, without rebuilding what is there.
  let shownFrom = Math.max(0, work.length - PAGE);
  const more = el("div.show-earlier", el("button.btn.ghost.sm", { on: { click: () => {
    const from = Math.max(0, shownFrom - PAGE);
    const frag = document.createDocumentFragment();
    for (const w of work.slice(from, shownFrom)) frag.append(block(w));
    list.insertBefore(frag, more.nextSibling);
    shownFrom = from;
    drawMore();
  } } }));
  const drawMore = () => {
    more.hidden = shownFrom === 0;
    more.firstChild.replaceChildren(ico("arrow-down"), `Show ${Math.min(PAGE, shownFrom)} earlier (${shownFrom} not shown)`);
  };
  list.append(more);
  for (const w of work.slice(shownFrom)) list.append(block(w));
  drawMore();
  requestAnimationFrame(() => { body.scrollTop = body.scrollHeight; });

  saveBtn.addEventListener("click", async () => {
    const kept = work.filter((w) => !w.deleted).map((w) => w.msg);
    if (![...before, ...kept].some((x) => x.type === "user")) return toast("Keep at least one of your messages", "err");
    if (body.querySelector(".bad-json")) return toast("A tool input isn't valid JSON", "err");
    if (!(await confirmDialog({ title: "Rewrite this thread's history?", body: "The model will see the edited version from the next message on. This can't be undone.", confirm: "Save & apply" }))) return;
    saveBtn.disabled = true;
    try {
      const session = await api.put(`/api/sessions/${thread.id}/messages`, { messages: [...before, ...kept], directory: ctx.project() });
      toast("Context updated", "ok");
      m.close();
      onSaved?.(session);
    } catch (e) {
      toast(e.message, "err", 7000);
      saveBtn.disabled = false;
    }
  });
}
