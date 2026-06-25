## 1. CLI 骨架與參數解析

實作設計決策「以 argparse 子命令區分 install 與 remove，install 為預設」與需求「Installer command-line flags」的解析層。

- [x] 1.1 在 `tests/test_script_mode.py` 新增 argparse 解析測試：`install` 為無子命令時的預設、`remove` 子命令、共用旗標（`--hermes-home`/`--no-enable`/`--dry-run`/`-v`）、`install` 專屬 `--local [PATH]`/`--version`/`--repo`（`remove` 不接受 `--repo`）、`remove` 專屬 `--version`，以及 `--local` 與 `--version` 互斥時退出非零。完成定義：測試先紅。驗證：`uv run pytest tests/test_script_mode.py`。
- [x] 1.2 在 `install.py` 依「以 argparse 子命令區分 install 與 remove，install 為預設」實作子命令骨架（`subparsers.required = False` + `set_defaults(func=...)` 使無子命令等同 `install`），依需求「Installer command-line flags」加入共用與各模式專屬旗標，並對 `--local`+`--version` 顯式報錯退出。完成定義：1.1 測試轉綠。驗證：`uv run pytest tests/test_script_mode.py`。

## 2. Release 下載與解壓

實作設計決策「預設從 GitHub release 抓 source tarball 安裝」與「下載與解壓僅用標準庫」。

- [x] 2.1 在 `tests/test_install.py` 新增 release 下載測試：以 monkeypatch 假造 `urllib.request` 回傳 release JSON（含 `tarball_url`）與一個內含頂層 `<owner>-<repo>-<sha>/plugin/` 的暫存 tarball，驗證 latest 與 `--version TAG`（tag 帶/不帶 `v`）皆能解析、下載、解壓並定位到 `plugin/`；並驗證 tarball 內無 `plugin/` 時報錯非零。完成定義：測試先紅。驗證：`uv run pytest tests/test_install.py -k release`。
- [x] 2.2 在 `install.py` 依「下載與解壓僅用標準庫」實作以 `urllib.request`（帶 `User-Agent`/`Accept` header）、`json`、`tarfile` 解析 release、下載 tarball、解壓到暫存目錄並定位 `plugin/` 的函式，含解壓路徑穿越防護（拒絕絕對路徑與逃逸暫存目錄的成員）。完成定義：2.1 測試轉綠，PEP 723 metadata 仍只含 `pyyaml`。驗證：`uv run pytest tests/test_install.py -k release`。

## 3. install 模式整合

實作需求「Provide a one-command installer」與「Install a specific release version」，及設計決策「網路 / 解析失敗一律明確報錯並提示 --local」「共用旗標語意」。

- [x] 3.1 在 `tests/test_install.py` 新增 install 整合測試：`--local` 安裝複製 `plugin/` 並 enable；預設（假造 release）安裝走下載路徑；`--version` 釘選指定 release；冪等與保留既有 `config.yaml` 其他鍵；`--no-enable` 不動 config；`--dry-run` 不建立/修改任何檔；`--hermes-home` 優先於環境變數；release 失敗時退出非零且訊息提示 `--local`。完成定義：測試先紅。驗證：`uv run pytest tests/test_install.py -k install`。
- [x] 3.2 在 `install.py` 串接 install 流程（涵蓋「Provide a one-command installer」與「Install a specific release version」）：依 `--local`/release 解析來源 → 複製到 `<hermes_home>/plugins/hermes-usage-hook/`（沿用既有 symlink/目錄覆寫處理）→ 除非 `--no-enable` 否則冪等、原子地更新 `plugins.enabled`；依「共用旗標語意」實作 `--dry-run` 動作輸出與 `--hermes-home` 優先序，並依「網路 / 解析失敗一律明確報錯並提示 --local」處理 release 失敗。完成定義：3.1 測試轉綠。驗證：`uv run pytest tests/test_install.py -k install`。

- [x] 3.3 依需求「Run standalone from a remote URL」與設計決策「腳本須可由遠端 URL 直接執行（自足、不依賴相鄰檔案）」，移除 `install.py` 對腳本旁 `plugin/` 的依賴：plugin 名稱改用固定常數 `hermes-usage-hook`（刪除 `read_plugin_name(PLUGIN_SRC)` 在預設/`remove` 路徑的呼叫），並在 `tests/test_install.py` 加測試：在無 `plugin/` 的工作目錄下，假造 release 的預設安裝與 `remove` 皆成功且不讀腳本相鄰檔案。完成定義：測試綠且預設/`remove` 路徑不觸及 `__file__` 相鄰 `plugin/`。驗證：`uv run pytest tests/test_install.py -k remote`。

## 4. remove 模式

實作需求「Remove the installed plugin」與設計決策「remove 子命令與版本守門」。

- [x] 4.1 在 `tests/test_install.py` 新增 remove 測試：無 `--version` 刪目錄並移除 `plugins.enabled` 項且保留其他鍵；目錄不存在 / 項目已不在時冪等回 0；`remove --version` 與已安裝 `plugin.yaml` 的 `version` 不符時退出非零、報告兩版本且不刪除；相符時正常移除；帶 `--version` 但目錄不存在時退出非零；`--no-enable` 只刪目錄不動 config。完成定義：測試先紅。驗證：`uv run pytest tests/test_install.py -k remove`。
- [x] 4.2 在 `install.py` 依「remove 子命令與版本守門」實作需求「Remove the installed plugin」的 `remove`：刪除安裝目錄、（除非 `--no-enable`）原子地從 `plugins.enabled` 移除該項，兩動作皆冪等；`--version` 版本守門讀已安裝 `plugin.yaml` 的 `version` 比對，不符或目錄不存在則退出非零不刪除。完成定義：4.1 測試轉綠。驗證：`uv run pytest tests/test_install.py -k remove`。

## 5. 文件與整體驗證

- [x] 5.1 [P] 更新 `README.md` 的 Install 段落：說明免 clone 的遠端安裝（`uv run https://raw.githubusercontent.com/chenwei791129/hermes-usage-hook/main/install.py [args]`）、預設從 GitHub release 安裝、`--local` 本地安裝（遠端用須帶明確 `PATH`）、`remove` 子命令與版本守門，以及 `--version`/`--repo`/`--hermes-home`/`--no-enable`/`--dry-run`/`-v` 各旗標，並標註預設連網與離線改用 `--local`。完成定義：README 安裝指示與新 CLI 行為一致。驗證：人工審閱 README Install 段落對照 `install.py --help`。
- [x] 5.2 全套品質檢查：`uv run pytest`、`uv run ruff check .`、`uv run ty check` 全綠。完成定義：三項檢查皆通過。驗證：依序執行上述三道指令。
