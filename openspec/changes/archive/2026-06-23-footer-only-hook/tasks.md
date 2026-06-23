## 1. 移除非 footer hook

- [x] 1.1 [P] 刪除 hooks/plugin_hook.py（含其 `_notify` / `_notify_macos` / `_notify_webhook` 通知實作）以滿足 "Distribute only the footer hook"；驗證：`hooks/plugin_hook.py` 不存在，且 `codex_usage.py` 與 `hooks/footer_hook.py` 內無對 plugin_hook 的 import
- [x] 1.2 [P] 刪除 hooks/gateway/handler.py 與 hooks/gateway/HOOK.yaml 並移除空的 hooks/gateway/ 目錄，滿足 "Distribute only the footer hook"；驗證：兩檔與 `hooks/gateway/` 目錄皆不存在

## 2. 文件精簡

- [x] 2.1 更新 README.md 使其只描述 footer hook 為唯一部署路徑，移除「固定目的地通知（plugin/gateway）」與 gateway hook 部署章節、`CODEX_USAGE_NOTIFIER` 設定表與 webhook 範例，並把 Files 表與 Hermes hook reference 精簡為 footer-only，滿足 "Documentation describes only the footer hook path"；驗證：README.md 內 grep 不到 `CODEX_USAGE_NOTIFIER`、`on_session_end` 固定目的地通知、gateway `agent:end` 部署等殘留字串
