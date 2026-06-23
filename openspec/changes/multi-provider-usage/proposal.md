## Why

目前 footer hook 寫死只抓 Codex (OAuth) 的用量，使用者實際同時使用 Codex 與 MiniMax 國際版兩個後端。當這次回覆其實是 MiniMax 模型產生時，footer 仍會去查 Codex 用量，顯示的數字與實際使用的 provider 不符，造成誤導。需要讓 footer 依當前 session 實際使用的 provider，回報對應的用量。

## What Changes

- 新增「provider 偵測 + 分派」層：footer hook 從 `transform_llm_output` context 的 `model` 欄位判斷本次回覆用哪個 provider，並分派到對應的用量抓取器。
- 偵測規則（對 `model` 字串大小寫不敏感比對）：Codex = 含 `codex` 或以 `gpt-` / `o1` / `o3` / `o4` 開頭；MiniMax = 含 `minimax` 或 `abab`；皆不符回傳 `None`，footer 保持不變。
- 新增 MiniMax 國際版用量抓取：呼叫 `GET https://www.minimax.io/v1/token_plan/remains`，token 先讀環境變數 `MINIMAX_API_KEY`，fallback 解析 `$HERMES_HOME/.env`（預設 `~/.hermes/.env`）；純 API key、不需 OAuth refresh。
- 定義兩個 provider 共用的正規化用量結構，並把 `format_summary` 從 `codex_usage.py` 移到新的 `usage.py`，使其只依賴正規化結構、可同時格式化兩種 provider。
- footer 輸出帶上 provider 名稱，例如 `Codex 5h | used 42%, left 58% (resets in 137 min) | plan pro` 與 `MiniMax 5h | used 4%, left 96% (resets in 281 min)`。
- 任何抓取或偵測失敗都回傳 `None`，維持「永不破壞回覆」的既有保證。

## Non-Goals

- 不刪除 `plugin_hook.py` 與 gateway `handler.py`（未來規劃，本次僅修正其 `format_summary` import 來源）。
- 不為 `on_session_end` / `agent:end` 等沒有 `model` context 的 hook 加上 provider 自動偵測；本次自動偵測僅適用於 footer hook。
- 不支援 Codex、MiniMax 以外的 provider（架構保留擴充點，但本次不實作）。
- 不測試第三方 HTTP 行為；不引入 `python-dotenv` 等新相依。

## Capabilities

### New Capabilities

- `provider-detection`: 依 footer hook 的 `model` 字串偵測當前 provider、分派到對應抓取器，並以共用正規化結構產生帶 provider 名稱的 footer 摘要。
- `minimax-usage`: 讀取並正規化 MiniMax 國際版 `token_plan/remains` 用量，含 token 來源解析（環境變數與 `.env` fallback）。

### Modified Capabilities

(none)

## Impact

- Affected specs: 新增 `provider-detection`、`minimax-usage`
- Affected code:
  - New:
    - usage.py
    - minimax_usage.py
    - tests/test_usage.py
  - Modified:
    - codex_usage.py
    - hooks/footer_hook.py
    - hooks/plugin_hook.py
    - hooks/gateway/handler.py
    - README.md
  - Removed: (none)
