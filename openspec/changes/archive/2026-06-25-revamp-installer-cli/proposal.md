## Why

目前 `install.py` 只能從複製下來的 repo 本地 `plugin/` 目錄安裝，使用者必須先 `git clone` 才能安裝；且沒有移除（uninstall）功能，要解除安裝得手動刪目錄並改 `config.yaml`。將預設來源改為 GitHub release，可讓使用者不必 clone 就一鍵安裝指定或最新版本，並補上對稱的 remove 流程。

## What Changes

- **BREAKING**：`uv run install.py` 的預設行為從「安裝本地 `plugin/`」改為「從 GitHub 抓取 latest release 的 source tarball 安裝」。需要本地安裝者改用 `--local`。
- 支援免 clone 的遠端執行：`uv run https://raw.githubusercontent.com/chenwei791129/hermes-usage-hook/main/install.py [args]`。為此非 `--local` 模式（預設安裝、`--version`、`remove`）一律不讀腳本旁檔案，plugin 名稱用固定常數 `hermes-usage-hook`（移除對本地 `plugin/plugin.yaml` 的 `read_plugin_name` 依賴）。
- 新增 `--local [PATH]` 選項：從本地目錄安裝（不帶路徑時為腳本旁的 `plugin/`，即原行為）。`--local` 與 `--version` 互斥。
- 新增 `remove` 子命令：移除已安裝的 plugin 目錄並從 `config.yaml` 的 `plugins.enabled` 移除該項；缺一不可的兩個動作都要冪等。
- 新增 `--version TAG`：install 釘選指定 release 版本（預設 latest）；remove 作為「版本守門」——讀取已安裝 `plugin/plugin.yaml` 的 `version`，相符才移除，否則中止並提示。
- 新增 `-v/--verbose`：輸出下載 URL、解壓路徑等診斷細節。
- 新增 `--repo OWNER/NAME`：覆寫來源 repo，預設 `chenwei791129/hermes-usage-hook`。
- 新增 `--hermes-home PATH`：以旗標覆寫 Hermes 家目錄（優先於 `HERMES_HOME` 環境變數）。
- 新增 `--no-enable`：只複製/移除目錄，不修改 `config.yaml`。
- 新增 `--dry-run`：印出將執行的動作但不寫入任何檔案。
- 下載一律使用標準庫（`urllib.request`、`tarfile`、`json`），不新增 `httpx` 依賴；PEP 723 metadata 維持只依賴 `pyyaml`。
- 維持 Hermes 單一目錄載入模型——安裝目錄固定為 `plugins/hermes-usage-hook/`，不做多版本並存。

## Non-Goals

- 不建立自訂 release 產物（沿用 release-please `simple` 類型自動產生的 source tarball，不在 CI 額外打包只含 `plugin/` 的 asset）。
- 不做多版本並存安裝（不採用 `hermes-usage-hook-<version>/` 目錄佈局），以符合 Hermes 以目錄名載入單一 plugin 的模型。
- 不新增執行期網路重試 / 快取機制；單次下載失敗即明確報錯。
- 不改動 plugin 本身的執行邏輯（providers、hook、usage 模組不變）。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `footer-hook-deployment`: 「Provide a one-command installer」需求擴充——預設來源改為 GitHub release、新增 `--local` 反轉本地安裝、新增 `remove` 子命令與版本守門，以及 `--version`/`--repo`/`--hermes-home`/`--no-enable`/`--dry-run`/`-v` 等旗標；下載僅用標準庫。

## Impact

- Affected specs: `footer-hook-deployment`
- Affected code:
  - Modified: `install.py`、`tests/test_install.py`、`tests/test_script_mode.py`、`README.md`
  - New: (none)
  - Removed: (none)
