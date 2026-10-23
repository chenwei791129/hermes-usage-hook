# Hermes Usage Hook

[![release-please](https://github.com/chenwei791129/hermes-usage-hook/actions/workflows/release-please.yml/badge.svg?branch=main)](https://github.com/chenwei791129/hermes-usage-hook/actions/workflows/release-please.yml)

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that
appends your **LLM provider's rate-limit usage** to the end of every reply.

It detects which provider produced the reply, fetches that provider's current
usage, and appends one line per available window (the 5h window, plus the weekly
window when present):

```
Codex 5h | used 42%, left 58% (resets in 2h17m) | plan pro
Codex weekly | used 10%, left 90% (resets in 6d4h)
MiniMax 5h | used 4%, left 96% (resets in 4h41m)
MiniMax weekly | used 30%, left 70% (resets in 6d)
```

The summary rides on the agent's own reply, so Hermes delivers it wherever the
conversation came from (Telegram → that chat, Discord → that channel) — no bot
tokens and no per-platform code. A failed usage fetch never breaks the reply;
the footer is simply skipped.

## Supported providers

The provider is detected from the reply's `model` name (case-insensitive), and
only that provider's usage is fetched:

| Provider | Matches when `model` … | Example models |
| --- | --- | --- |
| **Codex** | contains `codex`, or starts with `gpt-`, `o1`, `o3`, or `o4` | `gpt-5-codex`, `o3-mini` |
| **MiniMax** | contains `minimax` or `abab` | `MiniMax-M2.5`, `abab6.5s-chat` |
| _none_ | anything else, or no `model` | `claude-opus-4` → reply unchanged |

## Install

Run the installer straight from its raw URL — no clone required:

```bash
uv run https://raw.githubusercontent.com/chenwei791129/hermes-usage-hook/main/install.py
```

It downloads the latest GitHub release, copies the plugin into
`$HERMES_HOME/plugins/hermes-usage-hook/` (`HERMES_HOME` defaults to
`~/.hermes`), and adds `hermes-usage-hook` to `plugins.enabled` in
`$HERMES_HOME/config.yaml`. Re-running it is safe: it overwrites the install and
never duplicates the enable entry. Restart Hermes afterwards.

Remove it again with the `remove` subcommand:

```bash
uv run https://raw.githubusercontent.com/chenwei791129/hermes-usage-hook/main/install.py remove
```

`pyyaml` is the only runtime dependency; download and extraction use just the
Python standard library.

| Flag | Effect |
| --- | --- |
| `--version TAG` | install a specific release tag (install), or remove only if the installed version matches (remove) |
| `--ref BRANCH_OR_SHA` | install a branch/tag/commit tarball, e.g. `--ref main` for unreleased changes (install only) |
| `--local [PATH]` | install from a local directory instead of a release; defaults to the `plugin/` next to the script (install only) |
| `--repo OWNER/NAME` | source repository, default `chenwei791129/hermes-usage-hook` (install only) |
| `--hermes-home PATH` | override the Hermes home dir; takes precedence over `HERMES_HOME` |
| `--no-enable` | only copy/remove the plugin directory; do not touch `config.yaml` |
| `--dry-run` | print the planned actions without downloading, writing, or deleting |
| `-v`, `--verbose` | emit diagnostic detail (resolved tag, tarball URL, extraction path) |

`--local`, `--version`, and `--ref` are mutually exclusive — each names a
different install source. The default install needs network access to reach
GitHub; offline, clone the repo and use `--local`.

### Installing through Hermes' own plugin manager

`hermes plugins install` and the dashboard's Git install field take the same
identifier. The plugin lives in this repo's `plugin/` subdirectory, so the
identifier **must name that subdirectory**:

```
chenwei791129/hermes-usage-hook/plugin
```

`https://github.com/chenwei791129/hermes-usage-hook/tree/main/plugin` and
`https://github.com/chenwei791129/hermes-usage-hook.git#plugin` are equivalent.

Always include `/plugin`: Hermes does not automatically select the plugin
subdirectory. Omitting it installs the **whole repository**, including tests
and specs. If you previously installed without the subdirectory, remove that
installation and reinstall with the identifier above.

This path installs the default branch's latest commit, not the latest release.
The branch segment in a GitHub `tree` URL is ignored; use the installer above
when you need a release tag or branch.

Update a Hermes-managed installation with:

```bash
hermes plugins update hermes-usage-hook
```

The dashboard's update action works too. Hermes updates subdirectory installs
from their recorded source; no Git checkout is required in the installed
plugin directory. This behavior is confirmed in the Hermes v0.22.5 source and
upstream regression tests, but has not been tested end-to-end with this plugin.

Custom-source installs pinned with Hermes's `--ref` do not follow updates;
changing the pin requires an explicit reinstall. Unlike this repo's
`install.py --ref`, Hermes's `--ref` accepts only a full commit SHA, not a
branch or tag. Catalog-managed pins have a separate reviewed-update workflow.

If you installed with `install.py`, update by re-running that installer.

## After installing

Each provider reads its own credentials, and without them that provider's
footer is skipped:

- **Codex** needs ChatGPT **OAuth** credentials, read from Hermes'
  `$HERMES_HOME/auth.json` or the Codex CLI store at `~/.codex/auth.json`
  (`codex login` creates the latter). An API-key-only `auth.json` is rejected.
- **MiniMax** needs `MINIMAX_API_KEY`, from the environment or a
  `MINIMAX_API_KEY=<value>` line in `$HERMES_HOME/.env`.

See [`plugin/after-install.md`](plugin/after-install.md) for the full setup
notes, including optional Codex auto reset.

## License

MIT
