<!-- SPECTRA:START v1.0.2 -->

# Spectra Instructions

This project uses Spectra for Spec-Driven Development(SDD). Specs live in `openspec/specs/`, change proposals in `openspec/changes/`.

## Use `$spectra-*` skills when:

- A discussion needs structure before coding → `$spectra-discuss`
- User wants to plan, propose, or design a change → `$spectra-propose`
- Tasks are ready to implement → `$spectra-apply`
- There's an in-progress change to continue → `$spectra-ingest`
- User asks about specs or how something works → `$spectra-ask`
- Implementation is done → `$spectra-archive`
- Commit only files related to a specific change → `$spectra-commit`

## Workflow

discuss? → propose → apply ⇄ ingest → archive

- `discuss` is optional — skip if requirements are clear
- Requirements change mid-work? `ingest` → resume `apply`

## Parked Changes

Changes can be parked（暫存）— temporarily moved out of `openspec/changes/`. Parked changes won't appear in `spectra list` but can be found with `spectra list --parked`. To restore: `spectra unpark <name>`. The `$spectra-apply` and `$spectra-ingest` skills handle parked changes automatically.

<!-- SPECTRA:END -->

## 專案開發須知

行為的權威來源是 `openspec/specs/`。本節只是導覽：檔案職責、開發指令，以及散落在程式碼之外的封裝與部署知識。

### Repo layout

| 檔案 | 職責 |
| --- | --- |
| `plugin/plugin.yaml` | Hermes plugin manifest：宣告 plugin 名稱、`kind: standalone`，以及剛好兩個 hook（`transform_llm_output`、`pre_llm_call`）。 |
| `plugin/__init__.py` | Plugin 根進入點：把 plugin 目錄加進 `sys.path`，並 re-export footer hook 的 `register(ctx)`。 |
| `plugin/usage.py` | Provider 偵測與 dispatch：把回覆的 `model` 對到 provider、抓 normalized usage、render summary。 |
| `plugin/autoreset.py` | Codex auto-reset 的設定、門檻政策、最早到期 credit 選擇、state、lock、cooldown、冪等性與一次性 notice。 |
| `plugin/autoreset_audit.py` | Best-effort 永久 reset 歷史：建構隱私最小化的扁平 event、append（以 hash 過的 event ID 去重）、寬鬆讀回。 |
| `plugin/hermes_home.py` | 用 `hermes_constants.get_hermes_home()` 做 profile-safe 的 Hermes home 解析；該模組不存在時退回 `HERMES_HOME`。 |
| `plugin/providers/codex_usage.py` | 唯讀讀取 `auth.json`、抓取並正規化 Codex usage、列出 reset credits、POST 一次冪等的 reset-credit 消耗嘗試。 |
| `plugin/providers/minimax_usage.py` | 解析 MiniMax API token、抓取並正規化 MiniMax usage。 |
| `plugin/hooks/footer_hook.py` | Hermes hook 模組：註冊 footer 與 Codex preflight hook、`/usagehook` history 指令、附加 usage、render auto-reset audit notice。 |
| `plugin/after-install.md` | 安裝後說明面板，只有 Hermes 自己的 `hermes plugins install` 會 render。`install.py` 與 dashboard 都不會顯示。 |

### 開發指令

repo root 的 `pyproject.toml` 是開發用的，**不會被 ship**（`install.py` 只複製 `plugin/`）。它把 runtime 依賴 pin 在 Hermes 提供的版本（`httpx==0.28.1`、`pyyaml==6.0.3`），所以本地檢查跑的版本跟 plugin 載入時看到的一致。

```bash
uv sync            # 建立 .venv：pinned runtime deps + dev tools
uv run pytest      # 跑 tests/
uv run ruff check .
uv run ty check
```

Standalone 確認現有登入抓得到用量（需要先 `codex login`，這樣才有 `~/.codex/auth.json`）：

```bash
uv run plugin/providers/codex_usage.py
```

會印出 normalized JSON 加上 render 後的 summary。

### 架構

**兩個 hook。** `plugin.yaml` 只宣告這兩個；不要在 manifest 裡加 auto-reset 的值或 `requires_env`。

- `pre_llm_call` — 在打 provider 之前檢查，讓已耗盡的 weekly window 能在 model call 前先 reset。auto reset 關閉時它不打任何 usage / credit API，也不注入 model context，footer 照常運作。
- `transform_llm_output` — 回覆成功後檢查、reset 後重新抓 usage、附上 footer 與一次性 audit 行。

**Provider dispatch** 在 `usage.py`。每個 fetch 都包起來，失敗只會少掉 footer，不會弄壞回覆。

**憑證解析。** Codex 走 OAuth，hook 只**讀** access token，不 refresh、不寫回：先看 Hermes 的 `$HERMES_HOME/auth.json`（同時支援 `providers.openai-codex` 與 `credential_pool.openai-codex` 兩種 layout），standalone 則讀 Codex CLI 的 `~/.codex/auth.json`（或 `$CODEX_HOME/auth.json`）。查的是 Codex 工具在用的 ChatGPT 內部非公開 backend API，隨時可能變。Hermes 底下由 Hermes 保持 token 新鮮；token 過期就是 usage call 失敗、footer 被省略。Codex 的 5 小時視窗是**帳號層級**的 rolling quota，不是單一對話的用量，與 Codex CLI 顯示的數字相同。

MiniMax 是純 API key（沒有 OAuth）：`MINIMAX_API_KEY` 環境變數（空值視為未設）→ `$HERMES_HOME/.env` 裡的 `MINIMAX_API_KEY=<value>` 行（會剝掉外層引號；`HERMES_HOME` 未設時預設 `~/.hermes/.env`）。都拿不到就跳過 MiniMax。MiniMax 沒有 plan tier，所以 `| plan …` 段會省略。

**Codex auto reset。** 預設關閉。啟用 `plugins.entries.hermes-usage-hook.auto_reset.enabled` 等於明確授權 plugin 自主消耗 reset credit，而消耗是不可逆的。設定從 plugin entry 讀：

```yaml
plugins:
  entries:
    hermes-usage-hook:
      auto_reset:
        enabled: true
        threshold: 0
```

消耗一張 credit 會同時 reset 帳號的 5h 與 weekly 兩個視窗，但**資格判定只看 weekly**：5h 用完不會觸發 auto reset。`threshold` 是 weekly remaining 語意，只接受 `0..99`，資格判定為 `weekly remaining <= threshold`。`100` 故意不合法——剛 reset 完的 weekly 視窗 remaining 是 100%，會立刻再次符合條件。環境變數 `CODEX_ENABLE_AUTORESET`、`CODEX_AUTORESET_THRESHOLD` 供 process-managed 部署覆寫，優先序是 env → plugin config → 預設值。plugin config 每次 hook 呼叫都經 Hermes `load_config()` 重讀，所以改 `config.yaml` 不必重裝 plugin；改 process environment 要重啟 / reload Gateway。OAuth 憑證不屬於 plugin config。

Hermes 對 `plugins.entries.<plugin_id>` 的文件是 plugin LLM trust 設定（<https://hermes-agent.nousresearch.com/docs/developer-guide/plugin-llm-access#trust-gate>）。本 plugin 是從同一個 plugin entry 用 `load_config()` 讀自己的 `auto_reset.*` schema；Hermes 沒有為這些值提供通用的 plugin-config UI 或 schema。

State 在 `$HERMES_HOME/state/hermes-usage-hook/autoreset.json`，由 `autoreset.lock/` 保護；每次成功的終態轉換會在同一次 coordinator-locked 原子寫入裡存下一次性 audit notice、清掉 pending state、設好成功 cooldown。footer 另外會排空 `autoreset-notices.json` 佇列（由 `autoreset-notices.lock/` 保護），且不允許 notice 更新覆寫消耗的冪等性狀態。這些檔案只存非敏感的識別碼、cooldown 與 audit 值。

Credit 選擇是冪等的：挑最早到期的可用 credit、POST 前先存 redeem request ID、遇到不確定的 retry 就重用同一個 ID；null expiry 排最後。沒有 credit、nothing-to-reset、確定性失敗與未知回應都進短 cooldown，避免每次 hook 都 POST；transient GET 失敗用更短的 retry cooldown。成功的終態回應另外設五分鐘抑制窗，讓 backend 傳播期間的 stale usage 不會觸發第二次消耗。成功後 footer 會帶一行 audit：

```text
Codex auto reset | weekly 0% → 100% | reset credits 3 → 2
```

**Reset 歷史。** 每次成功 reset 會 append 一行到 `$HERMES_HOME/logs/hermes-usage-hook-autoreset.jsonl`。這個檔案永久保存，不 rotate、不 truncate、不清理（約 200 bytes 一筆，大致一週一筆）。Append 是 best-effort：失敗時 reset 結果、footer 與一次性 notice 都不受影響，只會留一行靜態 warning。每筆記錄做過隱私最小化，只有 hash 過的 event ID（redeem request ID 的 `sha256:<hex>`，絕不存原始 ID）、RFC 3339 UTC timestamp、backend status，以及 before/after 的 weekly 與 credit 快照；不寫入任何原始 request / credit / session / account 識別碼。任何聊天平台都能用 `/usagehook history [N]` 查（N 是 1–100，預設最新 5 筆）；快照缺值 render 成 `?`，還沒有歷史時回 `No Codex auto-reset history yet.`。

### 封裝與安裝路徑

Hermes 把 plugin 當**目錄**載入，目錄裡要有 `plugin.yaml`；`kind: standalone` 的第三方 plugin 不明確 enable 就一直停用。所以安裝是兩件事：裝目錄、然後 enable。所有 plugin 檔案都在 `plugin/` 底下，要裝的是這個子目錄，不是整個 repo（repo 還帶著 `tests/`、`openspec/`、`pyproject.toml` 與 git metadata）。

1. **`install.py`**（建議路徑，README 記的就是這條）。預設抓 latest release 的 source tarball，`--version` pin release tag、`--ref` 抓 branch/tag/commit tarball（繞過 Releases API，可安裝未發佈的變更）、`--local` 用本地 checkout（遠端呼叫時必須給一個存在的路徑）。這三個互斥。`remove --version TAG` 是 version guard：讀安裝好的 `plugin.yaml`，版本不符就非零離開、什麼都不刪。
2. **手動安裝**。先 `rm -rf ~/.hermes/plugins/hermes-usage-hook` 再 `cp -r plugin ~/.hermes/plugins/hermes-usage-hook`（開發時可改用 symlink）；先刪是為了讓重裝變成取代，而不是把 `plugin/` 疊進舊目錄裡。接著把名字加進 `plugins.enabled`，或跑 `hermes plugins enable hermes-usage-hook`。用 `hermes plugins` 確認列出來了（代表 manifest 被找到），然後重啟 Hermes。Codex home 非預設時 `CODEX_HOME` 會被尊重。
3. **Dashboard 的 Git 安裝**。三條裡最弱的一條：不能 pin 版本，而且產生的安裝永遠無法就地更新。identifier **必須帶 `/plugin` 子目錄**——`chenwei791129/hermes-usage-hook/plugin`（`https://github.com/chenwei791129/hermes-usage-hook/tree/main/plugin` 與 `https://github.com/chenwei791129/hermes-usage-hook.git#plugin` 等價；tree URL 的 branch 段會被忽略，一律 clone 預設分支）。省略子目錄會把**整個 repo** 複製進 plugins 目錄，而 dashboard 不會提示任何異常，因為 plugin 照樣載入：Hermes 把沒有 manifest 的安裝目錄當成 category namespace、往下掃一層找到嵌套的 `plugin/plugin.yaml`，再對上 dashboard 寫進 `plugins.enabled` 的名字。結果是 plugins 目錄裡躺著一整個 repo、plugin 註冊在嵌套的 key 底下、更新動作依然不可用（註冊到的目錄是嵌套的 `plugin/`，裡面沒有 `.git`）。遇到這種安裝要移除重裝。此路徑裝的是預設分支的最新 commit，且移動子目錄出 clone 之後安裝目錄裡沒有 `.git`，dashboard 的更新動作不可用——要更新只能移除再裝一次。Dashboard 也不會 render `plugin/after-install.md`。

上述 dashboard 行為**觀察自 Hermes 0.19.0**。upstream 兩邊都在追：issue **65314**（子目錄安裝丟掉 `.git`，更新動作永久不可用）、PR **65337**（記錄 install-source metadata，讓更新不再需要就地 `.git`；並自動偵測 repo 中同時含 `plugin.yaml` 與 `__init__.py` 的單一子目錄——本 repo 的 `plugin/` 符合）。65337 一旦合併，上面「整個 repo」的警告與「更新動作不可用」的敘述就過時了，屆時要回來重寫這段。

**Streaming caveat**：如果部署是 streaming responses，reply body 在這個 hook 跑之前就已經送出，footer 可能不會被加上。

### Troubleshooting

- **找不到 `auth.json`** — 跑 `codex login`，讓 Codex CLI 建出來。
- **401/403** — Codex usage endpoint 要 ChatGPT **OAuth** 憑證，只有 API key 的 `auth.json` 會被拒；用 ChatGPT 帳號登入（`codex login`）。hook 不 refresh token：Hermes 底下由 Hermes 保持新鮮，standalone 過期就重跑 `codex login`。
- **什麼都沒發生** — 確認 `hermes plugins` 列出 `hermes-usage-hook`（目錄裝好且 manifest 被找到），且它在 `~/.hermes/config.yaml` 的 `plugins.enabled` 裡，然後重啟 Hermes。hook 的錯誤會印到 stderr，前綴 `[hermes-usage-hook]`。
- **auto reset 從來不跑** — 確認 `plugins.entries.hermes-usage-hook.auto_reset.enabled` 是 true，或 Gateway process environment 有 `CODEX_ENABLE_AUTORESET=true`。`plugins.enabled` 與 plugin 自己的 `auto_reset.*` 是兩回事。
- **auto reset 失敗後在等** — cooldown 是刻意的，用來避免 no-credit、nothing-to-reset、transient 或 ambiguous 回應之後反覆嘗試消耗。
