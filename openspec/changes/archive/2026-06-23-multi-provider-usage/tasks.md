## 1. Codex provider 標記

- [x] 1.1 [P] 在 codex_usage.py 的 `_normalize` 輸出加上 `"provider": "Codex"`，保留 `get_codex_usage` 與 OAuth refresh 不變；驗證：`uv run codex_usage.py` 仍輸出 Codex 摘要，且回傳結構含 `provider` 欄位

## 2. MiniMax provider（minimax-usage）

- [x] 2.1 [P] 實作 minimax_usage.py 的 token 解析以滿足 "Resolve the MiniMax API token"，採「MiniMax token 來源：環境變數優先、.env fallback」決策（先讀 `MINIMAX_API_KEY` 環境變數，缺少時以極簡 KEY=VALUE parser 解析 `$HERMES_HOME/.env`，預設 `~/.hermes/.env`，去除外層引號，兩者皆無則拋例外）；驗證：tests/test_usage.py 的 token 來源案例（env 命中、.env fallback、皆無拋錯）通過
- [x] 2.2 實作 minimax_usage.py 的 `_normalize(raw)` 與 `get_minimax_usage()` 以滿足 "Normalize the MiniMax token-plan response"，依「MiniMax token_plan/remains 正規化（取 general 模型）」決策（檢查 `base_resp.status_code == 0`、取 `model_name == "general"`、映射 5h 與 weekly window，`provider` 設為 `MiniMax`、`plan_type` 設為 `None`）；驗證：tests/test_usage.py 以真實 sample payload 斷言 5h `{used:4, remaining:96, reset_in_min:10}`、weekly `{remaining:100}`，且 status≠0 與缺 general 模型皆拋錯

## 3. 偵測與分派層（provider-detection）

- [x] 3.1 在 usage.py 實作 provider matchers 與有序 registry 的 `get_usage_for_model(model)`，滿足 "Detect provider from the response model name" 與 "Dispatch to the matched provider and normalize usage"，採「以 model 字串偵測 provider 並分派」決策（Codex=含 codex 或以 gpt-/o1/o3/o4 開頭；MiniMax=含 minimax 或 abab；皆不中回傳 `None`）；驗證：tests/test_usage.py 的模型對應表案例（Codex、MiniMax、未知、缺漏各案例）通過
- [x] 3.2 將 `format_summary` 從 codex_usage.py 移到 usage.py 以滿足 "Render a provider-labeled usage summary"，採「共用正規化結構與 format_summary 移到 usage.py」決策（只吃正規化結構、輸出帶 provider 名稱、`plan_type` 為 `None` 時省略 `| plan` 段、5h window 缺失時回 unavailable），並同步把 codex_usage.py 的 `__main__` 區塊改為在區塊內延遲匯入 `from usage import format_summary`（避免循環匯入）；驗證：tests/test_usage.py 斷言 Codex（含 plan）與 MiniMax（無 plan）兩種輸出字串，且 `uv run codex_usage.py` 仍印出 Codex 摘要

## 4. Hook 接線

- [x] 4.1 修改 hooks/footer_hook.py 的 `append_usage_footer` 從 `kwargs.get("model")` 取模型，呼叫 `usage.get_usage_for_model(model)` 與 `usage.format_summary(...)`，偵測不中或例外皆回 `None`（記 stderr 前綴 `[codex-usage-hook]`）；驗證：以含 `model` 的呼叫手動驗證 Codex/MiniMax 各產生對應 footer，未知 model 回原文不變
- [x] 4.2 [P] 將 hooks/plugin_hook.py 與 hooks/gateway/handler.py 的 `format_summary` import 來源由 codex_usage 改為 usage（不刪除這兩個 hook）；驗證：`python -c "import plugin_hook"` 與對 handler.py 的 import 不報錯

## 5. 文件

- [x] 5.1 [P] 更新 README.md，說明 footer hook 多 provider 自動偵測、偵測規則（Codex/MiniMax 模型命名）、MiniMax token 來源（`MINIMAX_API_KEY` 環境變數與 `~/.hermes/.env` fallback）；驗證：內容檢視，README 描述與 usage.py 偵測規則一致
