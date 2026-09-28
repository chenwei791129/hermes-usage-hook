## MODIFIED Requirements

### Requirement: Ship a post-install notice with the plugin

The repository SHALL include `plugin/after-install.md`, a Markdown file that the `hermes plugins install` CLI command renders after a successful install. Neither `install.py` nor the dashboard install path renders it — `install.py` only copies it along, and the dashboard strips the notice path from its install response — so the README dashboard section carries the same steps independently.

The file SHALL state how to confirm the plugin is enabled, that Codex usage reads ChatGPT OAuth credentials from the Hermes credential store or the Codex CLI auth store and never refreshes or writes them, that the MiniMax fetcher needs `MINIMAX_API_KEY` from the environment or the Hermes `.env` file, that Codex auto reset is disabled by default and that enabling `plugins.entries.hermes-usage-hook.auto_reset.enabled` is standing authorization for irreversible autonomous reset-credit use, that `/usagehook history` reports past auto resets, that the footer model line is disabled by default and is enabled with `hermes config set plugins.entries.hermes-usage-hook.footer.show_model true`, and that a streaming deployment can send the reply before the footer is applied.

The file SHALL NOT ask the reader to supply credentials as plugin config values, and SHALL NOT describe `auto_reset` or `footer.show_model` as enabled by default.

#### Scenario: Post-install notice exists at the plugin root

- **WHEN** the repository is inspected after this change
- **THEN** `plugin/after-install.md` exists and is non-empty Markdown

#### Scenario: Post-install notice covers the required setup steps

- **WHEN** `plugin/after-install.md` is read after this change
- **THEN** it covers confirming enablement, the Codex ChatGPT OAuth credential requirement, the `MINIMAX_API_KEY` sources, the disabled-by-default state of Codex auto reset with the authorization meaning of enabling it, the `/usagehook history` command, the disabled-by-default `footer.show_model` option with its enabling command, and the streaming caveat

#### Scenario: Post-install notice keeps credentials out of plugin config

- **WHEN** `plugin/after-install.md` is read after this change
- **THEN** it contains no instruction to place OAuth credentials or API tokens under `plugins.entries.hermes-usage-hook`, and no statement that Codex auto reset or `footer.show_model` is enabled by default

#### Scenario: Installing the plugin carries the notice along

- **WHEN** the plugin is installed by copying the `plugin/` directory, whether by `install.py` or by a dashboard subdirectory install
- **THEN** `after-install.md` is present in the installed plugin directory without any installer change
