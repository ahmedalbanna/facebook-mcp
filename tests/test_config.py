"""Config loading: env parsing, ad-account normalisation, secret files."""

from __future__ import annotations

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
