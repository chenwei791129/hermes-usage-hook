# footer-hook-deployment Specification

## Purpose

Define what the repository ships and documents for deploying Hermes usage reporting: a single footer hook on `transform_llm_output` backed by the shared usage module, with documentation describing that footer hook as the sole deployment path.

## Requirements

### Requirement: Distribute only the supported usage hooks

The repository SHALL ship exactly two Hermes hooks: the footer hook implemented as a plugin hook on `transform_llm_output`, and the Codex auto-reset preflight hook on `pre_llm_call`. The repository SHALL NOT include the fixed-destination notification plugin hook (`on_session_end`), the gateway hook (`agent:end`), background polling, or any unrelated hook. Both hooks SHALL resolve their modules from the installed `plugin/` directory. The shared usage module SHALL remain available for the footer hook to import, and the provider implementations it dispatches to SHALL live in the `plugin/providers/` Python package within the plugin root rather than as top-level modules in the repository root.

#### Scenario: Supported hooks and shared module are present

- **WHEN** the repository is inspected after this change
- **THEN** `plugin/hooks/footer_hook.py`, `plugin/usage.py`, `plugin/autoreset.py`, and `plugin/providers/codex_usage.py` exist, and the plugin registers handlers for `transform_llm_output` and `pre_llm_call`

#### Scenario: Provider implementations are consolidated under the providers package

- **WHEN** the repository is inspected after this change
- **THEN** `plugin/providers/__init__.py`, `plugin/providers/codex_usage.py`, and `plugin/providers/minimax_usage.py` exist, and the root-level `usage.py`, `providers/`, and `hooks/` do not exist

#### Scenario: Fixed-destination and gateway hooks are removed

- **WHEN** the repository is inspected after this change
- **THEN** `hooks/plugin_hook.py`, `hooks/gateway/handler.py`, and `hooks/gateway/HOOK.yaml` do not exist, and the `hooks/gateway/` directory is absent

#### Scenario: Auto reset is disabled

- **WHEN** effective `auto_reset.enabled` resolves to false from env, plugin config, and defaults
- **THEN** the `pre_llm_call` hook returns without network activity or prompt context, and the footer hook continues to operate normally

---
### Requirement: Documentation describes footer and opt-in auto-reset behavior

The `README.md` SHALL document the footer hook as the sole deployment path, deployed as a Hermes plugin directory. The install instructions SHALL direct the reader to install the `plugin/` subdirectory (not the whole repository) to `~/.hermes/plugins/hermes-usage-hook/` and to enable it by adding `hermes-usage-hook` to `plugins.enabled` in `~/.hermes/config.yaml` (or the equivalent `hermes plugins enable` command). The `README.md` SHALL NOT instruct copying the hook as a single standalone `.py` file, SHALL NOT instruct copying the whole repository, SHALL NOT claim that no configuration is needed, and SHALL NOT contain the fixed-destination notification deployment section, the gateway hook deployment section, the `CODEX_USAGE_NOTIFIER` configuration table, or the webhook configuration example.

Describing a whole-repository install as a failure mode to avoid SHALL NOT count as instructing it. Text stating that omitting the plugin subdirectory from a dashboard install identifier copies the whole repository (`tests/`, `openspec/`, `pyproject.toml`, and git metadata) into the user's plugins directory SHALL satisfy this requirement as long as that outcome is presented as a warning and never as an install step.

Auto-reset documentation SHALL be split by audience across three files, and no single file SHALL be required to carry all of it:

- `README.md` SHALL point the reader to `plugin/after-install.md` for setup notes and SHALL state that Codex auto reset is optional. It SHALL NOT be required to carry the auto-reset configuration reference.
- `plugin/after-install.md` SHALL carry the operator-facing decision content. Its required contents are specified by the post-install notice requirement and SHALL NOT be restated here.
- `AGENTS.md` SHALL carry the development and operational detail: the `CODEX_ENABLE_AUTORESET` and `CODEX_AUTORESET_THRESHOLD` override names, the env then plugin config then defaults precedence, the explicit `1..99` threshold range with weekly-remaining semantics, that explicitly configuring threshold 0 fails closed and emits a warning directing operators to `/usage reset` for an already-frozen credential, that the plugin reads its own `auto_reset` schema from the same plugin entry through the host `load_config()` on every hook call, that OAuth credentials do not belong in plugin config, earliest-expiry idempotent credit selection, the notices queue file and the lock protecting it, the single coordinator-locked atomic write that persists a terminal transition, the five-minute post-success suppression window, and the rendered audit footer line.

The documentation SHALL NOT place runtime values in `plugin.yaml` and SHALL NOT instruct users to store OAuth tokens in plugin settings.

#### Scenario: README documents directory install and plugin enablement

- **WHEN** `README.md` is read after this change
- **THEN** it instructs installing the `plugin/` subdirectory as a directory under `~/.hermes/plugins/` and enabling it via `plugins.enabled` in `~/.hermes/config.yaml`, and it contains no single-file copy step, no whole-repository copy step, and no claim that no configuration is needed

#### Scenario: README contains only footer deployment guidance

- **WHEN** `README.md` is read after this change
- **THEN** it describes deploying the footer hook and contains no references to `CODEX_USAGE_NOTIFIER`, the `on_session_end` fixed-destination notifier, or the gateway `agent:end` hook deployment

#### Scenario: Whole-repository install appears only as a warning

- **WHEN** the dashboard install section of `README.md` is read after this change
- **THEN** every mention of installing the whole repository is framed as an outcome to avoid, and no install step directs the reader to use an identifier without the plugin subdirectory

#### Scenario: README delegates auto-reset setup to the post-install notice

- **WHEN** `README.md` is read after this change
- **THEN** it links to `plugin/after-install.md` and states that Codex auto reset is optional, and it is not required to contain the auto-reset config keys, override names, or threshold range

#### Scenario: AGENTS.md documents the auto-reset configuration and operational contract

- **WHEN** `AGENTS.md` is read after this change
- **THEN** it names both environment override variables, states the env then plugin config then defaults precedence, states the explicit `1..99` range with weekly-remaining semantics, states that explicit zero fails closed and directs an operator to `/usage reset`, states that the plugin reads its own config through the host `load_config()`, states that OAuth credentials do not belong in plugin config, describes earliest-expiry idempotent credit selection, names the notices queue file and its lock, describes the single coordinator-locked atomic write and the five-minute suppression window, and shows the audit footer line


---
### Requirement: Package the plugin under a dedicated subdirectory

The repository SHALL gather every file required by the Hermes plugin under a dedicated `plugin/` subdirectory — this subdirectory is the "plugin root". Files that are not part of the plugin (such as `openspec/`, `tests/`, `.git/`, `.claude/`, and `README.md`) SHALL remain outside `plugin/`, so that installing the plugin copies only plugin content and not the whole repository.

The plugin root SHALL also contain `plugin/after-install.md`, the post-install notice that the `hermes plugins install` CLI command renders after a successful install.

#### Scenario: Plugin files are gathered under `plugin/`

- **WHEN** the repository is inspected after this change
- **THEN** `plugin/plugin.yaml`, `plugin/__init__.py`, `plugin/usage.py`, `plugin/providers/__init__.py`, `plugin/hooks/__init__.py`, `plugin/hooks/footer_hook.py`, and `plugin/after-install.md` all exist
- **AND** `plugin/` contains no `tests/`, `openspec/`, `.git/`, `.claude/`, or `README.md`

---
### Requirement: Ship a Hermes plugin manifest

The repository SHALL include a `plugin.yaml` manifest at the plugin root (`plugin/plugin.yaml`) that declares the plugin name `hermes-usage-hook`, `kind: standalone`, and a `provides_hooks` list containing exactly `transform_llm_output` and `pre_llm_call`, so that Hermes discovery recognizes the directory as a loadable plugin. The manifest SHALL also declare `version`, `description`, and `author`. The manifest SHALL NOT declare `requires_env` and SHALL NOT carry any auto-reset runtime value; auto-reset settings are read from the host plugin config at call time.

#### Scenario: Manifest declares the plugin and both hooks

- **WHEN** `plugin/plugin.yaml` is parsed after this change
- **THEN** it parses as valid YAML, its `name` is `hermes-usage-hook`, its `kind` is `standalone`, and its `provides_hooks` list contains `transform_llm_output` and `pre_llm_call` exactly once each

#### Scenario: Manifest carries no runtime configuration

- **WHEN** `plugin/plugin.yaml` is parsed after this change
- **THEN** it declares no `requires_env` key and no `auto_reset` key

---
### Requirement: Expose a register entry point from the plugin root

The repository SHALL expose a callable `register(ctx)` from the plugin root package (`plugin/__init__.py`) that registers at least the footer handler on `transform_llm_output` and the Codex auto-reset preflight handler on `pre_llm_call`. Registering further host integrations from the same entry point SHALL be permitted. Registration SHALL NOT perform network access or filesystem mutation; the runtime handlers enforce configuration and safety policy. The footer hook SHALL resolve its `usage` and `providers` modules from the plugin root (`plugin/`) rather than from a separate `~/.hermes/lib` location, so the plugin loads from a single installed directory.

#### Scenario: Plugin root exposes register

- **WHEN** the plugin root package (`plugin/`) is imported after this change
- **THEN** importing it yields a callable `register`, and the import succeeds without `usage` or `providers` being on an external `~/.hermes/lib` path

#### Scenario: Register wires both hook handlers

- **WHEN** a fake plugin context records registration calls
- **THEN** one handler is registered for `transform_llm_output`, one handler is registered for `pre_llm_call`, and registration itself performs no usage or consume request

#### Scenario: Shared modules resolve from the plugin directory

- **WHEN** the plugin root (`plugin/`) is inspected after this change
- **THEN** `plugin.yaml`, `__init__.py`, `usage.py`, `autoreset.py`, `providers/__init__.py`, and `hooks/footer_hook.py` all reside in the plugin root, and `hooks/footer_hook.py` no longer inserts `~/.hermes/lib` into `sys.path`

---
### Requirement: Provide a one-command installer

The repository SHALL include an `install.py` script at the repository root, runnable as `uv run install.py`, that exposes an argparse command-line interface with two modes: an `install` mode (the default when no subcommand is given) and a `remove` mode. The script SHALL declare only `pyyaml` as its PEP 723 runtime dependency and SHALL perform all release download, parsing, and extraction using the Python standard library (`urllib.request`, `json`, `tarfile`) without adding an `httpx` dependency.

In `install` mode, the default source SHALL be the project's GitHub release: the script SHALL resolve the latest release of the source repository, download that release's source tarball, extract it, locate the `plugin/` directory inside the extracted tree, and install that directory. When `--local` is given, the script SHALL instead install from a local directory (the `plugin/` directory next to the script when no path is supplied, or the supplied path). In either case it SHALL copy the resolved plugin directory to `$HERMES_HOME/plugins/hermes-usage-hook/` and, unless `--no-enable` is given, SHALL add `hermes-usage-hook` to the `plugins.enabled` list in `$HERMES_HOME/config.yaml`, creating that config file when it does not exist.

The script SHALL be idempotent: re-running `install` SHALL overwrite the installed directory and SHALL NOT create a duplicate `plugins.enabled` entry, and it SHALL preserve any other existing keys and values in `config.yaml`, though it re-serializes the file so comments and original formatting are not retained. It SHALL write `config.yaml` atomically so an interrupted run cannot truncate an existing file. When a release source operation fails (release resolution, HTTP error, download interruption, or no `plugin/` directory found in the tarball), the script SHALL exit non-zero with a readable error that points the user to `--local`.

#### Scenario: Local install copies the plugin and enables it

- **WHEN** `uv run install.py --local` is run against a clean `$HERMES_HOME`
- **THEN** `$HERMES_HOME/plugins/hermes-usage-hook/plugin.yaml` exists, and `$HERMES_HOME/config.yaml` parses as YAML with `hermes-usage-hook` present in its `plugins.enabled` list

#### Scenario: Default install fetches the latest release

- **WHEN** `uv run install.py` is run with no subcommand and no `--local`
- **THEN** the script resolves the latest GitHub release of the source repository, downloads and extracts its source tarball, and installs the `plugin/` directory found inside it to `$HERMES_HOME/plugins/hermes-usage-hook/`

#### Scenario: Re-running the installer is idempotent

- **WHEN** `uv run install.py --local` is run a second time against the same `$HERMES_HOME`
- **THEN** `plugins.enabled` contains `hermes-usage-hook` exactly once, and keys and values that existed in `config.yaml` before the second run are still present

#### Scenario: Release source failure points to local install

- **WHEN** the release cannot be resolved or downloaded during a default `install`
- **THEN** the script exits non-zero with an error message that mentions using `--local` to install from a local directory

---
### Requirement: Install a specific release version

In `install` mode, the script SHALL accept `--version TAG` to install a specific GitHub release instead of the latest. When `--version` is given, the script SHALL resolve the release for that tag (matching the tag with and without a leading `v`), download its source tarball, and install the `plugin/` directory from it. The `--version` and `--local` options SHALL be mutually exclusive; supplying both SHALL cause the script to exit non-zero without installing anything.

#### Scenario: Pin a specific release

- **WHEN** `uv run install.py --version 0.2.0` is run
- **THEN** the script resolves the release tagged `0.2.0` (or `v0.2.0`), downloads its source tarball, and installs the `plugin/` directory from that release

#### Scenario: Version and local are mutually exclusive

- **WHEN** `uv run install.py --local --version 0.2.0` is run
- **THEN** the script exits non-zero with an error and does not install anything

---
### Requirement: Run standalone from a remote URL

The script SHALL be runnable directly from its raw source URL without a prior clone, e.g. `uv run https://raw.githubusercontent.com/chenwei791129/hermes-usage-hook/main/install.py [args]`. To support this, in every mode that does not pass `--local` (default release install, `--version` install, and `remove`), the script SHALL NOT read, import, or otherwise depend on any file located adjacent to the script itself — in particular it SHALL NOT read a `plugin/` directory or `plugin.yaml` next to the script to determine the plugin name, source, or installed version. The installed plugin name SHALL be the fixed identifier `hermes-usage-hook` (used for the install destination, the `plugins.enabled` entry, and the remove target), the install source SHALL come from the GitHub release tarball, and the version-guard comparison in `remove` SHALL read the `plugin.yaml` inside the already-installed `$HERMES_HOME/plugins/hermes-usage-hook/` directory — never a file beside the script. Only `--local` mode SHALL touch files beside the script, and then only its default `plugin/` path; a remote invocation that uses `--local` SHALL therefore require an explicit existing `PATH`.

#### Scenario: Remote default install needs no adjacent files

- **WHEN** the script is run from its raw URL via `uv run <raw-url>` with no subcommand and no `--local`, in a working directory that contains no `plugin/` directory
- **THEN** it installs the plugin to `$HERMES_HOME/plugins/hermes-usage-hook/` from the latest GitHub release without error, reading no file adjacent to the downloaded script

#### Scenario: Remote remove needs no adjacent files

- **WHEN** `uv run <raw-url> remove` is run from the raw URL in a directory with no `plugin/` directory, with the plugin already installed under `$HERMES_HOME`
- **THEN** it removes the installed directory and `plugins.enabled` entry, reading the installed `$HERMES_HOME/plugins/hermes-usage-hook/plugin.yaml` (not any file beside the script) for any `--version` guard

---
### Requirement: Remove the installed plugin

The script SHALL provide a `remove` mode, invoked as `uv run install.py remove`, that deletes the installed plugin directory at `$HERMES_HOME/plugins/hermes-usage-hook/` and, unless `--no-enable` is given, removes `hermes-usage-hook` from the `plugins.enabled` list in `$HERMES_HOME/config.yaml` while preserving all other keys and values and writing the file atomically. Both actions SHALL be idempotent: a missing directory or an entry already absent from `plugins.enabled` SHALL be treated as success, not an error.

When `--version TAG` is supplied to `remove`, the script SHALL act as a version guard: it SHALL read the `version` field from the installed `plugin/plugin.yaml`, remove the plugin only when that version equals the requested tag, and otherwise exit non-zero without deleting anything, reporting both the installed and requested versions. When `--version` is supplied but no installed plugin directory exists, the script SHALL exit non-zero without deleting anything.

#### Scenario: Remove deletes the directory and disables the plugin

- **WHEN** `uv run install.py remove` is run with the plugin installed and enabled
- **THEN** `$HERMES_HOME/plugins/hermes-usage-hook/` no longer exists and `hermes-usage-hook` is no longer present in `plugins.enabled`, while other keys in `config.yaml` are preserved

#### Scenario: Remove is idempotent

- **WHEN** `uv run install.py remove` is run when the plugin is not installed
- **THEN** the script exits zero and makes no changes

#### Scenario: Version guard blocks a mismatched remove

- **WHEN** `uv run install.py remove --version 9.9.9` is run while the installed `plugin/plugin.yaml` declares `version: 0.2.0`
- **THEN** the script exits non-zero, reports the installed version `0.2.0` and the requested version `9.9.9`, and deletes nothing

#### Scenario: Version guard allows a matching remove

- **WHEN** `uv run install.py remove --version 0.2.0` is run while the installed `plugin/plugin.yaml` declares `version: 0.2.0`
- **THEN** the plugin directory is deleted and `hermes-usage-hook` is removed from `plugins.enabled`

---
### Requirement: Installer command-line flags

The script SHALL accept the following flags in both `install` and `remove` modes: `--hermes-home PATH` to override the Hermes home directory, taking precedence over the `HERMES_HOME` environment variable and falling back to `~/.hermes` when neither is set; `--no-enable` to skip all modifications to `config.yaml`; `--dry-run` to print the actions that would be taken without downloading, writing, or deleting any files; and `-v`/`--verbose` to emit diagnostic detail such as the resolved release tag, tarball URL, and extraction path. The script SHALL additionally accept `--repo OWNER/NAME` in `install` mode only (defaulting to `chenwei791129/hermes-usage-hook`) to override the source repository; `remove` operates solely on the local installation and SHALL NOT accept `--repo`.

#### Scenario: Dry run makes no changes

- **WHEN** `uv run install.py --local --dry-run` is run
- **THEN** the script prints the planned source, destination, and config changes, and neither the plugin directory nor `config.yaml` is created or modified

#### Scenario: No-enable skips config changes

- **WHEN** `uv run install.py --local --no-enable` is run against a clean `$HERMES_HOME`
- **THEN** `$HERMES_HOME/plugins/hermes-usage-hook/` is installed but `$HERMES_HOME/config.yaml` is not created or modified

#### Scenario: Hermes home override takes precedence

- **WHEN** `uv run install.py --local --hermes-home /custom/home` is run with `HERMES_HOME` set to a different path
- **THEN** the plugin is installed under `/custom/home/plugins/hermes-usage-hook/`

---
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

---
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
