"""Custom audiences: local SHA-256 hashing of PII, gating, dry-run redaction."""

from __future__ import annotations

import hashlib
import json

from facebook_mcp import config
from facebook_mcp.tools import audiences


def _sha(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8")).hexdigest()


async def test_list_custom_audiences(fake, cfg_writes):
    fake.queue("GET", "act_1/customaudiences", {"data": [{"id": "AUD1"}]})
    out = json.loads(await audiences.list_custom_audiences())
    assert out["data"][0]["id"] == "AUD1"
    _, path, params = fake.last()
    assert path == "act_1/customaudiences"
    assert "subtype" in params["fields"]


async def test_create_custom_audience_payload(fake, cfg_writes):
    fake.queue("POST", "act_1/customaudiences", {"id": "AUD1"})
    out = json.loads(await audiences.create_custom_audience("VIPs", description="d"))
    assert out["id"] == "AUD1"
    _, path, params = fake.last()
    assert path == "act_1/customaudiences"
    assert params["subtype"] == "CUSTOM"
    assert params["customer_file_source"] == "USER_PROVIDED_ONLY"
    assert params["description"] == "d"


async def test_add_users_hashes_and_normalizes_email(fake, cfg_writes):
    fake.queue("POST", "AUD1/users", {"num_received": 1})
    raw = "  Alice@Example.COM "
    await audiences.add_users_to_audience("AUD1", emails=raw)
    _, path, params = fake.last()
    assert path == "AUD1/users"
    payload = json.loads(params["payload"])
    assert payload["schema"] == ["EMAIL"]
    # normalized (trimmed + lowercased) then hashed
    assert payload["data"] == [[_sha("alice@example.com")]]
    # raw PII must never appear in the outgoing request
    assert "Alice" not in params["payload"]
    assert "example.com" not in params["payload"]


async def test_add_users_phone_digits_only(fake, cfg_writes):
    fake.queue("POST", "AUD1/users", {"num_received": 1})
    await audiences.add_users_to_audience("AUD1", phones="+1 (415) 555-0100")
    _, _, params = fake.last()
    payload = json.loads(params["payload"])
    assert payload["schema"] == ["PHONE"]
    assert payload["data"] == [[_sha("14155550100")]]


async def test_add_users_both_keys_two_calls(fake, cfg_writes):
    fake.queue("POST", "AUD1/users", {"num_received": 1}, {"num_received": 1})
    out = json.loads(
        await audiences.add_users_to_audience("AUD1", emails="a@b.com", phones="15551234567")
    )
    schemas = [json.loads(p["payload"])["schema"][0] for _, _, p in fake.calls]
    assert schemas == ["EMAIL", "PHONE"]
    assert "results" in out and len(out["results"]) == 2


async def test_add_users_requires_input(fake, cfg_writes):
    out = json.loads(await audiences.add_users_to_audience("AUD1"))
    assert "provide" in out["error"].lower()
    assert fake.calls == []


async def test_remove_users_uses_delete(fake, cfg_writes):
    fake.queue("DELETE", "AUD1/users", {"num_received": 1})
    await audiences.remove_users_from_audience("AUD1", emails="a@b.com")
    assert fake.last()[:2] == ("DELETE", "AUD1/users")


async def test_add_users_blocked_when_readonly(fake, cfg_readonly):
    out = json.loads(await audiences.add_users_to_audience("AUD1", emails="a@b.com"))
    assert "disabled" in out["error"].lower()
    assert fake.calls == []


async def test_add_users_dry_run_redacts_hashes(fake, tmp_path):
    config.set_config(
        config.Config(access_token="t", enable_writes=True, dry_run=True, ad_account_id="act_1")
    )
    try:
        out = json.loads(await audiences.add_users_to_audience("AUD1", emails="a@b.com"))
        assert out["dry_run"] is True
        data = out["would_call"]["params"]["payload"]["data"]
        assert data == "<1 hashed rows>"
        # the hash itself is not present in the preview
        assert _sha("a@b.com") not in json.dumps(out)
        assert fake.calls == []
    finally:
        config._config = None


async def test_create_lookalike_spec(fake, cfg_writes):
    fake.queue("POST", "act_1/customaudiences", {"id": "LAL1"})
    out = json.loads(
        await audiences.create_lookalike_audience("LAL", "AUD1", "US", ratio=0.05)
    )
    assert out["id"] == "LAL1"
    _, path, params = fake.last()
    assert params["subtype"] == "LOOKALIKE"
    assert params["origin_audience_id"] == "AUD1"
    assert json.loads(params["lookalike_spec"]) == {"country": "US", "ratio": 0.05}


async def test_delete_custom_audience(fake, cfg_writes):
    fake.queue("DELETE", "AUD1", {"success": True})
    out = json.loads(await audiences.delete_custom_audience("AUD1"))
    assert out["success"] is True
    assert fake.last()[:2] == ("DELETE", "AUD1")


async def test_audiences_registered():
    from facebook_mcp import app as appmod

    rw = appmod.build_app(config.Config(access_token="t", enable_writes=True))
    names = {t.name for t in await rw.list_tools()}
    config._config = None
    assert "list_custom_audiences" in names
    assert "add_users_to_audience" in names
