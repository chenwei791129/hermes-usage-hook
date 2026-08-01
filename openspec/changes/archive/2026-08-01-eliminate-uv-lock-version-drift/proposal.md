## 原因

每次 release-please 發布都會更新開發用 `pyproject.toml` 的靜態版本，卻不會重建 `uv.lock`，導致所有 release tag 的 workspace package metadata 與同一份 tag 的版本宣告不一致。Issue #19 已確認這會讓 release tag 執行 `uv sync` 後產生非預期 dirty working tree，因此必須移除兩份 generated/development metadata 之間可漂移的版本狀態。

## 變更內容

- 將 repo-root development project 改為固定的 `0.0.0` development version；此值不代表 release，也不再由 release-please 更新。
- 讓 uv 重新產生 workspace lock entry，使 `uv.lock` 只保存固定且與 release 無關的 `0.0.0` development version。
- 從 release-please 的 `extra-files` 移除 `pyproject.toml`；發行版本仍由 `.release-please-manifest.json` 管理，並同步到實際 ship 的 `plugin/plugin.yaml`。
- 新增 release metadata regression tests，驗證 release-please 設定、固定 development version 及 lockfile workspace entry 持續符合此契約。

## 能力

### 新增能力

(none)

### 修改能力

- `release-automation`: 發布流程只同步實際發行的 plugin version，且 release tag 的 development lockfile 只含不隨發行變動的 workspace version。
- `dev-tooling`: repo-root development project 使用固定的 `0.0.0` development version，執行 `uv lock --check` 或 `uv sync` 不會因 release version bump 而改寫 lockfile。

## 影響範圍

- Affected specs: `release-automation`, `dev-tooling`
- Affected code:
  - Modified: `plugin/plugin.yaml`, `pyproject.toml`, `uv.lock`, `release-please-config.json`
  - New: `tests/test_release_metadata.py`
  - Removed: none
- Runtime/plugin behavior: none；`install.py` 仍只 ship `plugin/`。
- External APIs and dependencies: none；沿用現有 release-please 與 uv。
