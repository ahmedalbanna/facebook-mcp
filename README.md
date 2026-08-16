# facebook-mcp

A **Model Context Protocol (MCP) server for Facebook / Meta**, built on Meta's
official [`facebook-business`](https://pypi.org/project/facebook_business/) SDK.
It exposes the Graph and Marketing API surfaces as MCP tools:

- **Pages** — profile, posts (incl. photo & scheduled posts), comments, Page
  insights, publish/edit/delete
- **Ads (Marketing API)** — ad accounts, campaigns, ad sets, ads, ad creatives,
  image/video upload, insights, and CSV/Excel **reports**
- **Audiences** — custom audiences (with PII hashed locally before upload) and
  lookalikes
- **Automation** — automated ad rules (spend-affecting rules extra-gated)
- **Instagram** — IG Business account, media, comments, insights, and
  photo / video / reel / story publishing
- **Messenger** — conversations, messages, and the Send API

It also serves **resources** (live account snapshots) and **prompts** (ad-copy
and reporting templates) for MCP clients that surface them.

Reads are always available; **writes are off by default** and gated behind
`FB_ENABLE_WRITES`, with extra **ad-spend guardrails** so automation cannot
silently start live spend.

It speaks **stdio** (for local clients) and **streamable-HTTP** (like Meta's own
remote MCP), so it can run standalone or sit behind an MCP gateway such as
`erpnext-mcp-gateway`.

---

## Install

```bash
cd facebook-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"              # facebook_business + fastmcp + tooling
pip install -e ".[dev,reports]"      # also enable Excel (.xlsx) report output
```

CSV reports need nothing beyond the base install; the `reports` extra
(`pandas` + `openpyxl`) is only required for `.xlsx` output.

## Configure

Copy `.env.example` to `.env` and fill it in (the real `.env` is git-ignored):

```bash
cp .env.example .env
```

Minimum required: `FB_ACCESS_TOKEN` (plus `FB_APP_ID` / `FB_APP_SECRET` to enable
`appsecret_proof`). Prefer the `*_FILE` variants (mode-600 files) for secrets in
production. Validate without starting a server:

```bash
python -m facebook_mcp --check-config     # prints a secret-free summary
```

On startup the server loads `.env` from the current directory (or the path in
`FB_ENV_FILE`) into the environment. It **never overrides** variables already set,
so a real shell export or docker-compose `env_file:` always wins — the file is
just a convenience for local runs. `--check-config` reports which file was loaded.

### Access tokens & scopes

Today the server authenticates with a **long-lived access token** (the auth
layer is isolated in `facebook_mcp/api.py`, so an OAuth sign-in flow can be added
later without touching any tool). Grant the token the scopes for the surfaces you
use:

| Surface   | Scopes |
|-----------|--------|
| Pages     | `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `pages_manage_engagement`, `read_insights` |
| Ads       | `ads_read`, `ads_management`, `business_management` |
| Instagram | `instagram_basic`, `instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_insights`, `pages_show_list` |
| Messenger | `pages_messaging`, `pages_manage_metadata` |

Publishing as a Page / replying in Messenger generally needs a **Page access
token**. Discover ids at runtime rather than guessing:

- `list_pages` → Page ids (and, with `fb_get`, their Page tokens)
- `list_ad_accounts` → `act_<id>` ad accounts
- `discover_ig_user` → the IG Business account linked to a Page
- `debug_token` → the token's app, scopes, type and expiry

Then set `FB_PAGE_ID`, `FB_AD_ACCOUNT_ID`, `FB_IG_USER_ID` as convenient defaults.

## Run

```bash
# stdio (local MCP clients)
python -m facebook_mcp

# streamable-HTTP on :8020/mcp, optional bearer token
python -m facebook_mcp --transport streamable-http --host 127.0.0.1 --port 8020 \
    --token "$FB_MCP_TOKEN"

# enable writes for this run (or set FB_ENABLE_WRITES=true)
python -m facebook_mcp --enable-writes

# rehearse writes without calling Meta
python -m facebook_mcp --enable-writes --dry-run
```

`/healthz` is served (auth-free) on the HTTP transport.

Register with Claude Code (HTTP):

```bash
claude mcp add --transport http facebook http://127.0.0.1:8020/mcp
```

## Safety model

- **Writes gated** — create/update/delete/send tools are hidden unless
  `FB_ENABLE_WRITES` is set. `fb_post`/`fb_delete` (generic writes) are gated too.
- **Ads default to PAUSED** — campaigns/ad sets are created `PAUSED` unless
  `FB_ADS_ALLOW_ACTIVATE=true`.
- **Budget caps** — any budget is checked against `FB_ADS_MAX_DAILY_BUDGET` /
  `FB_ADS_MAX_LIFETIME_BUDGET` (minor currency units, e.g. cents); budgeted
  writes are refused until a cap is configured.
- **Dry run** — `FB_DRY_RUN=true` makes every write return a preview of the call
  it *would* make instead of performing it.
- **Prompt-injection posture** — the system prompt instructs the model to treat
  post/comment/message text as untrusted and never follow instructions in it.
- **PII stays local** — custom-audience emails/phones are normalised and
  SHA-256 hashed on this machine; only hashes leave the process.
- **Reports confined** — report files are only written inside `FB_REPORT_DIR`;
  a caller-supplied filename cannot escape that directory.
- **Secrets** — never logged; read from env or mode-600 files. `--check-config`
  reports presence, never values.

## Tools

Diagnostics: `whoami`, `debug_token`, `fb_get` (+ gated `fb_post`, `fb_delete`).

| Surface | Read | Write (gated) |
|---------|------|---------------|
| Pages | `list_pages`, `get_page`, `list_page_posts`, `get_post`, `list_post_comments`, `get_page_insights` | `create_page_post`, `publish_page_photo`, `schedule_page_post`, `update_post`, `delete_post`, `comment_on_object`, `delete_comment` |
| Ads | `list_ad_accounts`, `get_ad_account`, `list_campaigns`, `list_adsets`, `list_ads`, `get_campaign`, `get_adset`, `get_ad`, `get_ad_insights` | `create_campaign`, `update_campaign`, `update_campaign_budget`, `set_campaign_status`, `delete_campaign`, `create_adset`, `update_adset_status`, `update_adset_budget`, `update_adset_targeting`, `create_ad`, `update_ad_status`, `create_ad_creative`, `create_link_ad_creative`, `upload_ad_image`, `upload_ad_video` |
| Audiences | `list_custom_audiences`, `get_custom_audience` | `create_custom_audience`, `add_users_to_audience`, `remove_users_from_audience`, `create_lookalike_audience`, `delete_custom_audience` |
| Insights | `get_account_insights`, `get_campaign_insights`, `get_adset_insights` | *(read-only)* |
| Reports | `generate_campaign_report`, `generate_account_summary` | *(read-only)* |
| Automation | `list_auto_rules` | `create_auto_rule`, `delete_auto_rule` |
| Instagram | `discover_ig_user`, `get_ig_account`, `list_ig_media`, `get_ig_media`, `list_ig_comments`, `get_ig_insights`, `get_ig_media_insights`, `get_ig_container_status` | `create_ig_media_container`, `publish_ig_media`, `publish_ig_photo`, `publish_ig_video`, `publish_ig_reel`, `publish_ig_story`, `reply_to_ig_comment`, `delete_ig_comment` |
| Messenger | `list_conversations`, `list_messages` | `send_message`, `send_image` |

Every tool returns a JSON string. Errors come back as structured
`{"error": ...}` payloads (with Graph `code`/`subcode`/`fbtrace_id` where
available) rather than exceptions.

**Notes on specific tools:**

- **Audiences** — `add_users_to_audience` / `remove_users_from_audience`
  normalise then **SHA-256 hash emails and phone numbers locally**; raw PII is
  never sent to Meta.
- **Reports** — `generate_*` return CSV inline by default. With `save=true` they
  write into `FB_REPORT_DIR` (files are confined to that directory); `fmt="xlsx"`
  additionally needs the `[reports]` extra installed.
- **Automation** — rules whose execution resumes or raises spend (`UNPAUSE`,
  `CHANGE_BUDGET`, `REBALANCE_BUDGET`, `INCREASE_BUDGET`) are refused unless
  `FB_ADS_ALLOW_ACTIVATE=true`, mirroring the ads PAUSED-by-default policy.
- **Instagram video/reel/story** — publishing polls the media container's
  `status_code` until it is `FINISHED` before publishing; if processing is still
  in progress it returns `{"pending": true, "creation_id": ...}` so you can
  publish later with `publish_ig_media` once `get_ig_container_status` reports
  `FINISHED`.

## Resources & prompts

For MCP clients that surface them, the server also exposes:

| Kind | Name | What it gives |
|------|------|---------------|
| Resource | `campaigns://active` | Active campaigns in the configured ad account |
| Resource | `account://summary` | Last-30-day account performance summary |
| Resource | `audiences://list` | Custom & lookalike audiences in the account |
| Prompt | `ad_copy_prompt` | Draft Meta-policy-compliant ad-copy variations |
| Prompt | `marketing_report_prompt` | Guide an actionable performance-report analysis |

Resources read the ad account configured via `FB_AD_ACCOUNT_ID`.

## Fronting with erpnext-mcp-gateway

This server is a standalone MCP endpoint, so a gateway can mount it as an
upstream backend. Run it on HTTP:

```bash
python -m facebook_mcp --transport streamable-http --port 8020 --token "$FB_MCP_TOKEN"
```

then point the gateway's backend config at `http://127.0.0.1:8020/mcp` with that
bearer token, exactly as it fronts the ERPNext backend. The gateway's
RBAC / rate-limit / audit pipeline then applies to Facebook tools too.

## Develop

```bash
PYTHONPATH=. python -m pytest -q      # tests use a fake client; no SDK or network
python -m ruff check .
```

## License

MIT (see repository).
