## MODIFIED Requirements

### Requirement: Plugin config is the canonical auto-reset interface

The system SHALL read canonical settings from `plugins.entries.hermes-usage-hook.auto_reset.enabled` and `.threshold`. Defaults SHALL be `enabled=false` and `threshold=0`. The default threshold value exists only as inert state while auto reset is disabled; an operator SHALL NOT explicitly configure zero as an active threshold. Effective `enabled=true` with a valid threshold SHALL constitute explicit standing authorization to autonomously consume Codex reset credits.

#### Scenario: Plugin config is absent
- **WHEN** the plugin entry or `auto_reset` block is absent
- **THEN** effective enabled is false and threshold is 0
- **AND** auto reset makes no pre-request usage or credit API call
- **AND** no threshold warning is emitted

#### Scenario: Plugin config enables auto reset
- **WHEN** `plugins.entries.hermes-usage-hook.auto_reset.enabled=true` and threshold is an integer from 1 through 99
- **THEN** eligible Codex turns are evaluated

---
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

---
### Requirement: Threshold uses weekly remaining percentage

The system SHALL interpret threshold as weekly remaining percentage. Valid explicitly configured values SHALL be integers `1..99`; eligibility SHALL be `remaining_percent <= threshold`. Invalid, empty, zero, negative, non-integer, boolean-as-threshold, or greater-than-99 values from either source SHALL fail closed and consume no credit. When either source explicitly supplies zero, config resolution SHALL additionally emit exactly one best-effort line to standard error carrying the `[hermes-usage-hook]` prefix, naming the valid `1..99` range, and directing the operator to `/usage reset` for a credential Hermes has already frozen. Failure to write the warning SHALL NOT change the invalid configuration result.

The inactive default SHALL remain threshold 0 while enabled is false. An absent threshold SHALL NOT be treated as an explicit zero and SHALL NOT emit a warning.

#### Scenario: Disabled defaults remain inert and quiet
- **GIVEN** auto reset configuration is absent
- **WHEN** configuration is resolved
- **THEN** effective enabled is false and threshold is 0
- **AND** no warning is written

#### Scenario: Minimum boundary qualifies
- **GIVEN** effective threshold is 1
- **WHEN** weekly remaining is 1
- **THEN** the window qualifies

#### Scenario: Above threshold does not qualify
- **GIVEN** effective threshold is 10
- **WHEN** weekly remaining is 11
- **THEN** no credit is consumed

#### Scenario: Explicit plugin threshold zero fails closed with guidance
- **GIVEN** plugin config enables auto reset
- **WHEN** plugin config explicitly sets threshold to 0
- **THEN** auto reset is disabled for that invocation and no usage, credit-list, or consume API is called
- **AND** standard error receives exactly one line containing `[hermes-usage-hook]`, `threshold`, `1..99`, and `/usage reset`

#### Scenario: Explicit environment threshold zero fails closed with guidance
- **GIVEN** plugin config enables auto reset with threshold 10
- **WHEN** `CODEX_AUTORESET_THRESHOLD=0`
- **THEN** auto reset is disabled for that invocation and does not fall through to the plugin value
- **AND** standard error receives exactly one line containing `[hermes-usage-hook]`, `threshold`, `1..99`, and `/usage reset`

#### Scenario: Threshold 100 is rejected
- **WHEN** effective threshold is 100
- **THEN** auto reset is disabled for that invocation
