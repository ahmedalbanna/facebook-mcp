"""Config loading: env parsing, ad-account normalisation, secret files."""

from __future__ import annotations

import os

import pytest

from facebook_mcp import config
from facebook_mcp.errors import ConfigError


def test_load_from_env_normalises_and_parses():
    cfg = config.Config.load(
        {
            "FB_ACCESS_TOKEN": "tok",
            "FB_APP_ID": "1",
            "FB_APP_SECRET": "s",
            "FB_AD_ACCOUNT_ID": "12345",
            "FB_ENABLE_WRITES": "true",
            "FB_ADS_MAX_DAILY_BUDGET": "1000",
        }
    )
    assert cfg.access_token == "tok"
    assert cfg.ad_account_id == "act_12345"
    assert cfg.enable_writes is True
    assert cfg.ads_max_daily_budget == 1000
    assert cfg.appsecret_proof_enabled() is True


def test_ad_account_keeps_existing_act_prefix():
    cfg = config.Config.load({"FB_AD_ACCOUNT_ID": "act_99"})
    assert cfg.ad_account_id == "act_99"


def test_file_secret_wins_over_inline(tmp_path):
    path = tmp_path / "tok"
    path.write_text("filetok\n")
    cfg = config.Config.load(
        {"FB_ACCESS_TOKEN": "inline", "FB_ACCESS_TOKEN_FILE": str(path)}
    )
    assert cfg.access_token == "filetok"


def test_require_token_raises_when_missing():
    cfg = config.Config.load({})
    with pytest.raises(ConfigError):
        cfg.require_token()


def test_bad_int_raises():
    with pytest.raises(ConfigError):
        config.Config.load({"FB_ADS_MAX_DAILY_BUDGET": "abc"})


def test_defaults_are_safe():
    cfg = config.Config.load({"FB_ACCESS_TOKEN": "t"})
    assert cfg.enable_writes is False
    assert cfg.ads_allow_activate is False
    assert cfg.api_version == "v26.0"


def test_load_env_file_populates_without_override(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# a comment\n"
        "\n"
        "export FB_ZZ_TOKEN=fromfile\n"
        'FB_ZZ_QUOTED="quoted value"\n'
        "FB_ZZ_EXISTING=fromfile\n"
        "not a valid line\n"
    )
    saved = dict(os.environ)
    try:
        os.environ["FB_ZZ_EXISTING"] = "fromenv"  # real env must win
        loaded = config.load_env_file(env_path)
        assert loaded == str(env_path)
        assert os.environ["FB_ZZ_TOKEN"] == "fromfile"
        assert os.environ["FB_ZZ_QUOTED"] == "quoted value"
        assert os.environ["FB_ZZ_EXISTING"] == "fromenv"
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_load_env_file_missing_is_noop(tmp_path):
    assert config.load_env_file(tmp_path / "does-not-exist.env") is None
