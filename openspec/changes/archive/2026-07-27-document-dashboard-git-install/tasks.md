## 1. 安裝後指引檔隨外掛出貨

- [x] 1.1 在 tests/test_install.py 的 test_install_local_copies_and_enables 補一條斷言，要求本地安裝完成後安裝目標目錄下存在 after-install.md，確立「Installing the plugin carries the notice along」這個行為由測試把關。此時檔案還不存在，驗證方式是執行 uv run pytest tests/test_install.py::test_install_local_copies_and_enables 並確認它因缺少 after-install.md 而失敗（TDD 紅燈）。
- [x] 1.2 建立 `plugin/after-install.md`，交付「Ship a post-install notice with the plugin」要求的安裝後指引（唯一會顯示它的是 `hermes plugins install` 這個 CLI 指令；install.py 只是把它複製過去、dashboard 會在回應中移除它的路徑）：確認外掛已啟用的方式、Codex 用量讀取 ChatGPT OAuth 憑證的來源（Hermes 憑證存放區或 Codex CLI auth store）且只讀不刷新不寫回、MiniMax 需要 MINIMAX_API_KEY 及其兩個來源、Codex 自動重置預設關閉且啟用 plugins.entries.hermes-usage-hook.auto_reset.enabled 等同授權不可逆的自主重置額度消耗、查詢重置歷史的 /usagehook history 指令、以及串流部署下 footer 可能在回覆送出後才執行的限制。內容不得要求把憑證寫進外掛設定，也不得聲稱自動重置預設開啟。驗證方式是 1.1 的測試轉為通過，並逐項對照 delta spec 的「Post-install notice covers the required setup steps」與「Post-install notice keeps credentials out of plugin config」兩個 scenario 做內容審閱。
- [x] 1.3 確認「Package the plugin under a dedicated subdirectory」的打包邊界仍然成立：新檔位於 plugin root 之內，plugin/ 底下沒有出現 tests/、openspec/、.git/、.claude/ 或 README.md，且 install.py 未經修改就把新檔一併帶入安裝目標。驗證方式是執行 uv run pytest tests/test_install.py 全綠，並列出 plugin/ 目錄內容確認邊界。

## 2. README 記錄 dashboard 安裝路徑

- [x] 2.1 在 README.md 的安裝章節之後新增一節「Dashboard install」（README 全篇英文，標題與內文一律英文），交付「Document the dashboard Git install path」要求的識別字說明：給出 owner/repo 後接 plugin 子目錄的簡寫形式，列出兩種可接受的替代寫法（結尾為 /tree/<branch>/plugin 的 GitHub 網址、以及帶 #plugin 片段的 clone 網址），並明確寫出 tree 網址裡的 <branch> 會被忽略（安裝一律 clone 預設分支），所以那種寫法選到的是預設分支而不是指名的分支。驗證方式是對照 delta spec 的「README documents the dashboard install identifier」scenario 逐項審閱該節內容。
- [x] 2.2 在同一節加入省略子目錄的警告，措辭必須符合實際行為：只輸入 owner/repo 會把整個 repository（tests/、openspec/、pyproject.toml、.git）裝進 plugins 目錄；外掛並不會因此失效——Hermes 把那個沒有 plugin.yaml 的安裝目錄當成分類命名空間再往下掃一層，找到巢狀的 plugin/plugin.yaml，而 dashboard 寫進 plugins.enabled 的 manifest 名稱同時被啟用判斷接受，所以 hook 仍會註冊；真正的代價是使用者的 plugins 目錄被塞進整個 repository、外掛登錄在巢狀 key 之下、畫面上沒有任何提示，且巢狀登錄目錄裡沒有 .git 因此同樣沒有更新按鈕。文字必須把這個結果寫成應避免的裝法，不得寫成安裝步驟，以符合「Documentation describes only the footer hook path」對 README 不得指示整個 repository 安裝的既有約束。驗證方式是對照「README warns about the whole-repository identifier」與「Whole-repository install appears only as a warning」兩個 scenario 審閱措辭。
- [x] 2.3 在同一節記錄安裝來源與更新限制：dashboard 取得的是預設分支最新 commit（不接受在識別字裡指定分支或 tag），而 install.py 預設安裝最新 GitHub release；子目錄安裝不會留下 .git 目錄，因此 dashboard 的更新動作對它不可用，更新方式是先移除外掛再重新安裝。驗證方式是對照「README records the install source and update limitations」scenario 審閱該節內容。
- [x] 2.4 在同一節列出 dashboard 安裝者的必要後續步驟，因為 dashboard 不會顯示 after-install.md：Codex 用量需要 ChatGPT OAuth 憑證、Codex 自動重置預設關閉且啟用即為授權自主消耗重置額度、串流部署可能在 footer 套用前就送出回覆。驗證方式是對照「README carries the post-install steps for dashboard installers」scenario 審閱該節內容。
- [x] 2.5 在 README.md 的 Files 表格補上 `plugin/after-install.md` 一列（該表格逐檔列出 plugin/ 內容，漏列會讓 README 與實際打包內容不一致）。說明文字用英文，並點明它是 `hermes plugins install` 安裝後顯示的面板內容。驗證方式是對照 plugin/ 目錄實際檔案清單與表格逐列比對。
- [x] 2.6 為「Document the dashboard Git install path」這一節補上版本註記與上游追蹤指標，讓整節可被判斷是否過期：標明本節的行為描述以 Hermes 0.19.0 實測為準，依編號指向上游 issue 65314（子目錄安裝丟棄 .git、更新動作不可用）與 PR 65337（來源 metadata ＋ 自動偵測子目錄的修法），並明寫該 PR 合併後整個 repository 的警告與「更新動作不可用」的敘述都會失效、需要回頭調整本節。行為敘述一律取自實測，不得改寫自上游敘述（上游 issue 的對照表把整個 repository 安裝寫成不會被發現，與 0.19.0 實測不符）。驗證方式是對照 delta spec 的「README dates its claims and points at the upstream fix」scenario 逐項審閱該節內容。

## 3. 收尾驗證

- [x] 3.1 執行完整檢查確認這次變更沒有破壞既有行為與風格：uv run pytest 全綠、uv run ruff check . 無新增問題。文件變更不應改變任何 Python 執行路徑，若測試出現與本 change 無關的失敗，先確認其是否在變更前即已存在。
- [x] 3.2 執行 spectra analyze document-dashboard-git-install 與 spectra validate document-dashboard-git-install，確認四項 requirement 都有對應實作、artifacts 與實作內容一致。驗證方式是兩個指令皆無 Critical 或 Warning 層級的發現。
