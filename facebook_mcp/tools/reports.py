"""Generate human-shareable reports from insights (CSV always; xlsx optional).

CSV uses only the standard library, so it always works. xlsx export is lazy and
needs the optional ``[reports]`` extra (pandas + openpyxl). Files are written
only under ``FB_REPORT_DIR`` and only the basename of any requested filename is
used, so a report can never be written outside that directory.
"""

from __future__ import annotations

import csv
import io
import json
import os

from facebook_mcp import api, config
from facebook_mcp.errors import FacebookMCPError
from facebook_mcp.tools.ads import _acct
from facebook_mcp.tools.common import tool
from facebook_mcp.tools.insights import _build_params

_CAMPAIGN_REPORT_FIELDS = (
    "campaign_name,campaign_id,impressions,clicks,spend,cpc,cpm,ctr,reach,frequency"
)
_SUMMARY_FIELDS = "impressions,clicks,spend,cpc,cpm,ctr,reach,frequency"


def _columns(fields: str) -> list[str]:
    return [c.strip() for c in fields.split(",") if c.strip()]


def _flatten(rows: list, columns: list[str]) -> list[list[str]]:
    out = []
    for item in rows:
        line = []
        for col in columns:
            val = item.get(col, "")
            if isinstance(val, (dict, list)):
                val = json.dumps(val, ensure_ascii=False)
            line.append("" if val is None else str(val))
        out.append(line)
    return out


def _to_csv(columns: list[str], rows: list[list[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    writer.writerows(rows)
    return buf.getvalue()


def _report_path(cfg: config.Config, filename: str, default_stem: str, ext: str) -> str:
    if not cfg.report_dir:
        raise FacebookMCPError(
            "Saving reports needs FB_REPORT_DIR to be configured; omit save to get "
            "the report inline instead."
        )
    name = os.path.basename(filename.strip()) or f"{default_stem}.{ext}"
    if not name.endswith(f".{ext}"):
        name = f"{name}.{ext}"
    base = os.path.abspath(cfg.report_dir)
    os.makedirs(base, exist_ok=True)
    path = os.path.abspath(os.path.join(base, name))
    if os.path.commonpath([base, path]) != base:  # defense-in-depth
        raise FacebookMCPError("Refusing to write outside FB_REPORT_DIR.")
    return path


def _write_xlsx(path: str, columns: list[str], rows: list[list[str]]) -> None:
    try:
        import pandas as pd  # lazy: only needed for xlsx

        pd.DataFrame(rows, columns=columns).to_excel(path, index=False)
    except ImportError as exc:  # pandas or openpyxl missing
        raise FacebookMCPError(
            "xlsx export needs the reports extra: pip install 'facebook-mcp[reports]'."
        ) from exc


@tool
async def generate_campaign_report(
    ad_account_id: str = "",
    date_preset: str = "last_30d",
    time_range_json: str = "",
    fields: str = _CAMPAIGN_REPORT_FIELDS,
    fmt: str = "csv",
    save: bool = False,
    filename: str = "",
) -> str:
    """Per-campaign performance report for an ad account.

    fmt is "csv" (returned inline; also written to FB_REPORT_DIR when save=true)
    or "xlsx" (always written to FB_REPORT_DIR, needs the [reports] extra).
    time_range_json overrides date_preset, e.g.
    '{"since":"2026-07-01","until":"2026-07-31"}'.
    """
    cfg = config.current()
    columns = _columns(fields)
    params = _build_params(
        date_preset=date_preset,
        time_range_json=time_range_json,
        fields=fields,
        level="campaign",
        breakdowns="",
        time_increment="",
        limit=0,
    )
    rows_raw = await api.aget_all(f"{_acct(ad_account_id)}/insights", params, max_items=500)
    rows = _flatten(rows_raw, columns)

    if fmt.lower() == "xlsx":
        path = _report_path(cfg, filename, "campaign_report", "xlsx")
        _write_xlsx(path, columns, rows)
        return api.dumps(
            {"format": "xlsx", "path": path, "row_count": len(rows), "columns": columns}
        )

    csv_text = _to_csv(columns, rows)
    result: dict = {
        "format": "csv",
        "row_count": len(rows),
        "columns": columns,
        "csv": csv_text,
    }
    if save:
        path = _report_path(cfg, filename, "campaign_report", "csv")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(csv_text)
        result["path"] = path
    return api.dumps(result)


@tool
async def generate_account_summary(
    ad_account_id: str = "",
    date_preset: str = "last_30d",
    time_range_json: str = "",
    fields: str = _SUMMARY_FIELDS,
) -> str:
    """One-row account-level performance summary (JSON)."""
    params = _build_params(
        date_preset=date_preset,
        time_range_json=time_range_json,
        fields=fields,
        level="account",
        breakdowns="",
        time_increment="",
        limit=0,
    )
    rows = await api.aget_all(f"{_acct(ad_account_id)}/insights", params, max_items=1)
    return api.dumps(
        {
            "ad_account_id": _acct(ad_account_id),
            "date_preset": date_preset if not time_range_json else None,
            "time_range": json.loads(time_range_json) if time_range_json else None,
            "summary": rows[0] if rows else {},
        }
    )


READ_TOOLS = [generate_campaign_report, generate_account_summary]
WRITE_TOOLS: list = []
