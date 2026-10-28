# How AFH works

```
┌──────────────────────────────┐        HTTP + SSE         ┌─────────────────────────────────────────┐
│  Electron window / browser   │ ◄───────────────────────► │  afh backend (FastAPI, one process)     │
│  web/  (HTML, CSS, JS)       │   x-afh-token header      │  127.0.0.1:<random port>                │
└──────────────────────────────┘                           │  + optional 0.0.0.0:<port> for remote   │
         phone / other PC  ────── password login ────────► │                                         │
                                                           │  AFH Engine (afh/engine/)               │
                                                           │   runner ─ tools ─ permissions ─ MCP    │
                                                           │   providers: OpenAI / Anthropic / Gemini│
                                                           │   sessions.db (SQLite)                  │
                                                           └─────────────────────────────────────────┘
```

## Processes

- **Electron** (`desktop/main.js`) starts the backend (`afh-backend.exe --headless` when installed, `python run.py --headless` in dev), reads the one line it prints (`AFH is running at http://127.0.0.1:<port>/#token=…`), opens that URL in a window and kills the backend tree on quit.
- **Backend** (`run.py` → `afh/api.py`) serves the UI and a JSON API. Every `/api/*` call needs the per-launch token (passed once in the URL hash, then kept in `sessionStorage`). It refuses other `Host` headers, so a web page can't reach it through DNS rebinding.
- **Engine** (`afh/engine/core.py`) runs in the same process on the server's event loop. There is no child engine process; MCP servers are the only subprocesses.

## The engine

- **Providers** (`afh/engine/providers/`). Three wire adapters, each an async generator of small events (`text.delta`, `reasoning.delta`, `tool.start`, `tool.delta`, `tool.end`, `usage`, `finish`, `error`): OpenAI-compatible chat completions (also Kimi, Z.AI, DeepSeek, Groq, OpenRouter, Ollama…), Anthropic Messages, and Gemini. `catalog.py` holds the one-click provider list, static model metadata and heuristics for unknown ids. Configured providers live in `~/.afh/providers.json` (`afh/engine/config.py`).
- **Runner** (`afh/engine/runner.py`). One `Run` per prompt: build the request from the stored messages, stream the model, translate provider events into the UI events the web app listens to (`session.text.delta`, `session.tool.input.delta`, …), store the assistant message as it grows, execute tool calls, loop until the model answers without tools. Retries 429/5xx with `session.retry.scheduled`; interrupt is an `asyncio.Event`.
- **Tools** (`afh/engine/tools/`). `read`, `write`, `edit`, `patch`, `glob`, `grep`, `list`, `shell`, `webfetch`, `websearch` (when a search key is set), plus the `skill` tool and every tool from connected MCP servers. Each tool computes its result first, then asks the permission gate, then records an undo snapshot, then writes.
- **Permissions** (`afh/engine/permissions.py`). A thread holds rules `{action, resource, effect}`; the last match wins. Modes are rule presets: *Full access*, *Ask first* (edits and commands ask), *Read only* (edits and commands denied). Asking publishes `permission.asked`, the UI answers `once` / `always` / `reject`; `always` appends an allow rule to that thread.
- **Prompt** (`afh/engine/prompt.py`). The harness prompt (editable in Settings → Prompts) + mode rules + `AGENTS.md` files (global, legacy OpenCode, project) + personalization + the skills catalog + MCP server instructions + an environment block. The Prompt drawer shows the exact assembled text.
- **Sessions** (`afh/engine/sessions.py`). SQLite in `~/.afh/afh.db`: sessions, messages (JSON, in order) and snapshots (a file's bytes before a tool changed it).

## Delegate mode

Delegates are agents defined in Settings → Delegation. The leader (`delegate` mode) gets the harness prompt plus delegation rules and the list of delegates, and a `subagent` tool. Calling it creates a **child session** (`parentID` = the thread) that runs the delegate's own model and system prompt with the same permission rules; the leader waits for it (or continues in the background and receives the report as a message). `web/js/delegate.js` links each `subagent` tool call to its child session, shows live stats and pending approvals in the card, and mounts a second `ChatView` on the child for the Watch pane.

## Context editing and undo

- **Undo** rewinds the thread to just before a message and restores every file touched after it from the snapshots. The removed messages and the current file contents are stashed, so *Put it back* (`revert/clear`) restores both; *Keep* (`revert/commit`) drops the stash.
- **Context edit** replaces the thread's messages in place; the session keeps its id.
- **Compaction** runs before a step when the last request used about 80% of the model's context: older messages are summarised into a `compaction` message and the last few are kept.

## Session transfer and migration

`afh/transfer.py` exports `{format: "afh-session", info, messages}` and imports AFH files, raw OpenCode exports, and Zadloop/DeepSeek Harness logs (`~/.dsh/sessions/**/session.v4.jsonl.zstd`, converted to AFH messages with tool calls paired to their results). `afh/engine/migrate.py` reads an OpenCode install read-only (its SQLite database and `opencode.json`) and copies API keys, custom endpoints, MCP servers and threads into AFH.

## Remote control

`afh/remote.py` starts a second uvicorn listener on `0.0.0.0:<port>` on the same event loop, serving the same app. Requests arriving on that listener are only accepted with a token issued by `POST /api/remote/login` (PBKDF2-hashed password, rate-limited). An optional Cloudflare quick tunnel (`cloudflared tunnel --url …`) exposes it outside the network; its URL and a QR code are shown in Settings.
