## 1. 建立開發用 pyproject

- [x] 1.1 在 repo 根目錄建立 `pyproject.toml`，實現 Requirement「Provide a repo-root development pyproject.toml」與「Centralize development tooling configuration」：含 `requires-python = ">=3.10"`、`[dependency-groups]` 的 `dev` 群組列出 `pytest`/`ruff`/`ty`、`[tool.uv]` 設 `package = false`、`[tool.ruff]` 僅設 `target-version`（規則維持預設）、`[tool.pytest.ini_options]` 設 `testpaths = ["tests"]` 且不設 `pythonpath`。落實 Decision 1: pyproject 置於 repo 根目錄、Decision 2: uv 非套件模式 package false、Decision 4: dev 依賴用 dependency-groups、Decision 5: 保留 conftest import 機制、Decision 6: ruff 維持預設行為。完成判定：`uv sync` 在乾淨環境成功建立 `.venv` 並安裝上述依賴。
- [x] 1.2 於同一 `pyproject.toml` 的 `dependencies` 鎖定 `httpx==0.28.1` 與 `pyyaml==6.0.3`，實現 Requirement「Pin runtime dependencies to the Hermes host versions」並落實 Decision 3: 依賴版本對齊 Hermes base。完成判定：`dependencies` 中兩者版本與 Hermes 一致。
- [x] 1.3 以 `uv lock` 產生 `uv.lock` 並納入版控。完成判定：`uv.lock` 存在，且再次執行 `uv sync` 依鎖定檔還原相同版本（httpx 0.28.1、pyyaml 6.0.3）。

## 2. 驗證無回歸

- [x] 2.1 確認既有測試在新環境下全數通過且行為不變（佐證 Decision 5: 保留 conftest import 機制有效）。完成判定：`uv run pytest` 收集 `tests/` 下測試並全部 pass。
- [x] 2.2 確認 ruff 與 ty 設定可運作。完成判定：`uv run ruff check .` 與 `uv run ty check`（對應 ty 調用）皆可執行而不因設定錯誤中止。
- [x] 2.3 確認出貨產物不含 `pyproject.toml`，實現 Requirement「Keep the shipped plugin free of the development pyproject」（呼應 Decision 1: pyproject 置於 repo 根目錄）。完成判定：以暫時 `HERMES_HOME` 執行 `uv run install.py` 後，安裝到 `plugins/hermes-usage-hook/` 的目錄中不存在 `pyproject.toml`。

## 3. 文件與忽略清單

- [x] 3.1 [P] 在 README 新增「本地開發」說明，描述以 `uv sync` 建立環境、`uv run pytest` 執行測試。完成判定：README 含該段且指令與 pyproject 設定一致。
- [x] 3.2 [P] 確認 `.gitignore` 已涵蓋 `.venv/`（既有已含則維持不動，必要時補上），且 `uv.lock` 未被忽略。完成判定：`.gitignore` 含 `.venv/` 且不忽略 `uv.lock`。
