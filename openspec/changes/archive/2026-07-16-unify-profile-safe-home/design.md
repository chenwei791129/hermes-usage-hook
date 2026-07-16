## Context

The plugin resolves its Hermes home two ways. `plugin/autoreset_audit.py` uses `resolve_hermes_home()` from `plugin/hermes_home.py`, which prefers `hermes_constants.get_hermes_home()` (profile override + platform defaults) and falls back to `HERMES_HOME`/`~/.hermes`. The coordinator's state store and both lock acquirers in `plugin/autoreset.py` use the older private env-only helper (`_hermes_home()`), which reads only `HERMES_HOME`/`~/.hermes`.

Every production call anchors the history write to the coordinator's env-only home (the state store threads its own `home` into the append), and the reset-history query injects that same env-only home to stay consistent. As a result the profile-safe branch in `resolve_hermes_home()` never runs in production — it is exercised only by unit tests. On any environment where `get_hermes_home()` differs from `HERMES_HOME`/`~/.hermes` (active profile override, or a platform default like Windows AppData/Local), all plugin files land under `~/.hermes` instead of the official location.

This project runs single-user on `~/.hermes` with `HERMES_HOME` matching the official resolver, so no files move as a result of this change; the fix is about correctness on profile/platform-divergent environments and about removing the duplicated resolver and the query workaround.

## Goals / Non-Goals

**Goals:**

- One resolver decides the Hermes home for every plugin-owned file: coordinator state, locks, notices, and reset history.
- The profile-safe path (`get_hermes_home()`) actually runs in production, with the `HERMES_HOME` fallback preserved when the official module is absent.
- The reset-history query reads without injecting the coordinator store's home, because read and write now resolve identically.

**Non-Goals:**

- No data migration or file relocation tooling (out of scope; the deployment's resolvers already agree).
- No change to `resolve_hermes_home()`'s own contract, to the auto-reset eligibility/cooldown/pending/notice state machine, or to the reset-history event schema and query rendering.
- No new config keys, network calls, or user-facing output changes.
- No change to `plugin/providers/minimax_usage.py`, which reads the user's `$HERMES_HOME/.env` for a MiniMax token. That is the user's own environment file, not a plugin-owned state/lock/notice/history file, so it stays on its existing env-only lookup and is intentionally excluded from this unification.

## Decisions

1. **Make `_hermes_home()` delegate to `resolve_hermes_home()` rather than repoint each call site.**
   The state store and both lock acquirers already call `_hermes_home()` as their no-injection default. Having that one helper return `resolve_hermes_home()` unifies all four file kinds (state, locks, notices, history) in a single edit, instead of touching each call site. Alternative: change each call site to call `resolve_hermes_home()` directly and delete `_hermes_home()`. Rejected: more edits, and `_hermes_home()` is a stable internal seam that tests and call sites already depend on; keeping the name while changing its body is the smaller, lower-risk change.

2. **Preserve the exact `HERMES_HOME`/`~/.hermes` fallback semantics.**
   `resolve_hermes_home(None)` already falls back to `Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()` when `hermes_constants` is absent — identical to the current `_hermes_home()` body. So when the official module is absent (all current tests, and standalone runs) behavior is byte-for-byte unchanged; only when the module is present does resolution become profile-safe. Alternative: add a feature flag to opt into profile-safe resolution. Rejected: unnecessary indirection for behavior that is already backward-compatible in the fallback case.

3. **Remove the reset-history query's injected-home workaround.**
   The query currently calls the history reader with the coordinator store's home to force read/write agreement. Once `_hermes_home()` is profile-safe, the store's home and the reader's default (`resolve_hermes_home(None)`) resolve to the same path, so the injection is redundant. Reading with the default resolution also satisfies the existing history spec scenario "no home injected → resolves via the official API." Alternative: keep the injection. Rejected: it is dead weight once the resolvers are unified and keeps the query coupled to the coordinator store type.

4. **Invert the one regression test that encodes the old split.**
   The test asserting the query reads the coordinator's env-only home and ignores the profile-safe default encodes the very divergence this change removes; its premise is no longer true. Replace it with a test asserting that, with a profile-safe home present, a reset written by the coordinator is read back by the query (read and write resolve to the same profile-safe home). Alternative: delete the test outright. Rejected: the read/write-agreement property is worth keeping under test, just stated correctly.

## Implementation Contract

**Observable behavior after this change:**

- With `hermes_constants` importable and no injected home, the coordinator state file, both lock directories, the one-shot notices file, and the reset-history file all resolve under `get_hermes_home()`.
- With `hermes_constants` absent and `HERMES_HOME` set (or default `~/.hermes`), all four resolve under that env home exactly as before this change.
- A successful reset recorded by the coordinator is returned by the reset-history query in the same environment, with no injected home threaded from the query.

**Interfaces:**

- `_hermes_home()` in `plugin/autoreset.py` keeps its signature `() -> Path` and returns `resolve_hermes_home()`. Its three call sites (state store default home, and both lock acquirers' default home) are unchanged in shape.
- The reset-history query in `plugin/hooks/footer_hook.py` calls the history reader with no `home` argument (default resolution) instead of injecting `AutoResetStateStore().home`.

**Failure modes:**

- If `get_hermes_home()` itself raises, the failure surfaces as it would from `resolve_hermes_home()` today (not silently swallowed); only `ModuleNotFoundError` for the official module triggers the `HERMES_HOME` fallback. This matches the resolver's existing contract and is unchanged.

**Acceptance criteria:**

- `_hermes_home()` returns the same value as `resolve_hermes_home()` for both the module-present and module-absent cases (unit test).
- State store, lock acquirers, and history all resolve under the injected profile home when `hermes_constants` is present (unit test), and under `HERMES_HOME` when absent (existing tests stay green).
- The history query returns a coordinator-written event without injecting a home (updated regression test).
- Full suite passes; `ruff check`, `ruff format --check`, and `ty check` are clean.

**In scope:** `_hermes_home()` body; the history query's home argument; the one inverted regression test.

**Out of scope:** `resolve_hermes_home()` internals; the auto-reset state machine; the history event schema and rendering; any file migration.
