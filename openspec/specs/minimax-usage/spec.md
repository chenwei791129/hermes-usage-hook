# minimax-usage Specification

## Purpose

Resolve the MiniMax API token and normalize the MiniMax token-plan response into the shared usage structure consumed by the footer hook.

## Requirements

### Requirement: Resolve the MiniMax API token

The MiniMax usage fetcher SHALL obtain the API token from the `MINIMAX_API_KEY` environment variable first. When that variable is unset, it SHALL parse the Hermes home `.env` file (the path `$HERMES_HOME/.env`, defaulting to `~/.hermes/.env` when `HERMES_HOME` is unset) for a `MINIMAX_API_KEY=<value>` line, stripping surrounding quotes from the value. When neither source yields a token, the fetcher SHALL raise an error.

#### Scenario: Token from environment variable

- **WHEN** `MINIMAX_API_KEY` is set in the environment
- **THEN** the fetcher uses that value as the bearer token without reading any file

#### Scenario: Token from Hermes home .env fallback

- **WHEN** `MINIMAX_API_KEY` is absent from the environment but present in `$HERMES_HOME/.env`
- **THEN** the fetcher reads the value from that file, stripping surrounding quotes

#### Scenario: No token available

- **WHEN** neither the environment nor the `.env` file provides `MINIMAX_API_KEY`
- **THEN** the fetcher raises an error

---
### Requirement: Normalize the MiniMax token-plan response

The MiniMax fetcher SHALL call `GET https://www.minimax.io/v1/token_plan/remains` with the bearer token, and a pure `_normalize(raw)` function SHALL convert the response into the shared usage structure. Normalization SHALL raise when `base_resp.status_code` is not `0`. It SHALL select the `model_remains` entry whose `model_name` is `general`. For the `5h` window it SHALL set `remaining_percent` to `current_interval_remaining_percent`, `used_percent` to `100 - current_interval_remaining_percent`, and `reset_in_min` to `round(remains_time / 60000)`. For the `weekly` window it SHALL use `current_weekly_remaining_percent` and `weekly_remains_time` analogously. It SHALL set `provider` to `MiniMax` and `plan_type` to `None`.

#### Scenario: Successful normalization of the general model

- **WHEN** `_normalize` receives a successful response containing a `general` entry
- **THEN** it returns usage with `provider` `MiniMax`, `plan_type` `None`, and `5h`/`weekly` windows derived from the interval and weekly remaining percentages

##### Example: normalize the general entry

- **GIVEN** a response with `base_resp.status_code` `0` and a `model_remains` entry where `model_name` is `general`, `current_interval_remaining_percent` is `96`, `remains_time` is `616664`, `current_weekly_remaining_percent` is `100`, and `weekly_remains_time` is `483016664`
- **WHEN** `_normalize` is called
- **THEN** the `5h` window is `{used_percent: 4, remaining_percent: 96, reset_in_min: 10}` and the `weekly` window is `{used_percent: 0, remaining_percent: 100, reset_in_min: 8050}`

#### Scenario: Non-zero status code is rejected

- **WHEN** `_normalize` receives a response whose `base_resp.status_code` is not `0`
- **THEN** it raises an error

#### Scenario: Missing general model is rejected

- **WHEN** `_normalize` receives a response whose `model_remains` has no entry with `model_name` `general`
- **THEN** it raises an error
