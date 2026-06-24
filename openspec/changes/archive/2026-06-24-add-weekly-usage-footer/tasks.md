## 1. 實作呈現層

- [x] 1.1 在 `usage.py` 新增共用時間格式器（例如 `_format_duration(minutes: int) -> str`），把整數分鐘轉為緊湊字串：`<60` → `<m>m`（含 `0m`）、`60..<1440` → `<h>h<m>m`、`≥1440` → `<d>d<h>h`（殘餘小時為 0 時省略成 `<d>d`）。
      驗證：以 `tests/test_usage.py` 的參數化案例覆蓋邊界 `0→0m`、`45→45m`、`90→1h30m`、`137→2h17m`、`8640→6d`、`8880→6d4h`，執行 `uv run pytest tests/test_usage.py` 全綠。
- [x] 1.2 依需求「Render a provider-labeled usage summary」改寫 `usage.py` 的 `format_summary`，輸出多行：第一行渲染 `5h` 視窗、第二行渲染 `weekly` 視窗（存在時），兩行皆以 `<provider> <label>` 開頭，每行報 `used X%, left Y%`，`reset_in_min` 存在時以 1.1 的格式器附加 ` (resets in <duration>)`；`plan` 段只掛在 `5h` 行；`weekly` 缺失時只回 `5h` 行；`5h` 缺失時維持回傳 `<provider> usage: 5h window unavailable` 且不渲染 weekly。多行以換行字元 `\n` 串接。同步更新 `format_summary` 的 docstring 與 `usage.py` 模組 docstring，把「focused on the 5h window」改為反映 5h + weekly 兩行輸出與共用時間格式器。
      驗證：`uv run pytest tests/test_usage.py` 通過；對討論中的 Codex 範例（5h used 42% resets 137min plan pro、weekly used 10% resets 8880min）輸出恰為 `Codex 5h | used 42%, left 58% (resets in 2h17m) | plan pro\nCodex weekly | used 10%, left 90% (resets in 6d4h)`。
- [x] 1.3 更新 `hooks/footer_hook.py` 的模組 docstring，把「append the current provider's 5h usage」等只提 5h 的敘述改為 5h + weekly；不更動 `register`、`append_usage_footer` 的呼叫方式或 footer 外框（`───`、`🧮`）。
      驗證：`uv run pytest tests/test_usage.py` 仍全綠（行為未變，僅文件字句）；docstring 不再宣稱只有 5h。

## 2. 測試

- [x] 2.1 更新 `tests/test_usage.py`：補上 `_format_duration` 的參數化測試、`format_summary` 的兩行輸出測試（Codex 含 plan、MiniMax 無 plan）、weekly 缺失只印 5h 行、以及 5h 缺失維持 unavailable 訊息四種情境；同步調整既有 5h 斷言——`test_format_summary_codex_includes_plan`（`137 min` → `2h17m`）與 `test_format_summary_minimax_omits_plan`（`281 min` → `4h41m`）的重置字串會隨共用格式器改變，且兩者需改為斷言兩行輸出。
      驗證：`uv run pytest tests/test_usage.py` 全綠，且 `uv run ruff check usage.py tests/test_usage.py` 無錯。
