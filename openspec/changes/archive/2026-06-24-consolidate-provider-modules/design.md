## Context

目前 repo 根目錄是 flat 佈局：dispatch 核心 `usage.py`、兩個 provider 實作 `codex_usage.py` / `minimax_usage.py`、以及 `hooks/footer_hook.py` 並排。所有 import 都是 flat 頂層 import：

- `usage.py` 用 `import codex_usage` / `import minimax_usage`，registry 以一行 lambda 對應一個 provider。
- `tests/test_usage.py` 用 `import codex_usage` 等，並對 `minimax_usage.get_minimax_usage` 做 monkeypatch。
- 部署是把 flat 檔案 `cp` 進 `~/.hermes/lib/`，hook 於執行時 `sys.path.insert(0, "~/.hermes/lib")` 後 `from usage import ...`。
- 兩個 provider 各有 `__main__` 區塊，獨立執行時 `from usage import format_summary`。

約束：本變更為純結構重構，**不得改變任何執行時行為**（provider 偵測、normalize、summary、hook 失敗容錯皆不變）。provider 數量目前為 2。

## Goals / Non-Goals

**Goals:**

- 將 provider 實作收攏進 `providers/` package，與 dispatch/registry 明確分離。
- 保持「新增 provider = 新增一個 `providers/` 下的模組 + registry 一行」的低成本擴充性。
- 維持獨立執行（`python providers/<x>.py`）與既有測試、hook 部署路徑可運作。

**Non-Goals:**

- 不實作 provider 自動探索（掃描 `providers/` 動態註冊）。registry 維持明示。
- 不把 `usage.py`（dispatch/registry）或 `hooks/footer_hook.py` 搬進 `providers/`。
- 不改變任何 provider 的 API 行為、normalize 結構、summary 格式或 hook 容錯。
- 不調整 PEP 723 inline metadata 內容（dependencies 不變）。

## Decisions

### 將 providers/ 做成真正的 Python package

`providers/` 內含 `__init__.py`，成為可被 `from providers import codex_usage` import 的 package。理由：部署到 `~/.hermes/lib/providers/` 後，hook 既有的 `sys.path.insert(0, "~/.hermes/lib")` 即可讓 `import providers.*` 解析成功，無需改動 hook 的 path 邏輯。替代方案是用無 `__init__.py` 的純資料夾 + namespace package，但會讓 import 行為依賴 Python 版本與 sys.path 細節，較脆弱，否決。

### usage.py 留在根目錄，僅搬 provider 實作

dispatch/registry（`usage.py`）與 hook（`hooks/footer_hook.py`）位置不變，只搬 `codex_usage.py`、`minimax_usage.py`。理由：邊界乾淨——`providers/` 專責「可擴充的 provider 實作」，dispatch 是上層消費者。若連 `usage.py` 一起搬，`hooks/footer_hook.py:30` 的 `from usage import ...` 與部署路徑都要連動更改，擴大無謂的影響面。

### registry 維持明示一行，不做自動探索

`usage.py` 的 `_REGISTRY` 改為 `from providers import codex_usage, minimax_usage` 後維持原本的 tuple 結構，每個 provider 一行（name, matcher, fetcher lambda）。理由：目前僅 2 個 provider，自動探索會引入掃描順序、匯入失敗容錯等新行為，屬 YAGNI，且會把「純搬移」變成「行為變更」。

### __main__ 補 parent-path 以支援獨立執行

兩個 provider 搬入 `providers/` 後，獨立執行 `python providers/codex_usage.py` 時 `sys.path[0]` 為 `providers/`，上一層的 `usage` 不可 import。於各自 `__main__` 區塊（在 `from usage import format_summary` 之前）將 repo 根目錄插入 `sys.path`。理由：保留 README 既有的「Quick check」獨立執行體驗。替代方案是移除 `__main__` 的 summary 列印，但會損失既有的快速驗證能力，否決。

### 部署改為連 providers/ package 一併複製

README Install 從 `cp usage.py codex_usage.py minimax_usage.py ~/.hermes/lib/` 改為複製 `usage.py` 與整個 `providers/` 目錄（含 `__init__.py`）到 `~/.hermes/lib/`。理由：hook 於 `~/.hermes/lib` 解析 `import providers.*` 必須看得到 package 目錄；只複製檔案而不帶目錄結構會讓 hook 啟動時 import 失敗。

## Implementation Contract

**Behavior（重構後對外可觀察行為，全部維持不變）：**

- `usage.get_usage_for_model(model)` 與 `usage.format_summary(usage)` 的輸入/輸出完全不變。
- `hooks/footer_hook.append_usage_footer(...)` 行為不變：偵測 provider、附加 footer、任何失敗回傳 `None` 並記錄 `[hermes-usage-hook]` 到 stderr。
- `python providers/codex_usage.py` 與 `python providers/minimax_usage.py` 獨立執行仍印出 normalized JSON + 一行 summary。

**Interface / 結構：**

- 新增 `providers/__init__.py`（可為空，標記為 package）。
- `providers/codex_usage.py` 維持 `get_codex_usage()`、`WINDOW_5H`、`WINDOW_WEEKLY`、`_normalize` 等既有公開/測試用符號名稱。
- `providers/minimax_usage.py` 維持 `get_minimax_usage()`、`_resolve_token`、`_normalize` 等名稱。
- `usage.py` 的 import 改為 `from providers import codex_usage, minimax_usage`；`_REGISTRY` 結構與條目不變。
- `tests/test_usage.py` 改為 `from providers import codex_usage, minimax_usage`，monkeypatch target 變為 `providers.minimax_usage` 模組物件。

**Failure modes：** 不新增、不改變任何失敗路徑。

**Acceptance criteria：**

- `uv run --with pytest --with httpx python -m pytest tests/test_usage.py -v` 全數通過，且測試斷言內容未變更（僅 import / monkeypatch target 路徑調整）。
- 從 repo 根目錄執行 `python providers/codex_usage.py`（在有 auth.json 的環境）與 `python providers/minimax_usage.py`（在有 token 的環境）能正常印出結果，不因 `import usage` 失敗。
- 模擬部署：將 `usage.py` 與 `providers/` 複製到一個目錄後，`sys.path.insert` 該目錄並 `from usage import get_usage_for_model, format_summary` 可成功 import 且可分派到兩個 provider。
- 根目錄不再存在 `codex_usage.py`、`minimax_usage.py`。

**Scope boundaries：**

- In scope：搬移兩個 provider 模組、`usage.py` 與測試的 import 調整、兩個 `__main__` 的 parent-path、README 三處更新、`footer-hook-deployment` spec 的檔案路徑 scenario 更新。
- Out of scope：新增 provider、自動探索、改變 normalize/summary/hook 行為、調整 PEP 723 metadata、搬移 `usage.py` 或 hook。

## Risks / Trade-offs

- [獨立執行的 parent-path 注入順序錯誤，導致 import 到錯誤模組] → 在 `from usage import` 之前插入 repo 根目錄；以 acceptance criteria 的獨立執行驗證涵蓋。
- [部署只複製檔案、漏掉 `providers/` 目錄或 `__init__.py`，hook 啟動 import 失敗] → README Install 明確改為複製整個 `providers/` 目錄；以模擬部署 import 驗證涵蓋。
- [測試 monkeypatch target 未同步更新，導致 dispatch 測試誤判] → acceptance criteria 要求測試全通過且斷言內容不變。
