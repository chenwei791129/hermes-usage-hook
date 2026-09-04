## Why

Codex auto reset 在真實耗盡情境下從未成功執行過一次。

帳號 weekly 額度用完時，Codex completions endpoint 回 HTTP 429，Hermes 隨即把該筆 pooled Codex 憑證標記成 `exhausted`，並記下冷卻結束時間。plugin 的憑證選擇邏輯把「冷卻未結束的 `exhausted` 憑證」視為不可用而排除；池中沒有其他健康憑證時就一筆都選不出來，解析退回扁平 layout、找不到 token，usage 查詢直接拋錯。coordinator 把這個例外吞成 transient cooldown，60 秒後重試，再拋，無限循環。

auto reset 的唯一觸發條件是 weekly 耗盡，而 weekly 耗盡正是該憑證被排除的唯一原因。這個功能因此在設計上永遠到不了消耗 reset credit 那一步。footer 路徑靠 `append_usage_footer()` 外層的 `except` 還會留下一行 `[hermes-usage-hook] skipped: ...`（根因就是靠這兩行定位到的），但 preflight 路徑完全靜默，只有 state 檔裡一個 `transient` 冷卻原因留下痕跡。

排除規則的前提是錯的：`exhausted` 描述的是 completions endpoint 撞到帳號配額，而本 plugin 呼叫的 usage 與 reset-credit 查詢端點不受該配額限制。已在一個啟用 auto reset 的部署上實測確認：一筆 `exhausted` 且冷卻仍有兩天以上的憑證，對兩個端點都正常回 HTTP 200，且回傳的 weekly 用量為 100%、可用 reset credit 大於零——完全符合觸發條件。

**本次改動不宣稱讓 auto reset 變得可觸發。** 部署後在同一套環境實測，plugin 端的憑證解析確實修好了（`is_eligible` 回 `True`、`windows` 含 `weekly`、`reset_credits_available` 為 2），但 auto reset 仍未執行。追查後確認還有兩道**在本 plugin 之外**的阻塞，兩者都不在本次範圍內：

1. **hook 到不了。** `pre_llm_call` 與 `transform_llm_output` 都只在 agent conversation loop 內被 invoke（`agent/turn_context.py` 的 `build_turn_context()` 與 `agent/turn_finalizer.py`）。但 Hermes 的 上游 provider resolver 在 gateway 層就因為 pooled Codex 憑證被標記 `exhausted` 而拋出 rate-limited 的 `AuthError`，隨即轉走 fallback provider，conversation loop 從未執行。憑證一旦耗盡，plugin 的 hook 就永遠不會被呼叫——與本次修正的是同一個結構性陷阱，只是發生在更上游一層。已用檔案探針證實：plugin 在 gateway 行程內正常載入且兩個 hook 都註冊，在獨立行程直接呼叫 Hermes 的 `lifecycle.invoke_hook("pre_llm_call", ...)` 也能正常送達本 plugin 的 callback，但真實 turn 兩個 hook 都沒有觸發。
2. **就算觸發了也無法恢復服務。** Hermes 自己的兌換路徑 上游帳號 reset 路徑 在成功後會呼叫 上游 cooldown 清理 helper，解除 `auth.json` 上因 429 而寫下的凍結。本 plugin 直接呼叫 ChatGPT backend 消耗 credit，沒有做這件事，所以即使消耗成功，Hermes 仍會把該憑證凍結到 `retry timestamp` 為止。

因此本次改動的定位是**必要但不充分**：它修好 plugin 自己的憑證選擇、失敗語意與可觀測性，這些缺陷各自獨立成立（尤其是 `rank` 為 `null` 時拋 `TypeError`，與 auto reset 無關）。本次另收斂安全可用的設定範圍：有效 `threshold` 改為 `1..99`；明確設定 `0` 會 fail closed、停用本次 auto-reset invocation，並向 stderr 輸出一行警告，說明 `threshold=0` 無法從已被 Hermes 凍結的憑證狀態自動恢復，該狀態應使用 Hermes 內建的 `/usage reset` 手動處理。這不改變 5h 資格政策；5h 行為由 Issue #21 處理，本次不討論。

## What Changes

- 憑證選擇把 `exhausted` 從硬性排除改成排序上的降級：不在冷卻中的憑證優先，池中全部都在冷卻中時仍選出優先序最高的一筆，而不是解析失敗。多憑證部署的既有行為不變——只要還有健康憑證，選到的就仍是 Hermes 實際輪替到的那一筆。
- 排序鍵改用正規化後的 `rank`：缺值、`null`、布林或任何非數值都當作 100。現行實作把原始值直接交給 `sorted()`，一筆 `rank: null` 的記錄就會在與整數預設值比較時拋 `TypeError`，掉進本次要修的同一個 transient 迴圈。
- `dead` 維持硬性排除。該狀態代表 token 已被伺服器端撤銷，任何呼叫都會被拒，降級使用沒有意義。
- 修正誤導性的 fallthrough：Hermes pool layout 存在且非空、卻挑不出任何憑證時，必須以指名原因的錯誤結束，不再退回扁平 layout 並回報「檔案裡沒有可用的 access token」——實際上 token 就在檔案裡，被規則排除掉而已。
- auto-reset coordinator 在把 usage 或 reset-credit 取得失敗吞成 transient cooldown 之前，必須輸出一行診斷訊息，沿用既有的 stderr 前綴慣例。preflight 觸發點目前完全靜默，是這個 bug 長期不可見的直接原因。
- 收緊 `threshold` 有效範圍為 `1..99`。env 或 plugin config 明確設定 `0`（以及其他無效值）時 fail closed，且每次 config 載入向 stderr 輸出恰好一行帶 `[hermes-usage-hook]` 前綴、包含設定錯誤原因與 `/usage reset` 建議的 warning。未啟用 auto reset 時仍不打 usage / credit API。

## Capabilities

### New Capabilities

- `codex-credential-resolution`: 從 Hermes 憑證庫或 Codex CLI auth 檔中選出 plugin 用來唯讀查詢 ChatGPT backend 的 Codex OAuth 憑證，涵蓋 pooled 記錄的排除與排序規則、解析失敗的錯誤語意，以及失敗的可觀測性。

### Modified Capabilities

- `codex-auto-reset`: 將 weekly-remaining `threshold` 的有效範圍從 `0..99` 收緊為 `1..99`；明確設定 `0` 時 fail closed 並輸出可操作的 warning，已凍結狀態改由 `/usage reset` 手動恢復。
- `footer-hook-deployment`: 同步安裝後文件與 `AGENTS.md` 所宣告的 threshold 範圍及 `0` 值處理方式。

## Impact

- Affected specs: `codex-credential-resolution`（新增）、`codex-auto-reset`（修改）、`footer-hook-deployment`（修改）
- Affected code:
  - Modified:
    - `plugin/providers/codex_usage.py`
    - `plugin/autoreset.py`
    - `tests/test_usage.py`
    - `tests/test_autoreset.py`
    - `plugin/after-install.md`
    - `AGENTS.md`（`CLAUDE.md` 是指向它的 symlink，必須就地編輯、不可覆寫成一般檔案）
  - New: （無）
  - Removed: （無）
