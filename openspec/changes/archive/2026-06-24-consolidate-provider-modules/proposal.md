## Why

Provider 實作目前以 flat 模組散落在 repo 根目錄（`codex_usage.py`、`minimax_usage.py`），與 dispatch 核心 `usage.py`、hook 並排，看不出哪些檔案屬於「可擴充的 provider 實作」。隨 provider 增加，根目錄會持續膨脹且邊界模糊。將 provider 實作收攏進 `providers/` package，可讓「新增 provider」有明確落點，同時保持 dispatch/registry 與 provider 實作分離。

## What Changes

- 新增 `providers/` Python package（含 `__init__.py`），將 `codex_usage.py`、`minimax_usage.py` 搬入其中。
- `usage.py` 維持在根目錄當 dispatch/registry，import 改為 `from providers import codex_usage, minimax_usage`，registry 仍維持一行明示一個 provider（不做自動探索）。
- 兩個 provider 的 `__main__` 區塊補上 parent-path 處理，讓 `python providers/codex_usage.py` 獨立執行時仍能 `from usage import format_summary`。
- `tests/test_usage.py` 的 import 與 monkeypatch target 改為 `providers.*`。
- 更新部署方式與文件：README Install 從 flat `cp` 改為連同 `providers/` package 一併部署到 `~/.hermes/lib/`，並更新 Files 表與 Quick check 指令路徑。
- 零行為變更：provider 偵測、normalize、summary、hook 行為完全不變。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `footer-hook-deployment`: distribution 與檔案存在性 scenario 由根目錄的 `codex_usage.py` 改為 `providers/` package 下的 provider 模組；shared usage module 與 footer hook 的部署路徑相應更新。

## Impact

- Affected specs: `footer-hook-deployment`
- Affected code:
  - New: providers/__init__.py, providers/codex_usage.py, providers/minimax_usage.py
  - Modified: usage.py, tests/test_usage.py, README.md, openspec/specs/footer-hook-deployment/spec.md
  - Removed: codex_usage.py, minimax_usage.py
