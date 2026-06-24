## ADDED Requirements

### Requirement: Package the plugin under a dedicated subdirectory

The repository SHALL gather every file required by the Hermes plugin under a dedicated `plugin/` subdirectory — this subdirectory is the "plugin root". Files that are not part of the plugin (such as `openspec/`, `tests/`, `.git/`, `.claude/`, and `README.md`) SHALL remain outside `plugin/`, so that installing the plugin copies only plugin content and not the whole repository.

#### Scenario: Plugin files are gathered under `plugin/`

- **WHEN** the repository is inspected after this change
- **THEN** `plugin/plugin.yaml`, `plugin/__init__.py`, `plugin/usage.py`, `plugin/providers/__init__.py`, `plugin/hooks/__init__.py`, and `plugin/hooks/footer_hook.py` all exist
- **AND** `plugin/` contains no `tests/`, `openspec/`, `.git/`, `.claude/`, or `README.md`

### Requirement: Ship a Hermes plugin manifest

The repository SHALL include a `plugin.yaml` manifest at the plugin root (`plugin/plugin.yaml`) that declares the plugin name `hermes-usage-hook`, `kind: standalone`, and a `provides_hooks` list containing `transform_llm_output`, so that Hermes discovery recognizes the directory as a loadable plugin. The manifest SHALL also declare `version`, `description`, and `author`.

#### Scenario: Manifest declares the plugin and its hook

- **WHEN** `plugin/plugin.yaml` is parsed after this change
- **THEN** it parses as valid YAML, its `name` is `hermes-usage-hook`, its `kind` is `standalone`, and its `provides_hooks` list contains `transform_llm_output`

### Requirement: Expose a register entry point from the plugin root

The repository SHALL expose a callable `register(ctx)` from the plugin root package (`plugin/__init__.py`) that registers the footer hook on `transform_llm_output`. The footer hook SHALL resolve its `usage` and `providers` modules from the plugin root (`plugin/`) rather than from a separate `~/.hermes/lib` location, so the plugin loads from a single installed directory.

#### Scenario: Plugin root exposes register

- **WHEN** the plugin root package (`plugin/`) is imported after this change
- **THEN** importing it yields a callable `register`, and the import succeeds without `usage` or `providers` being on an external `~/.hermes/lib` path

#### Scenario: Shared modules resolve from the plugin directory

- **WHEN** the plugin root (`plugin/`) is inspected after this change
- **THEN** `plugin.yaml`, `__init__.py`, `usage.py`, `providers/__init__.py`, and `hooks/footer_hook.py` all reside in the plugin root, and `hooks/footer_hook.py` no longer inserts `~/.hermes/lib` into `sys.path`

### Requirement: Provide a one-command installer

The repository SHALL include an `install.py` script at the repository root that, when run as `uv run install.py`, installs the plugin in one command. It SHALL copy the `plugin/` directory to `$HERMES_HOME/plugins/hermes-usage-hook/` (defaulting `HERMES_HOME` to `~/.hermes`) and SHALL add `hermes-usage-hook` to the `plugins.enabled` list in `$HERMES_HOME/config.yaml`, creating that config file when it does not exist. The script SHALL be idempotent: re-running it SHALL overwrite the installed directory and SHALL NOT create a duplicate `plugins.enabled` entry, and it SHALL preserve any other existing keys and values in `config.yaml`, though it re-serializes the file so comments and original formatting are not retained. It SHALL write `config.yaml` atomically so an interrupted run cannot truncate an existing file.

#### Scenario: Installer copies the plugin and enables it

- **WHEN** `uv run install.py` is run against a clean `$HERMES_HOME`
- **THEN** `$HERMES_HOME/plugins/hermes-usage-hook/plugin.yaml` exists, and `$HERMES_HOME/config.yaml` parses as YAML with `hermes-usage-hook` present in its `plugins.enabled` list

#### Scenario: Re-running the installer is idempotent

- **WHEN** `uv run install.py` is run a second time against the same `$HERMES_HOME`
- **THEN** `plugins.enabled` contains `hermes-usage-hook` exactly once, and keys and values that existed in `config.yaml` before the second run are still present

## MODIFIED Requirements

### Requirement: Distribute only the footer hook

The repository SHALL ship exactly one Hermes hook: the footer hook implemented as a plugin hook on `transform_llm_output`. The repository SHALL NOT include the fixed-destination notification plugin hook (`on_session_end`) nor the gateway hook (`agent:end`). The shared usage module SHALL remain available for the footer hook to import, and the provider implementations it dispatches to SHALL live in the `plugin/providers/` Python package within the plugin root rather than as top-level modules in the repository root.

#### Scenario: Footer hook and shared module are present

- **WHEN** the repository is inspected after this change
- **THEN** `plugin/hooks/footer_hook.py`, `plugin/usage.py`, and `plugin/providers/codex_usage.py` exist

#### Scenario: Provider implementations are consolidated under the providers package

- **WHEN** the repository is inspected after this change
- **THEN** `plugin/providers/__init__.py`, `plugin/providers/codex_usage.py`, and `plugin/providers/minimax_usage.py` exist, and the root-level `usage.py`, `providers/`, and `hooks/` do not exist

#### Scenario: Fixed-destination and gateway hooks are removed

- **WHEN** the repository is inspected after this change
- **THEN** `hooks/plugin_hook.py`, `hooks/gateway/handler.py`, and `hooks/gateway/HOOK.yaml` do not exist, and the `hooks/gateway/` directory is absent

### Requirement: Documentation describes only the footer hook path

The `README.md` SHALL document the footer hook as the sole deployment path, deployed as a Hermes plugin directory. The install instructions SHALL direct the reader to install the `plugin/` subdirectory (not the whole repository) to `~/.hermes/plugins/hermes-usage-hook/` and to enable it by adding `hermes-usage-hook` to `plugins.enabled` in `~/.hermes/config.yaml` (or the equivalent `hermes plugins enable` command). The `README.md` SHALL NOT instruct copying the hook as a single standalone `.py` file, SHALL NOT instruct copying the whole repository, SHALL NOT claim that no configuration is needed, and SHALL NOT contain the fixed-destination notification deployment section, the gateway hook deployment section, the `CODEX_USAGE_NOTIFIER` configuration table, or the webhook configuration example.

#### Scenario: README documents directory install and plugin enablement

- **WHEN** `README.md` is read after this change
- **THEN** it instructs installing the `plugin/` subdirectory as a directory under `~/.hermes/plugins/` and enabling it via `plugins.enabled` in `~/.hermes/config.yaml`, and it contains no single-file copy step, no whole-repository copy step, and no claim that no configuration is needed

#### Scenario: README contains only footer deployment guidance

- **WHEN** `README.md` is read after this change
- **THEN** it describes deploying the footer hook and contains no references to `CODEX_USAGE_NOTIFIER`, the `on_session_end` fixed-destination notifier, or the gateway `agent:end` hook deployment
