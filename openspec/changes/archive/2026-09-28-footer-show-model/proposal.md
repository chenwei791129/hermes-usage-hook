## Why

同一個 Hermes 部署可能在不同 session 或中途切換 model，但目前 footer 只顯示 provider 用量，使用者無法從回覆本身看出這一輪到底是哪個 model 回的。提供一個可選的 model 顯示行，讓使用者不必另外查 session 設定就能確認。

## What Changes

- 新增 plugin 設定 `plugins.entries.hermes-usage-hook.footer.show_model`（布林，預設 `false`），可用 `hermes config set plugins.entries.hermes-usage-hook.footer.show_model true` 啟用；每次 hook 呼叫都經 Hermes `load_config()` 重讀，改設定不必重裝或重啟。
- 啟用時，footer 分隔線下的第一行為 `Model <model>`，其下接原本的 usage 行與一次性 auto-reset notice。
- 啟用時，即使 model 不屬於任何已知 provider、或 usage 抓取失敗，footer 仍會只帶 `Model <model>` 一行；停用時行為與現在完全相同。
- 設定值不是布林、或 plugin entry 結構不合法時，一律視為停用並輸出一行 `[hermes-usage-hook]` 前綴的 stderr warning，絕不影響回覆或 usage footer。
- `plugin/after-install.md` 與 `AGENTS.md` 記錄這個新選項。

## Capabilities

### New Capabilities

- `footer-model-display`: 可選的 footer model 顯示行——設定來源與解析、預設停用、行的位置與格式、在未知 provider 與 usage 失敗時的行為。

### Modified Capabilities

- `footer-hook-deployment`: post-install notice 必須說明 `footer.show_model` 選項預設停用及啟用方式。
- `provider-detection`: 未知 provider 時「回覆不變」的要求加上例外——啟用 model 顯示時改為附上 model-only footer。

## Impact

- Affected specs: `footer-model-display`（新增）、`footer-hook-deployment`（修改 post-install notice 需求）、`provider-detection`（修改未知 model 的回覆行為）
- Affected code:
  - New: `plugin/footer_config.py`、`tests/test_footer_config.py`
  - Modified: `plugin/hooks/footer_hook.py`、`tests/test_usage.py`、`plugin/after-install.md`、`AGENTS.md`
- `plugin/plugin.yaml` 不變：仍只宣告兩個 hook，不加任何設定值。
