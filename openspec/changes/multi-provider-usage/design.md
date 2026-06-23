## Context

`codex_usage.py` 內建 Codex (ChatGPT OAuth) 用量抓取與 `format_summary`，`hooks/footer_hook.py` 透過 `transform_llm_output` 把 Codex 5h 用量接在每則回覆後。但使用者的 Hermes 同時接 Codex (OAuth) 與 MiniMax 國際版兩個後端，footer 寫死抓 Codex，導致 MiniMax 回覆也顯示 Codex 數字。

關鍵事實：`transform_llm_output` 的 context 帶有 `model` 欄位（README 第 90 行），可作為「本次回覆用哪個 provider」的精準訊號；而 `on_session_end` / `agent:end` 沒有 `model`，因此自動偵測僅適用 footer hook。MiniMax 國際版提供 `GET https://www.minimax.io/v1/token_plan/remains`，回傳 per-model 的 interval（5h）與 weekly 視窗百分比，結構可正規化成與 Codex 相同的形狀。

## Goals / Non-Goals

**Goals:**

- footer hook 依當前回覆實際使用的 provider，回報對應用量。
- Codex 與 MiniMax 共用同一個正規化結構與同一個 `format_summary`。
- 偵測或抓取失敗時 footer 保持原回覆不變（永不破壞回覆）。
- 維持扁平模組結構與零外部新相依，新增第三個 provider 僅需一個新模組 + registry 加一行。

**Non-Goals:**

- 不刪除 `plugin_hook.py` 與 gateway `handler.py`（未來規劃）。
- 不為缺少 `model` context 的 hook 加自動偵測。
- 不支援 Codex / MiniMax 以外的 provider。
- 不測試第三方 HTTP 行為，不引入 `python-dotenv`。

## Decisions

### 以 model 字串偵測 provider 並分派

footer hook 從 `kwargs["model"]` 取得模型名，交給 `usage.get_usage_for_model(model)`。`usage.py` 維護一個有序 registry：每個 provider 提供一個 `matches(model) -> bool` 判斷式與一個 `fetch() -> dict` 抓取器，依序比對命中即抓取並回傳正規化結構，皆不命中回傳 `None`。比對採大小寫不敏感：Codex = 含 `codex` 或以 `gpt-` / `o1` / `o3` / `o4` 開頭；MiniMax = 含 `minimax` 或 `abab`。

替代方案：用「哪個 credential 存在」判斷 — 否決，因為兩個 provider 的 credential 可能同時存在，無法區分本次回覆實際用哪個。

### 共用正規化結構與 format_summary 移到 usage.py

正規化結構為 `{ "provider": str, "plan_type": str|None, "windows": {"5h": {...}, "weekly": {...}} }`，每個 window 為 `{used_percent, remaining_percent, reset_in_min}`。`format_summary(usage)` 移到 `usage.py`，只依賴此結構，讀 `usage["provider"]` 產生帶 provider 名稱的一行摘要；`plan_type` 為 `None` 時不接 `| plan ...` 段。`codex_usage.py` 保留 `get_codex_usage` 與 OAuth refresh，其 `_normalize` 額外帶上 `"provider": "Codex"`。`format_summary` 搬離後，`codex_usage.py` 的 `__main__` 區塊改為從 `usage` 匯入 `format_summary`（於 `__main__` 內延遲匯入，避免與 `usage.py` 在 top-level 匯入 `codex_usage` 形成循環匯入），使 `uv run codex_usage.py` 仍可印出摘要。

替代方案：每個 provider 各自有 format 函式 — 否決，會造成格式漂移；單一 formatter 確保兩 provider 輸出一致。

### MiniMax token 來源：環境變數優先、.env fallback

`minimax_usage.py` 先讀 `os.environ["MINIMAX_API_KEY"]`；缺少時用極簡 `KEY=VALUE` parser 解析 `$HERMES_HOME/.env`（`HERMES_HOME` 未設則預設 `~/.hermes/.env`），只擷取 `MINIMAX_API_KEY` 一行，去除外層引號。兩者皆無則拋出例外。

替代方案：引入 `python-dotenv` — 否決，為維持零外部新相依，自寫 ~10 行 parser 即足夠。

### MiniMax token_plan/remains 正規化（取 general 模型）

純函式 `_normalize(raw)` 接收 `token_plan/remains` 回傳 JSON：先檢查 `base_resp.status_code == 0`，否則拋例外；在 `model_remains` 中取 `model_name == "general"` 那筆；映射 `5h` window 為 `remaining_percent = current_interval_remaining_percent`、`used_percent = 100 - 它`、`reset_in_min = round(remains_time / 60000)`；`weekly` window 用 `current_weekly_remaining_percent` 與 `weekly_remains_time`。`plan_type` 設為 `None`。`provider` 設為 `"MiniMax"`。網路抓取與 `_normalize` 分離，測試只針對 `_normalize`。

## Implementation Contract

**Behavior:** 當 footer hook 收到一則回覆，依 `model` 判斷 provider：模型屬 Codex → footer 顯示 Codex 5h 用量；屬 MiniMax → 顯示 MiniMax 5h 用量；無法辨識或抓取失敗 → 回傳 `None`，回覆內容不變、不附 footer。

**Interface / data shape:**

- `usage.get_usage_for_model(model: str | None) -> dict | None`：回傳正規化結構或 `None`。
- 正規化結構：`{"provider": "Codex"|"MiniMax", "plan_type": str|None, "windows": {"5h": {"used_percent": int, "remaining_percent": int, "reset_in_min": int|None}, "weekly": {...}}}`。
- `usage.format_summary(usage: dict) -> str`：輸出如 `Codex 5h | used 42%, left 58% (resets in 137 min) | plan pro` 或 `MiniMax 5h | used 4%, left 96% (resets in 281 min)`。
- `minimax_usage.get_minimax_usage() -> dict`、`minimax_usage._normalize(raw: dict) -> dict`。
- `codex_usage.get_codex_usage() -> dict`（既有，輸出新增 `"provider": "Codex"`）。
- `hooks/footer_hook.py` 的 `append_usage_footer(response_text, **kwargs)` 從 `kwargs.get("model")` 取模型。

**Failure modes:** 任何例外（缺 token、HTTP 失敗、`status_code != 0`、找不到 general 模型、無法辨識 provider）一律在 footer hook 以 `try/except` 吞掉並回 `None`，記到 stderr 前綴 `[codex-usage-hook]`，絕不向上拋。

**Acceptance criteria:**

- `tests/test_usage.py` 通過：偵測映射（Codex/MiniMax/未知各案例）、MiniMax `_normalize`（用真實 sample payload 斷言 5h 與 weekly 百分比與 reset 分鐘數）、`format_summary` 對兩 provider（含有無 `plan_type`）的輸出格式。
- `plugin_hook.py` 與 `gateway/handler.py` 改從 `usage` import `format_summary` 後仍可正常 import。
- 手動：`uv run codex_usage.py` 仍輸出 Codex 摘要。

**Scope boundaries:**

- In scope：`usage.py`、`minimax_usage.py`、`codex_usage.py`（搬移 format_summary、normalize 加 provider 欄）、`hooks/footer_hook.py`、`hooks/plugin_hook.py` 與 `hooks/gateway/handler.py` 的 import 修正、`tests/test_usage.py`、README。
- Out of scope：刪除任何 hook、其他 provider、為無 model 的 hook 加偵測、MiniMax OAuth/refresh。

## Risks / Trade-offs

- [偵測規則仰賴 model 命名慣例，Hermes 實際傳的字串可能與假設不同] → 比對規則集中在 `usage.py` 易於調整；不命中時 footer 安全略過而非顯示錯誤 provider。
- [MiniMax `token_plan/remains` 為非公開合約，可能變動] → `_normalize` 防禦性檢查 `status_code` 與 general 模型存在；抓取整體包在 try/except，失敗只略過 footer。
- [Hermes 可能未把 home `.env` 注入 process 環境] → 故加上 `.env` fallback parser；兩路皆無才失敗。

## Open Questions

- Hermes 對 MiniMax 後端在 `model` 欄位實際送出的字串為何（用以驗證偵測規則涵蓋）；可於部署後以 stderr log 觀察並微調 `matches` 規則。
