## Why

這個 repo 已從「單一 codex 腳本」成長為多模組專案（`plugin/usage.py`、`plugin/providers/`、`plugin/hooks/`、`tests/`），但開發工具鏈仍是散落且未版本化的狀態：ruff/pytest/ty 沒有集中設定、執行期依賴（httpx、pyyaml）只靠各腳本檔頭的 PEP 723 區塊零散宣告，且該宣告在 Hermes 載入插件時完全不參與——目前能執行純粹是搭便車用 Hermes 自身 venv 已 pin 的 `httpx==0.28.1` 與 `pyyaml==6.0.3`。缺少一處集中的依賴與工具設定，導致本地版本漂移、且「本地測試版本」與「Hermes 執行期版本」可能不一致。

## What Changes

- 新增 **repo 根目錄**的 `pyproject.toml`，作為**純開發用**設定來源，集中：
  - 執行期依賴宣告，版本對齊 Hermes base（`httpx==0.28.1`、`pyyaml==6.0.3`），供本地測試與 quick-check 使用
  - 開發依賴（`pytest`、`ruff`、`ty`）以 dependency group 形式版本化
  - ruff、pytest、ty 的工具設定集中於 `[tool.*]`
- 維持目錄插件散佈模型不變：`install.py` 仍只複製 `plugin/`，`pyproject.toml` 位於 repo 根目錄、**不隨插件出貨**，Hermes 載入行為零改動。
- 更新 README 開發章節，補上以 `uv sync` 建立本地開發環境的說明。
- 視需要補 `.gitignore`（既有已含 `.venv/`）。

## Non-Goals

- **不轉成 entry-point / pip 可安裝插件**（Hermes 的另一種散佈模型）。那需要重構套件結構、import 風格與安裝流程，僅在要公開 pip/Nix 散佈時才划算，本次明確排除。
- **不更動 `plugin/` 內任何檔案**，包含 `__init__.py`、`hooks/footer_hook.py` 的 `sys.path.insert` 機制。
- **不移除或重構 `tests/conftest.py` 的 sys.path 注入**，亦不把它改用 pytest `pythonpath` 取代——保持本次變更為純加法、可逆。
- **不移除** provider 腳本與 `install.py` 檔頭的 PEP 723 區塊——保留 `uv run plugin/providers/codex_usage.py` 的零設定 standalone quick-check 體驗。
- **不改動** Hermes 載入器對依賴的處理（Hermes 本就不替目錄插件安裝依賴）。

## Capabilities

### New Capabilities

- `dev-tooling`: 規範 repo 根目錄存在一份純開發用的 `pyproject.toml`，集中宣告對齊 Hermes 的執行期依賴、版本化的開發依賴與 ruff/pytest/ty 工具設定；同時規範它不隨插件出貨，且不改動既有目錄插件散佈模型。

### Modified Capabilities

(none)

## Impact

- Affected specs: 新增 `dev-tooling`
- Affected code:
  - New:
    - pyproject.toml
    - uv.lock
  - Modified:
    - README.md
    - .gitignore
  - Removed: (none)
