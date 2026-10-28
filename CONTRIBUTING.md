# Contributing

Thanks for helping make Agent Flow Harness better.

## Set up

```bash
git clone <this repo> && cd AFH
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py --browser        # backend + UI in the browser (fastest loop)
cd desktop && npm install && npm run dev     # the Electron window
```

Set `AFH_HOME` to a scratch folder while developing so your real `~/.afh` stays untouched:

```powershell
$env:AFH_HOME = "$env:TEMP\afh-dev"; .venv\Scripts\python run.py --browser
```

## Tests

```bash
.venv\Scripts\python -m pytest tests -q
```

The MCP tests start a real MCP server with `npx` (they skip when `npx` is missing). No test prompts a model unless `AFH_LIVE_PROVIDER_JSON` is set.

## Code style

- Python: plain functions, type hints, short comments that say *why*. Never write outside `~/.afh` and the project folder; the OpenCode import is read-only.
- JavaScript: ES modules, no framework, no build step. Build DOM with the `el()` helper in `web/js/ui.js`. Animations go in `web/app.css` and must respect `.no-anim` and `prefers-reduced-motion`.
- Settings changes apply to the next message; only MCP changes return `{restarting: true}` (the UI shows the reload pill).

## Pull requests

- One topic per PR, with a short description of what changed and how you tested it (a screenshot for UI changes helps).
- Run the tests. For UI work, open the thread view, Settings tabs and the Context editor once in the browser and check the console is clean.
