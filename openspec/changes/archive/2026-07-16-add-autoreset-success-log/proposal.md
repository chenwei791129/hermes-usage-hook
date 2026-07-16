## Why

Codex auto reset 成功後，目前只留下一次性的 footer notice 與會被覆寫的 coordinator 狀態；Hermes 的標準日誌（`agent.log`）採 5MB × 3 份輪替，無法作為永久紀錄。使用者因此無法回答「上次 reset 是什麼時候發生的」。先前的 PR #15 以 durable outbox + 終端機 CLI 實作了這個需求，但引入了與需求不成比例的複雜度（每次回覆的跨程序鎖、outbox drain 機器、嚴格 schema 與權限強制），review 發現的最嚴重缺陷全部來自這些機器。本 change 以最小範圍重做：best-effort 寫入 + 聊天內查詢。

## What Changes

- 新增 profile-scoped、append-only 的 JSONL 歷史檔 `$HERMES_HOME/logs/hermes-usage-hook-autoreset.jsonl`（官方 Hooks 指南示範過的 plugin 自有 JSONL 模式）。
- `maybe_autoreset()` 的 terminal success 分支（backend 回覆 `reset` 或 `already_redeemed`）在既有 coordinator lock 內 best-effort 追加一筆事件；追加失敗只記標準 logging 警告，絕不影響 reset 結果、notice 或 footer。
- 事件以 `sha256(redeem_request_id)` 作為 `event_id` 去重，永不落地原始 request/credit/session 識別碼。
- 新增聊天內 slash command `/usagehook`（透過官方 `ctx.register_command()` API），在 CLI、Telegram、Discord 等所有平台輸入 `/usagehook history` 即可查詢最近的 reset 歷史。
- 路徑解析採 `hermes_constants.get_hermes_home()`（支援 HERMES_HOME 覆寫、Windows 平台預設與 profile override），模組不可匯入時退回 `HERMES_HOME` 環境變數。
- 歷史檔永久保留，不自動輪替、修剪或刪除。

## Capabilities

### New Capabilities

- `autoreset-success-history`: 成功 auto reset 的本地永久歷史——事件結構、best-effort 寫入語意、去重、以及 `/usagehook history` 查詢指令。

### Modified Capabilities

（無——既有 auto reset 能力的資格判定、redeem 流程與 notice 行為皆不變；成功分支僅「附帶」一次 best-effort 寫入，失敗時行為與現狀完全相同。）

## Impact

- Affected specs: 新增 `openspec/specs/autoreset-success-history/spec.md`（以 delta 形式建立）。
- Affected code:
  - New: `plugin/autoreset_audit.py`（事件建構、append、去重、讀取）、`plugin/hermes_home.py`（home 解析）、`tests/test_autoreset_audit.py`
  - Modified: `plugin/autoreset.py`（success 分支插入 best-effort 寫入）、`plugin/hooks/footer_hook.py`（註冊 `/usagehook` slash command）、`tests/test_autoreset.py`、`tests/test_usage.py`、`README.md`（文件與查詢說明）
  - Removed: 無
- 不新增設定鍵、不新增網路呼叫、不改變 auto reset 資格規則。
