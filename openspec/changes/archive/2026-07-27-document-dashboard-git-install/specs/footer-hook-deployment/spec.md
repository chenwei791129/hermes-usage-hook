## MODIFIED Requirements

### Requirement: Documentation describes only the footer hook path

The `README.md` SHALL document the footer hook as the sole deployment path, deployed as a Hermes plugin directory. The install instructions SHALL direct the reader to install the `plugin/` subdirectory (not the whole repository) to `~/.hermes/plugins/hermes-usage-hook/` and to enable it by adding `hermes-usage-hook` to `plugins.enabled` in `~/.hermes/config.yaml` (or the equivalent `hermes plugins enable` command). The `README.md` SHALL NOT instruct copying the hook as a single standalone `.py` file, SHALL NOT instruct copying the whole repository, SHALL NOT claim that no configuration is needed, and SHALL NOT contain the fixed-destination notification deployment section, the gateway hook deployment section, the `CODEX_USAGE_NOTIFIER` configuration table, or the webhook configuration example.

Describing a whole-repository install as a failure mode to avoid SHALL NOT count as instructing it. Text stating that omitting the plugin subdirectory from a dashboard install identifier copies the whole repository (`tests/`, `openspec/`, `pyproject.toml`, and git metadata) into the user's plugins directory SHALL satisfy this requirement as long as that outcome is presented as a warning and never as an install step.

#### Scenario: README documents directory install and plugin enablement

- **WHEN** `README.md` is read after this change
- **THEN** it instructs installing the `plugin/` subdirectory as a directory under `~/.hermes/plugins/` and enabling it via `plugins.enabled` in `~/.hermes/config.yaml`, and it contains no single-file copy step, no whole-repository copy step, and no claim that no configuration is needed

#### Scenario: README contains only footer deployment guidance

- **WHEN** `README.md` is read after this change
- **THEN** it describes deploying the footer hook and contains no references to `CODEX_USAGE_NOTIFIER`, the `on_session_end` fixed-destination notifier, or the gateway `agent:end` hook deployment

#### Scenario: Whole-repository install appears only as a warning

- **WHEN** the dashboard install section of `README.md` is read after this change
- **THEN** every mention of installing the whole repository is framed as an outcome to avoid, and no install step directs the reader to use an identifier without the plugin subdirectory

### Requirement: Package the plugin under a dedicated subdirectory

The repository SHALL gather every file required by the Hermes plugin under a dedicated `plugin/` subdirectory — this subdirectory is the "plugin root". Files that are not part of the plugin (such as `openspec/`, `tests/`, `.git/`, `.claude/`, and `README.md`) SHALL remain outside `plugin/`, so that installing the plugin copies only plugin content and not the whole repository.

The plugin root SHALL also contain `plugin/after-install.md`, the post-install notice that the `hermes plugins install` CLI command renders after a successful install.

#### Scenario: Plugin files are gathered under `plugin/`

- **WHEN** the repository is inspected after this change
- **THEN** `plugin/plugin.yaml`, `plugin/__init__.py`, `plugin/usage.py`, `plugin/providers/__init__.py`, `plugin/hooks/__init__.py`, `plugin/hooks/footer_hook.py`, and `plugin/after-install.md` all exist
- **AND** `plugin/` contains no `tests/`, `openspec/`, `.git/`, `.claude/`, or `README.md`

## ADDED Requirements

### Requirement: Document the dashboard Git install path

The `README.md` SHALL document installing the plugin through the Hermes dashboard's plugin-management Git install field, because that path clones a repository and moves an optional subdirectory into the user's plugins directory rather than running `install.py`.

The documented identifier SHALL name the `plugin/` subdirectory explicitly, in the shorthand form `<owner>/<repo>/plugin`. The section SHALL also record the equivalent accepted spellings: a GitHub tree URL ending in `/tree/<branch>/plugin`, and a clone URL with a `#plugin` fragment. Because the install always clones the default branch, the section SHALL state that the `<branch>` segment of a tree URL is ignored, so that spelling is equivalent only for the default branch.

The section SHALL warn that submitting an identifier without the plugin subdirectory copies the whole repository — `tests/`, `openspec/`, `pyproject.toml`, and git metadata — into the user's plugins directory. The warning SHALL state that the resulting install is still loaded (Hermes treats the manifest-less installed directory as a category namespace, finds the nested `plugin/plugin.yaml`, and matches the plugin name the dashboard wrote to `plugins.enabled`), so nothing in the dashboard flags the mistake, and that the plugin ends up registered under a nested key while the update action stays unavailable because the registered directory is the nested `plugin/`, which holds no `.git`.

The section SHALL record that this path installs the default branch's latest commit, in contrast to `install.py`, whose default install source is the latest GitHub release.

The section SHALL record that a subdirectory install leaves no `.git` directory in the installed plugin, so the dashboard's update action is unavailable for it, and that updating is done by removing the plugin and installing it again.

Because the dashboard does not render `plugin/after-install.md`, the section SHALL itself list the post-install steps a dashboard installer needs: that Codex usage requires ChatGPT OAuth credentials, that Codex auto reset is disabled by default and enabling it authorizes autonomous reset-credit use, and that a streaming deployment can send the reply before the footer is applied.

The section SHALL name the Hermes version its behavioral claims were observed against, and SHALL point at the upstream issue and pull request that would change those claims, so a reader can tell whether the section is still current. The upstream references SHALL be identified by number — issue 65314 for the discarded `.git` and unusable update action, and pull request 65337 for the source-metadata and subdirectory-autodetection fix — together with a statement that merging that pull request would make the whole-repository warning and the unavailable-update-action statement obsolete. Behavioral claims SHALL be written from observed behavior at the named version and SHALL NOT be copied from upstream descriptions, because the upstream issue's own table describes a whole-repository install as undiscoverable, which does not match the observed behavior at the named version.

#### Scenario: README documents the dashboard install identifier

- **WHEN** the dashboard install section of `README.md` is read after this change
- **THEN** it gives an install identifier whose last path segment is `plugin`, it lists the tree-URL and `#plugin`-fragment spellings as accepted alternatives, and it states that a tree URL's branch segment is ignored so that spelling selects the default branch rather than the named one

#### Scenario: README warns about the whole-repository identifier

- **WHEN** the dashboard install section of `README.md` is read after this change
- **THEN** it states that an identifier without the plugin subdirectory copies the whole repository into the plugins directory, that the plugin still loads from the nested `plugin/` directory under a nested registry key, that nothing in the dashboard flags the mistake, and that the update action remains unavailable for that install too

#### Scenario: README records the install source and update limitations

- **WHEN** the dashboard install section of `README.md` is read after this change
- **THEN** it states that the dashboard installs the default branch's latest commit rather than the latest release, that a subdirectory install leaves no `.git` directory, that the dashboard update action is therefore unavailable, and that updating means removing and reinstalling

#### Scenario: README dates its claims and points at the upstream fix

- **WHEN** the dashboard install section of `README.md` is read after this change
- **THEN** it names the Hermes version the behavior was observed against, references upstream issue 65314 and pull request 65337 by number, and states that merging that pull request would make the whole-repository warning and the unavailable-update-action statement obsolete

#### Scenario: README carries the post-install steps for dashboard installers

- **WHEN** the dashboard install section of `README.md` is read after this change
- **THEN** it lists the ChatGPT OAuth requirement for Codex usage, the disabled-by-default state of Codex auto reset together with the authorization meaning of enabling it, and the streaming caveat

### Requirement: Ship a post-install notice with the plugin

The repository SHALL include `plugin/after-install.md`, a Markdown file that the `hermes plugins install` CLI command renders after a successful install. Neither `install.py` nor the dashboard install path renders it — `install.py` only copies it along, and the dashboard strips the notice path from its install response — so the README dashboard section carries the same steps independently.

The file SHALL state how to confirm the plugin is enabled, that Codex usage reads ChatGPT OAuth credentials from the Hermes credential store or the Codex CLI auth store and never refreshes or writes them, that the MiniMax fetcher needs `MINIMAX_API_KEY` from the environment or the Hermes `.env` file, that Codex auto reset is disabled by default and that enabling `plugins.entries.hermes-usage-hook.auto_reset.enabled` is standing authorization for irreversible autonomous reset-credit use, that `/usagehook history` reports past auto resets, and that a streaming deployment can send the reply before the footer is applied.

The file SHALL NOT ask the reader to supply credentials as plugin config values, and SHALL NOT describe `auto_reset` as enabled by default.

#### Scenario: Post-install notice exists at the plugin root

- **WHEN** the repository is inspected after this change
- **THEN** `plugin/after-install.md` exists and is non-empty Markdown

#### Scenario: Post-install notice covers the required setup steps

- **WHEN** `plugin/after-install.md` is read after this change
- **THEN** it covers confirming enablement, the Codex ChatGPT OAuth credential requirement, the `MINIMAX_API_KEY` sources, the disabled-by-default state of Codex auto reset with the authorization meaning of enabling it, the `/usagehook history` command, and the streaming caveat

#### Scenario: Post-install notice keeps credentials out of plugin config

- **WHEN** `plugin/after-install.md` is read after this change
- **THEN** it contains no instruction to place OAuth credentials or API tokens under `plugins.entries.hermes-usage-hook`, and no statement that Codex auto reset is enabled by default

#### Scenario: Installing the plugin carries the notice along

- **WHEN** the plugin is installed by copying the `plugin/` directory, whether by `install.py` or by a dashboard subdirectory install
- **THEN** `after-install.md` is present in the installed plugin directory without any installer change
