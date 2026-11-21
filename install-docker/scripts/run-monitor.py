#!/usr/bin/env python3
"""ADN Monitor launcher: FastAPI API/WS + built SPA on / (Docker unified stack).

Routing mirrors bare-metal nginx (templates/nginx/snippets/http-app.conf.in):
  /api/*  -> FastAPI REST (create_app routers)
  /ws     -> FastAPI WebSocket (upgrade)
  /*      -> frontend/dist static SPA (try_files + index.html fallback)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

MON_ROOT = Path(os.environ.get("ADN_MONITOR_PATH", "/opt/adn-monitor"))
MONITOR_DIR = MON_ROOT / "monitor"
DIST_DIR = MON_ROOT / "frontend" / "dist"

for path in (MONITOR_DIR, MONITOR_DIR / "src"):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)

from adn_monitor.domain import is_fail  # noqa: E402
from adn_monitor.infrastructure import create_logger, load_config  # noqa: E402
from adn_monitor.infrastructure.env_loader import load_project_env  # noqa: E402
from adn_monitor.infrastructure.fastapi import create_app  # noqa: E402

load_project_env(MONITOR_DIR)

# Never serve these as static files (nginx: location /api and /ws proxy_pass).
_RESERVED_PREFIXES = ("api", "ws")


def _default_config_path() -> str:
    env = os.environ.get("ADN_CONFIG_PATH", "").strip()
    if env and Path(env).is_file():
        return env
    return str(MONITOR_DIR / "adn-monitor.yaml")


def _listen_settings(config: dict, args: argparse.Namespace) -> tuple[str, int]:
    app_conf = config.get("APP") or config.get("MONITOR_APP") or {}
    host = args.host if args.host is not None else app_conf.get("LISTEN_HOST", "")
    if args.port is not None:
        port = args.port
    elif os.environ.get("MONITOR_APP_PORT"):
        port = int(os.environ["MONITOR_APP_PORT"])
    else:
        port = int(app_conf.get("LISTEN_PORT", 8080))
    return host or "0.0.0.0", port


def _reserved_static_path(path: str) -> bool:
    if not path:
        return False
    head = path.split("/", 1)[0]
    return head in _RESERVED_PREFIXES


def _mount_spa(app, dist: Path) -> None:
    """Static SPA after API/WS routers — same split as nginx http-app.conf.in."""
    if not dist.is_dir() or not (dist / "index.html").is_file():
        print(f"  monitor: WARN frontend dist missing at {dist}", file=sys.stderr)
        return

    from fastapi import HTTPException
    from fastapi.staticfiles import StaticFiles
    from starlette.responses import FileResponse

    for name in ("assets", "img"):
        sub = dist / name
        if sub.is_dir():
            app.mount(f"/{name}", StaticFiles(directory=str(sub)), name=f"static-{name}")

    favicon = dist / "favicon.ico"
    if favicon.is_file():

        @app.get("/favicon.ico", include_in_schema=False)
        @app.head("/favicon.ico", include_in_schema=False)
        async def _favicon() -> FileResponse:
            return FileResponse(favicon)

    async def _spa_response(full_path: str) -> FileResponse:
        if _reserved_static_path(full_path):
            raise HTTPException(status_code=404)
        target = dist / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(dist / "index.html")

    @app.get("/", include_in_schema=False)
    @app.head("/", include_in_schema=False)
    async def _spa_root() -> FileResponse:
        return FileResponse(dist / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    @app.head("/{full_path:path}", include_in_schema=False)
    async def _spa(full_path: str) -> FileResponse:
        return await _spa_response(full_path)

    print(
        f"  monitor: routes /api/* + /ws + SPA static (dist={dist})",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="ADN Monitor (FastAPI + SPA)")
    parser.add_argument("-c", "--config", default=_default_config_path(), help="adn-monitor.yaml path")
    parser.add_argument("--host", default=None, help="Override listen host")
    parser.add_argument("--port", type=int, default=None, help="Override listen port")
    args = parser.parse_args()

    result = load_config(args.config)
    if is_fail(result):
        print(f"Config error: {result.error}", file=sys.stderr)
        sys.exit(1)
    config = result.value

    log_conf = config.get("LOG", {})
    create_logger(log_conf)

    bind, port = _listen_settings(config, args)
    app = create_app(config)
    _mount_spa(app, DIST_DIR)

    import uvicorn

    uvicorn.run(
        app,
        host=bind,
        port=port,
        log_level=str(log_conf.get("LOG_LEVEL", "info")).lower(),
    )


if __name__ == "__main__":
    main()
