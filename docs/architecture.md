# How AFH works

```
┌──────────────────────────────┐        HTTP + SSE         ┌───────────────────────────────┐
│  Electron window / browser   │ ◄───────────────────────► │  afh backend (FastAPI)        │
│  web/  (HTML, CSS, JS)       │   x-afh-token header      │  127.0.0.1:<random port>      │
└──────────────────────────────┘                           │  + optional 0.0.0.0:<port>    │
         phone / other PC  ────── password login ────────► │    for remote control         │
                                                           └──────────────┬────────────────┘
                                                                          │ opencode-python-sdk
                                                           ┌──────────────▼────────────────┐
                                                           │  opencode serve (child proc)  │
                                                           │  models · tools · MCP · skills│
                                                           └───────────────────────────────┘
```

## Processes

- **Electron** (`desktop/main.js`) starts the backend (`afh-backend.exe --headless` when installed, `python run.py --headless` in dev), reads the one line it prints (`AFH is running at http://127.0.0.1:<port>/#token=…`), opens that URL in a window and kills the backend tree on quit.
- **Backend** (`run.py` → `afh/api.py`) serves the UI and a JSON API. Every `/api/*` call needs the per-launch token (passed once in the URL hash, then kept in `sessionStorage`). It refuses other `Host` headers, so a web page can't reach it through DNS rebinding.
- **Engine** (`afh/engine.py`) owns the `opencode serve` child through `OpencodeServer`, fans its event stream out to connected UIs, and restarts it when configuration changes (agents, MCP, plugins, providers).

## Configuration layering

AFH never writes to `~/.config/opencode/opencode.json`. Instead `afh/store.py` keeps an **overlay** in `~/.afh/config.json` and passes it to the engine through `OPENCODE_CONFIG_CONTENT`. OpenCode merges it on top of the user's own config. The overlay holds:

- `agents.*` — system-prompt overrides, custom agents, the Delegate leader and every delegate (`mode: subagent`)
- `providers.*` — custom endpoints and `models.<id>.disabled` for hidden models
- `mcp.servers.*`, `plugins[]`
- `instructions[]` — always includes `~/.afh/personalization.md`, generated from the Personalization tab

## Delegate mode

Delegates are OpenCode **subagents**. Saving the Delegation tab writes one agent per delegate (its job as `description`, its model, optional read-only permissions) plus a leader agent `delegate` whose system prompt is OpenCode's harness prompt followed by the delegation rules and the list of delegates. The leader may only call the enabled delegates (`subagent` permission rules).

At runtime the leader calls the `subagent` tool; OpenCode creates a **child session** (`parentID` = the thread). `web/js/delegate.js` links each `subagent` tool call to its child session (from `session.created` events, or by title after a reload), keeps the child's messages in memory so the card can show live stats and pending approvals, and mounts a second `ChatView` on the child for the Watch pane.

## Context editing and undo

- **Undo** uses OpenCode's revert API: `revert.stage(messageId, files=True)` rewinds the conversation and restores files; the UI then offers *Keep* (`commit`) or *Put it back* (`clear`).
- **Context edit** exports the session, replaces the messages, deletes the session and re-imports it. Message ids are globally unique in OpenCode, so deleting first lets the import keep the same session id; if that fails the import retries with fresh ids and the UI switches to the new id.

## Session transfer

`afh/transfer.py` exports `{format: "afh-session", info, messages}` and imports AFH files, raw OpenCode exports, and Zadloop/DeepSeek Harness logs (`~/.dsh/sessions/**/session.v4.jsonl.zstd`, decoded and converted to OpenCode messages with tool calls paired to their results).

## Remote control

`afh/remote.py` starts a second uvicorn listener on `0.0.0.0:<port>` serving the same app. Requests arriving on that listener are only accepted with a token issued by `POST /api/remote/login` (PBKDF2-hashed password, rate-limited). An optional Cloudflare quick tunnel (`cloudflared tunnel --url …`) exposes it outside the network; its URL and a QR code are shown in Settings.
