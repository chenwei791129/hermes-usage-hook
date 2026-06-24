## Why

README 目前記載的安裝方式無法讓 Hermes 真正載入這個 hook：它把 footer hook 複製成單一檔 `~/.hermes/plugins/usage_footer.py`，而 Hermes 的 plugin discovery 只認得「含 manifest 的目錄」，loose `.py` 不會被掃到；即使被掃到，Hermes 對 `kind: standalone` 的使用者 plugin 預設停用，必須在 `~/.hermes/config.yaml` 的 `plugins.enabled` 顯式啟用才會掛上 hook。README 卻寫著「No configuration is needed」。結果是：使用者照文件安裝後 footer 永遠不出現，且沒有任何錯誤提示。

官方範例 plugin（GuanceCloud/hermes-otel-plugin）證實正確形態為：plugin 目錄含 `plugin.yaml` manifest（`kind: standalone` + `provides_hooks`）、`__init__.py` 匯出 `register(ctx)`，並由安裝程序把名稱寫入 `plugins.enabled`。

此外，初版以「repo 根目錄即 plugin 目錄」的形態出貨，導致安裝指令 `cp -r hermes-usage-hook ~/.hermes/plugins/hermes-usage-hook` 會把 `.git/`、`openspec/`、`tests/`、`.claude/` 等與 plugin 無關的內容一併複製進 `~/.hermes/plugins/`，污染安裝目錄、且 plugin 邊界不清。應將 plugin 真正需要的檔案收攏到專屬的 `plugin/` 子目錄，安裝只複製/symlink 該子目錄。

再者，手動安裝需多步（複製目錄 + 手改 `config.yaml` 的 `plugins.enabled`），對 agent 或使用者皆易出錯漏步。應提供一鍵安裝腳本 `install.py`（`uv run install.py`，對齊官方範例 plugin 的 `install.sh` 模式）：複製 `plugin/` 並自動把 `hermes-usage-hook` 寫入 `plugins.enabled`。Hermes agent 環境必有 uv CLI，故採 PEP 723 單檔形態、相依由 `uv run` 自動解析。

## What Changes

- 將所有 plugin 必要檔案（`plugin.yaml`、`__init__.py`、`usage.py`、`providers/`、`hooks/`）收攏到 repo 下專屬的 `plugin/` 子目錄；安裝只複製/symlink `plugin/`，排除 `.git/`、`openspec/`、`tests/`、`.claude/` 等非 plugin 內容。
- 新增 Hermes plugin manifest `plugin/plugin.yaml`，宣告 `kind: standalone` 與 `provides_hooks: [transform_llm_output]`，使 plugin 目錄能被 Hermes discovery 辨識。
- 在 `plugin/` 根部提供 `register(ctx)` 進入點（`plugin/__init__.py` 重新匯出 footer hook 的 `register`），讓 loader 啟用後能掛上 `transform_llm_output` hook。
- 改寫 README 安裝步驟：改為將 `plugin/` 子目錄複製或 symlink 到 `~/.hermes/plugins/hermes-usage-hook/`，並在 `~/.hermes/config.yaml` 的 `plugins.enabled` 註冊（或使用 hermes plugins enable 指令）；移除誤導的「No configuration is needed」與 loose 單檔複製步驟。
- 確保 `tests/` 仍能解析移入 `plugin/` 的模組（不再依賴 repo 根在 `sys.path` 上）。
- 新增 repo 根的 PEP 723 單檔 `install.py`（`uv run install.py`）：把 `plugin/` 複製到 `$HERMES_HOME/plugins/hermes-usage-hook/`（預設 `~/.hermes`，重裝覆蓋），並把 `hermes-usage-hook` 寫入 `$HERMES_HOME/config.yaml` 的 `plugins.enabled`（保留既有內容、不重複），達成一鍵安裝 + 啟用。README 新增此推薦安裝路徑，手動步驟保留為替代方案。
- 更新 footer-hook-deployment spec：要求 repo 以 `plugin/` 子目錄出貨 plugin manifest、規範 `plugin/` 內的目錄佈局與 `register(ctx)` 進入點、要求安裝只複製 `plugin/`、並要求文件描述 `plugins.enabled` 啟用步驟。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `footer-hook-deployment`: 新增「以合規 Hermes plugin 形態出貨」的需求——repo 必須提供 plugin manifest 與目錄根部的 `register(ctx)` 進入點，且 README 必須描述把 plugin 安裝為目錄並在 `plugins.enabled` 啟用，取代原本「複製單檔、免設定」的部署敘述。並新增「提供一鍵安裝腳本」的需求——repo 必須提供 `install.py`，複製 `plugin/` 並自動寫入 `plugins.enabled`。

## Impact

- Affected specs: footer-hook-deployment（modified）
- Affected code:
  - New:
    - plugin/plugin.yaml
    - plugin/__init__.py
    - plugin/hooks/__init__.py
    - tests/conftest.py（讓 tests 從 `plugin/` 解析模組）
    - install.py（repo 根；PEP 723 單檔，複製 `plugin/` + 寫入 `plugins.enabled`）
  - Moved（repo 根 → `plugin/`）:
    - usage.py → plugin/usage.py
    - providers/ → plugin/providers/
    - hooks/footer_hook.py → plugin/hooks/footer_hook.py
  - Modified:
    - README.md（安裝改為只複製 `plugin/`、路徑更新）
    - hooks/footer_hook.py → plugin/hooks/footer_hook.py（已移除 `~/.hermes/lib`；`sys.path` 邏輯相對於檔案位置，移動後不需再改）
    - tests/test_usage.py（`hooks` 搜尋路徑指向 `plugin/hooks`）
  - Removed:
    - (none)
