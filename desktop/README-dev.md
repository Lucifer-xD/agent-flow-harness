# AFH desktop shell (Electron)

The Electron app is a thin shell around the Python backend in the repo root. It starts
the backend, waits for its `AFH is running at http://127.0.0.1:<port>/#token=<token>` line,
opens that URL in a `BrowserWindow`, and exposes native dialogs to the page as `window.afh`
(see `preload.js`). On quit it kills the whole backend process tree (python + `opencode serve`).

```
desktop/
  main.js          Electron main process (backend lifecycle, window, tray, IPC)
  preload.js       window.afh bridge (contextBridge, sandboxed)
  package.json     scripts + electron-builder config
  assets/icon.png  window/tray icon (placeholder, generated)
  build/icon.ico   installer/exe icon (placeholder, generated)
  backend-dist/    output of scripts/build-backend.ps1 (ignored by git)
  dist/            output of electron-builder (ignored by git)
scripts/
  build-backend.ps1          PyInstaller build of run.py -> desktop/backend-dist/afh-backend/
  make-placeholder-icon.js   regenerates the placeholder icons
```

## Prerequisites

- Node 20+ (tested with 24) and npm
- The repo's Python venv at `.venv` with `requirements.txt` installed (run `AFH.bat` once,
  or `python -m venv .venv` + `.venv\Scripts\python -m pip install -r requirements.txt`)
- The `opencode` CLI on `PATH` (`npm install -g @opencode/cli`); the backend spawns `opencode serve`

## Run in development

```powershell
cd desktop
npm install          # first time only; downloads Electron (~100 MB)
npm run dev
```

npm 11+ has an install-scripts policy that can skip Electron's postinstall (the binary download).
If `node_modules\electron\dist\electron.exe` is missing after `npm install`, fetch it with
`node node_modules\electron\install.js` (or `npm install-scripts approve electron` and reinstall).

In dev mode (`app.isPackaged === false`) `main.js` spawns
`..\.venv\Scripts\python.exe ..\run.py --headless` with the repo root as cwd. The backend
picks a free port; never hard-code one. Logs from both Electron (`[afh] ...`) and the backend
(`[afh] [backend] ...`) go to the terminal; look for `backend URL parsed`, `ready-to-show`,
`did-finish-load` and `window.afh bridge: object`.

Environment variables pass straight through to the backend, so `AFH_HOME` works as usual:

```powershell
$env:AFH_HOME = "$env:TEMP\afh-dev"; npm run dev
```

Window size/position/maximized state is remembered in
`%APPDATA%\agent-flow-harness\window-state.json` (`app.getPath('userData')`).

## Build the backend (PyInstaller)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-backend.ps1
```

Output: `desktop\backend-dist\afh-backend\afh-backend.exe` plus `_internal\` (one-folder build,
console subsystem so stdout works). The script installs PyInstaller into `.venv` if needed,
bundles `web\` as `_internal\web` (which is where `afh.api.WEB_DIR` resolves inside the frozen
app, so no source change is needed), excludes pywebview/tkinter, and adds the uvicorn/anyio
hidden imports. Smoke test:

```powershell
$env:AFH_HOME = "$env:TEMP\afh-test"
.\desktop\backend-dist\afh-backend\afh-backend.exe --headless
# prints: AFH is running at http://127.0.0.1:<port>/#token=<token>
curl.exe -H "x-afh-token: <token>" http://127.0.0.1:<port>/api/bootstrap
```

Rebuild the backend whenever Python code or `web\` changes; the installer only picks up what is
in `backend-dist\afh-backend` at build time.

## Build the installer

```powershell
cd desktop
npm run dist:dir     # unpacked app in dist\win-unpacked\ (fast; good for testing)
npm run dist         # NSIS installer: dist\AFH-Setup-<version>.exe (~130 MB)
```

`build.extraResources` copies `backend-dist\afh-backend` to `resources\backend` inside the
app, and the packaged `main.js` runs `resources\backend\afh-backend.exe --headless`.
The installer is per-user, lets the user pick the directory, and creates desktop and
Start-menu shortcuts. Version comes from `package.json`.

electron-builder needs `build\icon.ico` to exist; regenerate the placeholder with
`npm run icon` (or `node scripts\make-placeholder-icon.js`) if you delete it. Replace both
`build\icon.ico` and `assets\icon.png` with the real artwork when available.

## The `window.afh` bridge

```ts
window.afh.pickFolder(): Promise<string | null>
window.afh.pickFiles(): Promise<string[]>
window.afh.openExternal(url: string): Promise<void>   // http/https only
window.afh.version: string
window.afh.platform: string                           // "win32" | "darwin" | "linux"
window.afh.window: { minimize(), maximize(), close(), isMaximized(): Promise<boolean> }
window.afh.onEvent(cb): () => void                    // e.g. { type: "maximized", value: boolean }
```

`target="_blank"` links and navigation away from the backend origin open in the default browser.

## Troubleshooting

- **"Backend did not start" dialog** - the backend printed no URL within 60 s. The dialog
  includes the last backend stderr lines; the same lines are in the terminal.
- **Second window never appears** - the app is single-instance; a second launch focuses the
  existing window.
- **Leftover processes** - quitting runs `taskkill /PID <backend> /T /F` on Windows (SIGINT then
  SIGTERM to the process group elsewhere). Check with
  `Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'run.py|afh-backend|opencode' }`.
