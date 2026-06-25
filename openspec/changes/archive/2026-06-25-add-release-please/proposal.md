## Why

目前版本號散落在 `plugin/plugin.yaml`（`0.1.0`，使用者實際看到的版本）與 `pyproject.toml`（佔位 `0`），需手動維護且容易漂移；專案也沒有自動產生 CHANGELOG 或 GitHub Release 的機制。本專案的 commit 已遵循 Conventional Commits，正好可由 release-please 自動推導版本、產生變更紀錄並開 Release PR。

## What Changes

- 新增 GitHub Actions workflow `.github/workflows/release-please.yml`，在 push 到 `main` 時執行 `googleapis/release-please-action@v4`，自動維護 Release PR、CHANGELOG 與 GitHub Release。
- 採用 `release-type: simple`，並新增 `release-please-config.json` 與 `.release-please-manifest.json`（起始版本 `0.1.0`）作為設定與版本權威來源。
- 透過 `extra-files` + `# x-release-please-version` 註解錨點，讓 release-please 同步更新 **兩個** 版本欄位：`plugin/plugin.yaml` 與 `pyproject.toml`。
- 改寫 `pyproject.toml` 開頭關於「version 為無意義佔位」的註解，並將 `version = "0"` 改為 `"0.1.0"`，使其反映由 release-please 同步的真實版本（仍維持 `package = false`、不發佈）。
- **不** 納入參考 workflow 中的 PyPI 發佈流程（本專案是 Hermes plugin，無發佈目標）。

## Non-Goals (optional)

(none)

## Capabilities

### New Capabilities

- `release-automation`: 以 release-please 從 Conventional Commits 自動推導語意化版本、產生 CHANGELOG 與 GitHub Release，並同步更新 `plugin/plugin.yaml` 與 `pyproject.toml` 的版本字串。

### Modified Capabilities

(none)

## Impact

- Affected specs: 新增 `release-automation`
- Affected code:
  - New:
    - `.github/workflows/release-please.yml`
    - `release-please-config.json`
    - `.release-please-manifest.json`
  - Modified:
    - `pyproject.toml`
    - `plugin/plugin.yaml`
  - Removed: (none)
