"""Runtime configuration for the Facebook MCP server.

All configuration comes from environment variables (12-factor). Secrets may be
supplied inline (FB_ACCESS_TOKEN) or, preferably, via a mode-600 file whose path
is given in FB_ACCESS_TOKEN_FILE / FB_APP_SECRET_FILE — the same
systemd-credentials-compatible pattern the erpnext gateway uses. Secrets are
never logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from facebook_mcp.errors import ConfigError

DEFAULT_API_VERSION = "v26.0"


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_env_file(path: str | os.PathLike | None = None) -> str | None:
    """Populate ``os.environ`` from a ``.env`` file, without clobbering real env.

    A dependency-free loader (the sibling gateway ships no python-dotenv). It is a
    no-op when the file is absent, and it NEVER overrides a variable already set in
    the environment, so docker-compose ``env_file:`` and shell exports still win.
    Values are never logged. Lines may use ``KEY=VALUE`` with an optional ``export``
    prefix and surrounding quotes; blank lines and ``#`` comments are ignored.

    Search order when ``path`` is omitted: ``FB_ENV_FILE`` if set, else ``.env`` in
    the current directory, else ``.env`` beside the project root. Returns the path
    that was loaded, or ``None``.
    """
    if path is not None:
        candidates = [Path(path)]
    elif os.environ.get("FB_ENV_FILE"):
        candidates = [Path(os.environ["FB_ENV_FILE"])]
    else:
        candidates = [Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]

    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"env file {str(candidate)!r} could not be read: {exc}") from exc
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = _strip_quotes(value.strip())
        return str(candidate)
    return None


def _file_secret(value: str | None, file_env: str) -> str | None:
    """Return a secret from an inline value, or read it from a file path in env.

    The file form wins when both are set, mirroring systemd-creds usage where
    the file is the source of truth. Never logs the value.
    """
    path = os.environ.get(file_env)
    if path:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read().strip() or None
        except OSError as exc:
            raise ConfigError(f"{file_env}={path!r} could not be read: {exc}") from exc
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _norm_act(value: str | None) -> str | None:
    """Normalise an ad-account id to the ``act_<n>`` form the API expects."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    return value if value.startswith("act_") else f"act_{value}"


@dataclass
class Config:
    """Effective server configuration. Build with :meth:`load`."""

    access_token: str | None = None
    app_id: str | None = None
    app_secret: str | None = None
    api_version: str = DEFAULT_API_VERSION

    # Default object ids so tools can be called without repeating them.
    page_id: str | None = None
    ad_account_id: str | None = None
    ig_user_id: str | None = None
    business_id: str | None = None

    # Write gating + ad-spend guardrails.
    enable_writes: bool = False
    dry_run: bool = False
    ads_allow_activate: bool = False
    ads_max_daily_budget: int = 0  # minor units (e.g. cents); 0 = unset
    ads_max_lifetime_budget: int = 0  # minor units; 0 = unset

    timeout: int = 30

    # Directory reports may be written to (FB_REPORT_DIR); empty disables file output.
    report_dir: str | None = None

    def require_token(self) -> str:
        if not self.access_token:
            raise ConfigError(
                "No access token configured. Set FB_ACCESS_TOKEN or FB_ACCESS_TOKEN_FILE."
            )
        return self.access_token

    def appsecret_proof_enabled(self) -> bool:
        return bool(self.access_token and self.app_secret)

    @classmethod
    def load(cls, env: dict | None = None) -> "Config":
        """Build a Config from the environment.

        When ``env`` is given, load from that mapping instead of the process
        environment (used by tests) without permanently mutating ``os.environ``.
        """
        if env is not None:
            saved = dict(os.environ)
            try:
                os.environ.clear()
                os.environ.update({k: str(v) for k, v in env.items()})
                return cls.load()
            finally:
                os.environ.clear()
                os.environ.update(saved)
        return cls(
            access_token=_file_secret(os.environ.get("FB_ACCESS_TOKEN"), "FB_ACCESS_TOKEN_FILE"),
            app_id=os.environ.get("FB_APP_ID") or None,
            app_secret=_file_secret(os.environ.get("FB_APP_SECRET"), "FB_APP_SECRET_FILE"),
            api_version=os.environ.get("FB_API_VERSION") or DEFAULT_API_VERSION,
            page_id=os.environ.get("FB_PAGE_ID") or None,
            ad_account_id=_norm_act(os.environ.get("FB_AD_ACCOUNT_ID")),
            ig_user_id=os.environ.get("FB_IG_USER_ID") or None,
            business_id=os.environ.get("FB_BUSINESS_ID") or None,
            enable_writes=_env_bool("FB_ENABLE_WRITES", False),
            dry_run=_env_bool("FB_DRY_RUN", False),
            ads_allow_activate=_env_bool("FB_ADS_ALLOW_ACTIVATE", False),
            ads_max_daily_budget=_env_int("FB_ADS_MAX_DAILY_BUDGET", 0),
            ads_max_lifetime_budget=_env_int("FB_ADS_MAX_LIFETIME_BUDGET", 0),
            timeout=_env_int("FB_TIMEOUT", 30),
            report_dir=os.environ.get("FB_REPORT_DIR") or None,
        )


# ---- module-level current config (set at app build; overridable in tests) ----
_config: Config | None = None


def set_config(cfg: Config) -> None:
    global _config
    _config = cfg


def current() -> Config:
    if _config is None:
        raise ConfigError("Config not initialised; call config.set_config(...) first.")
    return _config


def reload() -> Config:
    """Reload from the current environment and install as the active config."""
    cfg = Config.load()
    set_config(cfg)
    return cfg
