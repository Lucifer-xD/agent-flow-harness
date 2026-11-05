#!/usr/bin/env bash
# Builds the AFH Python backend for macOS with PyInstaller (scripts/build-backend.ps1 is the Windows one):
#   desktop/backend-dist/afh-backend/afh-backend --headless
# electron-builder then copies that folder into the app as Contents/Resources/backend.
#
# Usage: bash scripts/build-backend.sh     (PYTHON=... picks the interpreter, default .venv/bin/python)
# NAME=afh DIST=cli-dist builds the standalone terminal app instead (same program, called afh).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
NAME="${NAME:-afh-backend}"
DIST="$ROOT/${DIST:-desktop/backend-dist}"
WORK="$ROOT/desktop/backend-build"

"$PY" -m pip show pyinstaller >/dev/null 2>&1 || "$PY" -m pip install --upgrade pyinstaller
rm -rf "$DIST/$NAME"

"$PY" -m PyInstaller --noconfirm --clean --onedir --console --name "$NAME" \
  --distpath "$DIST" --workpath "$WORK" --specpath "$WORK" --paths "$ROOT" \
  --add-data "$ROOT/web:web" \
  --add-data "$ROOT/afh/engine/data:afh/engine/data" \
  --collect-submodules afh \
  --collect-all textual \
  --collect-submodules mcp.client \
  --collect-submodules mcp.shared \
  --collect-submodules mcp_types \
  --collect-submodules httpx2 \
  --collect-submodules httpx \
  --collect-submodules websockets \
  --copy-metadata mcp \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.loops.asyncio \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.http.h11_impl \
  --hidden-import uvicorn.protocols.http.httptools_impl \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.protocols.websockets.websockets_impl \
  --hidden-import uvicorn.protocols.websockets.websockets_sansio_impl \
  --hidden-import uvicorn.protocols.websockets.wsproto_impl \
  --hidden-import uvicorn.lifespan.on \
  --hidden-import uvicorn.lifespan.off \
  --hidden-import anyio._backends._asyncio \
  --hidden-import fastapi \
  --hidden-import pydantic \
  --hidden-import zstandard \
  --hidden-import qrcode \
  --exclude-module webview \
  --exclude-module tkinter \
  --exclude-module _tkinter \
  "$ROOT/run.py"

test -x "$DIST/$NAME/$NAME"
test -f "$DIST/$NAME/_internal/web/index.html"
echo "Built: $DIST/$NAME/$NAME ($(du -sh "$DIST/$NAME" | cut -f1))"
