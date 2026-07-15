## ADDED Requirements

### Requirement: Successful logical resets have durable append-only audit history

The system SHALL persist exactly one valid audit event for each successful logical Codex auto-reset. `reset` and an idempotent `already_redeemed` confirmation SHALL represent successful logical resets. Non-success, skipped, and failed evaluations SHALL NOT create history events.

#### Scenario: Backend resets the weekly window
- **WHEN** consume returns `reset`
- **THEN** exactly one `codex_autoreset_succeeded` event is eventually present

#### Scenario: Retry confirms an already-redeemed request
- **WHEN** consume returns `already_redeemed` for a persisted request
- **THEN** the logical reset is represented by exactly one valid event
- **AND** a matching existing `event_id` prevents a duplicate

#### Scenario: Evaluation does not successfully reset
- **WHEN** the result is disabled, non-Codex, missing-weekly, above-threshold, cooldown, `no_credit`, `nothing_to_reset`, timeout, unknown, or error
- **THEN** no audit history event is added

### Requirement: Audit history is profile-scoped under the Hermes log root

The system SHALL resolve the active profile through Hermes home and store history at `$HERMES_HOME/logs/hermes-usage-hook-autoreset.jsonl`. The audit file SHALL be UTF-8 JSONL, append-only, and mode `0600` where supported. The system SHALL NOT automatically rotate, truncate, prune, rewrite, or delete history.

#### Scenario: Default profile writes an event
- **WHEN** the active Hermes home is the default profile
- **THEN** the event is appended under that profile's `logs/` directory

#### Scenario: Named profile writes an event
- **WHEN** `HERMES_HOME` identifies a named profile
- **THEN** no default-profile audit file is read or modified

### Requirement: Audit events use a stable privacy-minimized schema

Every valid event SHALL contain exactly schema version, event type, hashed event ID, UTC observation time, backend status, trigger, before values, and after values. The event ID SHALL be `sha256(redeem_request_id)`. Raw request, credit, session, turn, user, account, model, prompt, response, credential, and backend-body data SHALL NOT be persisted.

#### Scenario: Reset usage refresh succeeds
- **WHEN** before and after usage/count values are available
- **THEN** the event records those non-sensitive values

#### Scenario: Reset usage refresh fails
- **WHEN** reset succeeds but refreshed usage/count values are unavailable
- **THEN** the event is still persisted
- **AND** unavailable after fields are `null`

#### Scenario: Event is inspected for identifiers
- **THEN** it contains only a `sha256:` event ID
- **AND** it contains none of the forbidden raw identifiers or credentials

### Requirement: A durable outbox closes reset-to-log crash windows

The system SHALL put the successful audit event in an optional `audit_outbox` in the same coordinator-locked atomic state write that clears pending consume state, sets success cooldown, and stores the footer notice. The system SHALL clear the outbox only after the event is durably appended or found already present by event ID.

#### Scenario: Process crashes before audit append
- **GIVEN** terminal success and the outbox were atomically persisted
- **WHEN** the process exits before appending JSONL
- **THEN** a later hook drains the outbox before any new consume attempt

#### Scenario: Process crashes after append before outbox clear
- **GIVEN** the valid event is already in JSONL and the outbox remains
- **WHEN** a later hook drains the outbox
- **THEN** event-ID deduplication clears the outbox without appending a duplicate

#### Scenario: Audit storage remains unavailable
- **WHEN** an outbox drain fails
- **THEN** the outbox remains durable
- **AND** no new reset credit is consumed
- **AND** the model response remains deliverable

### Requirement: Audit parsing tolerates malformed or partial lines

The system SHALL read all valid supported events while skipping malformed, partial, unsupported-schema, or unsupported-event lines. It SHALL report only a malformed count and SHALL NOT log or print malformed raw content. New valid events SHALL remain appendable without rewriting prior bytes.

#### Scenario: File ends with a partial line
- **WHEN** a later event is appended
- **THEN** the system appends a newline delimiter and then the valid event
- **AND** it does not truncate or rewrite the partial bytes

#### Scenario: History contains malformed lines
- **WHEN** history is queried
- **THEN** valid events remain available in file order
- **AND** a non-sensitive malformed count is reported

### Requirement: Native CLI queries local history without network access

The plugin SHALL register `hermes usage-hook history`. The command SHALL support `--last N`, `--since <positive duration>`, and `--json`. It SHALL read only the profile-local audit file and SHALL NOT load Codex credentials or call usage, credit-list, or consume endpoints.

#### Scenario: History is queried with defaults
- **WHEN** the operator runs `hermes usage-hook history`
- **THEN** the latest 20 valid events are displayed oldest-to-newest in local time

#### Scenario: Since and last are combined
- **WHEN** both filters are provided
- **THEN** UTC since filtering occurs before the last-N limit

#### Scenario: JSON mode is requested
- **WHEN** `--json` is present
- **THEN** selected events are emitted as compact JSONL in stored UTC form
- **AND** diagnostics do not contaminate stdout

#### Scenario: No history exists
- **WHEN** the file is missing or has no valid events
- **THEN** human mode reports that no history exists and exits zero
- **AND** JSON mode emits no lines and exits zero

#### Scenario: Coordinator lock is busy
- **WHEN** the history command cannot acquire the existing auto-reset coordinator lock
- **THEN** it reports a non-sensitive error on stderr and exits one
- **AND** it does not read the audit file without the lock

### Requirement: Audit diagnostics never break replies or expose sensitive data

Audit append, drain, parse, and query failures SHALL be non-sensitive. Runtime failures SHALL use standard Python logging and SHALL NOT suppress or replace a model response. Diagnostics SHALL NOT contain event bodies, raw identifiers, credentials, account/session IDs, or backend responses.

#### Scenario: Audit append fails after reset success
- **WHEN** local storage rejects the append
- **THEN** the successful footer behavior remains available
- **AND** the outbox is retried on a later hook
- **AND** only a non-sensitive warning is logged
