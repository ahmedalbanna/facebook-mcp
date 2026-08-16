"""Custom & lookalike audiences.

PII handling: emails and phone numbers are normalized and SHA-256 hashed
*locally* before they are uploaded (Meta's required format for the customer
list match). Raw PII never leaves this process, and neither the dry-run preview
nor any log line ever contains the hashes — only row counts.
"""

from __future__ import annotations

import hashlib
import json

from facebook_mcp import api, config, guardrails
from facebook_mcp.tools.ads import _acct
from facebook_mcp.tools.common import tool

_AUDIENCE_FIELDS = (
    "id,name,subtype,description,operation_status,"
    "approximate_count_lower_bound,approximate_count_upper_bound,time_updated"
)


def _split(raw: str) -> list[str]:
    """Split a comma/newline separated string into trimmed, non-empty items."""
    return [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _prep(schema: str, raw: str) -> list[str]:
    """Normalize then SHA-256 hash a list of emails or phone numbers."""
    out = []
    for item in _split(raw):
        if schema == "EMAIL":
            norm = item.strip().lower()
        else:  # PHONE — digits only (caller must include the country code)
            norm = "".join(ch for ch in item if ch.isdigit())
        if norm:
            out.append(_sha256(norm))
    return out


async def _apply_users(method: str, audience_id: str, batches, cfg) -> dict:
    """POST/DELETE hashed user rows to an audience, one call per schema."""
    path = f"{audience_id}/users"
    results = []
    for schema, hashes in batches:
        if not hashes:
            continue
        payload = {"schema": [schema], "data": [[h] for h in hashes]}
        preview = guardrails.maybe_dry_run(
            cfg,
            method,
            path,
            {"payload": {"schema": [schema], "data": f"<{len(hashes)} hashed rows>"}},
        )
        if preview:
            results.append(preview)
            continue
        params = {"payload": json.dumps(payload)}
        if method == "POST":
            results.append(await api.apost(path, params))
        else:
            results.append(await api.adelete(path, params))
    if not results:
        return {"error": "No valid users after normalization."}
    return results[0] if len(results) == 1 else {"results": results}


# ---- reads ----------------------------------------------------------------


@tool
async def list_custom_audiences(ad_account_id: str = "", limit: int = 50, after: str = "") -> str:
    """List custom and lookalike audiences in an ad account."""
    params = {"fields": _AUDIENCE_FIELDS, "limit": limit}
    if after:
        params["after"] = after
    return api.dumps(await api.aget(f"{_acct(ad_account_id)}/customaudiences", params))


@tool
async def get_custom_audience(audience_id: str) -> str:
    """Get one audience's subtype, size estimate and status."""
    return api.dumps(await api.aget(audience_id, {"fields": _AUDIENCE_FIELDS}))


# ---- writes (gated by FB_ENABLE_WRITES) -----------------------------------


@tool
async def create_custom_audience(
    name: str,
    description: str = "",
    customer_file_source: str = "USER_PROVIDED_ONLY",
    ad_account_id: str = "",
) -> str:
    """Create an empty customer-list custom audience to upload users into.

    customer_file_source is one of USER_PROVIDED_ONLY, PARTNER_PROVIDED_ONLY or
    BOTH_USER_AND_PARTNER_PROVIDED — it attests where the data came from.
    """
    cfg = config.current()
    guardrails.require_writes(cfg)
    params = {"name": name, "subtype": "CUSTOM", "customer_file_source": customer_file_source}
    if description:
        params["description"] = description
    path = f"{_acct(ad_account_id)}/customaudiences"
    preview = guardrails.maybe_dry_run(cfg, "POST", path, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(path, params))


@tool
async def add_users_to_audience(audience_id: str, emails: str = "", phones: str = "") -> str:
    """Add users to a custom audience by email and/or phone.

    emails and phones are comma/newline separated. Each value is normalized and
    SHA-256 hashed locally before upload — raw PII never leaves this process.
    Include the country code in phone numbers. Emails and phones are uploaded as
    independent match keys (one API call each).
    """
    cfg = config.current()
    guardrails.require_writes(cfg)
    batches = []
    if emails.strip():
        batches.append(("EMAIL", _prep("EMAIL", emails)))
    if phones.strip():
        batches.append(("PHONE", _prep("PHONE", phones)))
    if not batches:
        return api.dumps({"error": "Provide emails and/or phones to add."})
    return api.dumps(await _apply_users("POST", audience_id, batches, cfg))


@tool
async def remove_users_from_audience(audience_id: str, emails: str = "", phones: str = "") -> str:
    """Remove users from a custom audience by email and/or phone (hashed locally)."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    batches = []
    if emails.strip():
        batches.append(("EMAIL", _prep("EMAIL", emails)))
    if phones.strip():
        batches.append(("PHONE", _prep("PHONE", phones)))
    if not batches:
        return api.dumps({"error": "Provide emails and/or phones to remove."})
    return api.dumps(await _apply_users("DELETE", audience_id, batches, cfg))


@tool
async def create_lookalike_audience(
    name: str,
    origin_audience_id: str,
    country: str,
    ratio: float = 0.01,
    ad_account_id: str = "",
) -> str:
    """Create a lookalike audience from a source (custom) audience.

    country is an ISO code (e.g. "US"). ratio is the lookalike size, 0.01–0.20
    (1%–20% of the country's population); smaller is more similar.
    """
    cfg = config.current()
    guardrails.require_writes(cfg)
    spec = {"country": country, "ratio": float(ratio)}
    params = {
        "name": name,
        "subtype": "LOOKALIKE",
        "origin_audience_id": origin_audience_id,
        "lookalike_spec": json.dumps(spec),
    }
    path = f"{_acct(ad_account_id)}/customaudiences"
    preview = guardrails.maybe_dry_run(cfg, "POST", path, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(path, params))


@tool
async def delete_custom_audience(audience_id: str) -> str:
    """Delete a custom or lookalike audience."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    preview = guardrails.maybe_dry_run(cfg, "DELETE", audience_id, {})
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.adelete(audience_id, {}))


READ_TOOLS = [list_custom_audiences, get_custom_audience]
WRITE_TOOLS = [
    create_custom_audience,
    add_users_to_audience,
    remove_users_from_audience,
    create_lookalike_audience,
    delete_custom_audience,
]
