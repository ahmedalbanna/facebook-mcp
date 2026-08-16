"""CLI entry point: ``python -m facebook_mcp`` / ``facebook-mcp``.

Transports: stdio (default) and streamable-http (like Meta's own server). HTTP
can require a static bearer token (--token or FB_MCP_TOKEN). --check-config prints
a secret-free configuration summary and exits. --enable-writes / --dry-run flip
the corresponding env flags for this run.
"""

from __future__ import annotations

import logging
import os
import sys

from facebook_mcp import config as _config
from facebook_mcp.app import build_app

_TRANSPORTS = ("stdio", "http", "streamable-http")


def _usage() -> str:
    return (
        "Usage: python -m facebook_mcp [options]\n"
        "\n"
        "  --transport {stdio,http,streamable-http}  transport (default: stdio)\n"
        "  --host HOST            bind address for HTTP (default: 127.0.0.1)\n"
        "  --port PORT            bind port for HTTP (default: 8020)\n"
        "  --path PATH            endpoint path (default: /mcp)\n"
        "  --token TOKEN          require a static bearer token on HTTP\n"
        "                         (or set FB_MCP_TOKEN)\n"
        "  --enable-writes        enable write tools (FB_ENABLE_WRITES=true)\n"
        "  --dry-run              writes return a preview instead of calling Meta\n"
        "  --debug                verbose logging to stderr\n"
        "  --check-config         print a secret-free config summary and exit\n"
        "\n"
        "Auth:  FB_ACCESS_TOKEN or FB_ACCESS_TOKEN_FILE (mode-600 file),\n"
        "       FB_APP_ID, FB_APP_SECRET or FB_APP_SECRET_FILE, FB_API_VERSION.\n"
        "Defaults: FB_PAGE_ID, FB_AD_ACCOUNT_ID, FB_IG_USER_ID.\n"
        "Guardrails: FB_ENABLE_WRITES, FB_DRY_RUN, FB_ADS_ALLOW_ACTIVATE,\n"
        "       FB_ADS_MAX_DAILY_BUDGET, FB_ADS_MAX_LIFETIME_BUDGET (minor units).\n"
    )


def _check_config(cfg: "_config.Config") -> int:
    """Print a configuration summary that never reveals secret values."""
    def yn(v: object) -> str:
        return "yes" if v else "no"

    print("facebook-mcp configuration:")
    print(f"  access token set      : {yn(cfg.access_token)}")
    print(f"  app id set            : {yn(cfg.app_id)}")
    print(f"  app secret set        : {yn(cfg.app_secret)}  (appsecret_proof: "
          f"{yn(cfg.appsecret_proof_enabled())})")
    print(f"  api version           : {cfg.api_version}")
    print(f"  default page id       : {cfg.page_id or '-'}")
    print(f"  default ad account    : {cfg.ad_account_id or '-'}")
    print(f"  default ig user id    : {cfg.ig_user_id or '-'}")
    print(f"  writes enabled        : {yn(cfg.enable_writes)}")
    print(f"  dry run               : {yn(cfg.dry_run)}")
    print(f"  ads allow activate    : {yn(cfg.ads_allow_activate)}")
    print(f"  ads max daily budget  : {cfg.ads_max_daily_budget or '-'} (minor units)")
    print(f"  ads max lifetime      : {cfg.ads_max_lifetime_budget or '-'} (minor units)")
    if not cfg.access_token:
        print("error: no access token configured (FB_ACCESS_TOKEN / FB_ACCESS_TOKEN_FILE)",
              file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "-h" in args or "--help" in args:
        print(_usage())
        return 0

    transport = "stdio"
    host = "127.0.0.1"
    port = 8020
    path = "/mcp"
    token = None
    check_config_mode = False

    rest = list(args)
    while rest:
        arg = rest.pop(0)
        if arg == "--enable-writes":
            os.environ["FB_ENABLE_WRITES"] = "true"
        elif arg == "--dry-run":
            os.environ["FB_DRY_RUN"] = "true"
        elif arg == "--debug":
            logging.basicConfig(level=logging.DEBUG)
        elif arg == "--check-config":
            check_config_mode = True
        elif arg in ("--transport", "--host", "--port", "--path", "--token"):
            if not rest:
                print(f"error: {arg} requires a value", file=sys.stderr)
                return 2
            value = rest.pop(0)
            if arg == "--transport":
                if value not in _TRANSPORTS:
                    print(f"error: unknown transport {value!r} "
                          f"(choose from {', '.join(_TRANSPORTS)})", file=sys.stderr)
                    return 2
                transport = value
            elif arg == "--host":
                host = value
            elif arg == "--port":
                try:
                    port = int(value)
                except ValueError:
                    print(f"error: invalid port {value!r}", file=sys.stderr)
                    return 2
            elif arg == "--path":
                path = value
            elif arg == "--token":
                token = value
        else:
            print(f"error: unknown argument {arg!r}", file=sys.stderr)
            return 2

    cfg = _config.reload()

    if check_config_mode:
        return _check_config(cfg)

    app = build_app(cfg)

    if transport == "stdio":
        app.run(transport="stdio")
        return 0

    # ---- HTTP (streamable-http) with optional bearer auth ----
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    token = token or os.environ.get("FB_MCP_TOKEN")
    _public_paths = ["/healthz"]

    class _AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.url.path in _public_paths or not token:
                return await call_next(request)
            auth = request.headers.get("authorization", "")
            bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            if bearer != token:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    middleware = [Middleware(_AuthMiddleware)] if token else []
    mcp_app = app.http_app(path=path, middleware=middleware, transport="streamable-http")

    async def _healthz(request: Request):
        return JSONResponse(
            {
                "status": "ok",
                "server": "facebook-mcp",
                "api_version": cfg.api_version,
                "writes_enabled": cfg.enable_writes,
            }
        )

    mcp_app.routes.append(Route("/healthz", _healthz))

    import uvicorn

    uvicorn.run(mcp_app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
