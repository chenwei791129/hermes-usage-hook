## 1. 發行 metadata 契約測試

- [x] 1.1 新增 `tests/test_release_metadata.py`，以 repo-owned assertions 定義「Synchronized version across plugin manifest and pyproject」契約（完成後重新命名為「Synchronize the shipped plugin version from the release manifest」）：release-please package `.` 保持 simple type、只 target 帶 anchor 的 `plugin/plugin.yaml`、plugin version 與 release manifest 一致，且不 target `pyproject.toml` 或 `uv.lock`；先執行 `uv run pytest tests/test_release_metadata.py`，確認測試在目前 static metadata 上因預期違規而失敗。
- [x] 1.2 在同一測試模組定義「Provide a repo-root development pyproject.toml」與「Keep generated lock metadata independent of release versions」契約：`[project]` 與 virtual workspace lock entry 必須使用固定的 `0.0.0` development version，且 development version line 不帶 release-please updater anchor；以精準測試名稱與 failure message 驗證目前狀態會被偵測，而不測 uv 或 release-please 的第三方內部行為。

## 2. 消除可漂移的版本狀態

- [x] 2.1 依「使用固定的 development version 隔離 release version」決策，把 `pyproject.toml` 改為 `version = "0.0.0"`、移除 updater anchor並保留 uv non-package mode，使 development project 不再保存 release version；執行 metadata tests 驗證固定 development version 契約轉綠。
- [x] 2.2 依「release-please 只同步實際發行 artifact 的版本」決策，從 `release-please-config.json` 的 `extra-files` 移除 `pyproject.toml`，保留 `plugin/plugin.yaml` 與 updater anchor；執行 metadata tests 驗證 release config contract 轉綠。
- [x] 2.3 執行 `uv lock` 依固定 development metadata 重新產生 `uv.lock`，讓 workspace package entry 使用 `version = "0.0.0"`；保存第一次生成後的 `uv.lock` checksum，再執行 `uv lock --check` 與第二次 `uv lock` 並比較 checksum，證明 lockfile valid 且第二次生成沒有額外變化。

## 3. 規格同步與整體驗證

- [x] 3.1 [P] 依「以 metadata contract test 防止跨檔回歸」決策審查兩份 delta specs，確認它們完整保留未變更的既有契約、以精確 requirement 名稱描述變更，且不在 apply 階段直接修改 `openspec/specs/` 主規格；以 `spectra validate eliminate-uv-lock-version-drift` 與 artifact content review 驗證 normative requirements 可由後續 archive/sync 正確合併。
- [x] 3.2 執行 `uv run pytest tests/test_release_metadata.py`、`uv run pytest`、`uv run ruff check .`、`uv run ruff format --check .` 與 `uv run ty check`，確認 Implementation Contract 的 acceptance criteria；若有既有 failure，記錄具體 command/output 並確認本 change 的 targeted tests 與 lint/type scope 均通過。
- [x] 3.3 執行 `spectra analyze eliminate-uv-lock-version-drift --json` 與 `spectra validate eliminate-uv-lock-version-drift`，確認 proposal、design、delta specs 與 tasks 沒有 Critical/Warning，且 In scope 與 Out of scope 邊界未擴張到 runtime、installer、歷史 tags 或 CI bot commits。
