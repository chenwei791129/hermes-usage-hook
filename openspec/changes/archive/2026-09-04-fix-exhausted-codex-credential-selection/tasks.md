## 1. 憑證選擇的失敗測試

- [x] 1.1 為 "Rank pooled Codex credentials by cooldown state and rank" 補上目前缺少的核心情境：池中每一筆 pooled 憑證都處於 `exhausted` 冷卻時，憑證解析仍成功並回傳 `rank` 數值最小那筆的 access token。以新測試 all-cooled-records regression test 表達，加入 `tests/test_usage.py`；此時它必須失敗（現行實作拋出解析錯誤），失敗訊息即確認了缺陷存在。
- [x] 1.2 為 "Rank pooled Codex credentials by cooldown state and rank" 補上 `dead` 與冷卻中 `exhausted` 併存的情境：解析回傳 `exhausted` 那筆的 access token，證明 `dead` 是硬性排除而 `exhausted` 只是降級。以新測試 dead-versus-cooled regression test 表達，加入 `tests/test_usage.py`。
- [x] 1.3 為 "Fail explicitly when a non-empty credential pool yields no candidate" 表達失敗語意：池中僅有 `dead` 記錄時解析拋出 `RuntimeError`，訊息點名憑證池挑選失敗並帶出檢視過的記錄筆數，且不含記錄裡的 `token`、`renewal secret`、`id` 或 `account reference` 任一值。以新測試 no-selectable-record regression test 表達，斷言須同時檢查訊息內容與這四個欄位都不外洩（只斷言 token 不外洩不夠：像「no usable credential among 2 records (ids: primary, secondary)」這種訊息會通過弱斷言卻違反 spec），加入 `tests/test_usage.py`。
- [x] 1.4 為 "Fail explicitly when a non-empty credential pool yields no candidate" 表達不受影響的邊界：`provider-a` 對應到空清單時，解析仍退回扁平 layout 並取得該 layout 的 token。以新測試 empty-list regression test 表達，加入 `tests/test_usage.py`。
- [x] 1.5 確認 "Resolve the Codex credential from supported auth layouts" 的三層 layout 優先序在現有測試中已完整涵蓋（巢狀 `provider map` 優先於 `credential list`、扁平 layout 為最後備援），缺少的情境補為新測試。驗證方式為逐一比對該 requirement 的 scenario 與 `tests/test_usage.py` 中既有測試函式，並在任務結論中列出對應關係。
- [x] 1.6 為 "Rank pooled Codex credentials by cooldown state and rank" 表達非數值 `rank` 的邊界：池中一筆健康記錄的 `rank` 為 `null`、另一筆為 20 時，解析回傳 20 那筆且不拋 `TypeError`。現行實作把原始值直接餵給 `sorted()`，`None` 與整數預設值相比會拋例外並逃出 credential loader。以新測試 invalid-rank regression test 表達，加入 `tests/test_usage.py`。

## 2. 憑證選擇實作

- [x] 2.1 依「決策一：`exhausted` 從硬性排除改為兩層排序」重寫 pooled 憑證挑選：把單一 舊的單層 selector predicate 述詞拆成「硬性排除」與「處於 exhausted 冷卻」兩個獨立述詞，挑選時先在未冷卻候選中依 `rank` 昇冪取第一筆、該層為空才在冷卻候選中以同樣規則取第一筆，`rank` 缺值、`null`、布林或任何非數值都正規化為 100 後才作為排序鍵（不可把原始值直接交給 `sorted()`），排序穩定。完成後 1.1、1.2 與 1.6 轉為通過，且既有的 dead-record regression test、cooldown-demotion regression test、elapsed-cooldown regression test 三個測試在不修改斷言的前提下持續通過。
- [x] 2.2 依「決策二：`dead` 維持硬性排除」確保 `state marker` 為 `dead`、以及缺少非空 `token` 的記錄永不進入任一層候選。由 1.2 與 1.3 的斷言驗證，並確認既有 dead-record regression test 未受影響。
- [x] 2.3 依「決策三：pool 非空但選不出憑證時明確失敗，不退回扁平 layout」改寫 credential normalizer 的收尾路徑：`provider-a` 的 pool 清單非空但無候選時拋出點名原因與記錄筆數的 `RuntimeError`，清單不存在或為空時維持扁平 layout fallthrough。錯誤訊息不得帶出 token、refresh token、憑證識別碼、指紋、帳號識別碼或電子郵件。由 1.3 與 1.4 驗證。

## 3. Coordinator 失敗診斷

- [x] 3.1 [P] 為 "Surface auto-reset retrieval failures before the transient cooldown" 撰寫測試：coordinator 的 usage 取得與 reset-credit 取得分別拋例外時，回傳狀態仍為 `transient`、cooldown 秒數與持久化狀態不變，且 stderr 各收到恰好一行含 `[hermes-usage-hook]` 前綴、點名失敗步驟並帶有例外文字的訊息。另補一個 lock 已被持有、初次取 usage 拋例外的情境：回傳狀態為 `busy`，stderr 仍收到恰好一行。以 `test_maybe_autoreset_logs_transient_usage_fetch_failure`、`test_maybe_autoreset_logs_transient_credit_listing_failure` 與 `test_maybe_autoreset_logs_usage_fetch_failure_when_lock_busy` 表達，透過 capsys 擷取 stderr，加入 `tests/test_autoreset.py`。
- [x] 3.2 依「決策四：coordinator 的 transient 失敗輸出一行 stderr 診斷」在 `maybe_autoreset()` 三處 transient 例外處理（初次取 usage、鎖內重新取 usage、取 reset-credit 清單）的 `except` 區塊開頭——搶鎖與設定 cooldown 之前——各輸出一行 stderr 診斷，沿用 `[hermes-usage-hook]` 前綴並點名失敗步驟。回傳狀態、cooldown 秒數與冪等性行為皆不得改變。由 3.1 的測試與 `tests/test_autoreset.py` 中既有的 transient 相關測試共同驗證。

## 4. 文件與整體驗證

- [x] 4.1 [P] 更新專案 `AGENTS.md`「憑證解析」段落，說明 pooled 憑證的兩層挑選規則、`dead` 為硬性排除而 `exhausted` 僅為降級、以及 pool 非空卻無候選時會明確失敗而非退回扁平 layout。編輯目標是 `AGENTS.md`：`CLAUDE.md` 是指向它的 symlink，用 Write 覆寫 `CLAUDE.md` 會把 symlink 換成一般檔案並讓兩份文件從此分岔，必須就地編輯 `AGENTS.md`。該段落目前完全沒有描述 pool 挑選規則，所以這是純新增、沒有失效敘述要刪。驗證方式為朗讀該段落並確認它與 `codex-credential-resolution` spec 的四條 requirement 描述一致，且 `ls -l CLAUDE.md` 仍顯示 symlink。
- [x] 4.2 執行 uv run pytest、uv run ruff check . 與 uv run ty check 三項檢查並全數通過，確認本次改動未破壞既有測試、lint 與型別檢查。
- [x] 4.3 確認憑證解析不再是阻塞點：在啟用 auto reset 的部署上，用修好後的憑證取一次 `get_codex_usage()`，確認 normalized 結果的 `windows` 真的含 `weekly` 鍵、且 `reset_credits_available` 不是 `None`。若兩者皆成立，代表 design Risks 原先記的兩條殘留阻塞（window-label helper 未知視窗長度、reset-credit 欄位改名）都沒有發生。接著觀察一次真實 turn，確認 auto reset 是否實際觸發；未觸發時不要把本次 change 當成問題已解決，改為在 proposal 與 design 中記錄實際阻塞並開後續 change 處理。

## 5. Threshold 0 的失敗提示

- [x] 5.1 依 "Plugin config is the canonical auto-reset interface"、"Environment variables override plugin config" 與 "Threshold uses weekly remaining percentage" 補上 config resolution 邊界測試：把既有接受 0 與 99 的測試改成接受 1 與 99；新增 plugin config 明確設 `threshold: 0` 與 env override 設 `CODEX_AUTORESET_THRESHOLD=0` 的測試，兩者皆須取得 `valid=false`、`enabled=false`，並透過 `capsys` 確認 stderr 恰好一行且包含 `[hermes-usage-hook]`、`threshold`、`1..99` 與 `/usage reset`。另保留無設定時的 disabled/threshold 0 預設，並斷言該路徑不輸出 warning。加入 `tests/test_autoreset.py`，先確認新斷言在現行實作下失敗。
- [x] 5.2 依「決策五：`threshold` 僅接受 `1..99`，明確設定 0 時 fail closed 並警告」，在 `plugin/autoreset.py` 將 env 與 plugin threshold parser 的有效範圍收緊為 `1..99`；明確值 0 沿用 `_invalid()` 的 fail-closed 結果，但在 `load_autoreset_config()` 的解析失敗處，以 best-effort stderr 向維運輸出恰好一行 warning。訊息須帶 `[hermes-usage-hook]` 前綴、指出 `threshold` 只接受 `1..99`，並建議已被 Hermes 凍結的憑證使用 `/usage reset`；stderr 寫入失敗不得逃出 config resolution。其他無效值維持既有 fail-closed 語意，未設定的 disabled default 仍為 threshold 0 且不警告。由 5.1 測試驗證。
- [x] [P] 5.3 依 "Documentation describes footer and opt-in auto-reset behavior" 就地更新 `AGENTS.md` 的 auto-reset 設定範例與操作契約：範例使用有效的非零 threshold，範圍改為 `1..99`，說明明確設定 0 會 fail closed 並輸出 warning，已被 Hermes 標成 `exhausted` 而凍結時用 `/usage reset` 手動恢復；重申 5h 資格判定屬 Issue #21、本次不改。確認 `CLAUDE.md` 仍是指向 `AGENTS.md` 的 symlink。
- [x] [P] 5.4 依 "Ship a post-install notice with the plugin" 更新 `plugin/after-install.md`：auto-reset opt-in 指令改用 `1..99` 的有效 threshold，範圍與 zero-value guidance 與 `AGENTS.md` 一致，並保留消耗 credit 不可逆的警告。同步調整 `tests/test_usage.py` 的文件契約斷言，驗證安裝後文件與 `AGENTS.md` 都包含 `1..99` 與 `/usage reset`，且不再宣告 `0..99` 為有效範圍。
- [x] 5.5 執行 `uv run pytest`、`uv run ruff check .` 與 `uv run ty check` 並全數通過；重新執行 `spectra analyze fix-exhausted-codex-credential-selection --json` 與 `spectra validate fix-exhausted-codex-credential-selection`，確認更新後 artifacts 無 Critical/Warning 且 change 有效。
