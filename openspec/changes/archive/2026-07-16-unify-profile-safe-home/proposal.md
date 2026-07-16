## Summary

Route the plugin's env-only home resolver through the profile-safe resolver so coordinator state, locks, notices, and reset history all resolve the Hermes home the same official way, then drop the query-side workaround that only existed to paper over the split.

## Motivation

The plugin resolves its home directory two different ways. The audit-history module resolves through `resolve_hermes_home()`, which prefers the official `hermes_constants.get_hermes_home()` (honoring profile override and platform defaults) and falls back to the `HERMES_HOME` environment variable. The coordinator's state store, both lock acquirers, and therefore the history write path all resolve through the older private env-only helper, which reads only `HERMES_HOME`/`~/.hermes` and ignores profiles and platform defaults.

Because every production call injects the coordinator's env-only home, the profile-safe branch is never exercised at runtime — it fires only in unit tests. On any environment where the official resolver would return a different path (an active Hermes profile override, or a platform default such as Windows AppData/Local), the plugin writes state, locks, notices, and history under `~/.hermes` instead of the profile-safe location the framework expects. The reset-history query also carries a workaround: it reads the coordinator's env-only home explicitly, purely to stay consistent with the write path, which permanently defeats the profile-safe resolver on the read side.

Unifying on one resolver makes the plugin actually profile-safe everywhere, removes the duplicated fallback, and lets the query read without the injection workaround because read and write now resolve identically.

## Proposed Solution

- Make the plugin's env-only home helper delegate to `resolve_hermes_home()` so the coordinator state store, both lock acquirers, and the history write path all resolve the Hermes home through the official profile-safe resolver, with the same `HERMES_HOME` fallback preserved when the official module is absent.
- Remove the injected-home workaround in the reset-history query so it reads the history file through the default profile-safe resolution, which now matches the write path.
- Update the history-query regression test whose premise (query reads the env-only coordinator home and ignores the profile-safe default) is inverted by unification, replacing it with a test asserting read and write resolve to the same profile-safe home.

## Non-Goals

- No data migration: existing installs use `~/.hermes` with `HERMES_HOME` matching the official resolver's result, so no state/lock/notice/history files move. Migration tooling is explicitly out of scope.
- No change to the profile-safe resolver's own contract, the auto-reset eligibility/cooldown/pending/notice state machine, or the reset-history event schema and query behavior.
- No new configuration keys, network calls, or user-facing output changes.

## Alternatives Considered

- Keep the two resolvers and only fix the query to inject the coordinator home (the current workaround). Rejected: it hard-codes the plugin to the non-profile-safe home forever, leaving the official resolver dead in production and the framework's profile/platform handling unused.
- Add migration tooling to relocate existing files when the official resolver differs. Rejected as unnecessary for this project's single-user `~/.hermes` deployment, where the resolvers already agree.

## Impact

- Affected specs: new capability `plugin-home-resolution`.
- Affected code:
  - Modified: `plugin/autoreset.py` (env-only home helper delegates to the profile-safe resolver), `plugin/hooks/footer_hook.py` (remove the reset-history query's injected-home workaround), `tests/test_autoreset.py` (add profile-safe resolution tests for state/locks/notices), `tests/test_usage.py` (update the inverted regression test)
  - New: none
  - Removed: none
