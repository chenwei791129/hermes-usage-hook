## Why

Hermes Agent 的 dashboard「外掛管理」提供「從 GitHub / Git URL 安裝」，它 clone 指定 repo、可選擇性取出一個子目錄、讀該目錄的 plugin.yaml 取得名稱，再搬進使用者的 plugins 目錄並寫入 plugins.enabled。本 repo 的 plugin/ 子目錄佈局與這條官方路徑相容，但只有在使用者輸入的識別字帶上 /plugin 子目錄時才成立。

省略子目錄（只輸入 owner/repo）時，dashboard 會把整個 repository（含 tests/、openspec/、pyproject.toml 與 .git）搬進使用者的 plugins 目錄。該目錄根層既沒有 plugin.yaml 也沒有 __init__.py，安裝流程只把「可能不是有效外掛」寫進 Gateway 端日誌，dashboard 畫面上沒有任何提示。外掛本身仍然會生效：Hermes 掃描 plugins/ 時，把第一層沒有 plugin.yaml 的目錄當成分類命名空間再往下掃一層，於是找到巢狀的 plugin/plugin.yaml，並以巢狀 key 登錄；載入器的啟用判斷同時接受巢狀 key 與 manifest 名稱，而 dashboard 寫進 plugins.enabled 的正是 manifest 名稱，所以 hook 照樣註冊、footer 照樣出現。代價不是失效而是髒安裝：使用者的 plugins 目錄被塞進整個 repository、外掛登錄在巢狀 key 之下（CLI 與 dashboard 的訊息會以巢狀路徑呈現），而且被登錄的目錄是巢狀的 plugin/、裡面沒有 .git（.git 留在 repository 根層），所以連這種裝法也拿不到「更新」按鈕。

同時 README 目前只描述 install.py 與手動安裝兩條路徑，完全沒有 dashboard 這條路徑，也沒有記錄它的行為差異：它安裝的是預設分支最新 commit 而非最新 release（即使識別字寫成帶分支的 tree 網址，該分支名也會被忽略），以及子目錄安裝不會保留 .git，因此 dashboard 的「更新」按鈕不會出現。

此外，官方安裝流程會在安裝完成後尋找外掛目錄下的 after-install.md：`hermes plugins install` 這個 CLI 指令會把它的內容以 Markdown 面板印出來（install.py 與 dashboard 都不會顯示它），本 repo 沒有這個檔案，所以透過該指令安裝的使用者只會看到一則預設的「已安裝」訊息，而這個外掛裝完確實還有事要做：自動重置預設關閉、Codex 需要 OAuth 登入、串流部署下 footer 可能不生效。

需要一併記錄的限制：dashboard 這條路徑雖然也會偵測 after-install.md，但它在回應送出前把該路徑從 payload 中移除，前端沒有任何地方引用它。因此 after-install.md 對 dashboard 安裝者是不可見的，dashboard 使用者的後續步驟只能靠 README 承載——這也是 README 那一節必須自己把關鍵後續步驟寫齊、而不是只指向 after-install.md 的原因。

## 上游狀態（決定這份文件的保存期限）

本 change 記錄的兩個 dashboard 行為在上游都已有對應的 issue 與 PR，且都還沒合併，所以 README 必須寫成「會過期的觀察」而不是「永久事實」：

- hermes-agent issue #65314（open、P3、標籤 area/install-update）描述的正是子目錄安裝丟棄 .git 導致 plugins update 與 dashboard 更新動作永久不可用，並指出 dashboard 的更新函式有相同的 .git 前置條件。
- hermes-agent PR #65337（open、未合併、最後更新 2026-07-19）實作了該 issue 的第一條建議：安裝時寫入一份記錄 git URL、子目錄與 ref 的來源 metadata 檔，讓 update 改為依該 metadata 重新抓取而不再要求就地的 .git；同時新增「自動偵測 repository 根層下唯一同時具備 plugin.yaml 與 __init__.py 的子目錄」的邏輯。本 repo 的 plugin/ 同時具備這兩個檔案，因此該 PR 一旦合併，省略子目錄的識別字會被自動導向 plugin/，「髒安裝」與「更新按鈕不可用」兩個警告就會同時失效。
- hermes-agent PR #22419（open、2026-05-09 開啟）提議由 plugin.yaml 宣告結構化的安裝後 onboarding metadata，其描述明確指出現況只能退回通用安裝訊息或 after-install.md。該 PR 若合併，after-install.md 會多出一個結構化替代方案，但仍是可用的退路。

另外，issue #65314 的對照表把「repository 根層安裝」寫成不會被載入器發現，那是 v0.18.2 上的描述，與本 change 在 0.19.0 的實測不符——實測會以巢狀 key `hermes-usage-hook/plugin` 成功載入並註冊 hook。因此 README 一律以實測版本的行為為準，不引用上游敘述作為事實。

## What Changes

- README.md 新增一節「Dashboard install」（README 全篇英文，標題與內文一律英文），記錄 dashboard 這條安裝路徑：
  - 給出正確識別字（owner/repo 後面必須接 /plugin 子目錄），並列出等價的完整 URL 與 ssh 片段寫法
  - 明確警告省略子目錄的後果：整個 repository（含 tests/、openspec/、pyproject.toml、.git）被裝進 plugins 目錄，外掛雖然仍會以巢狀 key 載入，但畫面上不會有任何提示，而且巢狀登錄目錄裡沒有 .git，同樣拿不到更新按鈕——這是要避免的裝法，不是安裝步驟
  - 記錄它取得的是預設分支最新 commit（tree 網址裡的分支名會被忽略），而非 install.py 預設的最新 release
  - 記錄子目錄安裝不保留 .git，所以 dashboard 的「更新」按鈕不會出現，更新方式是移除後重新安裝
  - 因為 dashboard 不顯示 after-install.md，這一節必須自己列出安裝後的必要步驟，不能只指向該檔案
  - 同步更新 README 的 Files 表格，補上 `plugin/after-install.md` 一列（該表格逐檔列出 plugin/ 內容）
  - 為整節加上版本註記與上游追蹤指標：標明這些行為以 Hermes 0.19.0 實測為準，並指向 issue #65314 與 PR #65337，讓讀者知道 PR 合併後本節的警告會失效、需要回頭調整
- 新增 plugin/after-install.md，讓 `hermes plugins install` 這條 CLI 路徑在安裝後顯示必要的後續步驟：啟用確認、自動重置預設關閉且啟用即為授權、Codex OAuth 登入需求、MiniMax API token 來源、串流部署下的限制，以及查詢重置歷史的指令
- 更新 footer-hook-deployment 規格：plugin/ 打包內容要求納入 after-install.md，並新增「README 記錄 dashboard 安裝路徑」與「隨外掛提供安裝後指引」兩項要求

## Non-Goals

本 change 是純文件與安裝後指引，不碰任何執行路徑，也不改動 repository 佈局。以下明確排除：

- **不把外掛檔案從 plugin/ 提到 repository 根層。** 這樣做能讓省略子目錄的 owner/repo 識別字裝出乾淨的頂層外掛目錄（不再是巢狀 key），也會讓那種安裝保留 .git 使 dashboard 的「更新」按鈕生效；代價是 tests/、openspec/、pyproject.toml 全被搬進使用者的 plugins 目錄，而且 install.py 的本地安裝與打包邏輯、測試的 import 佈局都得跟著改。官方安裝欄位本身就以 owner/repo/subdir 為一等用法，為一顆更新按鈕犧牲佈局不成比例。
- **不設法讓 dashboard 的「更新」按鈕支援子目錄安裝。** 缺少 .git 是官方安裝流程搬移子目錄時的固有結果，任何採子目錄佈局的外掛都一樣，無法從本 repo 端改變。README 只記錄替代做法（移除後重新安裝）。
- **不修改 install.py 的行為、旗標或預設安裝來源。** 它已整體複製 plugin/ 目錄，新增檔案會自動隨附。
- **不改動 plugin.yaml 的既有欄位，也不新增 manifest_version 或 requires_env。** 現有欄位已符合官方 manifest 結構，且 requires_env 會讓安裝流程互動式索取憑證，與本外掛把憑證留在 Hermes 憑證存放區的設計相衝突。
- **不新增 dashboard 擴充（dashboard/manifest.json）。** 本外掛沒有要提供 dashboard 頁面。
- **不為尚未合併的上游 PR 預先改動本 repo。** 不新增來源 metadata 檔、不改 plugin.yaml 去配合 PR #65337 或 PR #22419 的提案格式。這兩個 PR 的機制都由 Hermes 端負責（安裝時寫入 metadata、或由載入器自動偵測子目錄），外掛作者端零負擔；預先配合未定案的格式只會製造需要回頭清掉的猜測。本 change 只在 README 留下追蹤指標，等 PR 實際合併後再依當時行為調整。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `footer-hook-deployment`: 打包內容要求納入安裝後指引檔；新增 README 必須記錄 dashboard Git 安裝路徑的要求；新增外掛目錄必須隨附安裝後指引的要求

## Impact

- Affected specs: `footer-hook-deployment`
- Affected code:
  - New: `plugin/after-install.md`
  - Modified: `README.md`, `openspec/specs/footer-hook-deployment/spec.md`
  - Removed: (none)
- 不影響任何 Python 執行路徑：不改 `plugin/__init__.py`、`plugin/hooks/footer_hook.py`、`plugin/usage.py`、`plugin/autoreset.py` 或 `install.py` 的行為
- install.py 已把 plugin/ 整個目錄複製到安裝目標，新增的檔案會自動隨附，無需修改 installer
