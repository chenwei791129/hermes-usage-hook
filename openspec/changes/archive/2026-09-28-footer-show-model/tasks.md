## 1. footer 設定解析（TDD）

- [x] 1.1 [P] 先寫失敗測試：在 `tests/test_footer_config.py` 以 dict 注入 `load_show_model(config=...)`，涵蓋「Model display is configured through the plugin entry and disabled by default」的 value resolution 表（absent / `true` / `false` / `"true"` / `1` / `null`）、`footer` 為字串的父層非 mapping、`plugins.entries` 為 list、以及 monkeypatch `load_config()` 拋例外；用 `capsys` 斷言：absent、`null`、`false` 零 warning，其餘各剛好一行 `[hermes-usage-hook]` 前綴且點名出錯 key 的 stderr。驗證：`uv run pytest tests/test_footer_config.py` 因模組不存在而失敗。
- [x] 1.2 實作「footer 設定放在獨立的 footer_config 模組」：新增 `plugin/footer_config.py` 的 `load_show_model(config: object | None = None) -> bool`，lazy import `hermes_cli.config`（ImportError 視為空 config），逐層檢查 `plugins` → `entries` → `hermes-usage-hook` → `footer` → `show_model`，`None` 視同缺鍵，只有布林 `true` 回 `True`，型別錯誤或 `load_config()` 例外寫一行 stderr warning 後回 `False`，不讀任何環境變數。驗證：`uv run pytest tests/test_footer_config.py` 全數通過。

## 2. footer 組裝（TDD）

- [x] 2.1 [P] 先寫失敗測試：在 `tests/test_usage.py` monkeypatch `footer_config.load_show_model` 與 provider fetcher，涵蓋「Enabled model display renders a model line above the usage lines」——啟用 + Codex usage 時回傳字串恰為 `Done.\n\n───\nModel gpt-5.5-codex\n<5h 行>\n<weekly 行>`、啟用 + auto-reset notice 時順序為 model 行 → usage 行 → notice、停用時輸出與現有期望完全相同且無 `Model ` 開頭的行、`model` 缺席 / `None` / `"   "` 不產生 model 行、`[SILENT]` 原樣回傳且不呼叫 fetcher；以及「Enabled model display still reports the model without usage」與修改後的「Detect provider from the response model name」——啟用 + `some-other-model` 回 model-only footer、啟用 + Codex fetch 拋例外時 stderr 有 `[hermes-usage-hook] skipped:` 且回 model-only footer、停用 + 未知 model 回 `None`。驗證：新測試在實作前失敗、既有測試仍通過。
- [x] 2.2 實作「footer 組裝改為先收集 lines 再決定是否回傳」與「show_model 設定在每次 footer 呼叫時重讀」：`append_usage_footer` 每次呼叫以 module attribute 方式呼叫 `footer_config.load_show_model()`，依「model 行格式為 Model 前綴加原樣 model 名稱」算出 `Model <model.strip()>`，再在 guarded 區塊內抓 usage、跑 `maybe_autoreset`、取 notice；usage fetch 例外保留原有 `[hermes-usage-hook] skipped:` stderr 後視為無 usage；lines 依 model → summary → notice 串接，lines 為空才回 `None`；model-only footer 不跑 coordinator、不帶 notice。同步更新 `footer_hook.py` 模組與 `append_usage_footer` docstring 中「unrecognized model / fetch failure returns None」的敘述，改為僅在停用時成立。驗證：`uv run pytest` 全數通過（含 2.1 新測試與所有既有 footer / auto-reset 測試）。

## 3. 文件

- [x] 3.1 [P] 依「Ship a post-install notice with the plugin」更新 `plugin/after-install.md`：新增一節說明 footer model 行預設停用、以 `hermes config set plugins.entries.hermes-usage-hook.footer.show_model true` 啟用、設回 `false` 或 `null` 關閉、啟用後未知 provider 也會出現 model-only footer（因此排在後面的其他 `transform_llm_output` plugin 不再被呼叫），並附一段 footer 範例；同時修正第 2 節「usage call fails and the footer is omitted」，註明啟用 model 顯示時仍會留下 model 行。另在 `tests/test_usage.py` 仿照 `test_after_install_documents_autoreset_optin` 新增文件斷言，檢查 `plugins.entries.hermes-usage-hook.footer.show_model` 出現在該檔。驗證：人工檢查該檔同時涵蓋 spec 列出的所有既有段落與新段落，且沒有把 `footer.show_model` 描述成預設啟用。
- [x] 3.2 [P] 更新 `AGENTS.md`：Repo layout 表新增 `plugin/footer_config.py` 一列；架構段新增「Footer model 行」小節，說明 config key、每次 hook 呼叫經 `load_config()` 重讀、嚴格布林與 `null` 視同缺席、型別錯誤 fail closed 加一行 warning、無環境變數覆寫、model 行位於 usage 行上方、未知 provider 或 fetch 失敗時的 model-only footer，以及因此搶下 `transform_llm_output` hook chain 的副作用；並修正「Provider dispatch」與「憑證解析」段裡「失敗只會少掉 footer」「footer 被省略」的敘述，註明啟用 model 顯示時仍保留 model 行。驗證：人工檢查內容與 `openspec/changes/footer-show-model/specs/footer-model-display/spec.md` 一致。

## 4. 最終檢查

- [x] 4.1 確認整體品質閘門：`uv run pytest`、`uv run ruff check .`、`uv run ty check` 全部通過，且 `plugin/plugin.yaml` 無任何差異（`git diff --stat plugin/plugin.yaml` 無輸出）。
