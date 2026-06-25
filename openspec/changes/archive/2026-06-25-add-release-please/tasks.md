## 1. release-please 設定檔（Manifest-driven configuration with simple release type）

對應 spec 需求 "Manifest-driven configuration with simple release type"；對應 design 決策「採用 release-type simple 而非 python」。

- [x] [P] 1.1 建立 `release-please-config.json`，實作 spec 需求 "Manifest-driven configuration with simple release type"：頂層 `packages` 含鍵 `"."`，設定 `"release-type": "simple"` 與 `"extra-files": ["plugin/plugin.yaml", "pyproject.toml"]`。完成時該檔為合法 JSON 且結構如上；以 `python3 -c "import json; json.load(open('release-please-config.json'))"` 解析無誤並人工檢視鍵值驗證。
- [x] [P] 1.2 建立 `.release-please-manifest.json`：內容為 `{ ".": "0.1.0" }`，作為版本權威起點並對齊現行 `plugin/plugin.yaml`。完成時該檔為合法 JSON 且 `"."` 對應 `0.1.0`；以 JSON 解析驗證。

## 2. 同步版本錨點（Synchronized version across plugin manifest and pyproject）

對應 spec 需求 "Synchronized version across plugin manifest and pyproject"；對應 design 決策「以 extra-files 加 x-release-please-version 註解錨點同步雙檔」與「改寫 pyproject.toml 的版本註解語意」。

- [x] [P] 2.1 實作 spec 需求 "Synchronized version across plugin manifest and pyproject"：在 `plugin/plugin.yaml` 的 `version` 行尾加上 `# x-release-please-version` 錨點註解，值維持 `0.1.0`。完成時 release-please 泛用更新器可定位該行；以 `grep "x-release-please-version" plugin/plugin.yaml` 命中且 `version: 0.1.0` 不變驗證。
- [x] [P] 2.2 改寫 pyproject.toml 的版本註解語意並加錨點：將 `version = "0"` 改為 `version = "0.1.0"` 並在行尾加 `# x-release-please-version`；改寫開頭版本相關註解，移除「version 為無意義佔位」說法，改述為「版本由 release-please 與 `plugin/plugin.yaml` 同步，本檔仍 `package = false`、不發佈」。完成時版本為 `0.1.0`、帶錨點、註解不再宣稱佔位，且 `[tool.uv]` 仍為 `package = false`；以 `grep` 檢查錨點與註解、`uv sync` 不報錯驗證。

## 3. GitHub Actions workflow（Automated release workflow driven by Conventional Commits）

對應 spec 需求 "Automated release workflow driven by Conventional Commits"；對應 design 決策「移除參考 workflow 的 PyPI 發佈 job」。

- [x] 3.1 建立 `.github/workflows/release-please.yml`，實作 spec 需求 "Automated release workflow driven by Conventional Commits"：`on: push: branches: [main]`；頂層 `permissions` 宣告 `contents: write` 與 `pull-requests: write`；單一 job 使用 `googleapis/release-please-action@v4`，不含任何 PyPI 發佈步驟（無 `uv build`、`uv publish`、artifact 上傳）。完成時為合法 YAML 且符合上述契約；以 YAML 解析與人工檢視 job 步驟驗證無 PyPI 步驟。

## 4. 驗證

- [x] 4.1 回歸驗證既有開發檢查不因本變更失敗：執行 `uv run pytest`、`uv run ruff check .`、`uv run ty check` 三者皆通過。
