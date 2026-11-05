# AFH in your terminal

All of AFH, full screen in any terminal, over SSH, or in a script. You don't need the desktop app.

## Install

Windows, in PowerShell:

```powershell
irm https://agentflowharness.com/install.ps1 | iex
```

Windows, in Command Prompt:

```bat
curl -fsSL https://agentflowharness.com/install.cmd -o install.cmd && .\install.cmd && del install.cmd
```

macOS and Linux:

```bash
curl -fsSL https://agentflowharness.com/install.sh | bash
```

This downloads the newest release from GitHub, checks its SHA-256, unpacks it to `.afh/cli` in your home folder and puts `afh` on your PATH. It doesn't need admin rights. On Linux it needs 64-bit x86 and glibc 2.35 or newer (Ubuntu 22.04 and later).

If you already have the desktop app, **Settings → Developer → Command line → Install** gives you the same `afh`.

`afh update` installs the newest version; the old one is removed once nothing runs from it. `afh uninstall` removes the program and keeps your threads, settings and keys.

## The app

```bash
afh
```

Opens AFH full screen in the current folder. `afh --continue` picks up the latest thread here.

It's the same AFH as the desktop app. Threads, settings, providers and keys are shared. If the desktop app is open, `afh` connects to it, so a thread shows up in both live. If it isn't, each terminal window starts its own engine, and one of them takes care of schedules and interrupted runs.

| Key | What it does |
| --- | --- |
| Enter | Send |
| Ctrl+J | New line |
| Esc | Stop the run. Twice, from an empty box: undo |
| Tab | Next agent: Build, Plan, Delegate, Red Team, yours |
| Shift+Tab | Approvals: ask first, full access, read only |
| Ctrl+P | Command palette: actions, threads, models, themes |
| Ctrl+K | Threads |
| Ctrl+N | New thread |
| F1 or `?` | Help |
| F2 | Settings |
| F3 | Threads rail |
| Ctrl+O | Open or close tool details |
| Ctrl+T | Show or hide the to-do list |
| Ctrl+B | Live panel |
| Ctrl+R | Search what you've sent |
| Ctrl+G | Write in your editor |
| Ctrl+Y | Copy the last answer |
| Alt+V | Paste an image |
| Ctrl+C | Clear the box. Twice: quit |

Type `/` for commands, including your own, `@` to attach a file, and `!` to run a shell command and show the agent the output.

The AFH mark at the message box flows while a model works, like the app's. On a wide terminal your threads sit in a rail on the left. The words along the top and the chips under the message box open what they name, with a click or a command. The live panel opens by itself during a run when there's room for it, and closes after. **Settings → Appearance** has the logo animation and its speed.

Things a terminal can't draw open outside it: images in your viewer, design previews in your browser. The mic stays in the desktop and phone apps.

`afh --plain`, a pipe or a very basic terminal gives a simple line chat instead of the full-screen app. Ctrl+C stops a run there, and `/help` lists its commands.

## One task

```bash
afh run "fix the failing tests"
```

The answer goes to stdout and progress to stderr, so you can pipe it. Text piped in joins the prompt:

```bash
git diff | afh run "review this" -q > review.md
```

| Flag | What it does |
| --- | --- |
| `-m provider/model` | Which model |
| `-d folder` | Project folder (default: here) |
| `--mode ask\|full\|read` | Approvals. With no one at the terminal, `ask` refuses what needs approval instead of waiting |
| `--agent name` | `build`, `plan`, `delegate`, `redteam` or your own |
| `-c` / `-t id` | Continue the latest thread here, or a given one |
| `--goal` | Keep working until the goal is met or blocked |
| `--worktree [name]` | Work in a new git worktree |
| `--json` | Every event as a JSON line, ending with a `result` line |
| `-q` | Print only the final answer |
| `--timeout seconds` | Stop after this long |

Exit codes: `0` finished, `1` failed, `2` bad usage or no model, `3` timed out, `130` stopped.

## Race models against each other

```bash
afh race "add caching to the API" -m openai/gpt-5 -m anthropic/claude-opus-5-5 --check "pytest -q"
```

Each model gets the same task in its own git worktree. The `--check` command scores each result, and you pick which one to merge. Nothing is merged until you do.

```bash
afh race show <id>
afh race pick <id> <number>
afh race discard <id>
```

The models run with Full access unless you pass `--mode`. A worktree holds only what's committed, so a check may need to install things first, like `npm ci && npm test`.

## GitHub agent

Write `/afh` and what to do at the start of a line in a comment on an issue or pull request. AFH does the work on your computer, then opens a draft pull request or pushes to the pull request. It needs the [GitHub CLI](https://cli.github.com) signed in, a local clone, and the app or `afh serve` running.

```bash
afh github add owner/repo --path ~/code/repo
afh github allow your-login a-teammate
afh github mode ask
afh github
```

Also in **Settings → GitHub**.

A comment can end up running code on your computer, so:

- Only logins you allow can start work. By default that's just you.
- The words after `/afh` are the instruction. The issue's own text reaches the model as untrusted content.
- Pull requests from forks are refused.
- It pushes only an `afh/...` branch or the pull request's own branch. It never force-pushes and never merges.
- In the default `ask` mode, edits and commands wait for your approval in the app or on your phone. `full` runs without asking, so an issue's text could steer it. Use it only on repositories you trust.

## Everything else

| Command | What it does |
| --- | --- |
| `afh threads [--all]` | List threads |
| `afh show <id>` | Print a thread |
| `afh diff [id]` | Files a thread changed |
| `afh models` | List models |
| `afh provider add <name>` | Add a provider. The key is read from a hidden prompt or `AFH_PROVIDER_KEY` |
| `afh status` | What `afh` is connected to |
| `afh serve` | Run the backend in this terminal, for SSH or a server |
| `afh install` | Put `afh` on your PATH, from the desktop app or a source checkout |
| `afh update` | Install the newest version |
| `afh uninstall` | Remove the terminal app; your threads, settings and keys stay |
