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
  <img alt="Engine" src="https://img.shields.io/badge/engine-OpenCode%20v2-ff6a2a" />
  <img alt="Models" src="https://img.shields.io/badge/models-100%2B%20providers-ff3d71" />
</p>

<p align="center">
  <img src="docs/screenshots/thread-delegation.png" width="880" alt="A thread where the lead model delegates to a second model" />
</p>

---

## What it does

| | |
|---|---|
| **Any model** | Sign in with the subscriptions you already have (ChatGPT, GitHub Copilot) or paste an API key for OpenAI, Anthropic, Google, OpenRouter, Groq, Mistral, DeepSeek, Kimi, Z.AI and 100+ more. Local models too (Ollama, LM Studio, vLLM). Hide the models you don't use so the picker stays short. |
| **Delegate mode** | One model leads: it plans, talks to you and reviews. It hands tasks to **delegates** — other models with jobs you describe ("writes code", "reviews diffs", "writes tests"). Every delegation shows live progress, needs-your-approval prompts, a **Watch** button that opens the delegate's thread beside yours, and its report. Switch modes any time, even mid-conversation. |
| **You stay in control** | *Ask first* mode shows every file change (with a diff) and every command before it runs. *Full access* and *Read only* are one click away. **Undo** rewinds the thread **and the files on disk** to before any message. |
| **See everything** | **Context** shows exactly what the model sees — your messages, its replies, tool inputs and outputs, system notices — and lets you edit or delete any of it. **Prompt** shows the real system prompt, including OpenCode's built-in one, which you can copy, change or replace. |
| **Extend it** | A **Skills store** (skills.sh) installs skills with one click. Add **MCP servers** (Chrome, Playwright, GitHub, filesystem…) and OpenCode **plugins** from Settings. |
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

1. **Install Node.js** (one-time, needed by the OpenCode engine): download the *LTS* version from [nodejs.org](https://nodejs.org) and run the installer with the default options.
2. **Download AFH**: open the [Releases](../../releases) page and download `AFH-Setup-1.0.0.exe`.
3. **Run the installer.** Windows may show a blue *"Windows protected your PC"* screen because the app isn't code-signed yet — click **More info → Run anyway**. Pick a folder, finish, and AFH opens.
4. **First launch**: if the OpenCode engine isn't on your PC yet, AFH shows an **Install OpenCode** button. Click it, wait about a minute, and you're in.
5. **Connect a model**: Settings → *Models & providers* → *Add a provider*. Choose **Sign in with ChatGPT** / **Login with GitHub Copilot** to use a subscription, or pick a provider and paste an API key. Then set your **Default model**.
6. **Open a folder** (the project you want to work on) and ask for something.

That's it. Your settings live in `C:\Users\<you>\.afh`; your API keys stay in OpenCode's own credential store on your PC.

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
| **Project menu** (sidebar) | Open folders, switch projects, **Import thread** (from a file, OpenCode or Zadloop). |

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
afh/        Python backend (FastAPI + SSE) on top of opencode-python-sdk
  engine.py   runs `opencode serve`, relays its event stream, restarts on config changes
  api.py      HTTP API the UI talks to (token-protected, loopback only)
  store.py    ~/.afh files: settings, the OpenCode config overlay, personalization, delegation
  transfer.py export/import, Zadloop conversion     skills_store.py  skills.sh client + installer
  builtin_prompts.py OpenCode's built-in prompts    remote.py        LAN listener + tunnel
web/        the UI: plain HTML/CSS/JS, no build step (js/main.js, chat.js, delegate.js, settings*.js)
desktop/    Electron shell (main.js, preload.js) + electron-builder config
scripts/    build-backend.ps1 (PyInstaller)
tests/      pytest (47 tests; some start a real OpenCode server)
```

```bash
# run from source
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
npm install -g @opencode/cli            # the engine
.venv\Scripts\python run.py --browser   # backend + UI in your browser
cd desktop && npm install && npm run dev   # or the Electron window

# build the installer
powershell -ExecutionPolicy Bypass -File scripts\build-backend.ps1   # PyInstaller → desktop/backend-dist
cd desktop && npm run dist                                           # → desktop/dist/AFH-Setup-<version>.exe
```

AFH never edits your global `opencode.json`. Its agents, prompts, delegates, MCP servers, plugins and custom providers live in `~/.afh/config.json`, which is layered on top of your OpenCode config when the engine starts (`OPENCODE_CONFIG_CONTENT`). See [docs/architecture.md](docs/architecture.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

- iOS and Android apps (the remote-control web UI works on phones today)
- Voice input
- Auto-update

## License

MIT. Built on [OpenCode](https://opencode.ai) and [opencode-python-sdk](https://github.com/shrijayan/opencode-python-sdk). Bundles marked (MIT), DOMPurify (Apache-2.0/MPL-2.0), highlight.js (BSD-3), Electron (MIT), FastAPI (MIT).
