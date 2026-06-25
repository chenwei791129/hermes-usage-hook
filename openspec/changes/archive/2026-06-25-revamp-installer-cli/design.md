## Context

`install.py` 目前是 PEP 723 單檔腳本（僅依賴 `pyyaml`），把腳本旁的 `plugin/` 複製到 `$HERMES_HOME/plugins/hermes-usage-hook/` 並把 `hermes-usage-hook` 加進 `config.yaml` 的 `plugins.enabled`。它只支援本地安裝、沒有移除功能、沒有任何命令列參數（無 argparse）。

本 repo 以 release-please（`release-type: simple`）發佈：只打 tag 並建立 GitHub Release，CI 不上傳任何自訂產物，因此 release 僅有 GitHub 自動產生的 source tarball（`tarball_url`，內含整個 repo 含 `plugin/`）。`plugin/plugin.yaml` 內有 `version:` 欄位，可作為「已安裝版本」的判斷依據。Hermes 以「目錄名 = plugin 名」載入單一外掛。

## Goals / Non-Goals

**Goals:**

- 預設無需 clone 即可從 GitHub latest release 安裝；可用 `--version` 釘選版本。
- 保留本地安裝路徑（`--local`），維持開發驗證流程。
- 提供對稱的 `remove` 子命令，含版本守門。
- 用標準庫完成下載與解壓，維持零額外執行期依賴。
- 以 argparse 提供一致、可發現的 CLI。

**Non-Goals:**

- 不建立自訂 release asset、不改 release-please 設定。
- 不做多版本並存安裝目錄。
- 不加網路重試 / 下載快取。
- 不改動 plugin 執行邏輯。

## Decisions

### 以 argparse 子命令區分 install 與 remove，install 為預設

採用 argparse 子命令：無子命令或 `install` 走安裝；`remove` 走移除。共用旗標（`--hermes-home`、`--no-enable`、`--dry-run`、`-v/--verbose`）置於各子命令。`install` 專屬 `--local [PATH]`、`--version` 與 `--repo`（`remove` 只操作本地安裝，不需 `--repo`）；`remove` 專屬 `--version`。

替代方案：用單一 `--remove` flag。否決原因：子命令在 `--help` 中對兩種模式各自列出專屬旗標，比 flag 互斥更清楚。

實作上以 `subparsers.required = False` 搭配 `set_defaults(func=...)`，讓 `uv run install.py`（無子命令）等同 `install`。

### 預設從 GitHub release 抓 source tarball 安裝

安裝來源解析順序：

1. `--local` 在場 → 從本地目錄安裝（路徑預設腳本旁 `plugin/`，可帶自訂路徑）。
2. 否則 → 從 GitHub release 下載：
   - 版本解析：`--version` 在場 → 取該 tag 的 release（`repos/<repo>/releases/tags/<tag>`，tag 同時嘗試帶與不帶 `v` 前綴）；否則取 `repos/<repo>/releases/latest`。
   - 由 release JSON 取 `tarball_url`，下載到暫存檔，以 `tarfile` 解壓到暫存目錄。
   - 在解壓內容中定位 `plugin/` 子目錄（GitHub tarball 會多包一層 `<owner>-<repo>-<sha>/` 頂層目錄），複製其內容到安裝目的地。

`--local` 與 `--version` 互斥（本地無版本概念），於 argparse 層以互斥群組或顯式檢查擋下並報錯。

替代方案：抓 `archive/refs/tags/<tag>.tar.gz` 固定 URL。否決原因：改用 release API 的 `tarball_url` 能同時驗證「該 release 確實存在」，並讓 latest 解析走同一條 API 路徑。

### 下載與解壓僅用標準庫

以 `urllib.request`（GET，帶 `User-Agent` 與 `Accept: application/vnd.github+json` header）呼叫 GitHub API 與下載 tarball，`json` 解析 release，`tarfile` 解壓。不新增 `httpx` 依賴，PEP 723 metadata 維持 `["pyyaml"]`。

替代方案：沿用 plugin 已釘的 `httpx`。否決原因：單純 GET tarball 標準庫即可，避免安裝器多一個依賴與下載成本。

解壓安全：對 tar 成員做路徑穿越防護（拒絕絕對路徑與含 `..` 跳脫安裝暫存目錄的成員），避免惡意 tarball 寫出範圍外檔案。

### 腳本須可由遠端 URL 直接執行（自足、不依賴相鄰檔案）

目標是讓使用者免 clone，直接 `uv run https://raw.githubusercontent.com/chenwei791129/hermes-usage-hook/main/install.py [args]`。為此，非 `--local` 的所有模式（預設 release 安裝、`--version` 安裝、`remove`）都不得讀取「腳本旁」的任何檔案：

- plugin 名稱一律用固定常數 `hermes-usage-hook`（安裝目的地、`plugins.enabled` 項、remove 目標），不沿用現行 `read_plugin_name(PLUGIN_SRC)` 去讀腳本旁 `plugin/plugin.yaml`。
- 安裝來源在預設/`--version` 模式一律來自 GitHub release tarball。
- `remove` 的版本守門讀的是「已安裝目錄」`$HERMES_HOME/plugins/hermes-usage-hook/plugin.yaml`，而非腳本旁檔案。
- 只有 `--local` 模式會碰腳本旁檔案（其預設路徑為腳本旁 `plugin/`）；因此遠端執行若要用 `--local`，必須帶明確且存在的 `PATH`。

替代方案：保留 `read_plugin_name` 從本地 `plugin/` 取名。否決原因：遠端執行時腳本旁無 `plugin/`，會在預設模式直接失敗，違背免 clone 的核心目標。

### remove 子命令與版本守門

`remove` 行為：刪除 `$HERMES_HOME/plugins/hermes-usage-hook/`（沿用既有 symlink/實體目錄處理），並從 `config.yaml` 的 `plugins.enabled` 移除 `hermes-usage-hook`（保留其他鍵值，原子寫入）。兩個動作皆冪等：目錄不存在 / 項目不在清單，都視為已達成而非錯誤。

版本守門：`remove --version X` 時，先讀已安裝目錄的 `plugin.yaml` 之 `version`；相符才移除，否則中止並以非零碼報錯，訊息含已安裝版本與要求版本。已安裝目錄不存在而帶 `--version` 時亦報錯（無從比對）。`remove` 不帶 `--version` → 無條件移除。

### 網路 / 解析失敗一律明確報錯並提示 --local

任何 release 解析、HTTP 非 2xx、下載中斷、tarball 內找不到 `plugin/` 等失敗，皆以非零碼結束並輸出可讀錯誤；release 來源失敗時提示「可改用 `--local` 從本地安裝」。沿用既有 `SIGINT`（130）/`SIGTERM`（143）處理。

### 共用旗標語意

- `--hermes-home PATH`：優先於 `HERMES_HOME` 環境變數；兩者皆無則 `~/.hermes`。
- `--no-enable`：install 時只複製目錄不改 `config.yaml`；remove 時只刪目錄不改 `config.yaml`。
- `--dry-run`：印出將進行的動作（來源、目的地、config 變更）但不下載、不寫檔、不刪檔。
- `-v/--verbose`：額外輸出解析到的 release tag、`tarball_url`、暫存解壓路徑等。

## Implementation Contract

**CLI 介面：**

- `uv run install.py [install] [--local [PATH]] [--version TAG] [--repo OWNER/NAME] [--hermes-home PATH] [--no-enable] [--dry-run] [-v]`
- `uv run install.py remove [--version TAG] [--hermes-home PATH] [--no-enable] [--dry-run] [-v]`（remove 只操作本地安裝，無 `--repo`）
- 無子命令等同 `install`。`--local` 與 `--version` 同時出現 → argparse 報錯退出（非零碼）。

**行為（install）：**

- 無 `--local`：解析 release（latest 或 `--version` 指定）→ 下載 `tarball_url` → 解壓 → 取 `plugin/` → 複製到 `<hermes_home>/plugins/hermes-usage-hook/`（覆寫，沿用既有 symlink/目錄處理）→ 除非 `--no-enable` 否則把 `hermes-usage-hook` 加入 `plugins.enabled`（冪等、原子寫入、保留其他鍵）。
- `--local`：來源改為指定本地目錄（預設腳本旁 `plugin/`），其餘同上。
- 成功輸出安裝目的地與 enable 結果，並提示重啟 Hermes。

**行為（remove）：**

- 帶 `--version X`：讀已安裝 `plugin.yaml` 的 `version`，不符或目錄不存在 → 非零碼報錯中止，不做任何刪除。
- 相符或不帶 `--version`：刪除安裝目錄並（除非 `--no-enable`）從 `plugins.enabled` 移除該項；皆冪等。

**行為（遠端執行）：** 非 `--local` 的所有模式皆自足，不讀腳本旁任何檔案；plugin 名稱用固定常數 `hermes-usage-hook`（移除 `read_plugin_name(PLUGIN_SRC)` 對本地 `plugin/` 的依賴）。`uv run <raw-url> [args]` 在無 `plugin/` 的工作目錄下，預設安裝與 `remove` 均正常運作。遠端用 `--local` 須帶明確存在的 `PATH`。

**失敗模式：** release/HTTP/下載/解壓/定位 `plugin/` 失敗 → 非零碼 + 可讀訊息 + 提示 `--local`；版本守門不符 → 非零碼 + 含兩版本號訊息。`--dry-run` 永不寫入/刪除/下載。

**驗收標準：**

- `tests/test_install.py`：以 monkeypatch 假造 urllib 回應（release JSON + 暫存 tarball）驗證預設 release 安裝；`--local` 安裝；冪等與保留既有 config 鍵；`remove` 刪目錄與 enabled 項；`remove --version` 相符移除與不符中止；`--no-enable`、`--dry-run` 不寫檔。
- `tests/test_script_mode.py`：CLI 參數解析（子命令、互斥、預設子命令）。
- 不對 urllib / tarfile / pyyaml 等第三方/標準庫本身行為寫測試，僅測本腳本邏輯。
- 遠端自足性：在無 `plugin/` 的工作目錄下，預設安裝（假造 release）與 `remove` 均成功且不讀腳本旁檔案；以測試確保預設/`remove` 路徑不呼叫任何讀取 `__file__` 相鄰 `plugin/` 的程式。

**範圍邊界：**

- In scope：`install.py` 重寫、對應測試、`README.md` 安裝段落更新、`footer-hook-deployment` spec 之 installer 需求更新。
- Out of scope：release-please 設定、CI 產物、plugin 執行邏輯、多版本並存。

## Risks / Trade-offs

- [預設行為變更為連網，離線環境會失敗] → 失敗訊息明確提示 `--local`；README 標註預設連網與離線替代。
- [GitHub API 速率限制（未認證 60 req/hr）] → 單次安裝僅 1～2 次請求，遠低於限制；429/403 時報錯提示稍後再試或用 `--local`。
- [惡意 / 損壞 tarball 路徑穿越] → 解壓前對成員做路徑驗證，拒絕逃逸安裝暫存目錄者。
- [版本守門依賴 `plugin.yaml` 的 `version` 欄位存在] → 欄位缺失時視為不符並報錯，不靜默移除。

## Migration Plan

- 既有使用者既有的安裝不受影響；下次執行 `install.py` 預設改走 release。需本地安裝者改加 `--local`。
- README 同步更新：標明預設來源、`--local`、`remove`、各旗標。
- 無資料遷移；回退方式為還原 `install.py`。

## Open Questions

- 無。`--repo` 預設值 `chenwei791129/hermes-usage-hook` 已與 README clone URL 一致。
