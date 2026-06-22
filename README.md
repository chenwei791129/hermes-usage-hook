# hermes-codex-usage-hook

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) hook that reports
your **Codex 5-hour rate-limit usage** at the end of every conversation.

It reads the OAuth credentials the Codex CLI stores in `~/.codex/auth.json`,
queries the same usage endpoint [codexbar](https://github.com/steipete/codexbar)
uses, and sends a one-line summary such as:

```
Codex 5h | used 42%, left 58% (resets in 137 min) | plan pro
```

## How it works

Codex does not expose a public "usage" API. The numbers shown by codexbar (and
the Codex CLI's `/status`) come from an internal endpoint that the ChatGPT
backend serves to authenticated Codex clients:

1. **Read credentials** — `~/.codex/auth.json` (or `$CODEX_HOME/auth.json`):
   `tokens.access_token`, `tokens.refresh_token`, `tokens.account_id`,
   and the top-level `last_refresh`.
2. **Refresh if needed** — when `last_refresh` is older than ~8 days, or the
   usage call returns 401/403, exchange the refresh token at
   `POST https://auth.openai.com/oauth/token` and write the new token back.
3. **Query usage** — `GET https://chatgpt.com/backend-api/wham/usage` with
   `Authorization: Bearer <token>` and `ChatGPT-Account-Id: <account_id>`.
4. **Parse windows** — `rate_limit.primary_window` / `secondary_window`, each
   with `used_percent`, `reset_at` (epoch seconds) and `limit_window_seconds`.
   A window of `18000` s is the **5-hour** bucket; `604800` s is the weekly one.

> **Note on "session":** Codex's 5-hour window is an *account-wide* rolling
> quota, not a per-conversation total. This hook fires when a Hermes
> conversation ends and reports how much of that account quota is currently
> used — the same figure codexbar shows in the menu bar.

> **Stability:** `wham/usage` and the OAuth client id are reverse-engineered
> from Codex CLI behavior, not a documented API. OpenAI may change them without
> notice, so every call is wrapped so a failure never breaks the agent.

## Files

| File | Purpose |
| --- | --- |
| `codex_usage.py` | Standalone module: read `auth.json`, refresh token, fetch and normalize usage. |
| `hooks/plugin_hook.py` | Hermes **plugin hook** (`on_session_end`) — runs in CLI **and** gateway modes. Recommended. |
| `hooks/gateway/HOOK.yaml` + `hooks/gateway/handler.py` | Hermes **gateway hook** (`agent:end`) — runs in messaging gateway mode only. |

## Quick check (before deploying)

Make sure you can fetch usage with your current Codex login:

```bash
# Requires the Codex CLI to be logged in (`codex login`) so ~/.codex/auth.json exists.
uv run codex_usage.py
# or, if httpx is already installed:
python codex_usage.py
```

You should see the normalized JSON plus a one-line summary.

## Deploy to Hermes Agent

Hermes loads hooks from `~/.hermes/`. Pick **one** of the two options below.

### Option A — Plugin hook (recommended: CLI + gateway)

The `on_session_end` hook fires at the end of every conversation in both CLI and
gateway modes.

```bash
git clone git@github.com:<you>/hermes-codex-usage-hook.git
cd hermes-codex-usage-hook

# Put the shared module where both hook styles can import it.
mkdir -p ~/.hermes/lib
cp codex_usage.py ~/.hermes/lib/

# Install the plugin hook into your Hermes plugins directory.
mkdir -p ~/.hermes/plugins
cp hooks/plugin_hook.py ~/.hermes/plugins/codex_usage_hook.py
```

Hermes discovers the `register(ctx)` entry point on startup and registers the
`on_session_end` callback. Restart Hermes to load it.

### Option B — Gateway hook (messaging gateway only)

Gateway hooks live in `~/.hermes/hooks/<name>/` as `HOOK.yaml` + `handler.py`.

```bash
mkdir -p ~/.hermes/lib ~/.hermes/hooks/codex-usage-notify
cp codex_usage.py ~/.hermes/lib/
cp hooks/plugin_hook.py ~/.hermes/lib/        # handler.py imports _notify from it
cp hooks/gateway/HOOK.yaml hooks/gateway/handler.py ~/.hermes/hooks/codex-usage-notify/
```

Restart the gateway. On each `agent:end` event the handler fetches usage and
notifies.

## Configuration

The notifier is selected with the `CODEX_USAGE_NOTIFIER` environment variable:

| Value | Behavior |
| --- | --- |
| `macos` | macOS desktop notification via `osascript` (default on macOS). |
| `webhook` | HTTP `POST {"text": ...}` to `CODEX_USAGE_WEBHOOK_URL` (Slack/Discord/your service). |
| `stdout` | Print to stdout (default off macOS; handy while developing). |

Example for a webhook target:

```bash
export CODEX_USAGE_NOTIFIER=webhook
export CODEX_USAGE_WEBHOOK_URL="https://hooks.slack.com/services/XXX/YYY/ZZZ"
```

`CODEX_HOME` is honored if your Codex install uses a non-default home.

## Troubleshooting

- **`auth.json` not found** — run `codex login` so the Codex CLI creates it.
- **401/403** — the usage endpoint needs ChatGPT **OAuth** credentials. An
  API-key-only `auth.json` cannot be refreshed and will be rejected; log in with
  a ChatGPT account (`codex login`) to get OAuth tokens. If you already use
  OAuth, the refresh token may be expired or revoked — re-run `codex login`.
- **Nothing happens at conversation end** — confirm the file landed in the right
  directory and restart Hermes; hook errors are logged to stderr, prefixed
  `[codex-usage-hook]`.

## License

MIT
