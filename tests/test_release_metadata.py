import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
PROJECT_NAME = "hermes-codex-usage-hook"


def _toml_section(path: str, heading: str) -> str:
    text = (ROOT / path).read_text()
    match = re.search(
        rf"^\[{re.escape(heading)}\]\s*$\n(?P<body>.*?)(?=^\[|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"{path} must contain [{heading}]"
    return match.group("body")


def _workspace_package() -> str:
    lock_text = (ROOT / "uv.lock").read_text()
    packages = re.findall(
        r"^\[\[package\]\]\s*$\n(?P<body>.*?)(?=^\[\[package\]\]|\Z)",
        lock_text,
        re.MULTILINE | re.DOTALL,
    )
    workspace_packages = [
        package
        for package in packages
        if re.search(rf'^name\s*=\s*"{PROJECT_NAME}"\s*$', package, re.MULTILINE)
        and re.search(
            r'^source\s*=\s*\{\s*virtual\s*=\s*"\."\s*\}\s*$', package, re.MULTILINE
        )
    ]
    assert len(workspace_packages) == 1, (
        "uv.lock must contain exactly one virtual root workspace package entry"
    )
    return workspace_packages[0]


def test_release_config_targets_only_shipped_version() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text())
    release_manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
    package = config["packages"]["."]

    assert package["release-type"] == "simple", (
        "release-please package '.' must keep the simple release type"
    )
    assert package["extra-files"] == ["plugin/plugin.yaml"], (
        "release-please must target only the shipped plugin/plugin.yaml version"
    )

    # release-please rewrites a .yaml extra-file through its YAML updater, which
    # re-serializes the document and drops comments, so no anchor comment is
    # required (or kept) on the version line.
    manifest = yaml.safe_load((ROOT / "plugin/plugin.yaml").read_text())
    assert str(manifest["version"]) == release_manifest["."], (
        "plugin/plugin.yaml version must match .release-please-manifest.json"
    )


def test_development_project_uses_fixed_development_version() -> None:
    project = _toml_section("pyproject.toml", "project")

    assert re.search(r'^version\s*=\s*"0\.0\.0"\s*$', project, re.MULTILINE), (
        "pyproject.toml [project] version must remain the fixed development value 0.0.0"
    )
    assert "x-release-please-version" not in project, (
        "pyproject.toml development version must not carry a release-please anchor"
    )


def test_development_project_remains_non_package() -> None:
    uv_config = _toml_section("pyproject.toml", "tool.uv")

    assert re.search(r"^package\s*=\s*false\s*$", uv_config, re.MULTILINE), (
        "pyproject.toml [tool.uv] must keep package = false"
    )


def test_virtual_workspace_package_uses_fixed_development_version() -> None:
    workspace_package = _workspace_package()

    assert re.search(
        r'^version\s*=\s*"0\.0\.0"\s*$', workspace_package, re.MULTILINE
    ), (
        "uv.lock virtual workspace package version must remain the fixed development value 0.0.0"
    )
