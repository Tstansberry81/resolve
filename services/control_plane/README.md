# RESOLVE control plane

The FastAPI service that runs RESOLVE: the assistant loop, the planner/executor worker, the policy
engine, approvals, routines, and every connector. It is the whole backend — the strangler migration
out of the legacy `vault1` monolith is finished, and nothing here imports it.

## Shape

| Module | What it does |
|---|---|
| `api.py` | HTTP surface. `/v1/*` behind a bearer token (`CP_TOKEN`, fails closed when unset). |
| `assistant.py` | The front door: Sonnet's tool-use loop, approvals, connector dispatch. |
| `executor.py` | Planner → step queue → single in-process worker, under the same policy engine. |
| `policy.py` | `config/tool_policies.json` as code: allow / require-approval / deny per action. |
| `routines.py` | Scheduled work (morning brief, daily ingest). |
| `bus.py` | The event bus behind the dashboard SSE feed and Telegram pushes. |
| `local.py` | Bridge to the laptop worker (`apps/local-worker`): files, web-read, gated shell. |
| `connectors/` | Gmail, Calendar, Notion, SimpleFIN, Composio, the GitHub vault, the local model, Telegram. |

## Telegram

Both directions live here.

- **Outbound** — `connectors/telegram_notify.py` posts to the Bot API with `TELEGRAM_TOKEN`.
  Selected bus events and every approval (with inline Approve/Reject buttons) get pushed.
- **Inbound** — `POST /v1/telegram/webhook` handles the button taps and `/resolve <text>`. Telegram
  can't send a bearer token, so this route is gated by the `setWebhook` secret instead of `auth()`,
  plus a hard `TELEGRAM_CHAT_ID` allowlist. It fails closed if `TELEGRAM_WEBHOOK_SECRET` is unset.

Register it once per deploy:

```sh
curl -X POST "https://api.telegram.org/bot$TELEGRAM_TOKEN/setWebhook" \
  -d "url=https://<your-host>/v1/telegram/webhook" \
  -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

## Run it

```sh
PYTHONPATH=src uvicorn resolve_control_plane.api:app --reload
python -m pytest tests -q
```

Schema: `infra/postgres/001_control_plane.sql`. Local Postgres + Redis + API: `infra/docker-compose.yml`.
