## Why

Footer 目前只顯示 5h 視窗用量，但兩個 provider 的 fetcher（`providers/codex_usage.py`、`providers/minimax_usage.py`）早已把 weekly 視窗正規化進 `windows["weekly"]`。使用者拿不到 weekly 資訊純粹是因為 `format_summary` 只渲染 5h，造成已抓取的資料被丟棄。補上 weekly 顯示能讓使用者一眼掌握短期與週用量兩個額度。

## What Changes

- `format_summary` 改為輸出**兩行**：第一行 5h、第二行 weekly，每行都以 provider 名開頭（例如 `Codex 5h …` / `Codex weekly …`）。
- 新增一個**統一的時間格式器**，5h 與 weekly 共用，把 `reset_in_min` 換算為人類可讀字串：`<1h` → `45m`、`<1d` → `2h17m`、`≥1d` → `6d4h`（小時為 0 時省略成 `6d`）、`0` → `0m`。
- `plan` 區段維持掛在 5h 行尾（沿用現狀），不重複出現在 weekly 行。
- **降級行為**：weekly 視窗缺失時只印 5h 行；5h 視窗缺失時維持現有 `<provider> usage: 5h window unavailable` 訊息。
- 不更動資料抓取層、provider 偵測、footer hook 或任何介面契約。

## Non-Goals

- 不修改 `providers/codex_usage.py`、`providers/minimax_usage.py` 的資料抓取或正規化邏輯（weekly 已存在）。
- 不改 `hooks/footer_hook.py` 的呼叫方式或 footer 外框（`───`、`🧮`）。
- 不新增 provider，也不調整 provider 偵測規則。
- 不引入額外的視窗（例如 monthly），僅渲染既有的 5h 與 weekly。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `provider-detection`: 「Render a provider-labeled usage summary」需求從「只渲染 5h 單行」擴充為「渲染 5h + weekly 兩行，並以統一時間格式器顯示重置時間」。

## Impact

- Affected specs: `provider-detection`
- Affected code:
  - Modified: usage.py（`format_summary` 與模組 docstring）、hooks/footer_hook.py（僅模組 docstring 字句，行為不變）
  - New: (none)
  - Removed: (none)
- Affected tests:
  - Modified: tests/test_usage.py
