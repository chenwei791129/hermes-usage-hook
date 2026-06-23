## Summary

將本 repo 精簡為只交付 footer hook，移除固定目的地通知（`on_session_end` plugin hook）與 gateway hook 及其相關設定與文件。

## Motivation

repo 目前同時提供三種交付方式：footer hook（`transform_llm_output`，推薦）、固定目的地通知 plugin hook（`on_session_end`）、gateway hook（`agent:end`）。實務上只使用 footer hook —— 它隨回覆自動路由回使用者所在平台、免 bot token、免 per-platform 程式碼。另外兩種增加維護面積、文件複雜度與 `CODEX_USAGE_NOTIFIER`/webhook/macOS 等設定分支，卻無人使用。移除可讓 repo 聚焦單一推薦路徑。

## Proposed Solution

- 刪除 `hooks/plugin_hook.py`（含其 `_notify` / `_notify_macos` / `_notify_webhook` 通知實作）。
- 刪除 `hooks/gateway/handler.py` 與 `hooks/gateway/HOOK.yaml`，並移除空的 `hooks/gateway/` 目錄。
- 更新 `README.md`：移除「固定目的地通知（plugin/gateway）」部署章節、gateway hook 部署章節、`CODEX_USAGE_NOTIFIER` 設定表與 webhook 範例；將 Files 表與 Hermes hook reference 精簡為 footer-only；保留 footer hook 部署與 quick check 段落。
- 結果：repo 僅交付 `codex_usage.py`（共用模組）與 `hooks/footer_hook.py`（唯一 hook）。

## Non-Goals

- 不更動 footer hook 的行為與既有 provider 偵測邏輯（屬 parked 的 `multi-provider-usage`）。
- 不刪除或更動 `codex_usage.py`。
- 不調整 `hooks/footer_hook.py` 的內容（除非為移除對已刪檔的引用，本 change 中 footer_hook 並未引用那些檔，故不動）。

## Alternatives Considered

- 保留另外兩種 hook 但標示為 deprecated —— 否決，仍需維護且文件依舊複雜，與「聚焦單一路徑」目標相違。
- 把 footer hook 上移至 repo 根目錄 —— 否決，屬非必要的結構調整，超出本次清理範圍。

## Impact

- 與 parked change `multi-provider-usage` 重疊：後者 task 4.2 會修改 `hooks/plugin_hook.py` 與 `hooks/gateway/handler.py` 的 import。處理方式為兩 change 各自獨立：**建議先 apply `multi-provider-usage`、再 apply 本 change**；本 change 取代並使其 task 4.2 失效（檔案已刪）。不修改 parked change。
- Affected specs: 新增 `footer-hook-deployment`
- Affected code:
  - Removed:
    - hooks/plugin_hook.py
    - hooks/gateway/handler.py
    - hooks/gateway/HOOK.yaml
  - Modified:
    - README.md
  - New: (none)
