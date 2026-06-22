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
| `hooks/footer_hook.py` | Hermes **plugin hook** (`transform_llm_output`) — appends usage to each reply, **auto-routed back to the user's current platform** (Telegram → that chat, Discord → that channel). **Recommended.** |
| `hooks/plugin_hook.py` | Hermes **plugin hook** (`on_session_end`) — sends a separate notification to a **fixed** destination (desktop / webhook). Runs in CLI **and** gateway. |
| `hooks/gateway/HOOK.yaml` + `hooks/gateway/handler.py` | Hermes **gateway hook** (`agent:end`) — same fixed-destination notifier, gateway mode only. |

Two delivery styles, pick by what you want:

- **Route to the user's current platform** → use `footer_hook.py`. The usage
  rides on the agent's reply, so Hermes delivers it wherever the user is, with no
  bot tokens and no per-platform code. (Caveat: streaming deployments — see below.)
- **Notify a fixed destination** (a desktop notification or one webhook,
  regardless of which chat triggered it) → use `plugin_hook.py` or the gateway
  hook, configured via `CODEX_USAGE_NOTIFIER`.

## Hermes hook reference

Hermes has **three independent hook systems**. All three are non-blocking,
catch their own errors, and never crash the agent.

| System | Defined in | Runs in | Can block / rewrite? |
| --- | --- | --- | --- |
| **Gateway hooks** | `~/.hermes/hooks/<name>/` (`HOOK.yaml` + `handler.py`) | Messaging gateway only (Telegram/Discord/Slack/…) — not the CLI | Observe only |
| **Plugin hooks** | A Python plugin's `ctx.register_hook(...)` | CLI **and** gateway | Some can block / inject |
| **Shell hooks** | The `hooks:` block in `~/.hermes/config.yaml` (calls an external script) | CLI **and** gateway | Some can block / inject |

### Events

**Gateway events** (`namespace:action` form, loaded by `gateway/hooks.py`)

| Event | Fires when | Notable context |
| --- | --- | --- |
| `gateway:startup` | Gateway starts | — |
| `session:start` / `session:end` / `session:reset` | Messaging session starts / ends / resets | `platform`, `user_id`, `session_key` |
| `agent:start` | Agent begins handling a message | `platform`, `user_id`, `session_id` |
| `agent:step` | Each tool-call loop iteration | `iteration`, `tool_names` |
| `agent:end` | Agent finishes handling a message (closest to "turn end") | `message`, `response` |
| `command:*` | Any slash command (wildcard) | command args |

**Plugin / Shell hook events** (fired in `agent/conversation_loop.py` and `agent/turn_finalizer.py`)

| Event | Fires when | Notable context |
| --- | --- | --- |
| `pre_llm_call` / `post_llm_call` | Before / after each turn | `approx_input_tokens` (pre), `assistant_response` (post) |
| `on_session_start` / `on_session_end` / `on_session_finalize` / `on_session_reset` | Conversation lifecycle; `on_session_end` fires at the end of every `run_conversation()` (success or interrupt) | `session_id`, `completed`, `interrupted` |
| `pre_tool_call` / `post_tool_call` / `transform_tool_result` | Around tool execution | `tool_name`, `tool_input` |
| `transform_llm_output` | Before the response is sent; return a non-empty string to replace it (rides Hermes' delivery path → auto-routes to the user's platform) | `response_text`, `session_id`, `model`, `platform` |
| `subagent_start` / `subagent_stop`, `pre_gateway_dispatch`, `pre_approval_request` / `post_approval_response` | Subagents, dispatch, approvals | varies |

> Shell hooks support a smaller subset: `pre_tool_call`, `post_tool_call`,
> `on_session_start`, `on_session_end`, `subagent_stop`.

Only three events can **change behavior** — `pre_tool_call` (block a tool),
`pre_llm_call` (inject context), and `pre_gateway_dispatch` (skip/rewrite/allow).
Everything else is a fire-and-forget observer.

**What this project uses:** `footer_hook.py` subscribes to
**`transform_llm_output`** (appends the usage to the reply, so it auto-routes to
the user's platform — the recommended path). The fixed-destination variants use
**`on_session_end`** (plugin, CLI + gateway) and **`agent:end`** (gateway only).
None use `session:end`, which only fires when the whole messaging session ends,
and to *actively* push at `agent:end` you would need the `chat_id` from its
context plus each platform's API token — which is exactly what the footer avoids.

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

Hermes loads hooks from `~/.hermes/`. Every option needs the shared module:

```bash
git clone git@github.com:<you>/hermes-codex-usage-hook.git
cd hermes-codex-usage-hook
mkdir -p ~/.hermes/lib
cp codex_usage.py ~/.hermes/lib/
```

Then pick **one** option.

### Option A — Footer on the reply (recommended: routes to the user's platform)

`transform_llm_output` appends the usage to the agent's reply, so Hermes
delivers it back to whatever platform the conversation came from (Telegram → that
chat, Discord → that channel). No bot tokens, no `chat_id`, no per-platform code.

```bash
mkdir -p ~/.hermes/plugins
cp hooks/footer_hook.py ~/.hermes/plugins/codex_usage_footer.py
```

Restart Hermes; it discovers `register(ctx)` and the footer appears under each
reply. No configuration is required.

> **Streaming caveat:** if your deployment streams responses, the reply body is
> already sent before this hook runs, so the footer may not be applied. If it
> never appears, use Option C (the `agent:end` gateway hook) instead.

### Option B — Fixed-destination notification, CLI + gateway

`on_session_end` fires at the end of every conversation (CLI and gateway) and
sends a separate notification to one fixed place (see Configuration).

```bash
mkdir -p ~/.hermes/plugins
cp hooks/plugin_hook.py ~/.hermes/plugins/codex_usage_hook.py
```

### Option C — Fixed-destination notification, gateway only

Gateway hooks live in `~/.hermes/hooks/<name>/` as `HOOK.yaml` + `handler.py`.

```bash
mkdir -p ~/.hermes/hooks/codex-usage-notify
cp hooks/plugin_hook.py ~/.hermes/lib/        # handler.py imports _notify from it
cp hooks/gateway/HOOK.yaml hooks/gateway/handler.py ~/.hermes/hooks/codex-usage-notify/
```

Restart the gateway. On each `agent:end` event the handler fetches usage and
notifies.

## Configuration

Option A (the footer) needs no configuration — restart and it works.

Options B and C select where the notification goes with the
`CODEX_USAGE_NOTIFIER` environment variable:

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
