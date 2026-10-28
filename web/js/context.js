// Context viewer/editor: everything the model sees, editable. Saving rewrites the thread's
// history through export → import, so the chat shows the new version immediately.

import { api } from "./api.js";
import { confirmDialog, el, ico, icon, modal, toast } from "./ui.js";

const TYPES = { user: "You", assistant: "Model", system: "System notice", idle: "Run ended", compaction: "Compaction", shell: "Shell", synthetic: "Injected", skill: "Skill" };

export async function openContextEditor(ctx, thread, { onSaved }) {
  const body = el("div.m-body");
  const m = modal([el("div.ctx-side"), body]);
  m.box.classList.add("ctx-modal");
  body.append(el("button.icon-btn.m-close", { title: "Close", html: icon("x"), on: { click: () => m.close() } }));
  let messages;
  try {
    messages = await api.get(`/api/sessions/${thread.id}/context`);
  } catch (e) {
    body.append(el("div.error-card", ico("alert"), el("div", e.message)));
    return;
  }
  const work = messages.map((msg) => ({ msg: JSON.parse(JSON.stringify(msg)), deleted: false }));
  let dirty = false;
  const saveBtn = el("button.btn.primary", { disabled: true });
  const markDirty = () => { dirty = true; saveBtn.disabled = false; count(); };
  const counter = el("span.h-muted", { style: { fontStyle: "normal" } });
  const count = () => { const live = work.filter((w) => !w.deleted).length; counter.textContent = `${live} of ${work.length} messages · ~${Math.round(JSON.stringify(work.filter((w) => !w.deleted).map((w) => w.msg)).length / 4 / 1000)}k tokens (rough)`; };
  count();

  const side = m.box.querySelector(".ctx-side");
  side.append(el("h3", "Context"), el("p.lead", { style: { fontSize: "12.5px" } }, "Everything in this thread, in the order the model sees it. Edit any text — your requests, the model's replies, tool inputs and outputs — or delete messages, then Save."),
    el("div.note", el("b", "Saving rewrites history. "), "Files on disk are not touched. The thread keeps its id when possible."),
    counter);

  const list = el("div.ctx-list");
  body.append(el("h2", thread.session.title || "Thread context"), list, el("div.actions", { style: { marginTop: "16px", position: "sticky", bottom: 0, background: "var(--bg)", padding: "10px 0" } }, el("span", { style: { flex: 1 } }), el("button.btn.ghost", { on: { click: () => m.close() } }, "Cancel"), saveBtn));

  const ta = (get, set, cls = "") => {
    const t = el(`textarea.ta.ctx-ta${cls}`, { value: get() ?? "", on: { input: (e) => { set(e.target.value); markDirty(); autosize(e.target); } } });
    requestAnimationFrame(() => autosize(t));
    return t;
  };
  const autosize = (t) => { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight + 2, 420) + "px"; };

  work.forEach((w, i) => {
    const msg = w.msg;
    const block = el(`div.ctx-msg.${msg.type}`);
    const head = el("div.ctx-head", el("span.ctx-type", TYPES[msg.type] || msg.type), msg.model ? el("span.pill-tag", `${msg.model.providerID}/${msg.model.id}`) : null, msg.agent ? el("span.pill-tag", msg.agent) : null,
      msg.time?.created ? el("span.h-muted", { style: { fontStyle: "normal", fontSize: "11.5px" } }, new Date(msg.time.created).toLocaleTimeString()) : null,
      el("span", { style: { flex: 1 } }),
      el("button.btn.ghost.sm", { title: "Delete this message", on: { click: () => { w.deleted = !w.deleted; block.classList.toggle("deleted", w.deleted); markDirty(); } } }, ico("trash")));
    block.append(head);
    if (msg.type === "user") block.append(ta(() => msg.text, (v) => (msg.text = v)));
    else if (msg.type === "assistant") {
      (msg.content || []).forEach((p, j) => {
        if (p.type === "text") block.append(el("div.ctx-part", el("div.tool-section-label", "reply"), ta(() => p.text, (v) => (p.text = v))));
        else if (p.type === "reasoning") block.append(el("details.ctx-part", el("summary", "thinking"), ta(() => p.text, (v) => (p.text = v), ".dim")));
        else if (p.type === "tool") {
          const st = p.state || {};
          const out = (st.content || []).filter((c) => c.type === "text");
          block.append(el("div.ctx-part.tool",
            el("div.tool-section-label", `tool · ${p.name} · ${st.status || ""}`),
            el("div.ctx-sub", "input (JSON)"), ta(() => JSON.stringify(st.input ?? {}, null, 2), (v) => { try { st.input = JSON.parse(v); block.classList.remove("bad-json"); } catch { block.classList.add("bad-json"); } }, ".mono"),
            out.length ? [el("div.ctx-sub", "output"), ta(() => out.map((c) => c.text).join("\n"), (v) => { st.content = [{ type: "text", text: v }]; }, ".mono")] : null,
            st.error ? el("div.ctx-sub", { style: { color: "var(--bad)" } }, `error: ${st.error.message || ""}`) : null));
        }
      });
    } else if (msg.type === "system" || msg.type === "synthetic") block.append(ta(() => msg.text, (v) => (msg.text = v), ".dim"));
    else block.append(el("div.ctx-sub", JSON.stringify({ ...msg, id: undefined, type: undefined, time: undefined }).slice(0, 200)));
    list.append(block);
  });

  saveBtn.textContent = "Save & apply";
  saveBtn.addEventListener("click", async () => {
    const kept = work.filter((w) => !w.deleted).map((w) => w.msg);
    if (!kept.some((x) => x.type === "user")) return toast("Keep at least one of your messages", "err");
    if (body.querySelector(".bad-json")) return toast("A tool input isn't valid JSON", "err");
    if (!(await confirmDialog({ title: "Rewrite this thread's history?", body: "The model will see the edited version from the next message on. This can't be undone.", confirm: "Save & apply" }))) return;
    saveBtn.disabled = true;
    try {
      const session = await api.put(`/api/sessions/${thread.id}/messages`, { messages: kept, directory: ctx.project() });
      toast("Context updated", "ok");
      m.close();
      onSaved?.(session);
    } catch (e) {
      toast(e.message, "err", 7000);
      saveBtn.disabled = false;
    }
  });
}
