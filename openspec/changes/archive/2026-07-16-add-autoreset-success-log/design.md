## Context

`hermes-usage-hook` v0.4.0 的 Codex auto reset 成功後只留下：(1) coordinator 狀態檔中會被下一次流程覆寫的 `cooldown_reason=success`，(2) 一次性的 footer notice。Hermes 官方 `hermes_logging.py` 將標準 logging 路由到 `$HERMES_HOME/logs/agent.log` / `errors.log`，皆為 5MB × 3 份輪替檔，不能作為永久歷史。

官方文件已確認三件事：plugin 自寫專用 JSONL 到 logs 目錄是官方 Hooks 指南示範過的模式（`command_usage.jsonl` 範例）；`hermes_constants.get_hermes_home()` 是 profile-safe 路徑解析的正式做法（依序讀 context override、`HERMES_HOME` 環境變數、平台預設）；`ctx.register_command()` 是聊天內 slash command 的正式 API，於 CLI 與 gateway 平台（Telegram、Discord）皆可用。

前一次嘗試（PR #15）以 durable outbox、每回覆 drain、終端機 CLI 與嚴格 schema 實作同一需求，程式碼 +1,000 行；xhigh code review 發現 12 個缺陷，最嚴重的三個（footer 被抑制、每回覆鎖競爭、非 POSIX 檔案系統上稽核永久失效）全部來自這些 durability 機器。本設計以「best-effort 寫入 + 聊天查詢」重做，接受極罕見的事件遺漏以換取一個數量級的複雜度下降。

## Goals / Non-Goals

**Goals:**

- 每次成功的 logical reset（backend 回 `reset` 或 idempotent retry 確認 `already_redeemed`）在本地留下一筆永久、可查詢的紀錄。
- 使用者在任何聊天平台輸入 `/usagehook history` 即可看到最近的 reset 歷史。
- 寫入為 best-effort：任何失敗都不影響 reset 結果、notice、footer 或後續流程。
- 隱私最小化：檔案中只有雜湊後的事件 ID、時間戳、backend 狀態與前後用量快照。

**Non-Goals:**

- 不做 durable outbox / drain / crash-window 保證——reset 約一週一次，掉一筆的代價只是歷史少一行。
- 不做終端機 CLI（`ctx.register_cli_command()`）——聊天內指令已覆蓋所有使用情境；未來確有需要時再以獨立 change 加入。
- 不記錄失敗或跳過的評估（`no_credit`、timeout、cooldown 等）。
- 不做輪替、修剪、刪除或歷史回填。
- 不在讀取端做嚴格 schema 拒絕——讀取寬容，略過無法解析的行。

## Decisions

1. **寫入點：`maybe_autoreset()` terminal success 分支，鎖內、`queue_fallback_notice_locked(...)`（success 分支唯一的持久化呼叫）完成之後，best-effort try/except 包裹**
   替代方案：PR #15 的 outbox + 三處 drain。否決理由：為毫秒級 crash 視窗引入的機器成為 review 缺陷的主要來源，且需求可容忍遺漏。append 失敗時以 `logging.getLogger(__name__).warning()` 記一行不含例外內文的靜態訊息（例外訊息可能含 backend 資料）。注意 success 分支目前以單一運算式直接 `return AutoResetResult(...)`，實作時需先完成 append 再 return（或先組出結果值）。單筆保證機制：preflight（`pre_llm_call`）與 footer（`transform_llm_output`）兩個 hook 都會呼叫 `maybe_autoreset`，同一回覆週期的第二次呼叫會被既有 success cooldown 擋下而不進 success 分支；即使兩次都進入，`event_id` 去重仍保證檔案只有一筆。

2. **查詢介面：`ctx.register_command()` 聊天內 slash command，而非終端機 CLI**
   替代方案：`ctx.register_cli_command()`（PR #15 的做法，argparse + `--last/--since/--json`，僅 terminal 可用）。否決理由：本 plugin 的使用者透過聊天平台互動（footer 本身就騎在回覆通道上）；slash command handler 收字串回字串，成本約為 CLI 的三分之一，且不需引入「讀取搶 coordinator lock」的規格。讀取不上鎖：JSONL append-only 檔的行級原子性足夠，最壞情況是漏看正在寫入的最後一行，下次查詢即可見。已查證官方 plugin 指南：`register_command()` 是純 runtime API，slash command 不需要在 manifest 宣告，因此 `plugin/plugin.yaml`（`provides_hooks` 清單）維持不變，既有的 manifest 測試也不受影響。

3. **去重：`sha256(redeem_request_id)` 作為 `event_id`，append 前全檔掃描跳過重複**
   替代方案：不去重。否決理由：`already_redeemed` retry 與 crash-after-append 情境會產生同一 logical reset 的第二筆，誤導「reset 了幾次」；檔案一週增長一行，全檔掃描成本趨近於零。雜湊同時保證原始 request ID 永不落地。

4. **路徑解析：獨立 `plugin/hermes_home.py` 模組，優先 `hermes_constants.get_hermes_home()`，`ModuleNotFoundError` 時退回 `HERMES_HOME` 環境變數（預設 `~/.hermes`）**
   替代方案：沿用 v0.4.0 `autoreset.py` 內建的 env-based 解析。否決理由：`get_hermes_home()` 是官方要求的 profile-safe 做法，且處理了 Windows 平台預設（AppData/Local）與 profile override；env fallback 讓單元測試與無 Hermes 環境照常運作。

5. **權限：開檔時以 mode `0o600` 建立並 best-effort `chmod`，不驗證、不 raise**
   替代方案：PR #15 的硬性驗證（st_mode 不符即 PermissionError）。否決理由：檔案內容本無敏感資料，硬性驗證在不支援 POSIX 權限的檔案系統上會讓寫入永久失敗（PR review CONFIRMED 缺陷）。

6. **事件為單層扁平 JSON，寫入時驗證、讀取時寬容**
   欄位見 Implementation Contract。替代方案：PR #15 的巢狀 before/after 快照 + 讀寫兩端 exact key-set 驗證。否決理由：扁平欄位讓 `jq` 與人工檢視更簡單；讀取端嚴格拒絕會讓 schema 演進時舊事件整批消失。

## Implementation Contract

**新模組 `plugin/autoreset_audit.py`**（目標 ≤ 100 行）：

- `build_success_event(*, redeem_request_id, observed_at, backend_status, weekly_before, weekly_after, credits_before, credits_after) -> dict`
  `observed_at` 輸入為 epoch 秒數（float，呼叫端傳 coordinator 的 `now`）。回傳扁平事件：`{"event_id": "sha256:<64 hex>", "observed_at": "<RFC3339 UTC，秒級，Z 結尾>", "backend_status": "reset"|"already_redeemed", "weekly_before": <0-100 數值|null>, "weekly_after": <同左>, "credits_before": <非負整數|null>, "credits_after": <同左>}`。
  `redeem_request_id` 空或非字串、`backend_status` 不在允許集合、`observed_at` 非有限或無法轉為 UTC 時間 → raise `ValueError`。用量快照欄位無效值一律寫 `null`（不 raise）。
- `append_success_event(event, *, home=None) -> bool`
  對 `<home>/logs/hermes-usage-hook-autoreset.jsonl` 追加一行 compact JSON；`event_id` 已存在於檔中則不追加並回傳 `False`，追加成功回傳 `True`。父目錄不存在時建立。以 `os.open(..., O_APPEND|O_CREAT|O_WRONLY, 0o600)` 開檔並 best-effort `chmod 0600`（失敗忽略）。
- `read_events(*, home=None) -> list[dict]`
  依檔案 append 順序回傳合法事件；「合法」= 該行可解析為 JSON dict、`event_id` 為符合 `sha256:<64 hex>` 的字串、`observed_at` 為可以 RFC 3339 解析的字串（不排序、不以 `observed_at` 重排）。無法解析或不合法的行靜默略過；檔案不存在回傳空 list。**不得**將原始行內容寫入任何日誌或例外訊息。

**新模組 `plugin/hermes_home.py`**：`resolve_hermes_home(home=None) -> Path`——注入值優先；否則 `hermes_constants.get_hermes_home()`；`ModuleNotFoundError`（限定 `hermes_constants` 本身）時退回 `Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()`。

**`plugin/autoreset.py` 修改**：terminal success 分支在 `queue_fallback_notice_locked(...)` 完成後，於同一 lock 範圍內執行：build event → `append_success_event(event, home=state_store.home)`，整段以 try/except 包裹；失敗僅 `logger.warning("auto-reset history append failed")`（靜態訊息，不含例外內文），回傳值與現有欄位完全不變。**home 必須貫穿注入 `state_store.home`**——不得讓 append 自行解析 home，否則注入 `home=tmp_path` 的測試會把事件寫進開發者真實家目錄，且正式環境的歷史檔可能與 coordinator 狀態落在不同 profile。呼叫端變數對應：`redeem_request_id` ← success 分支的區域變數 `request_id`；`weekly_before/weekly_after` ← `before_remaining`/`after_remaining`；`credits_before/credits_after` ← `before_credits`/`after_credits`；`observed_at` ← `now`。`maybe_autoreset` 新增可注入參數 `audit_log`（測試用，預設走真實模組函式）。

**`plugin/hooks/footer_hook.py` 修改**：`register(ctx)` 以 `getattr(ctx, "register_command", None)` 防護後註冊 `/usagehook`（缺 API 時記 warning 並跳過，兩個既有 hook 照常註冊）。handler 行為：

- 參數以空白 tokenize：恰為 `history`（區分大小寫）或 `history <N>`（N 為 1-100 的十進位整數）→ 回傳最新 N 筆（預設 5），依檔案 append 順序排列（舊在上、新在下），每筆一行：
  `2026-07-14 09:12 UTC | reset | weekly 4% → 100% | credits 3 → 2`
  時間戳由解析 `observed_at` 後以 UTC 分鐘精度 `YYYY-MM-DD HH:MM UTC` 格式化；快照為 null 的欄位顯示 `?`。標題行：`Codex auto-reset history (last <k>)`（k 為實際渲染筆數）。
- 無任何紀錄 → 回傳 `No Codex auto-reset history yet.`
- 其他輸入（含空字串、N 越界或非整數）→ 回傳用法說明 `Usage: /usagehook history [N]`。
- handler 內任何例外 → 回傳 `Codex auto-reset history is unavailable.`，不讓例外外洩到 gateway。

**驗收（新增測試涵蓋）**：成功 reset 恰寫一筆；同一 `redeem_request_id` 重試不產生第二筆；append raise 時 `maybe_autoreset` 回傳值與 notice 行為和現狀完全一致；malformed 行不出現在查詢輸出且不中斷解析；`/usagehook history` 三種輸出（有紀錄、無紀錄、錯誤用法）如上；`ctx` 無 `register_command` 時 plugin 照常註冊兩個 hook。

**Out of scope**：`maybe_autoreset` 既有的資格判定、cooldown、pending、notice 邏輯；terminal CLI；任何設定鍵。

## Risks / Trade-offs

- [Append 於 crash 或磁碟錯誤時遺漏一筆] → 接受：需求為便利性歷史，reset 頻率約一週一次；診斷 warning 仍可在 `errors.log` 看到。
- [讀取不上鎖，可能讀到寫到一半的最後一行] → 讀取端寬容略過無法解析的行；append-only 寫入下該行於下次查詢即完整可見。
- [`register_command` 在舊版 Hermes 不存在] → getattr 防護，缺 API 時僅失去查詢指令，footer 與 auto reset 不受影響。
- [歷史檔永久增長] → 每事件約 200 bytes、一週一筆，一年 <11KB；明確列為 Non-Goal，不做輪替。

## Migration Plan

無資料遷移。新檔案於首次成功 reset 時建立；舊安裝升級後行為不變，僅開始累積歷史。回滾即移除 plugin 新版本，歷史檔留在原地無副作用。
