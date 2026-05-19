#!/usr/bin/env python3
"""
drop_server.py — HTTPS file drop endpoint, tunnelled via ngrok.
Files land in ~/Desktop/Nest and are picked up by nest_watcher.

Usage (AHS side):
  curl -X POST https://prelaunch-bonus-effective.ngrok-free.dev/drop \
       -H "Authorization: Bearer <DROP_TOKEN>" \
       -F "file=@myfile.pdf"

Env:
  DROP_TOKEN  — required; shared secret for upload auth
  DROP_PORT   — local port (default 8742)
  DROP_DEST   — destination directory (default ~/Desktop/Nest)
"""
import os
import sys
import logging
from pathlib import Path
from datetime import datetime, timezone

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

logging.basicConfig(level=logging.INFO, format="[drop] %(message)s")
log = logging.getLogger(__name__)

DROP_TOKEN = os.environ.get("DROP_TOKEN", "")
DROP_DEST  = Path(os.environ.get("DROP_DEST", Path.home() / "Desktop" / "Nest"))

if not DROP_TOKEN:
    log.error("DROP_TOKEN is not set — refusing to start")
    sys.exit(1)


def _safe_filename(name: str) -> str:
    """Strip path components and neutralise dangerous characters."""
    name = Path(name).name
    name = "".join(c for c in name if c.isalnum() or c in "._- ")
    return name or "upload"


def _unique(dest_dir: Path, filename: str) -> Path:
    dest = dest_dir / filename
    if not dest.exists():
        return dest
    stem, suffix = Path(filename).stem, Path(filename).suffix
    i = 1
    while dest.exists():
        dest = dest_dir / f"{stem}_{i}{suffix}"
        i += 1
    return dest


async def drop(request: Request) -> JSONResponse:
    # Auth
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != DROP_TOKEN:
        log.warning("rejected — bad token from %s", request.client)
        return JSONResponse({"error": "forbidden"}, status_code=403)

    # Parse upload
    form = await request.form()
    upload = form.get("file")
    if upload is None:
        return JSONResponse({"error": "missing 'file' field"}, status_code=400)

    filename = _safe_filename(upload.filename or "upload")
    DROP_DEST.mkdir(parents=True, exist_ok=True)
    dest = _unique(DROP_DEST, filename)

    contents = await upload.read()
    dest.write_bytes(contents)

    log.info("saved %s → %s (%d bytes)", filename, dest, len(contents))
    return JSONResponse({"status": "ok", "filename": dest.name, "bytes": len(contents)})


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


app = Starlette(routes=[
    Route("/drop", drop, methods=["POST"]),
    Route("/health", health, methods=["GET"]),
])


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("DROP_PORT", 8742))
    log.info("listening on port %d — dest=%s", port, DROP_DEST)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
