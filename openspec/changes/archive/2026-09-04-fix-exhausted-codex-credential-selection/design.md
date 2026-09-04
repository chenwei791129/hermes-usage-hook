## Context

plugin 讀取 Codex OAuth 憑證時支援三種 auth 檔 layout：Hermes 的 `provider map` 巢狀記錄、Hermes 的 `credential list` 優先序清單，以及 Codex CLI 的扁平 layout。pool layout 的挑選規則來自一次未走 spec 流程的直接修補，目前沒有任何 capability 描述它。

該規則的意圖是「鏡射 Hermes 自己的輪替」：排除 `dead`，並排除冷卻未結束的 `exhausted`，避免在 Hermes 已切換到較低優先序的健康憑證時，footer 卻顯示一個被淘汰帳號的用量。意圖合理，但套用範圍錯了。

`exhausted` 是 Hermes 在 completions endpoint 收到 HTTP 429 配額耗盡時寫上的狀態，`retry timestamp` 記的是該配額的重置時間。plugin 呼叫的不是 completions endpoint，而是 usage 與 reset-credit 兩個唯讀查詢端點，這兩者不受帳號配額限制。以合成測試情境確認：一筆標記為 `exhausted` 且仍在冷卻中的憑證，仍可查詢兩個唯讀端點。

後果是 Codex auto reset 在設計上無法被觸發。它的唯一觸發條件是 weekly 耗盡，而 weekly 耗盡正是憑證被標記 `exhausted` 的原因；池中沒有其他健康憑證時，選擇結果為空，解析退回扁平 layout、找不到 token、拋錯。coordinator 把例外吞成 transient cooldown 後靜默返回。footer 路徑因為 `append_usage_footer()` 外層的 `except` 還會印一行 `[hermes-usage-hook] skipped: ...`，preflight 路徑則完全沒有任何日誌指出原因。

## Goals / Non-Goals

**Goals:**

- 池中所有 Codex 憑證都在 `exhausted` 冷卻中時，仍能解析出一筆可用憑證，讓 auto reset 在它唯一該啟動的狀態下實際可達。
- 保留原規則在多憑證情境下的正確行為：只要池中還有非冷卻憑證，選到的仍是 Hermes 實際輪替到的那一筆。
- 讓憑證解析失敗說出真正的原因，而不是回報一個與事實相反的訊息。
- 讓 coordinator 吞掉的取得失敗留下可追查的痕跡。
- 防止 `threshold=0` 提供錯誤的自動恢復期待：明確設為 0 時 fail closed、輸出可操作的 stderr warning，並引導維運以 `/usage reset` 恢復已凍結狀態。

**Non-Goals:**

- 不調整 5h 視窗的資格判定；這由 Issue #21 處理，本次只收緊 weekly threshold 設定的下限與失敗提示。
- 不調整 window-label helper 對未知視窗長度的處理。ChatGPT backend 近期確實改過 rate-limit payload 形狀，未知長度會讓 weekly 視窗消失並靜默判定不合格，但那是獨立缺陷，本次不處理。
- 不採用 backend 新增的 `eligible_remaining` 與 credit 的 `plan_eligible` 欄位。目前的選擇邏輯在實測資料上仍然正確。
- 不調整 coordinator 先取 usage 再檢查 cooldown 的順序。那個順序讓 preflight 觸發點在冷卻期間仍會打一次 usage API，屬於既有行為，改動會牽動現有 cooldown 語意與測試。
- 不處理 `maybe_autoreset()` 最外層那個把所有例外收成 `AutoResetResult("error")` 的 `except`。它同樣完全靜默（preflight 不會再拋，footer_hook 的 `except` 因此永遠不會觸發），涵蓋 config 載入、state 讀寫與搶鎖失敗。本次只補三個取得步驟，是因為那三處才是本 bug 的實際路徑；最外層的靜默是獨立且更廣的可觀測性缺口，留待後續。
- 不引入 token refresh。plugin 對憑證維持唯讀，不寫回、不輪換。
- 不改動 Hermes 端的憑證輪替行為，plugin 只調整自己的讀取偏好。
- 不處理「Hermes 在 gateway 層中止 turn，導致 plugin hook 從未被呼叫」這道阻塞。上游 provider resolver 對 `exhausted` 憑證拋 rate-limited `AuthError` 的行為屬 Hermes core，修正它需要的是改變 plugin 的觸發點或 Hermes 的解析行為，兩者都超出本次「修正 plugin 自己的挑選規則」的範圍。
- 不在成功消耗 reset credit 後呼叫 上游 cooldown 清理 helper 來解除 Hermes 的 pool 凍結。這是讓 reset 真正恢復服務所必需的一步，但它會讓本 plugin 從唯讀憑證消費者變成 `auth.json` 的寫入者，是獨立的設計決策，留待後續 change。

## Decisions

### 決策一：`exhausted` 從硬性排除改為兩層排序

把單一 舊的單層 selector predicate 述詞拆成兩個語意不同的述詞：

- **硬性排除**（不可選）：非 dict、`token` 缺失或為空、或 `state marker` 為 `dead`。
- **軟性降級**（可選但排後面）：`state marker` 為 `exhausted` 且 `retry timestamp` 是一個大於當下時間的數值。

挑選時先在「未降級」的候選中依 `rank` 昇冪取第一筆；該層為空時，才在「已降級」的候選中依同樣規則取第一筆。`rank` 缺失、為 `null`、為布林或任何非數值時一律當作 100，且排序鍵一律取正規化後的值——直接把原始 `rank` 丟給 `sorted()` 會在 `null` 與整數預設值之間比較而拋 `TypeError`，那個例外會沿著 credential loader 逃出去，掉進本次要修的同一個 transient 迴圈。排序維持穩定，優先序相同時保留檔案原始順序。

替代方案是直接刪掉 `exhausted` 判斷、讓所有非 `dead` 憑證同列一層依 `rank` 排序。捨棄的理由是它會退回到修補 #5 想解決的問題：Hermes 已輪替到較低優先序的健康憑證時，plugin 仍會選中優先序較高但已耗盡的那筆，footer 顯示的帳號與實際跑模型的帳號不一致。兩層排序同時滿足兩個需求，成本只是一次額外的分層。

### 決策二：`dead` 維持硬性排除

`dead` 代表 token 已被伺服器端撤銷或失效，任何呼叫都會拿到 401，降級使用不會產生任何可用結果，只會把一個明確的「無可用憑證」錯誤換成一個模糊的 HTTP 錯誤。維持排除。

### 決策三：pool 非空但選不出憑證時明確失敗，不退回扁平 layout

目前 pool 挑選為空時會落到扁平 layout 的 `return raw`，接著在頂層找不到 `credential bundle`，最終錯誤訊息宣稱 auth 檔沒有可用的 access token——與事實相反，token 就在檔案裡，只是被規則排除了。

改為：`provider-a` 的 pool 清單存在且非空、但通過硬性排除後沒有任何候選時，直接以一個指名原因的錯誤結束。清單不存在或為空時，維持既有的扁平 layout fallthrough，因為那代表該部署確實沒有 pooled Codex 憑證。

錯誤訊息只描述總筆數與排除原因的類別，不得包含 token、refresh token、憑證識別碼、指紋、帳號識別碼或電子郵件。

### 決策四：coordinator 的 transient 失敗輸出一行 stderr 診斷

coordinator 有三處把例外吞成 `transient` cooldown：初次取 usage、鎖內重新取 usage、取 reset-credit 清單。三處都在 `except` 區塊的開頭——也就是搶鎖與設定 cooldown 之前——輸出一行帶 `[hermes-usage-hook]` 前綴的 stderr 訊息，指出是哪一個取得步驟失敗與例外文字。

初次取 usage 那一處在鎖已被別人持有時回傳 `busy` 而非 `transient`，這條路徑同樣要輸出診斷：取得確實失敗了，只因為剛好撞到鎖就靜默，會把這個 requirement 想消除的盲點原樣搬回來。因此輸出點放在 `except` 開頭，而不是綁在 `_set_cooldown()` 旁邊。

選擇 stderr 而非模組 logger，是因為 stderr 是這個 plugin 已文件化且經實測會進到部署日誌的診斷通道——footer 路徑用的就是它，本次的根因也正是靠它留下的那兩行才被定位到。模組 logger 的輸出是否落地取決於宿主的 logging 設定，不可靠。代價是 autoreset 模組要新增 stderr 輸出（該模組目前只用 logger）。

### 決策五：`threshold` 僅接受 `1..99`，明確設定 0 時 fail closed 並警告

`threshold=0` 會讓 auto reset 直到 weekly remaining 已降到 0 才符合資格；若 Hermes 已先把 pooled 憑證標為 `exhausted` 並在 gateway provider resolution 階段轉走 fallback，agent conversation loop 不會開始，plugin 的 `pre_llm_call` 與 `transform_llm_output` 都到不了。這個值因而無法提供維運直覺中的「耗盡後自動恢復」保證。

收緊 env 與 plugin config 的有效範圍為整數 `1..99`。明確設定 `0` 時沿用既有 invalid-config 模型：effective config 為 `enabled=false`、`valid=false`，coordinator 回 `invalid_config` 且不呼叫 usage、credit-list 或 consume API。每次 config 載入遇到這個 invalid 值時，立即向 stderr 輸出恰好一行 warning，沿用 `[hermes-usage-hook]` 前綴，訊息同時包含 `threshold` 必須在 `1..99` 的原因與「已凍結狀態使用 `/usage reset`」的可操作指引。stderr 寫入必須 best-effort；輸出失敗不得改變 fail-closed 結果。

不採用「把 0 靜默提升成 1」：那會在操作者不知道的情況下改變 credit 消耗政策。也不在本次加入 `pre_gateway_dispatch`，因為操作者已選擇讓已凍結狀態由 `/usage reset` 手動處理。5h 資格判定由 Issue #21 獨立處理。

## Implementation Contract

**行為**

- `threshold` 只接受 `1..99`；env 或 plugin config 明確設定 `0` 時 fail closed，auto reset 不打 usage、credit-list 或 consume API。
- `threshold=0` 的每次 config 載入向 stderr 輸出恰好一行 warning；warning 帶 `[hermes-usage-hook]` 前綴、點名 `threshold` 的 `1..99` 有效範圍，並建議用 `/usage reset` 處理已凍結狀態。輸出本身失敗不得改變 fail-closed 結果。
- pooled Codex 憑證的挑選順序為：先取未處於 `exhausted` 冷卻中的候選、依 `rank` 昇冪取第一筆；該層為空時，於處於冷卻中的候選裡以同樣規則取第一筆。
- `state marker` 為 `dead`、或缺少非空 `token` 的記錄，永不被選中。
- 池中全部憑證都處於 `exhausted` 冷卻時，解析成功並回傳優先序最高的那一筆，usage 查詢與 auto reset 因此可以繼續進行。
- 池中同時存在 `dead` 與冷卻中的 `exhausted` 記錄時，選中的是 `exhausted` 那筆。

**介面與資料形狀**

- 憑證解析對外的回傳形狀不變：`credential list` layout 仍投影成一個帶 `credential bundle` 的 dict，內含 `token`、`renewal secret`、`account reference`；`provider map` 與扁平 layout 仍原樣回傳，不做正規化——它們可能合法地缺 `renewal secret` / `account reference`，扁平 layout 甚至可能只有頂層 `OPENAI_API_KEY` 而沒有 `credential bundle`，硬套統一形狀會打破現有的 flat-layout regression test。
- 三種 layout 的優先順序不變：`provider map` 巢狀記錄優先於 `credential list`，兩者都不適用時才是扁平 layout。
- 判定「處於 `exhausted` 冷卻中」的條件為：`state marker` 等於 `exhausted`，且 `retry timestamp` 是一個大於當下時間的數值（布林值不算數值）。缺值或已過期都不算冷卻中。

**失敗模式**

- `provider-a` 的 pool 清單存在且非空、但無任何記錄通過硬性排除時，拋出 `RuntimeError`。訊息須指出是憑證池挑選失敗與記錄總數，且不得包含任何 token、憑證識別碼、指紋、帳號識別碼或電子郵件。
- pool 清單不存在或為空時，維持既有行為，退回扁平 layout 解析。
- auto-reset coordinator 因取 usage 或取 reset-credit 清單失敗而設定 transient cooldown 時，先向 stderr 輸出一行帶 `[hermes-usage-hook]` 前綴、指出失敗步驟與例外文字的訊息。cooldown 秒數、回傳狀態與冪等性行為都不變。
- env 或 plugin config 的 `threshold=0` 與其他無效 threshold 一樣產生 invalid config：coordinator 回 `invalid_config` 且不執行任何 auto-reset API 呼叫；與一般 invalid threshold 不同的是 0 的 warning 必須包含 `/usage reset` 恢復指引。
- 被選中的憑證其 token 已過期時，行為與現行一致：usage 呼叫失敗、footer 省略，並由上述診斷行說明原因。

**驗收條件**

- 池中兩筆記錄皆為 `exhausted` 且冷卻未結束時，憑證解析回傳優先序較高那筆的 access token，且不拋錯。
- 池中一筆 `dead`、一筆 `exhausted` 冷卻中時，解析回傳 `exhausted` 那筆的 access token。
- 池中僅有 `dead` 記錄時，解析拋出 `RuntimeError`，且訊息字串不包含記錄裡的 `token`、`renewal secret`、`id` 或 `account reference` 任一值。
- 池中兩筆健康記錄、其中一筆 `rank` 為 `null` 時，解析回傳另一筆的 access token 且不拋 `TypeError`。
- `provider-a` 對應到空清單時，解析仍退回扁平 layout 並取得該 layout 的 token。
- 既有三個 pool 挑選測試在不修改斷言的前提下持續通過：`dead` 被跳過、冷卻中的 `exhausted` 讓位給健康憑證、冷卻結束後的 `exhausted` 依 `rank` 被選回。
- coordinator 的 usage 取得函式拋例外時，回傳狀態仍為 `transient`，且 stderr 收到恰好一行含 `[hermes-usage-hook]` 前綴的訊息。初次取 usage 失敗且搶不到鎖（回傳 `busy`）時，同樣收到恰好一行。
- plugin config 與 env override 各自明確設定 `threshold=0` 時，config resolution 回 invalid/disabled，stderr 各收到恰好一行含 `[hermes-usage-hook]`、`threshold`、`1..99` 與 `/usage reset` 的 warning，且 API test doubles 都沒有被呼叫。
- `threshold=1` 與 `threshold=99` 仍是有效邊界；threshold 缺省時 effective config 維持 `enabled=false`、`threshold=0`，因為 disabled default 不是操作者明確設定 0，不輸出 warning。
- `uv run pytest`、`uv run ruff check .` 與 `uv run ty check` 全數通過。

**範圍邊界**

- 在範圍內：pooled Codex 憑證的挑選順序與失敗語意、coordinator transient 失敗的診斷輸出、`threshold=0` 的 fail-closed warning、對應測試，以及 `plugin/after-install.md` 與專案 `AGENTS.md`（`CLAUDE.md` 是指向它的 symlink）的同步說明。
- 在範圍外：5h 資格判定（Issue #21）、`pre_gateway_dispatch`、成功 reset 後解除 Hermes pool cooldown、視窗標籤對未知長度的處理、backend 新增欄位的採用、coordinator 取 usage 與檢查 cooldown 的先後順序、token refresh、Hermes 端輪替邏輯、plugin 版本號與發布流程。

## Risks / Trade-offs

- 本次修好憑證解析後，auto reset 仍不會觸發 → 部署實測已確認這件事發生了，但**原因不是**原先記在這裡的兩條 Non-Goal。window-label helper 對未知視窗長度、以及 `quota.remaining` 的欄位名，兩者都經實測排除：合成驗證顯示 normalized 結果含預期的 weekly bucket、可用 credit 為非零、資格判定成立且 cooldown 未啟用。真正的阻塞有兩道，都在本 plugin 之外：（一）`pre_llm_call` 與 `transform_llm_output` 都只在 agent conversation loop 內 invoke（上游 conversation-loop hooks），而 Hermes 的 上游 provider resolver 在 gateway 層就因憑證被標記 `exhausted` 而拋 rate-limited `AuthError` 並轉走 fallback，conversation loop 從未執行，hook 因此永遠不會被呼叫；（二）Hermes 自己的 `redeem_codex_reset_credit()` 成功後會呼叫 `clear_codex_pool_quota_cooldowns()` 解除 `auth.json` 上的凍結，本 plugin 直接打 backend 消耗 credit，沒有做這件事，所以即使消耗成功，Hermes 仍會把憑證凍結到 `retry timestamp` 為止。因此本次改動的驗收僅保證「plugin 端的憑證解析不再是阻塞點」，明確**不**保證 auto reset 已可實際觸發；兩道上游阻塞留待後續 change。
- 診斷資訊不足會讓上游阻塞難以定位 → 這次追查耗時的主因正是 coordinator 與 hook 路徑全程靜默：`maybe_autoreset()` 最外層的 catch-all（本次列為 Non-Goal）不輸出任何訊息，`codex_autoreset_preflight` 也只在 `maybe_autoreset` 拋出時才印，而它從不拋。最後是靠在部署版臨時插入寫檔探針才確認 hook 根本沒被呼叫。本次新增的三處 stderr 診斷涵蓋的是取得步驟失敗，涵蓋不到「hook 未被呼叫」這種情況；後續 change 若要處理上游阻塞，應一併補上最外層 catch-all 的診斷。
- 池中僅有 `dead` 記錄、但同一份 auth.json 又保留著舊版的頂層 `credential bundle` 時，決策三會讓原本可用的解析改成硬失敗 → 這種形狀只會出現在從單憑證 layout 遷移到 pool layout 後仍留著舊欄位的 Hermes 安裝。取捨是刻意的：舊的頂層 token 與 pool 已經不同步，沿用它會讓 footer 顯示一個 Hermes 根本沒在用的帳號，而明確失敗至少會說出原因。實作時要確認錯誤訊息點名的是「池中沒有可用憑證」，讓維運看得出頂層 token 被刻意忽略。
- 池中所有憑證都在冷卻時，footer 會顯示一個 Hermes 當下無法用於 completions 的帳號 → 該情況下 Hermes 也沒有健康的 Codex 憑證可輪替，顯示優先序最高的那筆仍是最貼近實際的答案；且這正是需要顯示用量與觸發 auto reset 的時刻。
- 被降級選中的憑證，其 access token 可能已過期 → plugin 本來就不 refresh token，過期的結果與現行一致（usage 失敗、footer 省略），差別只在於現在會留下一行說明原因的診斷。
- transient 診斷行在持續失敗時會每回合輸出一次，而非每個 cooldown 週期一次 → 這是既有「先取 usage 再檢查 cooldown」順序的結果，屬本次範圍外；輸出量上限為每回合一行，且靜默正是這個 bug 長期不可見的成因，可觀測性優先。
- 兩層排序讓挑選邏輯比單一述詞略複雜 → 以兩個語意明確、各自獨立可測的述詞取代一個混合了排除與冷卻判斷的述詞，實際上降低了理解成本。
