# The `afh` command

The agent in a terminal, over SSH, or in a script. Turn it on in **Settings → Developer → Command line**, then open a new terminal.

When the AFH app is open, `afh` uses it, so threads show up there live. When it isn't, `afh` starts a private backend for as long as the command runs. That backend leaves schedules and interrupted runs for the app.

## Chat

```bash
afh
```

Chats in the current folder. Ctrl+C stops a run. `/help` lists the commands.

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
| `afh install` | Put `afh` on your PATH |
