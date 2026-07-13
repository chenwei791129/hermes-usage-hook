## ADDED Requirements

### Requirement: Plugin config is the canonical auto-reset interface

The system SHALL read canonical settings from `plugins.entries.hermes-usage-hook.auto_reset.enabled` and `.threshold`. Defaults SHALL be `enabled=false` and `threshold=0`. Effective `enabled=true` SHALL constitute explicit standing authorization to autonomously consume Codex reset credits.

#### Scenario: Plugin config is absent
- **WHEN** the plugin entry or `auto_reset` block is absent
- **THEN** effective enabled is false and threshold is 0
- **AND** auto reset makes no pre-request usage or credit API call

#### Scenario: Plugin config enables auto reset
- **WHEN** `plugins.entries.hermes-usage-hook.auto_reset.enabled=true`
- **THEN** eligible Codex turns are evaluated

### Requirement: Environment variables override plugin config

The system SHALL treat explicit `CODEX_ENABLE_AUTORESET` and `CODEX_AUTORESET_THRESHOLD` values as operator overrides. Resolution SHALL be env → plugin config → defaults. Boolean env SHALL accept `1/true/yes/on` and `0/false/no/off` after trimming and case-folding. Invalid explicit env values SHALL fail closed for that invocation.

#### Scenario: Environment disables enabled plugin config
- **GIVEN** plugin config enabled is true
- **WHEN** `CODEX_ENABLE_AUTORESET=false`
- **THEN** effective enabled is false

#### Scenario: Environment overrides threshold
- **GIVEN** plugin config threshold is 10
- **WHEN** `CODEX_AUTORESET_THRESHOLD=5`
- **THEN** effective threshold is 5

### Requirement: Threshold uses weekly remaining percentage

The system SHALL interpret threshold as weekly remaining percentage. Valid values SHALL be integers `0..99`; eligibility SHALL be `remaining_percent <= threshold`. Invalid, empty, negative, non-integer, boolean-as-threshold, or greater-than-99 values from either source SHALL fail closed and consume no credit.

#### Scenario: Default threshold
- **GIVEN** auto reset is effectively enabled and threshold is unspecified
- **WHEN** weekly remaining is 0
- **THEN** the window qualifies

#### Scenario: Boundary qualifies
- **GIVEN** effective threshold is 10
- **WHEN** weekly remaining is 10
- **THEN** the window qualifies

#### Scenario: Above threshold does not qualify
- **GIVEN** effective threshold is 10
- **WHEN** weekly remaining is 11
- **THEN** no credit is consumed

#### Scenario: Threshold 100 is rejected
- **WHEN** effective threshold is 100
- **THEN** auto reset is disabled for that invocation

### Requirement: Only real Codex weekly windows are eligible

The system SHALL require a Codex model and normalized `weekly.remaining_percent`. It SHALL NOT infer weekly state from other windows, positions, or timestamps.

#### Scenario: Non-Codex provider
- **WHEN** model maps to MiniMax or unknown
- **THEN** no Codex auto-reset API is called

#### Scenario: Weekly missing
- **WHEN** Codex usage omits weekly
- **THEN** no credit is consumed

### Requirement: Dual hooks close request timing gaps

The system SHALL evaluate from `pre_llm_call` and post-response footer using one coordinator, lock, state, and decision policy.

#### Scenario: Exhausted before request
- **WHEN** weekly is eligible before a turn
- **THEN** pre-LLM attempts reset before provider request

#### Scenario: Response crosses threshold
- **WHEN** a successful response reduces weekly remaining to threshold or below
- **THEN** footer flow evaluates immediately

### Requirement: Earliest-expiring available credit is selected

The system SHALL list detailed credits and choose the `available` row with earliest non-null `expires_at`; null expiry sorts last. No usable row SHALL fail closed.

#### Scenario: Three expiries
- **WHEN** available credits expire July 18, July 27, and July 31
- **THEN** July 18 credit ID is consumed

#### Scenario: Count/detail mismatch
- **WHEN** count is positive but no detail row is available
- **THEN** no consume request is sent

### Requirement: Consumption is locked, rechecked, and idempotent

The system SHALL acquire a cross-process lock, re-fetch live usage inside it, and persist UUID `redeem_request_id` plus `credit_id` before POST. Ambiguous retries SHALL reuse both identifiers.

#### Scenario: Hooks race
- **WHEN** pre-LLM and footer race on eligible stale usage
- **THEN** at most one logical consumption occurs

#### Scenario: POST timeout
- **WHEN** POST may have reached the server but times out
- **THEN** pending state remains and retry reuses identifiers

#### Scenario: Already redeemed
- **WHEN** retry returns `already_redeemed`
- **THEN** attempt is successful and terminal

### Requirement: Outcomes never break replies

`reset` and `already_redeemed` SHALL be successful terminal outcomes. `nothing_to_reset` and `no_credit` SHALL be non-success terminal outcomes. Errors, invalid config, malformed data, lock contention, and unknown codes SHALL never suppress/replace the model response.

#### Scenario: Reset succeeds
- **WHEN** consume returns reset
- **THEN** usage/count refresh and pending state completes

#### Scenario: Nothing to reset
- **WHEN** consume returns nothing-to-reset
- **THEN** no success is reported and cooldown prevents per-hook POST spam

#### Scenario: Provider fails
- **WHEN** any provider call fails
- **THEN** original response remains deliverable and footer claims no reset

### Requirement: Successful resets are transparent

The next matching footer SHALL append exactly one audit line with before/after weekly remaining percentages and credit counts. No notice SHALL be injected into model prompts.

#### Scenario: Reset changes quota and count
- **GIVEN** weekly changes 0 to 100 and credits 3 to 2
- **THEN** footer includes `Codex auto reset | weekly 0% → 100% | reset credits 3 → 2`

### Requirement: State contains no credentials

State SHALL live under `$HERMES_HOME/state/hermes-usage-hook/` and SHALL NOT persist/log bearer tokens, refresh tokens, account IDs, user IDs, or full backend bodies.

#### Scenario: Pending attempt is persisted
- **THEN** state contains only UUID, credit ID, timestamps, status, cooldown, and non-sensitive audit values
