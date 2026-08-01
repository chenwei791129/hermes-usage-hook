## 背景

repo-root `pyproject.toml` 只定義本地開發環境，`[tool.uv] package = false`，且 `install.py` 只複製 `plugin/`。然而它目前仍宣告靜態 PEP 621 version，uv 因而把該值複製到 `uv.lock` 的 virtual workspace package entry。release-please 以 generic extra-file updater 修改 `pyproject.toml`，但不重建 lockfile，造成每一個 release tag 的兩份 metadata 不一致。

驗證顯示，PEP 621 dynamic version 即使搭配 uv non-package mode，仍會要求 build backend 提供版本，與此 repo 不建置、不發佈 development project 的模型衝突。改用固定的 `0.0.0` development version 後，uv 會在 workspace entry 保存相同固定值；release-please 不再更新它，因此後續發行版本變動不會產生可漂移的 generated version。相較之下，在 `uv.lock` 手動加入 release-please annotation 並不耐久：一旦 `pyproject.toml` 版本變動，uv 會重寫該 entry 並移除註解。

## 目標與非目標

**Goals:**

- 消除 `pyproject.toml`、release-please 與 `uv.lock` 之間重複且可漂移的 development project version state。
- 維持 `.release-please-manifest.json` 作為 release-please 的版本來源，並只把版本同步到實際 ship 的 `plugin/plugin.yaml`。
- 讓 clean release checkout 執行 `uv lock --check` 不因 workspace version metadata 過期而失敗或改寫 lockfile。
- 以 repo-owned regression tests 固定 release metadata 的跨檔契約。

**Non-Goals:**

- 不修改 plugin runtime、installer、依賴版本或 GitHub Release 的產生方式。
- 不讓 `pyproject.toml` 成為可發布的 Python package，也不新增 build backend。
- 不在 GitHub Actions 中加入 bot 自行執行、commit 或 push `uv lock` 的步驟。
- 不嘗試修補既有 release tags；歷史 tag 保持 immutable。
- 不處理 release PR #17 中與 Issue #19 無關的版本或功能內容。

## 決策

### 使用固定的 development version 隔離 release version

`pyproject.toml` 將使用固定的 `version = "0.0.0"`，並移除 release-please updater anchor。此值只滿足 PEP 621 與 uv workspace metadata 的版本需求，不代表任何 plugin release。uv 會讓 virtual workspace entry 保留相同固定值；因 release-please 不再更新兩者，development metadata 從 release version lifecycle 隔離而不會漂移。

替代方案是使用 `dynamic = ["version"]`，但實測 uv 0.11.24 仍會呼叫 build backend 解析版本，對此 flat-layout、non-package repo 造成 build failure，且新增 build backend provider 違反 scope。另一方案是把 `uv.lock` 納入 release-please generic updater；annotation 在 uv 重新產生 entry 時會消失，無法持久。也可在 release workflow 提交重建後 lockfile，但這需要 checkout、uv 安裝、PR branch 權限、bot commit 與併發處理，對 development-only metadata 過於複雜。

### release-please 只同步實際發行 artifact 的版本

`release-please-config.json` 的 `extra-files` 將只保留 `plugin/plugin.yaml`。`.release-please-manifest.json` 繼續驅動 semantic version，release-please 仍會產生 CHANGELOG、tag 與 GitHub Release；移除 `pyproject.toml` target 不改變發行流程的其餘行為。

替代方案是保留 `pyproject.toml` 為 extra-file 並繼續同步 release version，但 development-only project 不需要、也不應保存 release version placeholder。

### 以 metadata contract test 防止跨檔回歸

新增 `tests/test_release_metadata.py`，使用 Python 標準函式庫解析 JSON/TOML 與有限的 lockfile/package YAML 文字結構，檢查：development project 與 workspace lock entry 都使用固定的 `0.0.0`、development version line 沒有 updater anchor、release-please 不再 target `pyproject.toml`、plugin manifest 仍帶 updater anchor。測試只驗證本 repo 的設定契約，不測 release-please 或 uv 的第三方內部實作。

另外以 `uv lock --check` 做整合驗證，確認 checked-in lockfile 與 project metadata 一致；不把呼叫 uv CLI 寫成單元測試，以免重複測第三方工具行為。

## 實作契約

**Observable behavior:**

- `pyproject.toml` 的 `[project]` 宣告固定的 `version = "0.0.0"`，且 version line 不含 release-please updater annotation。
- `uv.lock` 中 `name = "hermes-codex-usage-hook"` 的 virtual workspace package entry 保留固定的 `version = "0.0.0"`。
- `release-please-config.json` 的 package `.` 仍使用 `release-type: simple`，`extra-files` 包含 `plugin/plugin.yaml` 且不包含 `pyproject.toml` 或 `uv.lock`。
- `plugin/plugin.yaml` 保持唯一由 release-please extra-file updater 同步的 ship-time version，version line 保留 `x-release-please-version` anchor。

**Failure modes:**

- 若 development 或 lockfile workspace version 不再是 `0.0.0`、development updater anchor 再度出現，或錯誤的 extra-file target 再度出現，release metadata regression test 必須失敗並指出違反的檔案契約。
- 若 checked-in lockfile 與 `pyproject.toml` 的依賴或 metadata 不一致，`uv lock --check` 必須非零退出；實作者必須執行 `uv lock` 更新 lockfile，而非手動編輯 generated dependency metadata。

**Acceptance criteria:**

1. `uv lock` 重新產生後，workspace package entry 的 version 固定為 `0.0.0`，且第二次執行不產生 diff。
2. `uv lock --check` 成功。
3. `uv run pytest tests/test_release_metadata.py` 成功。
4. `uv run pytest`、`uv run ruff check .`、`uv run ruff format --check .` 與 `uv run ty check` 的結果均被執行並如實回報；若存在與此 change 無關的既有 failure，必須清楚區分。
5. `spectra validate eliminate-uv-lock-version-drift` 成功。

**Scope boundaries:**

- In scope：development metadata、lockfile workspace entry、release-please extra-file configuration、對應 specs 與 regression tests。
- Out of scope：runtime hook 程式、installer 行為、dependency upgrades、歷史 tags、release branch maintenance workflow，以及自動 commit/push lockfile 的 CI automation。

## 風險與取捨

- [固定的 `0.0.0` 可能被誤認為 release version] → comment 與 regression test 明確標示 development-only，且 release-please config 不 target 該檔。
- [未來若 repo 轉為可發布 Python package，development-only version 不再合適] → 此 change 明確限於 non-package development project；該轉換必須另行設計並更新 dev-tooling spec。
- [歷史 tags 仍保持不一致] → 不改寫已發布 Git history；修復保證自下一次包含本 change 的 release 起不再產生新的 workspace version drift。
