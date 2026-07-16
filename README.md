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

Codex has no public usage API, so the hook reuses OAuth credentials from
Hermes' credential store (`$HERMES_HOME/auth.json`, including both
`providers.openai-codex` and `credential_pool.openai-codex` layouts) or, when
run standalone, the Codex CLI store in `~/.codex/auth.json` (or
`$CODEX_HOME/auth.json`). It queries the same internal, unstable ChatGPT
backend API that Codex tooling uses. The internal, unstable ChatGPT backend API
can change without notice. The hook only **reads** the access token — it never
refreshes or writes back. Under Hermes the credential store is Hermes' own, and
Hermes keeps the token fresh; if the token is expired the usage call fails and
the footer is simply omitted.

> Codex's 5-hour window is an **account-wide** rolling quota, not a
> per-conversation total — the same figure shown by the Codex CLI.

### Codex auto reset

Codex auto reset is disabled by default. When enabled, it can autonomously
consume one Codex reset credit after the weekly remaining percentage reaches the
configured threshold. That consumption is irreversible, so enabling
`plugins.entries.hermes-usage-hook.auto_reset.enabled` is explicit standing
authorization for autonomous reset-credit use.

Canonical Hermes plugin config:

```yaml
plugins:
  entries:
    hermes-usage-hook:
      auto_reset:
        enabled: true
        threshold: 0
```

Equivalent CLI configuration:

```bash
hermes config set plugins.entries.hermes-usage-hook.auto_reset.enabled true
hermes config set plugins.entries.hermes-usage-hook.auto_reset.threshold 0
```

`plugins.entries.hermes-usage-hook.auto_reset.enabled` defaults to `false`.
`plugins.entries.hermes-usage-hook.auto_reset.threshold` defaults to
`threshold: 0`, uses weekly remaining semantics, and accepts only `0..99`.
Eligibility is `weekly remaining <= threshold`; `100` is intentionally invalid
because a freshly reset weekly window has 100% remaining and would qualify
again.

Optional environment overrides are available for process-managed deployments:
`CODEX_ENABLE_AUTORESET` and `CODEX_AUTORESET_THRESHOLD`. Precedence is
env → plugin config → defaults. Plugin config is read through Hermes
`load_config()` on each hook invocation, so `config.yaml` edits can take effect
without reinstalling the plugin. Process environment changes require a Gateway
restart/reload.

Hermes documents `plugins.entries.<plugin_id>` for plugin LLM trust
configuration at
`https://hermes-agent.nousresearch.com/docs/developer-guide/plugin-llm-access#trust-gate`.
This plugin also reads its own `auto_reset.*` schema from the same plugin entry
via `load_config()`; Hermes does not provide a generic plugin-config UI/schema
for these values.

OAuth credentials do not belong in plugin config. Keep ChatGPT OAuth state in
Hermes' `auth.json` or the Codex CLI auth store. Pending attempts and cooldowns
live in `$HERMES_HOME/state/hermes-usage-hook/autoreset.json`, protected by
`autoreset.lock/`. Every successful terminal transition stores its one-shot audit
notice in `autoreset.json` in the same coordinator-locked atomic write that
clears pending state and sets the success cooldown. The footer also drains the
separate `autoreset-notices.json` queue, protected by
`autoreset-notices.lock/`, when present, without allowing notice updates to
overwrite consume idempotency state. These files store only
non-sensitive identifiers, cooldowns, and audit values.

The plugin ships dual hooks: `pre_llm_call` checks before the provider request
so an already-exhausted weekly window can be reset before the model call, and
`transform_llm_output` checks after a successful reply, refreshes usage after a
reset, and appends a one-shot audit line. When auto reset is disabled, the
pre-request hook makes no usage or credit API calls and injects no model
context; the normal footer still works.

Reset credit selection is idempotent: the coordinator chooses the
earliest-expiring available credit, persists a redeem request ID before POST,
and reuses that ID on ambiguous retries. Null expiries sort last. Missing
credits, nothing-to-reset responses, deterministic failures, and unknown
responses enter short cooldowns to avoid per-hook POST spam; transient GET
failures use a shorter retry cooldown. A successful terminal response also sets
a five-minute suppression window so stale usage during backend propagation cannot
start a second consume attempt.

After a successful reset, the footer includes an audit example like:

```text
Codex auto reset | weekly 0% → 100% | reset credits 3 → 2
```

Do not add auto-reset values or `requires_env` to `plugin/plugin.yaml`; the
manifest only declares the supported hooks.

### Reset history

Each successful Codex auto reset also appends one line to a permanent, local
history file:

```text
$HERMES_HOME/logs/hermes-usage-hook-autoreset.jsonl
```

The append is best-effort: if it fails, the reset outcome, footer, and one-shot
notice are unchanged and only a static warning is logged. The file is never
rotated, truncated, or pruned — it is kept permanently (about 200 bytes per
event, roughly one event per week). Each record is privacy-minimized: it stores
only a hashed event ID (`sha256:<hex>` of the redeem request ID — never the raw
ID), an RFC 3339 UTC timestamp, the backend status, and the before/after weekly
and credit usage snapshots. No raw request, credit, session, or account
identifiers are ever written.

Query the history from any chat platform with the in-session command
`/usagehook history [N]` (N is 1–100; defaults to the newest 5 events):

```text
/usagehook history
Codex auto-reset history (last 1)
2026-07-14 09:12 UTC | reset | weekly 4% → 100% | credits 3 → 2
```

Unavailable snapshot values render as `?`. When no history exists yet the
command replies `No Codex auto-reset history yet.`

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
| `plugin/plugin.yaml` | Hermes plugin manifest: declares the plugin name, `kind: standalone`, and exactly two hooks: `transform_llm_output` and `pre_llm_call`. |
| `plugin/__init__.py` | Plugin root entry point: puts the plugin directory on `sys.path` and re-exports `register(ctx)` from the footer hook. |
| `plugin/usage.py` | Provider detection + dispatch: maps a reply's `model` to a provider, fetches its normalized usage, and renders the summary. |
| `plugin/autoreset.py` | Codex auto-reset config, threshold policy, earliest-expiry credit selection, state, lock, cooldowns, idempotency, and one-shot notices. |
| `plugin/autoreset_audit.py` | Best-effort permanent reset history: build privacy-minimized flat events, append (deduplicated by hashed event ID), and read them back leniently. |
| `plugin/hermes_home.py` | Profile-safe Hermes home resolution via `hermes_constants.get_hermes_home()`, falling back to `HERMES_HOME` when that module is absent. |
| `plugin/providers/codex_usage.py` | Read `auth.json` (read-only), fetch and normalize Codex usage, list reset credits, and POST one idempotent reset-credit consume attempt. |
| `plugin/providers/minimax_usage.py` | Resolve the MiniMax API token, fetch and normalize MiniMax usage. |
| `plugin/hooks/footer_hook.py` | The Hermes hook module that registers the footer and Codex preflight hooks, the `/usagehook` history command, appends usage, and renders auto-reset audit notices. |

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

The quickest way to install is the one-command installer, `install.py`. It runs
**directly from its raw URL — no clone required** — and by default downloads the
plugin from the project's latest GitHub release:

```bash
uv run https://raw.githubusercontent.com/chenwei791129/hermes-usage-hook/main/install.py
```

The installer downloads the latest release's source tarball, extracts the
`plugin/` directory from it, copies that to `$HERMES_HOME/plugins/hermes-usage-hook/`
(`HERMES_HOME` defaults to `~/.hermes`), and adds `hermes-usage-hook` to
`plugins.enabled` in `$HERMES_HOME/config.yaml`. Re-running it is safe — it
overwrites the install and never duplicates the enable entry. Restart Hermes,
and the footer appears under each reply.

> The default install needs network access to reach GitHub. **Offline?** Clone
> the repo and install from the local `plugin/` with `--local` (see below).

### Modes and flags

`install.py` has two modes: `install` (the default when no subcommand is given)
and `remove`. Download and extraction use only the Python standard library;
`pyyaml` is the sole runtime dependency.

**Install a specific release** with `--version` (the tag is matched with and
without a leading `v`):

```bash
uv run https://raw.githubusercontent.com/chenwei791129/hermes-usage-hook/main/install.py --version 0.2.0
```

**Install from a local checkout** with `--local`. With no path it uses the
`plugin/` directory next to the script (the classic clone-and-install flow); a
remote invocation must pass an explicit existing path:

```bash
git clone git@github.com:chenwei791129/hermes-usage-hook.git
cd hermes-usage-hook
uv run install.py --local
```

`--local` and `--version` are mutually exclusive (a local directory has no
release version).

**Remove the plugin** with the `remove` subcommand. It deletes the installed
directory and removes the `plugins.enabled` entry; both actions are idempotent:

```bash
uv run https://raw.githubusercontent.com/chenwei791129/hermes-usage-hook/main/install.py remove
```

`remove --version TAG` acts as a **version guard**: it reads the installed
`plugin.yaml` and only removes the plugin when its version matches `TAG`,
otherwise it exits non-zero without deleting anything.

**Flags** (available in both modes unless noted):

| Flag                 | Effect                                                                             |
| -------------------- | ---------------------------------------------------------------------------------- |
| `--version TAG`      | install a specific release tag (install), or guard removal by version (remove)     |
| `--local [PATH]`     | install from a local directory instead of a release (install only)                 |
| `--repo OWNER/NAME`  | source repository for downloads, default `chenwei791129/hermes-usage-hook` (install only) |
| `--hermes-home PATH` | override the Hermes home dir; takes precedence over `HERMES_HOME` (default `~/.hermes`) |
| `--no-enable`        | only copy/remove the plugin directory; do not touch `config.yaml`                  |
| `--dry-run`          | print the planned actions without downloading, writing, or deleting anything       |
| `-v`, `--verbose`    | emit diagnostic detail (resolved release tag, tarball URL, extraction path)        |

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
  (`codex login`). The hook does not refresh tokens: under Hermes, Hermes keeps
  the access token fresh; standalone, an expired token means you re-run
  `codex login`.
- **Nothing happens** — confirm `hermes plugins` lists `hermes-usage-hook` (the
  directory is installed and the manifest was found) and that it's in
  `plugins.enabled` in `~/.hermes/config.yaml`, then restart Hermes. Hook errors
  are logged to stderr, prefixed `[hermes-usage-hook]`.
- **Auto reset never runs** — confirm
  `plugins.entries.hermes-usage-hook.auto_reset.enabled` is true or
  `CODEX_ENABLE_AUTORESET=true` is present in the Gateway process environment.
  Keep `plugins.enabled` separate from the plugin's `auto_reset.*` settings.
- **Auto reset waits after a failure** — cooldowns are intentional. They prevent
  repeated consume attempts after no-credit, nothing-to-reset, transient, or
  ambiguous backend responses.

## License

MIT
