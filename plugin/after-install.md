# Hermes Usage Hook — after install

A few steps decide whether the footer actually shows up.

## 1. Confirm the plugin is enabled

Third-party (`kind: standalone`) plugins stay disabled until they are enabled,
so check the listing and enable it if it is missing:

```bash
hermes plugins                     # hermes-usage-hook should be listed
hermes plugins enable hermes-usage-hook
```

That is the same as adding `hermes-usage-hook` to `plugins.enabled` in
`$HERMES_HOME/config.yaml` (`HERMES_HOME` defaults to `~/.hermes`). Restart
Hermes once the steps below are done.

## 2. Codex usage needs ChatGPT OAuth credentials

Codex has no public usage API, so the hook reuses OAuth credentials that are
already on the machine — Hermes' own credential store (`$HERMES_HOME/auth.json`)
or, when running standalone, the Codex CLI store at `~/.codex/auth.json`
(`$CODEX_HOME/auth.json` if you use a non-default Codex home). Run `codex login`
if that file does not exist yet; an API-key-only `auth.json` is rejected by the
usage endpoint.

The hook only **reads** the access token — it never refreshes it and never
writes back, so under Hermes it relies on Hermes keeping the token fresh. An
expired token means the usage call fails and the usage lines are omitted; with
the model display from section 5 enabled, the `Model` line still remains.

## 3. MiniMax usage needs `MINIMAX_API_KEY`

The MiniMax fetcher takes a plain API key (no OAuth) from either:

1. the `MINIMAX_API_KEY` environment variable (a blank value counts as unset), or
2. a `MINIMAX_API_KEY=<value>` line in `$HERMES_HOME/.env`.

Without a token the MiniMax fetch is skipped.

Neither provider's credentials belong in the plugin config — keep them in the
stores above.

## 4. Codex auto reset is disabled by default

Auto reset stays off unless you turn it on. When enabled, the plugin can
autonomously consume one Codex reset credit once the weekly remaining percentage
reaches the configured threshold. **That consumption is irreversible**, so
setting `plugins.entries.hermes-usage-hook.auto_reset.enabled` to `true` is
explicit standing authorization for autonomous reset-credit use.

```bash
hermes config set plugins.entries.hermes-usage-hook.auto_reset.enabled true
hermes config set plugins.entries.hermes-usage-hook.auto_reset.threshold 1
```

`threshold` uses weekly-remaining semantics and accepts explicit values `1..99`. Explicit `0` fails closed and emits a warning; if Hermes has already frozen the Codex credential as `exhausted`, use `/usage reset` to recover it manually. Once auto reset
is on, `/usagehook history [N]` reports past resets from any chat platform (`N`
is 1–100, newest 5 by default).

## 5. Footer model line is disabled by default

The footer can also show which model answered the reply. The line is off unless
you turn it on:

```bash
hermes config set plugins.entries.hermes-usage-hook.footer.show_model true
```

Set it back to `false` (or `null`) to turn it off. Only the YAML boolean `true`
enables it; any other value is treated as off and logs one
`[hermes-usage-hook]` warning. The setting is re-read on every reply, so no
reinstall or restart is needed. When enabled, the model line sits above the
usage lines:

```text
───
Model gpt-5.5-codex
Codex 5h | used 42%, left 58% (resets in 2h17m) | plan pro
Codex weekly | used 10%, left 90% (resets in 6d4h)
```

With it enabled, a reply from a model this plugin has no usage provider for —
or one whose usage fetch fails — still gets a footer carrying only the `Model`
line. Because Hermes stops at the first `transform_llm_output` hook that returns
text, any other `transform_llm_output` plugin ordered after this one is then no
longer called for those replies either.

## Streaming caveat

If your deployment streams responses, the reply body is already sent before this
hook runs, so the footer may not be applied.
