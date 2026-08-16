"""Report generation: inline CSV, sandboxed file output, xlsx guard, summary."""

from __future__ import annotations

import json

from facebook_mcp import config
from facebook_mcp.tools import reports

_TWO_CAMPAIGNS = {
    "data": [
        {"campaign_name": "Alpha", "campaign_id": "C1", "impressions": "100", "clicks": "5"},
        {"campaign_name": "Beta", "campaign_id": "C2", "impressions": "200", "clicks": "9"},
    ]
}


async def test_campaign_report_inline_csv(fake, cfg_writes):
    fake.queue("GET", "act_1/insights", _TWO_CAMPAIGNS)
    out = json.loads(
        await reports.generate_campaign_report(fields="campaign_name,impressions,clicks")
    )
    assert out["format"] == "csv"
    assert out["row_count"] == 2
    lines = out["csv"].strip().splitlines()
    assert lines[0] == "campaign_name,impressions,clicks"
    assert lines[1] == "Alpha,100,5"
    assert "path" not in out  # not saved
    _, _, params = fake.last()
    assert params["level"] == "campaign"


async def test_campaign_report_saves_file(fake, tmp_path):
    config.set_config(
        config.Config(
            access_token="t",
            enable_writes=True,
            ad_account_id="act_1",
            report_dir=str(tmp_path),
        )
    )
    try:
        fake.queue("GET", "act_1/insights", _TWO_CAMPAIGNS)
        out = json.loads(
            await reports.generate_campaign_report(
                fields="campaign_name,impressions", save=True, filename="july"
            )
        )
        path = out["path"]
        assert path.endswith("july.csv")
        assert (tmp_path / "july.csv").read_text().splitlines()[0] == "campaign_name,impressions"
    finally:
        config._config = None


async def test_report_filename_cannot_escape_dir(fake, tmp_path):
    config.set_config(
        config.Config(
            access_token="t",
            enable_writes=True,
            ad_account_id="act_1",
            report_dir=str(tmp_path),
        )
    )
    try:
        fake.queue("GET", "act_1/insights", _TWO_CAMPAIGNS)
        out = json.loads(
            await reports.generate_campaign_report(
                fields="campaign_name", save=True, filename="../../etc/evil"
            )
        )
        # basename only: written inside the report dir, not the parent
        assert out["path"] == str(tmp_path / "evil.csv")
        assert (tmp_path / "evil.csv").exists()
    finally:
        config._config = None


async def test_xlsx_without_report_dir_errors(fake, cfg_writes):
    fake.queue("GET", "act_1/insights", _TWO_CAMPAIGNS)
    out = json.loads(await reports.generate_campaign_report(fmt="xlsx"))
    assert "FB_REPORT_DIR" in out["error"]


async def test_account_summary(fake, cfg_writes):
    fake.queue("GET", "act_1/insights", {"data": [{"impressions": "1000", "spend": "50"}]})
    out = json.loads(await reports.generate_account_summary())
    assert out["summary"]["impressions"] == "1000"
    assert out["ad_account_id"] == "act_1"
    assert out["date_preset"] == "last_30d"


async def test_reports_and_insights_registered():
    from facebook_mcp import app as appmod

    app = appmod.build_app(config.Config(access_token="t", enable_writes=False))
    names = {t.name for t in await app.list_tools()}
    config._config = None
    # reports & insights are read-only, so present even without writes
    assert "generate_campaign_report" in names
    assert "generate_account_summary" in names
    assert "get_account_insights" in names
