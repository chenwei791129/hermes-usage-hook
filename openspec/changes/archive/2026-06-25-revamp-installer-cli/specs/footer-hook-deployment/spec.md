## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Install a specific release version

In `install` mode, the script SHALL accept `--version TAG` to install a specific GitHub release instead of the latest. When `--version` is given, the script SHALL resolve the release for that tag (matching the tag with and without a leading `v`), download its source tarball, and install the `plugin/` directory from it. The `--version` and `--local` options SHALL be mutually exclusive; supplying both SHALL cause the script to exit non-zero without installing anything.

#### Scenario: Pin a specific release

- **WHEN** `uv run install.py --version 0.2.0` is run
- **THEN** the script resolves the release tagged `0.2.0` (or `v0.2.0`), downloads its source tarball, and installs the `plugin/` directory from that release

#### Scenario: Version and local are mutually exclusive

- **WHEN** `uv run install.py --local --version 0.2.0` is run
- **THEN** the script exits non-zero with an error and does not install anything

### Requirement: Run standalone from a remote URL

The script SHALL be runnable directly from its raw source URL without a prior clone, e.g. `uv run https://raw.githubusercontent.com/chenwei791129/hermes-usage-hook/main/install.py [args]`. To support this, in every mode that does not pass `--local` (default release install, `--version` install, and `remove`), the script SHALL NOT read, import, or otherwise depend on any file located adjacent to the script itself — in particular it SHALL NOT read a `plugin/` directory or `plugin.yaml` next to the script to determine the plugin name, source, or installed version. The installed plugin name SHALL be the fixed identifier `hermes-usage-hook` (used for the install destination, the `plugins.enabled` entry, and the remove target), the install source SHALL come from the GitHub release tarball, and the version-guard comparison in `remove` SHALL read the `plugin.yaml` inside the already-installed `$HERMES_HOME/plugins/hermes-usage-hook/` directory — never a file beside the script. Only `--local` mode SHALL touch files beside the script, and then only its default `plugin/` path; a remote invocation that uses `--local` SHALL therefore require an explicit existing `PATH`.

#### Scenario: Remote default install needs no adjacent files

- **WHEN** the script is run from its raw URL via `uv run <raw-url>` with no subcommand and no `--local`, in a working directory that contains no `plugin/` directory
- **THEN** it installs the plugin to `$HERMES_HOME/plugins/hermes-usage-hook/` from the latest GitHub release without error, reading no file adjacent to the downloaded script

#### Scenario: Remote remove needs no adjacent files

- **WHEN** `uv run <raw-url> remove` is run from the raw URL in a directory with no `plugin/` directory, with the plugin already installed under `$HERMES_HOME`
- **THEN** it removes the installed directory and `plugins.enabled` entry, reading the installed `$HERMES_HOME/plugins/hermes-usage-hook/plugin.yaml` (not any file beside the script) for any `--version` guard

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
