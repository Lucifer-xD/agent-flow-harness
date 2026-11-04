# Contributing

Thanks for helping make Agent Flow Harness better. Bug reports, ideas and pull requests are all welcome.

- **Found a bug?** [Open a bug report](https://github.com/Lucifer-xD/agent-flow-harness/issues/new?template=bug_report.yml). **Settings → Report a bug** makes a zip with the details, with every key, token and password removed.
- **Have an idea?** [Suggest a feature](https://github.com/Lucifer-xD/agent-flow-harness/issues/new?template=feature_request.yml). For anything large, please open an issue before you write the code.
- **Found a security problem?** Please don't open an issue. See [SECURITY.md](SECURITY.md).

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Set up

You need Windows, Python 3.12 and Node 20 or newer.

```powershell
git clone https://github.com/Lucifer-xD/agent-flow-harness.git
cd agent-flow-harness
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python run.py --browser        # backend + UI in the browser (the fastest loop)
```

For the Electron window, see [desktop/README-dev.md](desktop/README-dev.md). For the phone app, see [app/README.md](app/README.md).

Set `AFH_HOME` to a scratch folder while developing so your real `~/.afh` stays untouched:

```powershell
$env:AFH_HOME = "$env:TEMP\afh-dev"; .venv\Scripts\python run.py --browser
```

[docs/architecture.md](docs/architecture.md) explains how the pieces fit together.

## Tests

```powershell
.venv\Scripts\python -m pytest tests -q
```

The MCP tests start a real MCP server with `npx` and skip when `npx` is missing. No test prompts a model unless `AFH_LIVE_PROVIDER_JSON` is set. The same tests run on every push and pull request.

## Code style

- **Python:** plain functions, type hints, and short comments that say *why*. Never write outside `~/.afh` and the project folder. The OpenCode import is read-only.
- **JavaScript:** ES modules, no framework, no build step. Build DOM with the `el()` helper in `web/js/ui.js`. Animations go in `web/app.css` and must respect `.no-anim` and `prefers-reduced-motion`.
- **Settings:** changes apply to the next message. Only MCP changes return `{restarting: true}`, and the UI shows the reload pill.
- **Files:** LF line endings and a final newline. `.editorconfig` covers the rest.
- **Words in the UI:** short and plain, in the voice of the rest of the app. New strings need an Arabic entry in `web/js/i18n.js`.

## Pull requests

- Keep each PR to one topic, with a short description of what changed and how you tested it. A screenshot helps for UI changes.
- Run the tests. For UI work, open the thread view, the Settings tabs and the Context editor in the browser, and check that the console is clean.
- Never commit keys, tokens, or personal details such as your own paths or email address.
