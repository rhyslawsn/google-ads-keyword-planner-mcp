# Google Ads Keyword Planner MCP server

An MCP server that exposes Google Ads Keyword Planner to Claude: keyword ideas, historical volume, competition and bid ranges.

## Tools

| Tool | What it does |
|---|---|
| `keyword_ideas` | Seed keywords and/or a URL → related ideas with avg monthly searches, competition, top-of-page bid range, 12-month trend |
| `keyword_metrics` | Exact keyword list → the same metrics, no expansion |
| `list_locations` | Search geo targets by name (e.g. "Victoria") → numeric IDs |
| `list_languages` | Common language names → constant IDs |

`locations` accepts names for a few common countries ("united states", "canada", …) or any numeric geo target ID from `list_locations`. Defaults to the United States, English.

## What you need from Google

1. **Developer token**: Google Ads → Tools → API Center. This only appears on a *manager* account. Keyword Planner works with Basic access, but new tokens start at Test access, which only works against test accounts, so apply for Basic access.
2. **OAuth client**: Google Cloud Console → enable the *Google Ads API* → Credentials → OAuth client ID (type *Desktop app*).
3. **Refresh token**: run `python get_refresh_token.py` (see the file header) and sign in with a user who has access to the ads account.
4. **Customer ID**: the 10-digit account to run planner queries against. If you reach it through a manager account, also set `GOOGLE_ADS_LOGIN_CUSTOMER_ID` to the manager's ID.

Copy `.env.example` to `.env` and fill it in.

## Run locally (stdio)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Claude Desktop / Claude Code config:

```json
{
  "mcpServers": {
    "google-ads-keyword-planner": {
      "command": "/path/to/.venv/bin/python",
      "args": ["/path/to/server.py"],
      "env": { "GOOGLE_ADS_DEVELOPER_TOKEN": "...", "...": "..." }
    }
  }
}
```

## Deploy remotely (Railway, streamable HTTP)

1. Push this folder to a repo and create a Railway service from it (the Dockerfile is picked up automatically).
2. Set all variables from `.env.example` in Railway, with `MCP_TRANSPORT=http` and a long random `MCP_AUTH_TOKEN`.
3. Generate a domain. The MCP endpoint is `https://<domain>/mcp`; `/health` is unauthenticated for health checks.
4. Add it as a custom connector in Claude using that URL. The server expects `Authorization: Bearer <MCP_AUTH_TOKEN>`; if your Claude plan's custom connectors only support OAuth, put the server behind an auth proxy or add OAuth to it.

## Notes

- Keyword Planner volumes come back as ranges for accounts with little or no ad spend (e.g. 1K–10K collapsed to a bucket). That's Google's behaviour, not a bug.
- Money values (`*_top_of_page_bid`) are in the ad account's currency.
- Quota: Keyword Planner requests count against your developer token's daily operations. Cache results if you automate large sweeps.
