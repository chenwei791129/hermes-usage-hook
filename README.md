# hermes-usage-hook

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) hook that appends
your **LLM provider's rate-limit usage** to the end of every reply.

It detects which provider produced the reply (Codex or MiniMax), fetches that
provider's current usage, and appends a one-line summary such as:

```
Codex 5h | used 42%, left 58% (resets in 137 min) | plan pro
MiniMax 5h | used 4%, left 96% (resets in 281 min)
```

The summary rides on the agent's own reply, so Hermes delivers it wherever the
conversation came from (Telegram → that chat, Discord → that channel) — no bot
tokens, no per-platform code, and no configuration.

## How it works

The hook detects the provider from the reply's `model` name (case-insensitive)
and fetches **only** that provider's usage. A MiniMax reply shows MiniMax usage,
a Codex reply shows Codex usage, and anything else is left untouched.

| Provider | Matches when `model` … | Example models |
| --- | --- | --- |
| **Codex** | contains `codex`, or starts with `gpt-`, `o1`, `o3`, or `o4` | `gpt-5-codex`, `o3-mini` |
| **MiniMax** | contains `minimax` or `abab` | `MiniMax-M2.5`, `abab6.5s-chat` |
| _none_ | anything else, or no `model` | `claude-opus-4` → reply unchanged |

Every fetch is wrapped so a failure never breaks the reply — if usage can't be
retrieved, the footer is simply skipped.

### Codex usage

Codex has no public usage API, so the hook reuses the OAuth credentials the
Codex CLI stores in `~/.codex/auth.json` (or `$CODEX_HOME/auth.json`) and queries
the same internal endpoint the Codex CLI's `/status` uses. When the token is
stale it refreshes automatically and writes the new token back.

> Codex's 5-hour window is an **account-wide** rolling quota, not a
> per-conversation total — the same figure shown by the Codex CLI.

### MiniMax usage

The MiniMax fetcher needs an API token (pure API key — no OAuth), resolved in
this order:

1. The `MINIMAX_API_KEY` environment variable (a blank value is treated as unset).
2. A `MINIMAX_API_KEY=<value>` line in `$HERMES_HOME/.env` (defaulting to
   `~/.hermes/.env` when `HERMES_HOME` is unset). Surrounding quotes are stripped.

If neither yields a token, the MiniMax fetch is skipped. MiniMax has no plan
tier, so the `| plan …` segment is omitted.

## Files

| File | Purpose |
| --- | --- |
| `usage.py` | Provider detection + dispatch: maps a reply's `model` to a provider, fetches its normalized usage, and renders the summary. |
| `providers/codex_usage.py` | Read `auth.json`, refresh token, fetch and normalize Codex usage. |
| `providers/minimax_usage.py` | Resolve the MiniMax API token, fetch and normalize MiniMax usage. |
| `hooks/footer_hook.py` | The Hermes hook that appends the provider's usage to each reply. |

## Quick check (before deploying)

Confirm you can fetch usage with your current login:

```bash
# Requires the Codex CLI to be logged in (`codex login`) so ~/.codex/auth.json exists.
uv run providers/codex_usage.py
# or, if httpx is already installed:
python providers/codex_usage.py
```

You should see the normalized JSON plus a one-line summary.

## Install

```bash
git clone git@github.com:chenwei791129/hermes-usage-hook.git
cd hermes-usage-hook

# Shared modules + the footer hook. Copy the whole providers/ package
# (including its __init__.py) so the hook can import providers.* at startup.
mkdir -p ~/.hermes/lib ~/.hermes/plugins
cp usage.py ~/.hermes/lib/
cp -r providers ~/.hermes/lib/
cp hooks/footer_hook.py ~/.hermes/plugins/usage_footer.py
```

Restart Hermes and the footer appears under each reply. No configuration is
needed; `CODEX_HOME` is honored if your Codex install uses a non-default home.

> **Streaming caveat:** if your deployment streams responses, the reply body is
> already sent before this hook runs, so the footer may not be applied.

## Troubleshooting

- **`auth.json` not found** — run `codex login` so the Codex CLI creates it.
- **401/403** — the Codex usage endpoint needs ChatGPT **OAuth** credentials. An
  API-key-only `auth.json` is rejected; log in with a ChatGPT account
  (`codex login`). If you already use OAuth, the refresh token may be expired or
  revoked — re-run `codex login`.
- **Nothing happens** — confirm the files landed in the right directories and
  restart Hermes; hook errors are logged to stderr, prefixed `[hermes-usage-hook]`.

## License

MIT
