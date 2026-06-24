## 1. Rename in-repo identifier strings

- [x] [P] 1.1 Change the footer hook's stderr failure log prefix from `[codex-usage-hook]` to `[hermes-usage-hook]` in hooks/footer_hook.py (the `print(... file=sys.stderr)` in `append_usage_footer`), and add a test in tests/test_usage.py asserting that when the usage fetch raises, `append_usage_footer` logs a message prefixed `[hermes-usage-hook]` to stderr and returns the reply text unchanged. Verifies the provider-detection requirement "Render a provider-labeled usage summary" (its "Failure never breaks the reply" scenario). Note for the implementer: tests/test_usage.py currently imports only the flat modules (codex_usage, minimax_usage, usage) and has no footer-hook scaffolding, so the new test must import `append_usage_footer` from the hooks package (add the hooks dir to the import path) and capture stderr with pytest's `capsys`/`capfd`; monkeypatch `get_usage_for_model` to raise so the except branch runs. Verification: `uv run --with pytest --with httpx python -m pytest tests/test_usage.py -q` passes and the new test fails before the prefix change.
- [x] [P] 1.2 Change the outbound `User-Agent` request header value from `"hermes-codex-usage-hook"` to `"hermes-usage-hook"` in both codex_usage.py and minimax_usage.py (the `_call_usage` request headers in each). Verification: grep finds no `hermes-codex-usage-hook` in either module and both contain `"hermes-usage-hook"`.

## 2. Documentation

- [x] [P] 2.1 Update README.md to the new project name: the H1 title `hermes-codex-usage-hook` → `hermes-usage-hook`; the `git clone` URL and the `cd` directory in the deploy section; the deployed footer plugin filename in the `cp` command from `codex_usage_footer.py` to `usage_footer.py`; and the Troubleshooting reference to the stderr log prefix `[codex-usage-hook]` → `[hermes-usage-hook]`. Verification: grep finds no `hermes-codex-usage-hook`, no `codex_usage_footer`, and no `[codex-usage-hook]` in README.md.

## 3. GitHub repository (gh CLI, external side effects)

- [x] 3.1 Rename the GitHub repository to hermes-usage-hook using the gh CLI run from inside the clone, which also rewrites the local `origin` remote URL. Verification: `git remote get-url origin` ends with `hermes-usage-hook.git` and `gh repo view --json name` reports `hermes-usage-hook`.
- [x] 3.2 Set the GitHub repository description via the gh CLI to: Hermes Agent footer hook: append your AI provider's rate-limit usage (Codex, MiniMax, …) under each reply. Verification: `gh repo view --json description` reports the new description.
