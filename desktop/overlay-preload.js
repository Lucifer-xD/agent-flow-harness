// Preload for the computer-use overlay windows: a small bridge to receive what to draw and to send
// back the user's clicks on the Stop pill, approval cards and lesson tooltips.
"use strict";

const { contextBridge, ipcRenderer } = require("electron");

const on = (channel) => (cb) => ipcRenderer.on(channel, (_e, d) => cb(d));

contextBridge.exposeInMainWorld("overlayApi", {
  onState: on("overlay:state"),
  onFx: on("overlay:fx"),
  onAsk: on("overlay:ask"),
  onAskDone: on("overlay:ask-done"),
  onTeach: on("overlay:teach"),
  onTeachDone: on("overlay:teach-done"),
  setInteractive: (v) => ipcRenderer.send("afh:overlay:interactive", !!v),
  stop: (lessonOnly) => ipcRenderer.send("afh:overlay:stop", { lessonOnly: !!lessonOnly }),
  answer: (id, decision) => ipcRenderer.send("afh:overlay:answer", { id: String(id), decision: String(decision) }),
  teach: (id, choice) => ipcRenderer.send("afh:overlay:teach", { id: String(id), choice: String(choice) }),
  openAfh: () => ipcRenderer.send("afh:overlay:open-afh"),
});
