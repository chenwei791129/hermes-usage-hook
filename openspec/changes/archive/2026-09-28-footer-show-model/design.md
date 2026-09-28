## Context

`append_usage_footer`（`transform_llm_output` handler）目前流程是：空回覆或 silence marker 直接處理 → 依 `model` 找 provider 並抓 usage → 沒有 usage 就回 `None` → 有 usage 才跑 auto-reset coordinator、取 notice、render footer。任何例外都被外層 `try` 吃掉並回 `None`。

Hermes 呼叫這個 hook 時傳入 `model=agent.model`，也就是 session 當下設定的 model，所以 hook 不需要自己去查 session。`hermes config set` 會把 `true` / `false` 轉成 YAML boolean、把 `null` 轉成 `None`，因此 plugin 端可以嚴格要求布林值。

Auto-reset 已經示範了「從 `plugins.entries.hermes-usage-hook.<namespace>` 讀自己的 schema、每次呼叫重讀 `load_config()`」的做法（`plugin/autoreset.py` 裡的 lazy import `hermes_cli.config` 與逐層 mapping 檢查），本變更沿用同一個模式。

## Goals / Non-Goals

**Goals:**

- 以 `plugins.entries.hermes-usage-hook.footer.show_model` 提供預設關閉的 model 顯示行。
- 啟用時 model 行在 usage 行上方；未知 provider 或 usage 失敗時仍輸出 model-only footer。
- 設定錯誤 fail closed、只留一行 stderr warning，絕不影響回覆或既有 usage footer。
- 停用時 footer 輸出與現在逐位元組相同。

**Non-Goals:**

- 不提供環境變數覆寫（例如 `CODEX_SHOW_MODEL`）：需求只要求 `hermes config set`，且顯示偏好不需要 process-managed 覆寫。
- 不做 model 名稱的美化或別名對映（例如把 `gpt-5.5-codex` 改寫成顯示名稱），原樣輸出。
- 不顯示 provider 名稱以外的 session 資訊（reasoning effort、token 數、session ID 等）。
- 不在 `plugin/plugin.yaml` 宣告設定值，不新增 hook。
- 不改 auto-reset 的設定讀取程式碼，也不把兩者的 config loader 合併成共用模組。

## Decisions

### footer 設定放在獨立的 footer_config 模組

新增 `plugin/footer_config.py`，對外只暴露 `load_show_model(config=None) -> bool`。`config` 為 `None` 時 lazy import `hermes_cli.config` 並呼叫 `load_config()`；import 失敗視為空 config（standalone / 測試環境），`load_config()` 例外則 warning 後回 `False`。逐層檢查 `plugins` → `entries` → `hermes-usage-hook` → `footer` → `show_model`：`None` 或缺鍵視為 absent（回 `False`、不 warning），非 mapping / 非布林則寫一行 `[hermes-usage-hook] footer config warning: <key path> ...` 到 stderr 後回 `False`。

替代方案：直接 import `autoreset._load_hermes_config` 與 `_plugin_autoreset` 的結構。否決原因是那些是 autoreset 的私有 helper，且 `_plugin_autoreset` 以 raise 表達錯誤、錯誤訊息綁 `auto_reset`；硬共用會讓 footer 設定依賴 autoreset 的內部細節。兩份約二十行的逐層檢查重複是可接受的代價。

### show_model 設定在每次 footer 呼叫時重讀

`append_usage_footer` 每次都呼叫 `load_show_model()`，與 auto-reset 一致，改 `config.yaml` 立即生效。代價是一次回覆會有兩次 `load_config()`（footer 一次、coordinator 一次）；`load_config()` 讀的是本機小型 YAML，成本可忽略，不值得為此改 coordinator 的簽章。

### footer 組裝改為先收集 lines 再決定是否回傳

重寫 `append_usage_footer` 的組裝方式：先算出 `model_line`（啟用且 model 為非空字串時才有），再在 guarded 區塊內抓 usage、跑 coordinator、取 notice。最終 footer lines 依序為 model 行、usage summary、notice；lines 為空才回 `None`。usage 抓取例外不再讓整個 hook 回 `None`，而是維持原本的 `[hermes-usage-hook] skipped:` stderr 訊息後，視同「沒有 usage」繼續，讓 model-only footer 成立。

替代方案：保留原本「無 usage 即回 None」的早退，再另外在最外層補一段 model-only 分支。否決原因是會出現兩個 render 出口，停用路徑與啟用路徑的輸出容易分歧；單一 lines 組裝能直接保證「停用時輸出不變」。

### model 行格式為 Model 前綴加原樣 model 名稱

格式固定為 `Model <model>`，`<model>` 是 `model` kwarg `strip()` 後的字串。選 `Model` 前綴是為了跟 usage 行的 `<Provider> <window> |` 形式區隔、且不需要額外分隔符號。

## Implementation Contract

**Behavior**

- 設定缺席、`null`、`false` → footer 與現在完全相同。
- 設定 `true` 且 model 非空 → footer body 第一行 `Model <model>`，接 usage 行，再接 notice。
- 設定 `true`、model 非空、但沒有 usage（未知 provider 或 fetch 例外）→ footer body 只有 `Model <model>`；fetch 例外仍寫 `[hermes-usage-hook] skipped:` 到 stderr。
- 設定值或父層結構不合法、或 `load_config()` 例外 → 視為停用，該次呼叫寫剛好一行 `[hermes-usage-hook]` 前綴的 stderr warning，並點名出錯的 key。
- silence marker 原樣回傳、空回覆回 `None`，兩者都與設定無關。

**Interface**

- `plugin/footer_config.py`：`load_show_model(config: object | None = None) -> bool`。`config` 參數讓測試直接注入 dict，不需 monkeypatch `hermes_cli`。
- `plugin/hooks/footer_hook.py`：`append_usage_footer(response_text, **kwargs)` 簽章不變；內部改用 `footer_config.load_show_model()`，以 module attribute 方式呼叫以便測試 monkeypatch。
- 回傳字串格式維持 `f"{response_text}\n\n───\n{footer}"`，`footer` 為 lines 以 `\n` 串接。

**Acceptance criteria**

- `tests/test_footer_config.py` 以 dict 注入涵蓋 spec 的 value resolution 表（absent / `true` / `false` / `"true"` / `1` / `null`）、父層非 mapping、`load_config()` 例外，並用 `capsys` 斷言 warning 行數與內容。
- `tests/test_usage.py` 以 monkeypatch `load_show_model` 與 provider fetcher 涵蓋：啟用 + Codex usage 的完整輸出字串、啟用 + notice 的順序、停用時輸出與現有測試期望相同、blank / `None` model、silence marker、未知 model 啟用 / 停用、fetch 例外啟用。
- `uv run pytest`、`uv run ruff check .`、`uv run ty check` 全部通過。

**Scope boundaries**

- In scope：`plugin/footer_config.py`（新）、`plugin/hooks/footer_hook.py` 的 footer 組裝、對應測試、`plugin/after-install.md` 與 `AGENTS.md` 的文件段落。
- Out of scope：`plugin/usage.py` 的 `format_summary`、provider fetcher、auto-reset coordinator、`plugin/plugin.yaml`、`install.py`、README（README 依既有 spec 只導向 `after-install.md`）。

## Risks / Trade-offs

- [啟用後未知 provider 的回覆也會多出 footer，行為與現在「未知 model 不動回覆」不同] → 這是使用者明確選擇的行為，且只在 opt-in 後發生；spec 保證停用時完全不變。
- [Hermes 的 `transform_llm_output` 是「第一個回傳非空字串的 hook 勝出」，啟用後本 plugin 對未知 provider 的回覆也會回傳字串，排在後面的其他 transform plugin 就不再被呼叫] → 只在 opt-in 後發生；after-install.md 與 AGENTS.md 要點明這個副作用，讓同時裝有其他 `transform_llm_output` plugin 的 operator 知情後再啟用。
- [設定錯誤時每個回覆都寫一次 warning，stderr 可能變吵] → 這正是提醒 operator 修正設定的訊號；錯誤只在明確寫錯型別時出現，`null` 被視為清除而不 warning。
- [usage fetch 例外改成繼續 render，而非整個 hook 回 None] → 停用且沒有 model 行時 lines 為空仍回 `None`，停用路徑的外部行為不變；由「停用時輸出不變」的測試守住。
- [model 名稱原樣輸出，若 Hermes 傳入含換行的字串會打亂 footer] → Hermes 的 `agent.model` 是設定裡的 model ID，不含換行；`strip()` 處理首尾空白，不另做內部字元過濾。

## Migration Plan

純新增、預設關閉，不需遷移。升級後 operator 執行 `hermes config set plugins.entries.hermes-usage-hook.footer.show_model true` 即可啟用；要關閉就設回 `false` 或 `null`。回滾只需重裝前一版 plugin，殘留的 `footer` 設定會被舊版忽略。
