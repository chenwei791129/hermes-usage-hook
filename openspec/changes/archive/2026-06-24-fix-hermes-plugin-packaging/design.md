## Context

目前 repo 以兩個位置安裝：共用模組（`usage.py`、`providers/`）放到 `~/.hermes/lib/`，footer hook 複製成單一檔 `~/.hermes/plugins/usage_footer.py`。但 Hermes 的 plugin discovery 只辨識「含 manifest 的目錄」，loose `.py` 不會被掃到；且對 `kind: standalone` 的使用者 plugin 預設停用，需在 `~/.hermes/config.yaml` 的 `plugins.enabled` 顯式啟用才會掛上 hook。

`hooks/footer_hook.py` 以 `register(ctx)` + `ctx.register_hook("transform_llm_output", ...)` 的形式撰寫，與 Hermes plugin 機制相容；它在啟動時把自身所在目錄與 `~/.hermes/lib` 插入 `sys.path` 以匯入 `usage`。官方範例 plugin（GuanceCloud/hermes-otel-plugin）證實合規形態為：plugin 目錄含 `plugin.yaml`（`kind: standalone` + `provides_hooks`）、`__init__.py` 匯出 `register`，並由安裝把名稱寫入 `plugins.enabled`。

初版以「repo 根目錄即 plugin 目錄」出貨，使安裝 `cp -r` 會把 `.git/`、`openspec/`、`tests/`、`.claude/` 等非 plugin 內容一併複製進 `~/.hermes/plugins/`。本設計進一步將 plugin 必要檔案收攏到專屬的 `plugin/` 子目錄，安裝只複製/symlink 該子目錄。

本設計只處理「打包與部署形態」與其連帶的模組搜尋路徑調整；hook 的偵測/抓取邏輯與 provider 行為不變。各 Python 檔的 `sys.path` 計算皆相對於自身檔案位置（`dirname(...abspath(__file__))`），檔案移入 `plugin/` 後仍正確解析，無需改動匯入邏輯；唯獨 `tests/` 原先依賴 repo 根在 `sys.path` 上解析 `import usage`，模組移走後需另行把 `plugin/` 放上 `sys.path`。

## Goals / Non-Goals

**Goals:**

- 讓使用者照 README 安裝後，Hermes 能實際 discovery 並載入這個 plugin、掛上 `transform_llm_output` hook，使 footer 出現。
- 以單一 plugin 目錄出貨，消除 `~/.hermes/lib` 與 `~/.hermes/plugins` 雙位置的拆分與其脆弱的硬編路徑。
- README 安裝步驟與實際 Hermes 載入機制一致，包含 `plugins.enabled` 啟用步驟。
- 提供一鍵安裝腳本 `install.py`，讓 agent/使用者以 `uv run install.py` 完成「複製 plugin + 啟用」全部步驟，免除手動漏步。

**Non-Goals:**

- 安裝腳本僅以 `install.py`（PEP 723 單檔、`uv run`）形態提供；不另寫 shell `install.sh`，亦不提供 symlink 安裝模式（僅複製）。手動安裝步驟保留為 README 替代方案。
- 不更動 provider 偵測規則、usage 抓取邏輯、footer 文案格式。
- 不新增 plugin 自身的 config 區塊（本 plugin 無需 endpoint/token 類設定；MiniMax token 沿用既有 `.env`/環境變數解析）。
- 不處理 streaming 部署下 footer 不生效的既有限制（維持 README 既有 caveat）。

## Decisions

### 將 plugin 檔案收攏到專屬的 `plugin/` 子目錄

把 plugin 真正需要的檔案放進 repo 下的 `plugin/` 子目錄：`plugin/plugin.yaml`、`plugin/__init__.py`、`plugin/usage.py`、`plugin/providers/`、`plugin/hooks/`。安裝只複製/symlink `plugin/`，使 `~/.hermes/plugins/hermes-usage-hook/` 僅含 plugin 相關內容，排除 `.git/`、`openspec/`、`tests/`、`.claude/`、`README.md` 等非 plugin 檔案。`plugin/` 即為「plugin 根目錄」，下文凡稱「plugin 根目錄」均指此子目錄。

替代方案：維持「repo 根即 plugin 目錄」，安裝時以 `--exclude` 或 `.gitattributes export-ignore` 過濾無關內容。否決原因：過濾名單需隨 repo 結構維護、易遺漏，且安裝者仍可能誤複製整個 repo；以實體子目錄界定 plugin 邊界最直接、最不易出錯。

### 以「整個 plugin 目錄」形態出貨，取代 lib/plugins 雙位置拆分

安裝改為把 `plugin/` 子目錄複製或 symlink 到 `~/.hermes/plugins/hermes-usage-hook/`，目錄內含 `plugin.yaml`、`__init__.py`、`usage.py`、`providers/`、`hooks/footer_hook.py`。`usage` 與 `providers` 改由 plugin 自身目錄解析，不再依賴 `~/.hermes/lib`。

替代方案：維持單檔 + lib 拆分，僅補上 `plugins.enabled`。否決原因：Hermes discovery 不掃 loose `.py`，補 `plugins.enabled` 也無從啟用一個未被 discovery 認得的 plugin；單檔形態根本不可行。

### 新增 plugin.yaml manifest 宣告 standalone 與 transform_llm_output hook

新增 `plugin.yaml`，欄位含 `name: hermes-usage-hook`、`version`、`description`、`author`、`kind: standalone`、`provides_hooks: [transform_llm_output]`。`name` 即 discovery 後在 `plugins.enabled` 註冊所用的名稱。

替代方案：省略 `provides_hooks`。否決原因：對齊官方範例 plugin 的 manifest 慣例，明示宣告所掛 hook 有助 discovery 顯示與審閱。

### 由根目錄 __init__.py 匯出 register(ctx) 進入點

新增 plugin 目錄根部的 `__init__.py`，將 plugin 根目錄加入 `sys.path` 後 `from hooks.footer_hook import register`，使 Hermes loader 能取得 `register(ctx)`。hook 實作維持在 `hooks/footer_hook.py`（既有且已測試），不重寫。

替代方案：把 `register` 直接搬到根 `__init__.py`。否決原因：會打散既有測試所覆蓋的 hook 模組，徒增變動面；以重新匯出維持單一實作來源即可。

### 調整 footer_hook.py 的模組搜尋路徑改用 plugin 根目錄

`plugin/hooks/footer_hook.py` 啟動時的 `sys.path` 設定，移除硬編的 `~/.hermes/lib`，改為插入 plugin 根目錄（其所在 `hooks/` 的上層，即 `plugin/`），使 `usage` 與 `providers` 由 plugin 自身目錄解析，與安裝位置無關。此 `sys.path` 計算為 `dirname(dirname(abspath(__file__)))`，相對於檔案位置，檔案移入 `plugin/hooks/` 後自動解析到 `plugin/`，無需再改。

替代方案：保留 `~/.hermes/lib` fallback。否決原因：雙位置拆分正是本次要消除的脆弱點；保留會讓部署狀態出現兩種來源、增加除錯成本。

### tests 改由 `plugin/` 解析模組

`tests/` 不隨 plugin 出貨，留在 repo 根。模組移入 `plugin/` 後，`tests/test_usage.py` 原先依賴「pytest 由 repo 根執行、repo 根在 `sys.path` 上」來解析 `import usage` / `from providers import ...` 的假設失效。新增 `tests/conftest.py`，於收集前把 `plugin/` 與 `plugin/hooks/` 插入 `sys.path`，使 `usage`、`providers`、`footer_hook` 可被解析；並把 `test_usage.py` 中硬編的 `hooks` 搜尋路徑指向 `plugin/hooks`。

替代方案：把 `tests/` 也移入 `plugin/`。否決原因：測試屬開發產物，不應隨 plugin 安裝進 `~/.hermes/plugins/`；應留在 repo 根並以 `sys.path` 指向 `plugin/`。

### README 安裝改為複製 `plugin/` 子目錄並在 plugins.enabled 啟用

改寫 README 安裝段：將 `plugin/` 子目錄複製或 symlink 到 `~/.hermes/plugins/hermes-usage-hook/`，並在 `~/.hermes/config.yaml` 的 `plugins.enabled` 加上 `hermes-usage-hook`（或 hermes plugins enable 指令）；移除 loose 單檔複製步驟與「No configuration is needed」敘述，並說明可用 hermes plugins 清單確認 discovery 是否掃到。快速檢查指令亦更新為 `python plugin/providers/codex_usage.py`，Files 表路徑改為 `plugin/` 下。

替代方案：僅補一行 `plugins.enabled`。否決原因：與目錄化安裝不一致，且會殘留錯誤的單檔步驟。

### 新增 PEP 723 單檔 install.py 自動化安裝與啟用

新增 repo 根的 `install.py`，採 PEP 723 inline script metadata（`requires-python`、`dependencies = ["pyyaml"]`），以 `uv run install.py` 執行、相依由 uv 自動解析。腳本行為：解析 `HERMES_HOME`（預設 `~/.hermes`）；把 repo 的 `plugin/` 目錄複製到 `$HERMES_HOME/plugins/hermes-usage-hook/`（若已存在先移除再複製，達成重裝覆蓋的 idempotent 行為）；以 `pyyaml` 讀取 `$HERMES_HOME/config.yaml`（不存在則建立），把 `hermes-usage-hook` 加入 `plugins.enabled` 清單（已存在則不重複、其餘鍵與值保留（既有 config.yaml 的註解與排版會被 YAML 寫入器正規化）），再以「暫存檔 + `os.replace`」原子寫回（避免中斷時截斷既有檔）。完成後印出安裝路徑與「重啟 Hermes」提示。依全域 Python 慣例處理 `SIGINT`/`SIGTERM`（退出碼 128+signal）。

替代方案一：shell `install.sh`（對齊 GuanceCloud 範例）。否決原因：YAML 的就地編輯（保留既有鍵、避免重複）以 shell 處理脆弱；Python + pyyaml 較穩且跨平台，且環境保證有 uv。
替代方案二：以 pyproject.toml 專案形態提供。否決原因：對單一安裝腳本過度工程，且此 repo 無 pyproject.toml；PEP 723 單檔自含相依、最易維護與攜帶。
替代方案三：提供 symlink 安裝模式。否決原因：複製為一般使用者最直觀且最不易因 repo 移動而失效；本次僅做複製。

## Implementation Contract

**Behavior（部署後可觀察結果）：**

- 使用者把 plugin 目錄安裝到 `~/.hermes/plugins/hermes-usage-hook/` 後，`hermes plugins`（或 `/plugins`）清單中出現 `hermes-usage-hook`。
- 在 `~/.hermes/config.yaml` 的 `plugins.enabled` 加入 `hermes-usage-hook` 並重啟 Hermes 後，被辨識為 Codex/MiniMax 的回覆末端出現 usage footer；未啟用時不出現且不報錯。
- 於 repo 根執行 `uv run install.py` 後，`$HERMES_HOME/plugins/hermes-usage-hook/`（預設 `~/.hermes`）含 `plugin/` 的內容，且 `$HERMES_HOME/config.yaml` 的 `plugins.enabled` 含 `hermes-usage-hook`；重啟 Hermes 後 footer 即出現，無需任何手動編輯。

**Interface / data shape：**

- 安裝腳本：repo 根的 `install.py`，PEP 723 inline metadata（`requires-python`、`dependencies = ["pyyaml"]`），以 `uv run install.py` 執行。讀 `HERMES_HOME`（預設 `~/.hermes`）；複製來源為 repo 的 `plugin/`，目的地為 `$HERMES_HOME/plugins/hermes-usage-hook/`；編輯目標為 `$HERMES_HOME/config.yaml` 的 `plugins.enabled`（YAML 清單）。

- `plugin/plugin.yaml`（YAML）：頂層鍵至少含 `name: hermes-usage-hook`、`kind: standalone`、`provides_hooks` 為包含字串 `transform_llm_output` 的清單，另含 `version`、`description`、`author`。
- plugin 進入點：plugin 根目錄（`plugin/`）的 `__init__.py` 匯出可呼叫的 `register(ctx)`；`register` 內呼叫 `ctx.register_hook("transform_llm_output", ...)`（沿用 `plugin/hooks/footer_hook.py` 既有實作）。
- repo 內 plugin 佈局：`plugin/` 下同時存在 `plugin.yaml`、`__init__.py`、`usage.py`、`providers/__init__.py`、`hooks/__init__.py`、`hooks/footer_hook.py`；`tests/` 與 `openspec/`、`README.md` 等留在 repo 根、不在 `plugin/` 內。
- 安裝後目錄佈局：把 `plugin/` 複製/symlink 為 `~/.hermes/plugins/hermes-usage-hook/`，其下同時存在 `plugin.yaml`、`__init__.py`、`usage.py`、`providers/__init__.py`、`hooks/footer_hook.py`；不含 `.git/`、`openspec/`、`tests/`、`.claude/`、`README.md`。

**Failure modes：**

- 未在 `plugins.enabled` 啟用 → hook 不載入、footer 不出現，且不產生錯誤（符合 Hermes 預設停用第三方 plugin 的安全行為）。
- usage 抓取失敗 → 沿用既有行為，footer 略過、回覆不變（不在本次變更範圍）。
- `install.py` 重複執行 → 目的地目錄先移除再複製（覆蓋）、`plugins.enabled` 已含 `hermes-usage-hook` 則不重複加入；結果 idempotent。
- `$HERMES_HOME/config.yaml` 不存在 → 建立含 `plugins.enabled: [hermes-usage-hook]` 的最小設定；已存在 → 僅就地新增名稱，其餘鍵與值保留（既有 config.yaml 的註解與排版會被 YAML 寫入器正規化）。
- `install.py` 收到 `SIGINT`/`SIGTERM` → 以退出碼 128+signal 結束，不留半完成的破損狀態之外的副作用。

**Acceptance criteria：**

- 於 `plugin/` 目錄執行 `python -c "import __init__ as p; assert callable(p.register)"`（或等效匯入 `plugin/` 根套件的方式）可取得 callable `register`，且匯入不因 `usage`/`providers` 找不到而失敗。
- `python plugin/providers/codex_usage.py` 仍可獨立執行並輸出 normalized JSON 與 summary（確認檔案移入 `plugin/` 後快速檢查仍有效）。
- `uv run pytest` 全綠：`tests/` 透過 `tests/conftest.py` 將 `plugin/` 放上 `sys.path`，`usage`/`providers`/`footer_hook` 的匯入未被破壞。
- README 安裝段指示複製/symlink `plugin/` 子目錄（而非整個 repo），不再出現把 hook 複製為單一 `.py` 檔的步驟，也不再出現「No configuration is needed」；且包含 `plugins.enabled` 啟用步驟與 `hermes-usage-hook` 名稱；快速檢查指令為 `python plugin/providers/codex_usage.py`。
- `plugin/plugin.yaml` 通過 YAML 解析且包含上述必要鍵。
- `plugin/` 內不含 `tests/`、`openspec/`、`.git/`、`README.md` 等非 plugin 內容。
- 以暫時性的 `HERMES_HOME` 執行 `uv run install.py` 後：目的地 `$HERMES_HOME/plugins/hermes-usage-hook/plugin.yaml` 存在，`$HERMES_HOME/config.yaml` 以 pyyaml 解析後 `plugins.enabled` 含 `hermes-usage-hook`；二次執行不新增重複條目（清單仍只有一個 `hermes-usage-hook`）。
- README 含 `uv run install.py` 一鍵安裝段，列為推薦路徑，手動步驟保留為替代方案。
- 在乾淨環境執行 `uv run install.py` 後：`$HERMES_HOME/plugins/hermes-usage-hook/plugin.yaml` 存在，且 `$HERMES_HOME/config.yaml` 的 `plugins.enabled` 含 `hermes-usage-hook`；再次執行不產生重複條目、不破壞既有 config 內容（idempotent）。

**Scope boundaries：**

- In scope：建立 `plugin/` 子目錄並把 `plugin.yaml`、`__init__.py`、`hooks/__init__.py`、`usage.py`、`providers/`、`hooks/footer_hook.py` 收攏其下；新增 `tests/conftest.py` 並調整 `tests/test_usage.py` 的 `hooks` 搜尋路徑；改寫 README 安裝/troubleshooting/Files 段與快速檢查指令；新增 PEP 723 單檔 `install.py`（複製 `plugin/` + 寫入 `plugins.enabled`）並在 README 記載；更新 footer-hook-deployment spec。
- Out of scope：shell `install.sh`、symlink 安裝模式、provider 邏輯、footer 文案、plugin 專屬 config 區塊、streaming 限制、各 Python 檔的 `sys.path` 計算邏輯（相對於檔案位置，移動後不需改）。

## Risks / Trade-offs

- [`__init__.py` 置於 `plugin/` 而非 repo 根，使 `plugin/`（而非整個 repo）成為 Python 套件] → repo 根不再有 `__init__.py`，化解了「repo 目錄名含連字號、pytest 套件解析衝突」的疑慮；`tests/` 以 `tests/conftest.py` 將 `plugin/` 放上 `sys.path`、仍以頂層模組匯入 `usage`/`providers`/`footer_hook`，匯入解析穩定。
- [模組由 repo 根移入 `plugin/`，tests 與快速檢查若未同步調整會匯入失敗] → 以 `tests/conftest.py` 集中處理 `sys.path`、README 快速檢查改用 `python plugin/providers/codex_usage.py`；驗收標準明確要求 `uv run pytest` 全綠與該指令可獨立執行。
- [Hermes 不同版本對 manifest 欄位或 discovery 慣例可能略有差異] → manifest 對齊官方範例 plugin 的欄位；README 加入用 `hermes plugins` 確認是否被掃到的驗證步驟，使偏差可被即時發現。
- [移除 `~/.hermes/lib`、且安裝來源改為 `plugin/` 子目錄後，既有已用舊方式安裝的使用者升級需重裝] → 屬一次性遷移；README 安裝段改寫即涵蓋，無需保留相容路徑。
