# codex-credential-resolution Specification

## Purpose

TBD - created by archiving change 'fix-exhausted-codex-credential-selection'. Update Purpose after archive.

## Requirements

### Requirement: Resolve the Codex credential from supported auth layouts

The Codex usage provider SHALL read the OAuth credential from the auth store without refreshing, rotating, or writing it back. It SHALL support three layouts and apply them in a fixed precedence: a Hermes nested record under `provider map` keyed by `provider-a`, then a Hermes prioritized list under `credential list` keyed by `provider-a`, then the flat Codex CLI layout that carries `credential bundle` at the top level.

Only the `credential list` layout SHALL be normalized: resolution SHALL project the selected pooled record into a new record carrying `credential bundle` with `token`, `renewal secret`, and `account reference`. The `provider map` and flat layouts SHALL be returned unchanged, because they already carry the consumer's expected shape and SHALL be allowed to omit `renewal secret` or `account reference`, or carry a top-level API key instead of `credential bundle`.

#### Scenario: Nested provider record wins over the credential pool

- **WHEN** the auth store contains both a `provider map` record for `provider-a` and a non-empty `credential list` list for `provider-a`
- **THEN** resolution returns the nested `provider map` record and does not inspect the pool

#### Scenario: Flat layout is used when no Hermes layout applies

- **WHEN** the auth store carries `credential bundle` at the top level and has neither a `provider map` record nor a `credential list` list for `provider-a`
- **THEN** resolution returns the top-level record unchanged

---
### Requirement: Rank pooled Codex credentials by cooldown state and rank

When resolution reads the `credential list` layout, it SHALL exclude and rank records by two separate rules.

A record SHALL be excluded from selection entirely when it is not a mapping, when it carries no non-empty `token`, or when its `state marker` is `dead`. A `dead` credential has been invalidated server-side, so every call with it would be rejected.

A record SHALL be treated as being in an exhausted cooldown when its `state marker` is `exhausted` and its `retry timestamp` is a non-boolean number greater than the current time. A missing, non-numeric, or already-elapsed `retry timestamp` SHALL NOT count as a cooldown.

Selection SHALL prefer records that are not in an exhausted cooldown, ordering them by ascending `rank`. A `rank` that is missing, `null`, boolean, or otherwise not a number SHALL be treated as 100; ordering SHALL never compare a raw `rank` value against the default, because mixing a non-numeric value with the numeric default raises and would abort resolution exactly as the defect this change fixes does. When no non-cooldown record exists, selection SHALL fall back to the records that are in an exhausted cooldown, ordered by the same rule, rather than failing. Ordering SHALL be stable, so records of equal rank keep their original order.

The exhausted cooldown SHALL NOT exclude a record, because `state marker` of `exhausted` describes the account quota on the Codex completions endpoint, while this plugin reads only the usage and reset-credit endpoints, which that quota does not gate. Excluding exhausted credentials would make Codex auto reset unreachable, because an exhausted weekly window is its only trigger condition.

#### Scenario: A healthy record outranks an exhausted one

- **WHEN** the pool holds a rank-10 record in an exhausted cooldown and a rank-20 record that is not
- **THEN** selection returns the rank-20 record that is not in a cooldown

#### Scenario: Every pooled record is in an exhausted cooldown

- **WHEN** every record in the pool is in an exhausted cooldown and none is `dead`
- **THEN** selection returns the record with the lowest `rank` value and resolution succeeds

#### Scenario: A non-numeric rank is treated as the default

- **WHEN** the pool holds a healthy record whose `rank` is `null` and a healthy record with `rank` 20
- **THEN** selection returns the `rank` 20 record and resolution does not raise

#### Scenario: A dead record never wins over an exhausted one

- **WHEN** the pool holds a `dead` record and a record in an exhausted cooldown
- **THEN** selection returns the record in the exhausted cooldown

##### Example: Pool selection ordering

| Pool records (rank, state marker, cooldown) | Selected |
| --- | --- |
| (10, dead, —), (20, ok, —) | rank 20 |
| (10, exhausted, active), (20, ok, —) | rank 20 |
| (10, exhausted, elapsed), (20, ok, —) | rank 10 |
| (10, exhausted, active), (20, exhausted, active) | rank 10 |
| (10, dead, —), (20, exhausted, active) | rank 20 |
| (10, ok, —) with no token, (20, ok, —) | rank 20 |
| (null, ok, —), (20, ok, —) | rank 20 (null ranks as 100) |

---
### Requirement: Fail explicitly when a non-empty credential pool yields no candidate

When the `credential list` layout holds a non-empty list for `provider-a` and no record survives exclusion, resolution SHALL raise an error naming credential-pool selection as the cause and reporting how many records were examined. It SHALL NOT fall through to the flat layout in that case, because doing so reports that the auth store holds no usable access token when the tokens are present and were excluded by rule.

The error message SHALL NOT contain an access token, a refresh token, a credential identifier, a secret fingerprint, an account identifier, or an email address.

When the `credential list` list for `provider-a` is absent or empty, resolution SHALL continue to the flat layout, because that deployment holds no pooled Codex credential.

#### Scenario: Pool holds only dead records

- **WHEN** every record in the pool is `dead`
- **THEN** resolution raises an error that names credential-pool selection and the number of records examined, and the message contains none of the records' token values

#### Scenario: Pool list is empty

- **WHEN** the `credential list` list for `provider-a` is an empty list and the auth store carries `credential bundle` at the top level
- **THEN** resolution returns the top-level record

---
### Requirement: Surface auto-reset retrieval failures before the transient cooldown

When the auto-reset coordinator aborts because fetching usage or listing reset credits raised, it SHALL write exactly one diagnostic line to standard error. The line SHALL carry the plugin's `[hermes-usage-hook]` prefix, name which retrieval step failed, and include the exception text. This applies to all three retrieval points: the initial usage fetch, the usage fetch performed under the coordinator lock, and the reset-credit listing.

The line SHALL be written as soon as the retrieval raises, before the coordinator attempts to acquire the lock or set the cooldown. The initial usage fetch returns `busy` instead of `transient` when the lock is already held, and that path SHALL emit the diagnostic too: the retrieval failed either way, and suppressing the line exactly when another process holds the lock would reintroduce the silence this requirement exists to remove.

Emitting the diagnostic SHALL NOT change the returned status, the cooldown duration, the persisted state, or any idempotency behavior.

#### Scenario: Usage fetch raises during the coordinator run

- **WHEN** the coordinator's usage fetch raises an exception
- **THEN** one line prefixed with `[hermes-usage-hook]` naming the usage fetch and carrying the exception text is written to standard error, and the coordinator still returns the transient status and sets the transient cooldown

#### Scenario: Reset-credit listing raises during the coordinator run

- **WHEN** the coordinator's reset-credit listing raises an exception
- **THEN** one line prefixed with `[hermes-usage-hook]` naming the credit listing and carrying the exception text is written to standard error, and the coordinator still returns the transient status
