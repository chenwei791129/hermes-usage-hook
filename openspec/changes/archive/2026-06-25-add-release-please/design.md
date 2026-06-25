## Context

本專案是一個 Hermes plugin，透過 `git clone` + `uv run install.py` 安裝（只複製 `plugin/` 目錄），**不是** PyPI 套件。版本字串目前散落兩處且需手動維護：

- `plugin/plugin.yaml` 的 `version: 0.1.0` — 使用者透過 `hermes plugins` 實際看到的版本。
- `pyproject.toml` 的 `version = "0"` — 開發專用、`package = false`、永不發佈的佔位值。

commit 歷史已一致遵循 Conventional Commits（`feat:`/`fix:`/`chore:`/`docs:`/`refactor:`），具備導入 release-please 的前提。GitHub repo 的「Allow GitHub Actions to create and approve pull requests」權限已於本變更前置作業中開啟（`can_approve_pull_request_reviews: true`）。

參考來源 `chenwei791129/commit-with-ai` 的 workflow 同時做 release-please 與 PyPI 發佈；本專案僅取前者。

## Goals / Non-Goals

**Goals:**

- 以 release-please 從 Conventional Commits 自動推導語意化版本、產生 CHANGELOG 與 GitHub Release。
- 讓 release-please 自動同步 `plugin/plugin.yaml` 與 `pyproject.toml` 兩處版本字串，消除手動維護與漂移。
- 設定收斂於版本控制中的設定檔，可重現、可審查。

**Non-Goals:**

- 不發佈到 PyPI 或任何套件 registry（本專案無發佈目標）。
- 不改變安裝流程（仍為 git clone + `install.py`）。
- 不在 GitHub Release 附帶 `plugin/` zip 壓縮檔（未來需要時再以獨立變更處理）。
- 不調整既有 commit 規範（已是 Conventional Commits）。

## Decisions

### 採用 release-type simple 而非 python

`release-type: python` 會嘗試 bump 標準 Python 套件的版本欄位（`pyproject.toml` / `setup.py` / `__init__.py`），預設套件語意。本專案要 bump 的主版本來源是 `plugin/plugin.yaml`（YAML manifest），且 `pyproject.toml` 是 `package = false` 的非發佈設定。`simple` 型別不假設套件結構，搭配 `extra-files` 泛用更新器即可精準更新任意檔案，最貼合本專案形態。替代方案 `python` 會去動佔位的 `pyproject` 版本並引入套件假設，反而增加摩擦。

### 以 extra-files 加 x-release-please-version 註解錨點同步雙檔

在 `plugin/plugin.yaml` 與 `pyproject.toml` 的版本行各加上行尾註解錨點，並於 `release-please-config.json` 的 `extra-files` 同時列出兩個檔案，由 release-please 的泛用更新器在每次發版時一併寫入新版本。版本權威為 `.release-please-manifest.json`，兩個檔案皆為其鏡像，由 release-please 保證鎖步，避免兩處各自為政產生漂移。替代方案「只同步 plugin.yaml、pyproject 維持佔位」會保留 `version="0"` 的尷尬且使 pyproject 版本無意義；「手動同步」則重新引入漂移風險。

### 改寫 pyproject.toml 的版本註解語意

`pyproject.toml` 開頭現有註解明示「version 為無意義佔位」並設 `version = "0"`。一旦改由 release-please 同步真實版本，該理由過時，必須改寫為「版本由 release-please 與 `plugin/plugin.yaml` 同步維護，本檔仍 `package = false`、不發佈」，並將 `version = "0"` 改為 `"0.1.0"` 作為起始基準。否則程式碼註解與實際行為自相矛盾。

### 移除參考 workflow 的 PyPI 發佈 job

參考 workflow 的 `publish-to-pypi` job（version 對比、`uv build`、`uv publish`、上傳 artifact）整段不納入，因本專案非發佈套件、無 `PYPI_TOKEN` 發佈目標。workflow 僅保留 release-please job，並在檔案層級宣告 `permissions: contents: write` / `pull-requests: write`（最小權限，覆蓋 repo 預設的 `read`）。

## Implementation Contract

**行為**：當 Conventional Commits 被 push 到 `main` 分支時，release-please workflow 執行並維護一個 Release PR；該 PR 累積待發版的變更、更新 CHANGELOG，並將下一版版本號寫入 `plugin/plugin.yaml` 與 `pyproject.toml`。合併該 Release PR 後，release-please 建立對應的 git tag 與 GitHub Release。

**設定檔契約**：

- `release-please-config.json`：頂層含 `packages`，鍵為 `"."`，其值設定 `"release-type": "simple"` 與 `"extra-files": ["plugin/plugin.yaml", "pyproject.toml"]`。
- `.release-please-manifest.json`：單一條目 `{ ".": "0.1.0" }`，作為版本權威起點。
- `plugin/plugin.yaml`：`version` 行尾帶 `# x-release-please-version` 錨點，值維持 `0.1.0`。
- `pyproject.toml`：`version = "0.1.0"` 行尾帶 `# x-release-please-version` 錨點；開頭註解改寫為由 release-please 同步、仍不發佈。
- `.github/workflows/release-please.yml`：`on: push: branches: [main]`；頂層 `permissions: contents: write` 與 `pull-requests: write`；單一 job 使用 `googleapis/release-please-action@v4`，不含任何 PyPI 發佈步驟。

**失敗模式**：若版本錨點註解與 `extra-files` 設定的檔案不一致，release-please 不會更新該檔（靜默略過），因此錨點與設定必須對齊。Release PR 的建立依賴 repo 已開啟 Actions 開 PR 權限（前置已完成）。

**驗收標準**：

- `release-please-config.json` 與 `.release-please-manifest.json` 為合法 JSON，且鍵結構如上。
- `.github/workflows/release-please.yml` 為合法 YAML，無 PyPI 發佈步驟，含上述 `permissions` 與 `on` 設定。
- `plugin/plugin.yaml` 與 `pyproject.toml` 版本皆為 `0.1.0` 且各帶 `x-release-please-version` 錨點註解。
- `pyproject.toml` 的版本相關註解不再宣稱 version 為無意義佔位。
- 既有 `uv run pytest` / `uv run ruff check .` / `uv run ty check` 不因本變更而失敗。

**範圍邊界**：

- In scope：上述五個檔案的新增／修改。
- Out of scope：PyPI 發佈、安裝流程變更、GitHub Release 附帶 zip、commit 規範調整、實際觸發一次真實發版（由後續合併 PR 自然發生，非本變更任務）。

## Risks / Trade-offs

- [release-please 版本錨點與 extra-files 不一致導致某檔未被更新] → 在 tasks 中明確要求兩個檔案各加錨點且 `extra-files` 同列兩者；驗收標準逐檔檢查。
- [首次導入時 manifest 起始版本與現況不符會造成版本跳號] → 起始 manifest 設為現行 `0.1.0`，與 `plugin.yaml` 現值一致。
- [pyproject 版本由佔位改為真實值，可能讓人誤以為專案已可發佈] → 同步改寫註解明確說明仍 `package = false`、不發佈。
- [Actions 開 PR 權限為 repo 層級設定，非本變更檔案可涵蓋] → 已於前置作業開啟並驗證，design Context 留存記錄。
