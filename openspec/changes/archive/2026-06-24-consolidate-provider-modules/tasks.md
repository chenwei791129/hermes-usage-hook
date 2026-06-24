## 1. 收攏 provider 實作進 providers/ package

- [x] 1.1 將 providers/ 做成真正的 Python package：新增 `providers/__init__.py`，使其可被 import。驗證：自 repo 根目錄執行 `python -c "import providers"` 成功無誤。
- [x] 1.2 usage.py 留在根目錄，僅搬 provider 實作：將 `codex_usage.py`、`minimax_usage.py` 移入 `providers/`，公開/測試用符號（`get_codex_usage`、`WINDOW_5H`、`WINDOW_WEEKLY`、`get_minimax_usage`、`_resolve_token`、`_normalize`）名稱不變，根目錄不再保留這兩個檔案。驗證：`python -c "from providers import codex_usage, minimax_usage"` 成功，且根目錄已無 `codex_usage.py`、`minimax_usage.py`。
- [x] 1.3 __main__ 補 parent-path 以支援獨立執行：於兩個 provider 的 `__main__` 區塊在 `from usage import format_summary` 前將 repo 根目錄插入 `sys.path`，使獨立執行仍能 import 上一層的 usage。驗證：自 repo 根目錄執行 `python providers/codex_usage.py` 與 `python providers/minimax_usage.py`（具備對應憑證時）印出 normalized JSON 與一行 summary，不因 `import usage` 失敗。

## 2. 更新 dispatch 與測試 import

- [x] 2.1 registry 維持明示一行，不做自動探索：`usage.py` 的 import 改為 `from providers import codex_usage, minimax_usage`，`_REGISTRY` tuple 結構與條目維持不變，`get_usage_for_model` 分派行為不變。驗證：provider 偵測相關測試（`test_match_provider_mapping`、`test_get_usage_for_model_dispatches_to_matched_provider`）通過。
- [x] 2.2 測試 import 與 monkeypatch target 同步：`tests/test_usage.py` 改為 `from providers import codex_usage, minimax_usage`，monkeypatch target 改為 `providers.minimax_usage`，所有既有斷言內容不變。驗證：`uv run --with pytest --with httpx python -m pytest tests/test_usage.py -v` 全數通過。

## 3. 部署與文件

- [x] 3.1 [P] 部署改為連 providers/ package 一併複製：更新 README 的 Install（複製 `usage.py` 與整個 `providers/` 目錄至 `~/.hermes/lib/`）、Files 表（provider 列改為 `providers/` 下路徑）、Quick check（兩種執行形式皆更新路徑：`uv run providers/codex_usage.py` 與 `python providers/codex_usage.py`）。驗證：內容 review，Install 段落明確包含複製整個 `providers/` 目錄（含 `__init__.py`）。
- [x] 3.2 驗證 Distribute only the footer hook 的部署可運作：將 `usage.py` 與 `providers/` 複製到一個暫存目錄，`sys.path.insert` 該目錄後 `from usage import get_usage_for_model, format_summary` 成功且可分派到兩個 provider。驗證：手動 import 與分派腳本執行成功，模擬 hook 於 `~/.hermes/lib` 的 import 路徑。
