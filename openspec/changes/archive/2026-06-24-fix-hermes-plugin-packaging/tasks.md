## 1. Plugin 打包

- [x] 1.1 [P] 新增 plugin.yaml manifest 宣告 standalone 與 transform_llm_output hook（對應需求 Ship a Hermes plugin manifest）：含 `name: hermes-usage-hook`、`kind: standalone`、`provides_hooks: [transform_llm_output]`、`version`、`description`、`author`，使 Hermes discovery 能辨識此目錄為可載入 plugin。驗證：`python -c "import yaml; d=yaml.safe_load(open('plugin.yaml')); assert d['name']=='hermes-usage-hook' and d['kind']=='standalone' and 'transform_llm_output' in d['provides_hooks']"` 成功無錯。
- [x] 1.2 [P] 由根目錄 __init__.py 匯出 register(ctx) 進入點（對應需求 Expose a register entry point from the plugin root）：將 plugin 根目錄加入 `sys.path` 並 `from hooks.footer_hook import register` 重新匯出，使 Hermes loader 可從根套件取得 callable `register(ctx)`。驗證：於 repo 根匯入根套件後 `callable(register)` 為真，且匯入過程不報 `usage`/`providers` 找不到。
- [x] 1.3 [P] 落實設計決策「以「整個 plugin 目錄」形態出貨，取代 lib/plugins 雙位置拆分」，並調整 footer_hook.py 的模組搜尋路徑改用 plugin 根目錄：移除 `hooks/footer_hook.py` 中硬編的 `~/.hermes/lib`，改為插入 plugin 根目錄（`hooks/` 的上層），使 `usage` 與 `providers` 由 plugin 自身目錄解析、與安裝位置無關。驗證：原始碼中不再出現 `~/.hermes/lib` 字串；`python providers/codex_usage.py` 仍可輸出 normalized JSON 與 summary。

## 2. 文件

- [x] 2.1 README 安裝改為複製目錄並在 plugins.enabled 啟用（對應需求 Documentation describes only the footer hook path）：改寫 `README.md` 安裝段為將整個 plugin 目錄複製或 symlink 到 `~/.hermes/plugins/hermes-usage-hook/`，並在 `~/.hermes/config.yaml` 的 `plugins.enabled` 加入 `hermes-usage-hook`（或 hermes plugins enable 指令）；移除 loose 單檔複製步驟與「No configuration is needed」敘述，並加入用 `hermes plugins` 確認 discovery 是否掃到的步驟。驗證：內容審查確認 README 無單檔複製步驟、無「No configuration is needed」，且含 `plugins.enabled` 與 `hermes-usage-hook` 字樣。

## 3. 驗證（初版佈局）

- [x] 3.1 確認既有單元測試在模組搜尋路徑調整後仍通過：執行 `uv run pytest` 全綠，確保 `usage`、`providers` 的頂層匯入未被破壞。

## 4. 重構為 plugin/ 子目錄

- [x] 4.1 建立 `plugin/` 子目錄並把 plugin 必要檔案以 `git mv` 移入（對應需求 Package the plugin under a dedicated subdirectory、Distribute only the footer hook；對應設計決策「將 plugin 檔案收攏到專屬的 `plugin/` 子目錄」）：將 `plugin.yaml`、`__init__.py`、`hooks/`（含 `hooks/__init__.py`、`hooks/footer_hook.py`）、`usage.py`、`providers/`（含 `providers/__init__.py`、`codex_usage.py`、`minimax_usage.py`）由 repo 根移入 `plugin/`；`tests/`、`openspec/`、`README.md`、`.claude/` 等留在 repo 根。各 Python 檔的 `sys.path` 計算相對於檔案位置，不需改動。驗證：`plugin/plugin.yaml`、`plugin/__init__.py`、`plugin/usage.py`、`plugin/providers/__init__.py`、`plugin/hooks/__init__.py`、`plugin/hooks/footer_hook.py` 皆存在；repo 根不再有 `plugin.yaml`、`__init__.py`、`usage.py`、`providers/`、`hooks/`；`plugin/` 內不含 `tests/`、`openspec/`、`README.md`。
- [x] 4.2 [P] 新增 `tests/conftest.py` 讓 tests 由 `plugin/` 解析模組（對應決策 tests 改由 `plugin/` 解析模組）：於 `tests/conftest.py` 將 `<repo>/plugin` 與 `<repo>/plugin/hooks` 插入 `sys.path`，並把 `tests/test_usage.py` 中硬編的 `hooks` 搜尋路徑由 `<repo>/hooks` 改指向 `<repo>/plugin/hooks`。驗證：`uv run pytest` 全綠（27 passed），`usage`/`providers`/`footer_hook` 匯入未被破壞。
- [x] 4.3 [P] 改寫 README 使安裝來源為 `plugin/` 子目錄（對應需求 Documentation describes only the footer hook path；對應設計決策「README 安裝改為複製 `plugin/` 子目錄並在 plugins.enabled 啟用」）：安裝段改為複製/symlink `plugin/` 到 `~/.hermes/plugins/hermes-usage-hook/`（而非整個 repo）；快速檢查指令改為 `python plugin/providers/codex_usage.py`；Files 表路徑改為 `plugin/` 下。驗證：README 指示複製 `plugin/`（非整個 repo）、含 `python plugin/providers/codex_usage.py`、Files 表列 `plugin/…` 路徑、無整個 repo 複製步驟。
- [x] 4.4 重構後 acceptance 驗證：於 `plugin/` 執行 `python -c "import __init__ as p; assert callable(p.register)"` 取得 callable `register`；`python plugin/providers/codex_usage.py` 可獨立輸出 normalized JSON 與 summary；`python -c "import yaml; d=yaml.safe_load(open('plugin/plugin.yaml')); assert d['name']=='hermes-usage-hook' and d['kind']=='standalone' and 'transform_llm_output' in d['provides_hooks']"` 成功；`uv run pytest` 全綠。驗證：上述四項皆通過無錯。

## 5. 安裝腳本

- [x] 5.1 [P] 撰寫 PEP 723 單檔 `install.py`（對應需求 Provide a one-command installer；對應設計決策「新增 PEP 723 單檔 install.py 自動化安裝與啟用」）：repo 根新增 `install.py`，頂部 PEP 723 metadata（`requires-python`、`dependencies = ["pyyaml"]`）；解析 `HERMES_HOME`（預設 `~/.hermes`）；複製 repo 的 `plugin/` 到 `$HERMES_HOME/plugins/hermes-usage-hook/`（已存在先移除再複製、達成 idempotent 覆蓋）；以 `pyyaml` 讀取或建立 `$HERMES_HOME/config.yaml`，把 `hermes-usage-hook` 加入 `plugins.enabled`（已存在不重複、其餘鍵與內容原樣保留）後寫回；印出安裝路徑與「重啟 Hermes」提示；依全域慣例處理 `SIGINT`/`SIGTERM`（退出碼 128+signal）。驗證：以暫時性 `HERMES_HOME` 執行 `uv run install.py` 後，`$HERMES_HOME/plugins/hermes-usage-hook/plugin.yaml` 存在、且 `config.yaml` 經 pyyaml 解析後 `plugins.enabled` 含 `hermes-usage-hook`；二次執行後該清單仍只有一個 `hermes-usage-hook`、既有鍵不變。
- [x] 5.2 [P] README 新增 `uv run install.py` 一鍵安裝段（對應需求 Provide a one-command installer）：於 Install 章節最前加入推薦的 `git clone` 後 `uv run install.py` 步驟，說明其複製 `plugin/` 並寫入 `plugins.enabled`；把現有手動複製 + 啟用步驟標示為替代方案。驗證：README 含 `uv run install.py` 且保留手動步驟作為替代。

## 6. 實機驗證

- [ ] 6.1 請使用者實機驗證：於 repo 根執行 `uv run install.py`（或照 README 手動安裝）後重啟 Hermes，`hermes plugins` 清單出現 `hermes-usage-hook`，且 Codex/MiniMax 回覆末端出現 usage footer。驗證：使用者回報 `hermes plugins` 含該名稱且 footer 顯示。
