# Hermes Usage Hook

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) hook that appends
your **LLM provider's rate-limit usage** to the end of every reply.

It detects which provider produced the reply (Codex or MiniMax), fetches that
provider's current usage, and appends a summary — one line per available
window (the 5h window, plus the weekly window when present) — such as:

```
Codex 5h | used 42%, left 58% (resets in 2h17m) | plan pro
Codex weekly | used 10%, left 90% (resets in 6d4h)
MiniMax 5h | used 4%, left 96% (resets in 4h41m)
MiniMax weekly | used 30%, left 70% (resets in 6d)
```

The summary rides on the agent's own reply, so Hermes delivers it wherever the
conversation came from (Telegram → that chat, Discord → that channel) — no bot
tokens and no per-platform code.

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
| `plugin/plugin.yaml` | Hermes plugin manifest: declares the plugin name, `kind: standalone`, and the `transform_llm_output` hook it provides, so Hermes discovery recognizes the directory. |
| `plugin/__init__.py` | Plugin root entry point: puts the plugin directory on `sys.path` and re-exports `register(ctx)` from the footer hook. |
| `plugin/usage.py` | Provider detection + dispatch: maps a reply's `model` to a provider, fetches its normalized usage, and renders the summary. |
| `plugin/providers/codex_usage.py` | Read `auth.json`, refresh token, fetch and normalize Codex usage. |
| `plugin/providers/minimax_usage.py` | Resolve the MiniMax API token, fetch and normalize MiniMax usage. |
| `plugin/hooks/footer_hook.py` | The Hermes hook that appends the provider's usage to each reply. |

## Local development

The repo root holds a development-only `pyproject.toml` (it is **not** shipped —
`install.py` copies only `plugin/`). It pins the runtime dependencies to the
versions Hermes provides (`httpx==0.28.1`, `pyyaml==6.0.3`) and declares the dev
tools (`pytest`, `ruff`, `ty`), so local checks run against the same versions
the plugin sees at load time. Create the environment with [uv](https://docs.astral.sh/uv/):

```bash
uv sync            # create .venv with pinned runtime deps + dev tools
uv run pytest      # run the test suite under tests/
uv run ruff check .
uv run ty check
```

## Quick check (before deploying)

Confirm you can fetch usage with your current login:

```bash
# Requires the Codex CLI to be logged in (`codex login`) so ~/.codex/auth.json exists.
uv run plugin/providers/codex_usage.py
# or, if httpx is already installed:
python plugin/providers/codex_usage.py
```

You should see the normalized JSON plus the rendered summary.

## Install

The plugin ships under the repo's `plugin/` subdirectory. The quickest way to
install is the one-command installer, which copies that directory into Hermes'
plugins dir and enables it for you:

```bash
git clone git@github.com:chenwei791129/hermes-usage-hook.git
cd hermes-usage-hook
uv run install.py
```

`install.py` copies `plugin/` to `$HERMES_HOME/plugins/hermes-usage-hook/`
(`HERMES_HOME` defaults to `~/.hermes`) and adds `hermes-usage-hook` to
`plugins.enabled` in `$HERMES_HOME/config.yaml`. Re-running it is safe — it
overwrites the install and never duplicates the enable entry. Restart Hermes,
and the footer appears under each reply.

### Manual install (alternative)

Hermes loads plugins as **directories** that contain a `plugin.yaml` manifest,
and third-party (`kind: standalone`) plugins stay disabled until you enable them
explicitly. So installation is two steps: install the directory, then enable it.

**1. Install the plugin directory.** All plugin files live under the repo's
`plugin/` subdirectory; install that subdirectory (not the whole repo, which
also carries `tests/`, `openspec/`, and git metadata) into Hermes' plugins
directory as `hermes-usage-hook/`:

```bash
git clone git@github.com:chenwei791129/hermes-usage-hook.git
mkdir -p ~/.hermes/plugins

# Copy just the plugin/ subdirectory (remove any previous copy first so a
# re-install replaces it instead of nesting plugin/ inside the existing dir):
rm -rf ~/.hermes/plugins/hermes-usage-hook
cp -r hermes-usage-hook/plugin ~/.hermes/plugins/hermes-usage-hook
# …or symlink it instead (handy during development):
# ln -s "$(pwd)/hermes-usage-hook/plugin" ~/.hermes/plugins/hermes-usage-hook
```

**2. Enable the plugin.** Add `hermes-usage-hook` to `plugins.enabled` in
`~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - hermes-usage-hook
```

or, equivalently, run `hermes plugins enable hermes-usage-hook`.

**3. Confirm discovery.** Run `hermes plugins` — `hermes-usage-hook` should
appear in the list (this confirms the manifest was found). Restart Hermes and
the footer appears under each reply. `CODEX_HOME` is honored if your Codex
install uses a non-default home.

> **Streaming caveat:** if your deployment streams responses, the reply body is
> already sent before this hook runs, so the footer may not be applied.

## Troubleshooting

- **`auth.json` not found** — run `codex login` so the Codex CLI creates it.
- **401/403** — the Codex usage endpoint needs ChatGPT **OAuth** credentials. An
  API-key-only `auth.json` is rejected; log in with a ChatGPT account
  (`codex login`). If you already use OAuth, the refresh token may be expired or
  revoked — re-run `codex login`.
- **Nothing happens** — confirm `hermes plugins` lists `hermes-usage-hook` (the
  directory is installed and the manifest was found) and that it's in
  `plugins.enabled` in `~/.hermes/config.yaml`, then restart Hermes. Hook errors
  are logged to stderr, prefixed `[hermes-usage-hook]`.

## License

MIT
