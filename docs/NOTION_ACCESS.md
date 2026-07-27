# Notion access

## The two separate limits

RESOLVE's Notion reach is gated in two independent places. Confusing them wastes
an afternoon, so:

| Limit | Where it lives | Who fixes it |
|---|---|---|
| **What the code can express** | `connectors/notion_api.py` | code — **done**, it's now generic |
| **What the token can see** | Notion's share menu | **you, in the Notion UI** |

Until 2026-07-26 the connector hardcoded one database id (`NOTION_TASKS_DB`) and
exposed exactly three operations: list open tasks, create a task, archive a page.
So *every* Notion request had to become a row in the Tasks inbox, because that
was the only door in the code. That's fixed. The connector now does search,
schema reads, queries, page creation and edits, block appends, and database
creation, against any object the token can see.

That leaves limit #2, which is not a code problem and never was.

## Sharing the workspace with the integration (the part only you can do)

An internal integration sees **nothing by default**. It sees a page only if that
page — or an ancestor of it — has been explicitly connected to it. Sharing a
parent page cascades to everything nested under it, which is the whole trick:

1. Notion → **Settings → Connections → develop or manage integrations** → open
   the integration whose secret is in `NOTION_TOKEN`.
2. Under **Capabilities**, confirm all three are on: *Read content*,
   *Update content*, *Insert content*. Read-only capabilities are a common cause
   of "it found the database but the write 403'd."
3. In the workspace, go to the **top-level page that contains everything** —
   ideally your workspace root or the single parent your databases live under.
4. `···` menu → **Connections** → **Connect to** → pick the integration.
5. Confirm the cascade prompt. Everything nested beneath inherits access.

Anything living *outside* that parent — a database at the workspace root, a page
in a teamspace the integration isn't in — needs its own connect step. Private
pages owned by another member are never reachable this way.

### Verifying

```python
from resolve_control_plane.connectors import notion_api
[d["title"] for d in notion_api.list_databases()]
```

If a database you expect isn't in that list, it isn't shared — step 4 again on
its parent. Do this before assuming a bug: a missing database and an unshared
database look identical from the model's side, which is exactly why
`notion_search`'s description tells it to say so rather than write elsewhere.

## Why not OAuth

`NOTION_CLIENT_ID` / `NOTION_CLIENT_SECRET` in `.env.example` are for the OAuth
flow, which isn't wired up. OAuth would let *you* pick pages at consent time
instead of connecting them one by one, but it doesn't grant anything broader
than the same page-level permissions — it's a nicer picker, not more reach.
Single-user workspace, one static secret: the internal integration is the right
call. Not worth building until there's a second user.

## Working with an unfamiliar database

The model is told to call `notion_schema` before its first write to a database.
This matters more than it sounds: property names are case- and space-sensitive,
and `select` values must already exist as options — the API rejects a new option
on write rather than creating it. `notion_schema` returns the allowed options so
the model picks a real one instead of inventing "Fall '26" when the option is
"Fall 2026".

Values are passed as plain JSON (`{"Days": ["Mon","Wed"], "Credits": 4}`) and
typed against the live schema by `_build_props`. Properties that don't exist, or
that are computed (`formula`, `rollup`, `created_time`), come back in a
`skipped` list on the result rather than failing the whole write — a partial
write you can see beats a hard failure the model then retries blindly.
