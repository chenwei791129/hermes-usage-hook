## Context

Repo 目前無任何 `pyproject.toml`、`setup.py` 或 `requirements.txt`，亦無 CI。工具鏈現況：
- ruff 以**預設設定**執行（無 ruff 設定檔，僅有 `.ruff_cache/`）。
- pytest 透過 `tests/conftest.py` 的 `sys.path.insert` 注入 `plugin/` 與 `plugin/hooks/` 後執行。
- 執行期依賴（httpx、pyyaml）只在各腳本檔頭的 PEP 723 區塊宣告（`httpx>=0.27`、`pyyaml`），僅在 `uv run <script>` standalone 執行時生效。
- Hermes 以「目錄插件」模型載入本插件（`spec_from_file_location` → `exec_module`），**不讀取也不安裝任何依賴**；執行期 `import httpx` / `import yaml` 成功，是因為 Hermes 自身 venv 已 pin `httpx[socks]==0.28.1`、`pyyaml==6.0.3`。

約束：本次為純工具鏈強化，**不得改動出貨內容與 Hermes 載入行為**。`install.py` 僅複製 `plugin/` 子目錄，故任何放在 repo 根目錄的檔案都不會進入安裝後的插件。

## Goals / Non-Goals

**Goals**
- 在 repo 根目錄提供單一、版本化的開發設定來源（依賴 + ruff/pytest/ty）。
- 讓本地測試/quick-check 跑在與 Hermes 執行期一致的依賴版本上，消除版本漂移。

**Non-Goals**
- 不轉 entry-point / pip 可安裝插件（沿用 proposal Non-Goals）。
- 不更動 `plugin/` 內任何檔案、不動 `tests/conftest.py`、不動 PEP 723 區塊、不動 `install.py` 行為。

## Decisions

### Decision 1: pyproject 置於 repo 根目錄
`install.py` 用 `shutil.copytree` 整包複製 `plugin/`；若把 pyproject 放進 `plugin/` 會被一併出貨，污染插件。放根目錄確保它純屬開發資產、不進安裝產物。
- 替代方案：放 `plugin/` → 否決（會出貨）。

### Decision 2: uv 非套件模式 package false
本 repo 是開發 workspace，不是要被 build/install 的可散佈套件。設 `package = false` 讓 `uv sync` 只建立含依賴的環境，而不嘗試把 repo 自身打包安裝。
- 替代方案：宣告完整可安裝 `[project]` 套件並設 entry point → 否決，那是 entry-point 散佈模型（proposal 已列為 Non-Goal）。

### Decision 3: 依賴版本對齊 Hermes base
`dependencies` 宣告 `httpx==0.28.1`、`pyyaml==6.0.3`，與 Hermes `pyproject.toml` 完全一致，使本地測試/quick-check 跑在與插件實際執行環境相同的版本，避免「本地過、Hermes 掛」。
- 替代方案：寬鬆範圍（`httpx>=0.27`）→ 否決，重新引入漂移。provider 腳本檔頭的 PEP 723 區塊維持其既有寬鬆宣告不動（standalone 用途，與此處互不影響）。

### Decision 4: dev 依賴用 dependency-groups
`pytest`、`ruff`、`ty` 放入 `[dependency-groups] dev`，由 `uv sync` 預設安裝。
- 替代方案：`[project.optional-dependencies]` extras → 否決，extras 是給散佈套件的使用者裝的，本 repo 不散佈；dependency-groups 是 uv 原生的「僅開發用」機制。

### Decision 5: 保留 conftest import 機制
`[tool.pytest.ini_options]` 僅設 `testpaths = ["tests"]`（與必要 addopts），**不**新增 `pythonpath`；`tests/conftest.py` 的 sys.path 注入維持原樣。
- 替代方案：把 pythonpath 移進 pyproject 並刪除 conftest 注入 → 否決，會動到測試基礎設施，違反「純加法、可逆」與 proposal Non-Goal。

### Decision 6: ruff 維持預設行為
`[tool.ruff]` 僅設 `target-version`（對齊 `requires-python`），規則維持 ruff 預設（現況即預設），不引入新 lint 規則，避免本次變更夾帶大量風格修改。
- 替代方案：開啟嚴格規則集 → 否決，超出本次範圍。

## Implementation Contract

**範圍內（in scope）**
- 新增 `pyproject.toml`（root），含：`requires-python = ">=3.10"`、`dependencies`（httpx==0.28.1、pyyaml==6.0.3）、`[dependency-groups] dev`（pytest、ruff、ty）、`[tool.uv] package = false`、`[tool.ruff]`（target-version）、`[tool.pytest.ini_options]`（testpaths）。
- 由 `uv lock` 產生 `uv.lock` 並納管。
- README 新增「本地開發」說明（以 `uv sync` 建立環境、`uv run pytest` 跑測試）。
- 確認 `.gitignore` 已涵蓋 `.venv/`（已存在則不動）。

**範圍外（out of scope）**：`plugin/` 任何檔案、`tests/conftest.py`、`install.py` 行為、PEP 723 區塊、Hermes 載入流程。

**可觀察的完成條件**
- 在乾淨 checkout 執行 `uv sync` 成功建立 `.venv`，內含 pinned httpx/pyyaml 與 dev 工具。
- `uv run pytest` 收集並執行 `tests/` 下既有測試且全部通過（行為與變更前一致）。
- `uv run ruff check .` 可執行（不要求零警告，只要求設定生效可跑）。
- `uv run ty check`（或對應 ty 調用）可執行。
- 執行 `install.py` 後，安裝到 `$HERMES_HOME/plugins/hermes-usage-hook/` 的目錄中**不含** `pyproject.toml`（出貨產物不變）。

## Risks / Trade-offs

- [Hermes 未來調整 base 依賴版本，導致 pin 值落後] → 版本對齊以「目前 Hermes 一致」為準；README/design 記錄來源，後續可隨 Hermes 升版手動同步。
- [pyproject 宣告 deps 但 conftest 仍以 sys.path 注入，兩套機制並存可能令人困惑] → 以 Decision 5 註明分工：pyproject 管依賴與工具設定、conftest 管測試 import path；本次刻意不合併以維持可逆。
- [PEP 723 寬鬆版本與 pyproject pin 版本不一致] → 兩者用途不同（standalone vs 開發環境），可接受；design 已載明，避免被誤判為矛盾。

## Migration Plan

純加法變更，無資料或流程遷移。實作後執行 `uv sync` 即建立本地環境；既有以系統 python/pytest 執行測試的流程仍可運作（conftest 不變）。回滾僅需刪除 `pyproject.toml` 與 `uv.lock`，出貨內容與插件行為不受影響。
