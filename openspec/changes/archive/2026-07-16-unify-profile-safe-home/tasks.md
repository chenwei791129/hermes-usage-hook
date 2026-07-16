## 1. 統一 profile-safe home 解析

- [x] 1.1 實作 spec 需求 "Plugin-owned files resolve the Hermes home through one profile-safe resolver"：先於 `tests/test_autoreset.py` 新增（TDD 紅）測試，斷言 `autoreset._hermes_home()` 在「注入 fake `hermes_constants`（`get_hermes_home()` 回傳 tmp_path 下自訂 profile 目錄）」與「模組缺席且 `HERMES_HOME` 設定」兩種情境的回傳值，分別等於 `hermes_home.resolve_hermes_home()` 的對應結果；再將 `plugin/autoreset.py` 的 `_hermes_home()` 改為 `return resolve_hermes_home()`（於檔頂 `from .hermes_home import resolve_hermes_home`），保留官方模組缺席時的 `HERMES_HOME`/`~/.hermes` fallback（由 resolver 提供，語意不變）。驗證：新測試通過；既有以 `HERMES_HOME` 為基準的 state/lock/notice 測試（`hermes_constants` 於測試環境缺席）維持通過。注意：`tests/test_usage.py` 既有的 `test_usagehook_reads_the_coordinator_store_home_not_the_profile_default` 因前提被反轉會在此步後失敗，將於任務 2.1 一併更新。
- [x] 1.2 驗證 state store 與兩個 lock acquirer 在 profile 環境下與 history 落點一致：於 `tests/test_autoreset.py` 新增測試，注入 fake `hermes_constants`（`get_hermes_home()` 指向 tmp_path 下 profile 目錄），斷言 `AutoResetStateStore().home`、`acquire_autoreset_lock`、`acquire_notice_lock` 的預設 home 皆解析到該 profile 目錄；`hermes_constants` 缺席時皆解析到 `HERMES_HOME`。驗證：新測試通過（涵蓋 spec 的「Hermes runtime present」與「Standalone」兩情境於 coordinator 檔案）。

## 2. 移除查詢端 workaround 並修正回歸測試

- [x] 2.1 實作 spec 需求 "History reads and writes resolve to the same home without a query-side workaround"：先（TDD 紅）將 `tests/test_usage.py` 前提已反轉的 `test_usagehook_reads_the_coordinator_store_home_not_the_profile_default` **改名**（例如 `test_usagehook_reads_history_from_the_unified_profile_safe_home`，因舊名的斷言在統一後已相反）並改寫為新前提——注入 fake `hermes_constants`（`get_hermes_home()` 指向 tmp_path 下 profile 目錄），以 coordinator 寫入路徑（`append_success_event(home=AutoResetStateStore().home)`）在該 profile 目錄寫入一筆事件，斷言 `/usagehook history` 能讀回該事件（read 與 write 解析到同一 profile home）；再將 `plugin/hooks/footer_hook.py` 的查詢由 `autoreset_audit.read_events(home=AutoResetStateStore().home)` 改為 `autoreset_audit.read_events()`（移除 `AutoResetStateStore().home` 注入），並更新該行上方註解使其反映「read 與 write 已由統一 resolver 對齊、不需注入」。驗證：改名改寫後測試與既有全部 `usagehook` 測試通過。

## 3. 整體品質關卡

- [x] 3.1 品質關卡：`uv run python -m pytest -q` 全數通過、`uv run ruff check plugin/ tests/` 與 `uv run ruff format --check` 對本次觸及檔案無新增違規、`uv run ty check plugin/` 通過。驗證：三個指令輸出乾淨；此為完成本 change 的必要條件。
