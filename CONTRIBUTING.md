# Contributing

Thanks for helping make Agent Flow Harness better.

## Set up

```bash
git clone <this repo> && cd AFH
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
npm install -g @opencode/cli
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

Some tests start a real OpenCode server (they skip when `opencode` isn't on PATH). They never prompt a model.

## Code style

- Python: plain functions, type hints, short comments that say *why*. Keep the OpenCode overlay approach: never write the user's global `opencode.json`.
- JavaScript: ES modules, no framework, no build step. Build DOM with the `el()` helper in `web/js/ui.js`. Animations go in `web/app.css` and must respect `.no-anim` and `prefers-reduced-motion`.
- Every settings change that needs an engine restart returns `{restarting: true}` from the API; the UI shows the restart pill automatically.

## Pull requests

- One topic per PR, with a short description of what changed and how you tested it (a screenshot for UI changes helps).
- Run the tests. For UI work, open the thread view, Settings tabs and the Context editor once in the browser and check the console is clean.
