## Why

Codex 現在提供 banked rate-limit reset credits，且 ChatGPT backend API 支援列出與消耗重置券。現有 plugin 只顯示可用次數；使用者在 weekly 額度耗盡時仍需切換到 Codex App 手動操作。新增 opt-in auto reset，可在 weekly 剩餘額度達指定門檻時安全使用最早到期的券，避免模型請求因 weekly quota 中斷。

## What Changes

- 新增正式 Hermes plugin config：`plugins.entries.hermes-usage-hook.auto_reset.enabled`（預設 `false`）與 `plugins.entries.hermes-usage-hook.auto_reset.threshold`（預設 `0`，代表 weekly 剩餘百分比，合法範圍 `0..99`）。
- 保留 `CODEX_ENABLE_AUTORESET` 與 `CODEX_AUTORESET_THRESHOLD` 作為部署環境 override；優先順序為 env → plugin config → defaults。啟用值為 true 視為使用者對 plugin 自動消耗 Codex reset credit 的持續授權。
- 同時在 `pre_llm_call` 與既有 footer 流程檢查：模型請求前可救援已耗盡狀態，成功回覆後可立即處理剛跨過門檻的狀態。
- 兩個觸發點共用單一 auto-reset coordinator，以跨程序鎖、鎖內重新查詢、持久化 idempotency key 與 cooldown 防止重複消耗。
- 符合條件時，查詢 reset-credit 詳細清單，選擇最早到期且狀態為 `available` 的券，呼叫 `POST /wham/rate-limit-reset-credits/consume`。
- 成功後重新抓取 usage 與 credits，footer 顯示一行透明稽核訊息，例如 `Codex auto reset | weekly 0% → 100% | reset credits 3 → 2`。
- 所有錯誤 fail-closed：不猜測缺失的 weekly window、不自動改用其他 window、不破壞原本模型回覆。

## Non-Goals

- 不自動 reset 5h、daily、monthly、annual 或其他非 weekly window。
- 不在 effective `auto_reset.enabled` 為 false 時增加 pre-request usage API 呼叫。
- 不提供排程背景 polling；只在 Hermes 對話生命週期 hook 被觸發時檢查。
- 不新增手動 `/codex-reset` 指令。
- 不在 state file 保存 OAuth token、refresh token 或其他秘密。
- 不承諾 ChatGPT 內部 backend API 的長期穩定性；schema 或 endpoint 改變時只記錄錯誤並停用該次重置。

## Capabilities

### New Capabilities

- `codex-auto-reset`: 以明確 opt-in 設定、weekly 剩餘百分比門檻與防重機制，自動消耗 Codex banked reset credit。

### Modified Capabilities

- `footer-hook-deployment`: plugin 新增 `pre_llm_call` hook，並在 auto reset 成功後於 footer 顯示稽核訊息。

## Impact

- Affected specs: new `codex-auto-reset`; modified `footer-hook-deployment`.
- Expected code: new `plugin/autoreset.py`; modify `plugin/providers/codex_usage.py`, `plugin/hooks/footer_hook.py`, `plugin/plugin.yaml`, `README.md`, and tests.
- Runtime state: `$HERMES_HOME/state/hermes-usage-hook/autoreset.json` and atomic lock directory `autoreset.lock/`.
