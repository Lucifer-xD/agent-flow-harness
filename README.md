<p align="center">
  <img src="web/brand/logo-480.png" width="220" alt="Agent Flow Harness" />
</p>

<h1 align="center">Agent Flow Harness</h1>

<p align="center">
  <b>An open-source desktop coding agent that works with any AI model — and lets models work together.</b><br/>
  Pick a model, point it at a folder, and it reads, edits and runs code there with your approval.<br/>
  Let one model lead and delegate to others. Control it from your phone. Everything runs on your own computer.
</p>

<p align="center">
  <img alt="Windows" src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white" />
  <img alt="License" src="https://img.shields.io/badge/license-MIT-f59f00" />
  <img alt="Engine" src="https://img.shields.io/badge/engine-AFH%20Engine%20(own)-ff6a2a" />
  <img alt="Models" src="https://img.shields.io/badge/models-any%20OpenAI%2FAnthropic%2FGemini%20API-ff3d71" />
</p>

<p align="center">
  <img src="docs/screenshots/thread-delegation.png" width="880" alt="A thread where the lead model delegates to a second model" />
</p>

---

## What it does

| | |
|---|---|
| **Any model** | Paste an API key for OpenAI, Anthropic, Gemini, Kimi, Z.AI, DeepSeek, Groq, OpenRouter, Mistral, xAI, Together, Fireworks, Cerebras or Perplexity, or point AFH at any OpenAI-, Anthropic- or Gemini-compatible endpoint. Local models too (Ollama, LM Studio, vLLM) with no key. Hide the models you don't use so the picker stays short. |
| **Delegate mode** | One model leads: it plans, talks to you and reviews. It hands tasks to **delegates** — other models with jobs you describe ("writes code", "reviews diffs", "writes tests"). Every delegation shows live progress, needs-your-approval prompts, a **Watch** button that opens the delegate's thread beside yours, and its report. Switch modes any time, even mid-conversation. |
| **You stay in control** | *Ask first* mode shows every file change (with a diff) and every command before it runs. *Full access* and *Read only* are one click away. **Undo** rewinds the thread **and the files on disk** to before any message. |
| **See everything** | **Context** shows exactly what the model sees — your messages, its replies, tool inputs and outputs, system notices — and lets you edit or delete any of it. **Prompt** shows the exact system prompt the model receives, which you can copy, change or replace. |
| **Extend it** | A **Skills store** (skills.sh) installs skills with one click. Add **MCP servers** (Chrome, Playwright, GitHub, filesystem…) from Settings. |
| **Your own engine** | No third-party harness underneath: the agent loop, tools (read, write, edit, patch, glob, grep, list, shell, webfetch, websearch), permissions, undo snapshots, delegation, compaction and MCP client are all in this repo, in plain Python. Tool calls stream live, so you watch files being written line by line. |
| **Take it anywhere** | **Remote control**: open the same app on your phone or another computer over Wi-Fi (password-protected), optionally from outside your network through a free Cloudflare tunnel. **Export** any thread as a file and **import** it on another PC; import your old **Zadloop / DeepSeek Harness** sessions. |
| **Feels good** | Smooth streaming, eased scrolling, a logo that flows while a model is thinking, dark and light themes, your accent color. |

<p align="center">
  <img src="docs/screenshots/settings-delegation.png" width="430" alt="Delegation settings" />
  <img src="docs/screenshots/settings-models.png" width="430" alt="Models and providers" />
</p>
<p align="center">
  <img src="docs/screenshots/settings-skills.png" width="430" alt="Skills store" />
  <img src="docs/screenshots/context-editor.png" width="430" alt="Context editor" />
</p>

## Install (no programming needed)

1. **Download AFH**: open the [Releases](../../releases) page and download `AFH-Setup-1.3.0.exe`.
2. **Run the installer.** Windows may show a blue *"Windows protected your PC"* screen because the app isn't code-signed yet — click **More info → Run anyway**. Pick a folder, finish, and AFH opens.
3. **Connect a model**: on first launch AFH opens *Models & providers*. Pick a provider and paste its API key (local servers like Ollama need none). If you used OpenCode before, one click imports its keys, MCP servers and threads. Then set your **Default model**.
4. **Open a folder** (the project you want to work on) and ask for something.

That's it. Nothing else to install. Your settings, keys and threads live in `C:\Users\<you>\.afh` and never leave your PC except to the model providers you chose.

### Using it from your phone

Settings → **Remote control** → set a password → turn it on. Scan the QR code (or type the address) on a phone connected to the same Wi-Fi. For access from anywhere, turn on the Cloudflare tunnel (requires [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/) installed on the PC). Windows Firewall will ask once to allow Python on private networks — allow it.

## Everyday use

| Where | What |
|---|---|
| **Mode pill** (bottom of the composer) | *Build* does the work itself. *Plan* only plans. *Delegate* leads and delegates to your delegates. Custom agents you create appear here too. |
| **Approval pill** | *Ask first* / *Full access* / *Read only*. Per thread, changeable any time. |
| **Model pill** | Model and effort level for this thread. |
| **Context** (top right) | See and edit everything the model sees. |
| **Prompt** | The exact system prompt, instructions, skills and permissions in effect. |
| **Changes** | Every file the thread changed, with diffs. |
| **⋯ menu** | Rename, fork, edit context, export, copy as Markdown, archive, delete. |
| **Hover a message of yours** | **Undo to here** — rewinds the thread and your files. |
| **Project menu** (sidebar) | Open folders, switch projects, **Import thread** (from an export file, OpenCode or Zadloop). |

Keyboard: `Enter` send · `Shift+Enter` new line · `Esc` stop · `Ctrl+N` new thread · `Ctrl+K` search · `Ctrl+B` sidebar · `Ctrl+,` settings.

## Setting up Delegate mode

1. Settings → **Delegation** → *Add delegate*.
2. Give it a name, pick its **model** (and effort), and write its **job** — this is what the leader reads to decide when to use it. Example: *"Writes and edits code. Send it implementation tasks, bug fixes and tests. Good at Python and TypeScript."*
3. Optionally make it **read-only** (good for reviewers) or give it extra system-prompt instructions.
4. Add **leader instructions** if you want house rules ("always have the Reviewer check the Coder's work").
5. Save. In any thread, pick **Delegate** in the mode pill.

The leader can continue a delegate's existing session or start a fresh one, and can run delegates in the background. If a delegate needs your approval (Ask first mode), the request appears inside the delegation card.

## For developers

```
afh/            Python backend (FastAPI + SSE), token-protected, loopback only
  api.py          the HTTP API the UI talks to
  store.py        ~/.afh files: settings, prompts, personalization, delegation, agents, MCP servers
  transfer.py     export/import, Zadloop conversion     skills_store.py  skills.sh client + installer
  remote.py       LAN listener + Cloudflare tunnel
afh/engine/     the AFH Engine
  core.py         Engine facade: providers, sessions, runs, undo, compaction, titles, delegation (subagent tool)
  runner.py       the agent loop: stream the model → emit UI events → run tools → repeat
  providers/      OpenAI-compatible, Anthropic and Gemini adapters (streaming, tool-call deltas) + catalog
  tools/          read, write, edit, patch, glob, grep, list, shell, webfetch, websearch
  permissions.py  Ask first / Full access / Read only rules and the approval gate
  sessions.py     SQLite store (threads, messages, undo snapshots)
  prompt.py       system prompt assembly       agents.py   modes, custom agents, delegates
  mcp.py          MCP client (stdio + HTTP)    skills.py   SKILL.md discovery and the skill tool
  migrate.py      one-click import of an OpenCode install (keys, endpoints, MCP servers, threads)
web/            the UI: plain HTML/CSS/JS, no build step (js/main.js, chat.js, delegate.js, settings*.js)
desktop/        Electron shell (main.js, preload.js) + electron-builder config
scripts/        build-backend.ps1 (PyInstaller)
tests/          pytest (about 190 tests: providers, tools, MCP, skills, transfer, skills store)
```

```bash
# run from source
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py --browser   # backend + UI in your browser
cd desktop && npm install && npm run dev   # or the Electron window

# build the installer
powershell -ExecutionPolicy Bypass -File scripts\build-backend.ps1   # PyInstaller → desktop/backend-dist
cd desktop && npm run dist                                           # → desktop/dist/AFH-Setup-<version>.exe
```

Everything AFH knows lives under `~/.afh`: `settings.json`, `providers.json` (keys), `afh.db` (threads, messages, undo snapshots), `skills/`, `AGENTS.md`, `personalization.md`. See [docs/architecture.md](docs/architecture.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

- iOS and Android apps (the remote-control web UI works on phones today)
- Voice input
- Auto-update

## License

MIT. Bundles marked (MIT), DOMPurify (Apache-2.0/MPL-2.0), highlight.js (BSD-3), Electron (MIT), FastAPI (MIT), httpx (BSD-3), the MCP Python SDK (MIT).
