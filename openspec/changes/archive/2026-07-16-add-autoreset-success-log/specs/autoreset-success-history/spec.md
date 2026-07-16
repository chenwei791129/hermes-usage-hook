## ADDED Requirements

### Requirement: Successful resets attempt one best-effort local history append

The system SHALL attempt to append exactly one event for each successful logical Codex auto reset — a terminal backend outcome of `reset`, or an idempotent retry confirmed as `already_redeemed` — to `<home>/logs/hermes-usage-hook-autoreset.jsonl`, where `<home>` SHALL be the same home directory the coordinator state store uses. The attempt SHALL run inside the existing coordinator-locked success path, after the success state and one-shot notice are persisted by the existing locked write. The write is best-effort: a failed append SHALL NOT be retried by any recovery mechanism (no outbox) and SHALL NOT change the coordinator outcome. The system SHALL create the parent directory when missing, SHALL open the file append-only with mode `0600` requested best-effort, and SHALL NOT rotate, truncate, prune, rewrite, or delete history.

#### Scenario: Terminal reset success appends one event

- **WHEN** the redeem call returns backend status `reset`
- **THEN** one JSON line is appended to the history file
- **AND** the coordinator result, cooldown, and one-shot notice behavior are unchanged from the pre-history behavior

#### Scenario: History append failure never affects the reset outcome

- **WHEN** appending the history event raises any exception
- **THEN** the coordinator returns the same result as it would without the history feature
- **AND** a static warning without exception detail is emitted via standard logging

#### Scenario: Two hook invocations in one reply cycle record one event

- **WHEN** the preflight hook completes the reset and the footer hook invokes the coordinator again in the same reply cycle
- **THEN** the second invocation returns under the existing success cooldown without a new consume attempt
- **AND** the history file holds exactly one event for that redeem request ID

### Requirement: Events are privacy-minimized flat records deduplicated by hashed redeem request ID

Each event SHALL be one flat JSON object with exactly the fields `event_id`, `observed_at`, `backend_status`, `weekly_before`, `weekly_after`, `credits_before`, and `credits_after`. `event_id` SHALL be `sha256:<64 lowercase hex>` computed from the raw redeem request ID, and raw request, credit, session, turn, user, and account identifiers SHALL NOT be persisted. `observed_at` SHALL be an RFC 3339 UTC timestamp with `Z` suffix. `backend_status` SHALL be `reset` or `already_redeemed`. Snapshot fields SHALL be a number from 0 to 100 (`weekly_*`), a non-negative integer (`credits_*`), or `null` when the value is unavailable or invalid. The system SHALL NOT append an event whose `event_id` already exists in the file.

#### Scenario: Idempotent retry does not duplicate the event

- **WHEN** a pending redeem for request ID `req-1` was already recorded and a later retry confirms `already_redeemed` for the same request ID
- **THEN** the history file still contains exactly one event with `event_id` equal to the SHA-256 hash of `req-1`

#### Scenario: Invalid snapshot values degrade to null instead of failing

- **WHEN** a usage snapshot value is missing, non-numeric, boolean, out of range, or non-finite
- **THEN** the corresponding event field is `null` and the event is still appended

##### Example: Snapshot coercion

| input value        | stored value |
| ------------------ | ------------ |
| 4                  | 4            |
| 101                | null         |
| true               | null         |
| NaN                | null         |
| "5" (string)       | null         |

### Requirement: History resolves the Hermes home through the official profile-safe API

History file paths SHALL resolve the Hermes home via `hermes_constants.get_hermes_home()` when that module is importable, and SHALL fall back to the `HERMES_HOME` environment variable (default `~/.hermes`, user-expanded) only when the module is absent. An explicitly injected home path SHALL take precedence over both.

#### Scenario: Hermes runtime present

- **WHEN** `hermes_constants` is importable and no home is injected
- **THEN** the history file lives under the path returned by `get_hermes_home()`

#### Scenario: Standalone environment without Hermes

- **WHEN** `hermes_constants` is not importable and `HERMES_HOME` is set
- **THEN** the history file lives under `$HERMES_HOME/logs/`

### Requirement: Users query history with the /usagehook in-session command

The plugin SHALL register an in-session slash command named `usagehook` through the host `register_command` API. When the host context lacks `register_command`, the plugin SHALL log a warning, skip the command, and still register both existing hooks. The handler SHALL read the history file without acquiring the coordinator lock. A line counts as a valid event only when it parses as JSON with a string `event_id` matching `sha256:<64 lowercase hex>` and an `observed_at` string that parses as an RFC 3339 timestamp; every other line SHALL be silently skipped and its raw content SHALL NOT appear in output or logs. Events SHALL be ordered by file position (append order); `observed_at` SHALL NOT be used for sorting. The handler SHALL interpret arguments by whitespace-tokenizing the raw argument string: exactly the token `history` (case-sensitive), optionally followed by one token that is a decimal integer N from 1 to 100 selecting the newest N events; any other token shape or N value SHALL be answered with the usage message. Each rendered event line SHALL format the parsed `observed_at` in UTC to minute precision as `YYYY-MM-DD HH:MM UTC`. The handler SHALL catch every exception and degrade to a static unavailable message.

#### Scenario: History query returns recent events in append order

- **WHEN** a user sends `/usagehook history` and the file holds valid events
- **THEN** the reply is a header line `Codex auto-reset history (last <k>)` where `<k>` is the number of events actually rendered, followed by the newest 5 events (or all events when the file holds fewer than 5), one line per event, in file append order (earliest appended first)

##### Example: Rendered history line

- **GIVEN** an event with `observed_at` `2026-07-14T09:12:00Z`, `backend_status` `reset`, `weekly_before` 4, `weekly_after` 100, `credits_before` 3, `credits_after` 2
- **WHEN** the handler renders it
- **THEN** the line is `2026-07-14 09:12 UTC | reset | weekly 4% → 100% | credits 3 → 2`
- **AND** a `null` snapshot field renders as `?`

#### Scenario: Explicit count within bounds

- **WHEN** a user sends `/usagehook history 20`
- **THEN** the reply contains at most 20 events

#### Scenario: Out-of-range or non-integer count shows usage

- **WHEN** a user sends `/usagehook history 0`, `/usagehook history 101`, or `/usagehook history 5.5`
- **THEN** the reply is exactly `Usage: /usagehook history [N]`

#### Scenario: No history yet

- **WHEN** a user sends `/usagehook history` and no valid events exist
- **THEN** the reply is exactly `No Codex auto-reset history yet.`

#### Scenario: Invalid input shows usage

- **WHEN** a user sends `/usagehook` with empty arguments or any unrecognized subcommand
- **THEN** the reply is exactly `Usage: /usagehook history [N]`

#### Scenario: Handler failure degrades gracefully

- **WHEN** reading or rendering history raises any exception inside the handler
- **THEN** the reply is exactly `Codex auto-reset history is unavailable.` and no exception propagates to the host
