"""Tests for install.py: config enablement and plugin-directory copy.

These exercise our own installer logic (idempotency, preserving existing config
keys, overwrite-on-reinstall) — not pyyaml itself. install.py lives at the repo
root, so add the repo root to sys.path to import it.

Run the suite with pyyaml available (install.py imports it):

    uv run --with pytest --with httpx --with pyyaml python -m pytest tests -v
"""

from __future__ import annotations

import email.message
import io
import json
import os
import sys
import tarfile

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import install  # noqa: E402

# The installed plugin name is a fixed identifier — no longer read from a file
# beside the script — so non-local modes (default release install, --version,
# remove) work when the script runs standalone from its raw URL.
NAME = install.PLUGIN_NAME


def test_plugin_name_is_fixed_constant():
    assert install.PLUGIN_NAME == "hermes-usage-hook"


def test_shipped_manifest_name_matches_constant():
    # The installer now installs under the fixed PLUGIN_NAME constant instead of
    # reading the manifest. Guard against the shipped plugin/plugin.yaml drifting
    # from that constant (which would install the plugin under a mismatched name).
    manifest = yaml.safe_load((install.PLUGIN_SRC / "plugin.yaml").read_text())
    assert manifest["name"] == install.PLUGIN_NAME


# ---------------------------------------------------------------------------
# Release download / extraction helpers (shared by release & install tests)
# ---------------------------------------------------------------------------

_REPO = "myowner/myrepo"
# GitHub source tarballs wrap everything in a single <owner>-<repo>-<sha>/ dir.
_TOP = "myowner-myrepo-abc1234"


def _latest_url() -> str:
    return f"https://api.github.com/repos/{_REPO}/releases/latest"


def _tag_url(tag: str) -> str:
    return f"https://api.github.com/repos/{_REPO}/releases/tags/{tag}"


def _tarball_url(tag: str) -> str:
    return f"https://api.github.com/repos/{_REPO}/tarball/{tag}"


def _make_tarball(files: dict[str, str]) -> bytes:
    """Build an in-memory gzip tarball from ``{member_name: text_content}``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _plugin_tarball(version: str = "0.2.0") -> bytes:
    """A realistic source tarball containing a top-level dir wrapping plugin/."""
    return _make_tarball(
        {
            f"{_TOP}/README.md": "# hermes-usage-hook\n",
            f"{_TOP}/plugin/plugin.yaml": f"name: hermes-usage-hook\nversion: {version}\n",
            f"{_TOP}/plugin/hooks/footer_hook.py": "# footer hook\n",
        }
    )


class _FakeResponse:
    """Minimal context-manager stand-in for an ``http.client.HTTPResponse``."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(responses: dict[str, bytes]):
    """Return a urlopen stand-in that maps request URLs to byte payloads.

    Any URL not present raises a 404 ``HTTPError`` — this lets the version
    resolver fall through its with/without-``v`` candidate tags.
    """

    def fake(req, *args, **kwargs):
        # Production always passes a urllib.request.Request (see _http_get).
        url = req.full_url
        if url in responses:
            return _FakeResponse(responses[url])
        raise install.urllib.error.HTTPError(
            url, 404, "Not Found", email.message.Message(), None
        )

    return fake


def _release_json(tag: str) -> bytes:
    return json.dumps({"tag_name": tag, "tarball_url": _tarball_url(tag)}).encode()


# ---------------------------------------------------------------------------
# Release resolution / download / extraction (task 2.x)
# ---------------------------------------------------------------------------


def test_release_resolve_latest(monkeypatch):
    monkeypatch.setattr(
        install.urllib.request,
        "urlopen",
        _fake_urlopen({_latest_url(): _release_json("0.2.0")}),
    )
    release = install.resolve_release(_REPO, None)
    assert release["tag_name"] == "0.2.0"
    assert release["tarball_url"].endswith("/tarball/0.2.0")


@pytest.mark.parametrize(
    "requested, actual_tag",
    [
        ("0.2.0", "v0.2.0"),  # user omits v, release is tagged v0.2.0
        ("v0.2.0", "0.2.0"),  # user includes v, release is tagged 0.2.0
    ],
)
def test_release_resolve_version_tries_with_and_without_v(
    monkeypatch, requested, actual_tag
):
    monkeypatch.setattr(
        install.urllib.request,
        "urlopen",
        _fake_urlopen({_tag_url(actual_tag): _release_json(actual_tag)}),
    )
    release = install.resolve_release(_REPO, requested)
    assert release["tag_name"] == actual_tag


def test_release_resolve_unknown_version_errors(monkeypatch):
    monkeypatch.setattr(install.urllib.request, "urlopen", _fake_urlopen({}))
    with pytest.raises(install.InstallerError):
        install.resolve_release(_REPO, "9.9.9")


def test_release_download_extract_locates_plugin(tmp_path, monkeypatch):
    tarball_url = _tarball_url("0.2.0")
    monkeypatch.setattr(
        install.urllib.request,
        "urlopen",
        _fake_urlopen({tarball_url: _plugin_tarball()}),
    )
    plugin_dir = install.download_and_locate_plugin(tarball_url, tmp_path)
    assert (plugin_dir / "plugin.yaml").is_file()
    assert (plugin_dir / "hooks" / "footer_hook.py").is_file()


def test_release_tarball_without_plugin_errors(tmp_path, monkeypatch):
    tarball_url = _tarball_url("0.2.0")
    no_plugin = _make_tarball({f"{_TOP}/README.md": "# no plugin here\n"})
    monkeypatch.setattr(
        install.urllib.request,
        "urlopen",
        _fake_urlopen({tarball_url: no_plugin}),
    )
    with pytest.raises(install.InstallerError):
        install.download_and_locate_plugin(tarball_url, tmp_path)


def test_release_extract_rejects_path_traversal(tmp_path, monkeypatch):
    # A member escaping the extraction dir must be rejected before any write.
    tarball_url = _tarball_url("0.2.0")
    malicious = _make_tarball(
        {
            "../evil.txt": "pwned\n",
            f"{_TOP}/plugin/plugin.yaml": "name: hermes-usage-hook\n",
        }
    )
    monkeypatch.setattr(
        install.urllib.request,
        "urlopen",
        _fake_urlopen({tarball_url: malicious}),
    )
    with pytest.raises(install.InstallerError):
        install.download_and_locate_plugin(tarball_url, tmp_path)
    # Nothing escaped the working directory.
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path.parent / "evil.txt").exists()


# ---------------------------------------------------------------------------
# install mode integration via main() (task 3.x)
# ---------------------------------------------------------------------------


def _patch_release(monkeypatch, tag: str = "0.2.0", *, latest: bool = True):
    """Wire urlopen to a fake release + tarball for ``tag``.

    Maps both the latest and the with/without-``v`` tag endpoints to the same
    release JSON so either resolution path succeeds.
    """
    rel = _release_json(tag)
    responses = {_tarball_url(tag): _plugin_tarball(tag), _tag_url(tag): rel}
    if latest:
        responses[_latest_url()] = rel
    monkeypatch.setattr(install.urllib.request, "urlopen", _fake_urlopen(responses))


def test_install_local_copies_and_enables(tmp_path):
    home = tmp_path / "hermes"
    rc = install.main(["--local", "--hermes-home", str(home)])
    assert rc == 0
    assert (home / "plugins" / NAME / "plugin.yaml").is_file()
    # The post-install notice lives in the plugin root, so copying the plugin
    # directory carries it along without any installer change.
    assert (home / "plugins" / NAME / "after-install.md").is_file()
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert NAME in config["plugins"]["enabled"]


def test_install_default_fetches_release(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    _patch_release(monkeypatch)
    rc = install.main(["--repo", _REPO, "--hermes-home", str(home)])
    assert rc == 0
    assert (home / "plugins" / NAME / "plugin.yaml").is_file()
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert NAME in config["plugins"]["enabled"]


def test_install_version_pins_release(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    _patch_release(monkeypatch, tag="0.2.0", latest=False)
    rc = install.main(
        ["--version", "0.2.0", "--repo", _REPO, "--hermes-home", str(home)]
    )
    assert rc == 0
    installed = yaml.safe_load((home / "plugins" / NAME / "plugin.yaml").read_text())
    assert installed["version"] == "0.2.0"


def test_ref_tarball_url_targets_the_tarball_endpoint():
    # Our helper points straight at GitHub's /tarball/{ref} endpoint (not the
    # Releases API), passing the ref through verbatim.
    assert (
        install.ref_tarball_url("owner/repo", "main")
        == "https://api.github.com/repos/owner/repo/tarball/main"
    )


def test_install_ref_fetches_branch_tarball_without_release_api(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    # Wire ONLY the ref's tarball endpoint — no releases/latest or releases/tags
    # responses — so a passing install proves --ref bypasses the Releases API and
    # pulls the branch source tarball directly.
    responses = {_tarball_url("main"): _plugin_tarball("0.5.0")}
    monkeypatch.setattr(install.urllib.request, "urlopen", _fake_urlopen(responses))
    rc = install.main(["--ref", "main", "--repo", _REPO, "--hermes-home", str(home)])
    assert rc == 0
    installed = yaml.safe_load((home / "plugins" / NAME / "plugin.yaml").read_text())
    assert installed["version"] == "0.5.0"
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert NAME in config["plugins"]["enabled"]


def test_install_ref_dry_run_reports_ref_source_without_changes(tmp_path, capsys):
    home = tmp_path / "hermes"
    rc = install.main(
        ["--ref", "main", "--repo", _REPO, "--hermes-home", str(home), "--dry-run"]
    )
    assert rc == 0
    assert "main" in capsys.readouterr().out
    assert not (home / "plugins" / NAME).exists()


@pytest.mark.parametrize("other", [["--version", "0.2.0"], ["--local"]])
def test_install_ref_conflicts_with_other_sources(other):
    # --ref shares the mutually exclusive source group with --version/--local, so
    # combining them exits non-zero via argparse instead of installing.
    with pytest.raises(SystemExit):
        install.parse_args(["--ref", "main", *other])


def test_install_idempotent_preserves_config(tmp_path):
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "config.yaml").write_text(
        yaml.safe_dump({"gateway": {"port": 8080}, "plugins": {"enabled": ["other"]}})
    )
    assert install.main(["--local", "--hermes-home", str(home)]) == 0
    assert install.main(["--local", "--hermes-home", str(home)]) == 0
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert config["plugins"]["enabled"].count(NAME) == 1
    assert "other" in config["plugins"]["enabled"]
    assert config["gateway"] == {"port": 8080}


def test_install_no_enable_skips_config(tmp_path):
    home = tmp_path / "hermes"
    rc = install.main(["--local", "--no-enable", "--hermes-home", str(home)])
    assert rc == 0
    assert (home / "plugins" / NAME / "plugin.yaml").is_file()
    assert not (home / "config.yaml").exists()


def test_install_dry_run_changes_nothing(tmp_path):
    home = tmp_path / "hermes"
    rc = install.main(["--local", "--dry-run", "--hermes-home", str(home)])
    assert rc == 0
    assert not (home / "plugins" / NAME).exists()
    assert not (home / "config.yaml").exists()


def test_install_hermes_home_overrides_env(tmp_path, monkeypatch):
    env_home = tmp_path / "env_home"
    flag_home = tmp_path / "flag_home"
    monkeypatch.setenv("HERMES_HOME", str(env_home))
    rc = install.main(["--local", "--hermes-home", str(flag_home)])
    assert rc == 0
    assert (flag_home / "plugins" / NAME / "plugin.yaml").is_file()
    assert not env_home.exists()


def test_install_release_failure_points_to_local(tmp_path, monkeypatch, capsys):
    home = tmp_path / "hermes"
    # No responses registered: latest resolution 404s -> InstallerError.
    monkeypatch.setattr(install.urllib.request, "urlopen", _fake_urlopen({}))
    rc = install.main(["--repo", _REPO, "--hermes-home", str(home)])
    assert rc != 0
    assert "--local" in capsys.readouterr().err
    assert not (home / "plugins" / NAME).exists()


# ---------------------------------------------------------------------------
# Remote self-sufficiency: non-local modes read no file beside the script (3.3)
# ---------------------------------------------------------------------------


def test_remote_default_install_needs_no_adjacent_files(tmp_path, monkeypatch):
    # Simulate `uv run <raw-url>`: no plugin/ exists beside the script. Pointing
    # PLUGIN_SRC at a non-existent path proves the default release install never
    # touches an adjacent plugin/ and uses the fixed name constant instead.
    home = tmp_path / "hermes"
    monkeypatch.setattr(install, "PLUGIN_SRC", tmp_path / "nowhere" / "plugin")
    _patch_release(monkeypatch)
    rc = install.main(["--repo", _REPO, "--hermes-home", str(home)])
    assert rc == 0
    assert (home / "plugins" / "hermes-usage-hook" / "plugin.yaml").is_file()


def test_remote_remove_needs_no_adjacent_files(tmp_path, monkeypatch):
    # `uv run <raw-url> remove` must work with no plugin/ beside the script: the
    # version guard reads the *installed* plugin.yaml, never an adjacent file.
    home = tmp_path / "hermes"
    _install_fixture(home)
    monkeypatch.setattr(install, "PLUGIN_SRC", tmp_path / "nowhere" / "plugin")
    rc = install.main(["remove", "--hermes-home", str(home)])
    assert rc == 0
    assert not (home / "plugins" / NAME).exists()


# ---------------------------------------------------------------------------
# remove mode integration via main() (task 4.x)
# ---------------------------------------------------------------------------


def _install_fixture(home, version="0.2.0", other_enabled=None, extra_config=None):
    """Create an installed plugin directory + config.yaml under ``home``."""
    dest = home / "plugins" / NAME
    dest.mkdir(parents=True)
    (dest / "plugin.yaml").write_text(f"name: {NAME}\nversion: {version}\n")
    enabled = list(other_enabled or []) + [NAME]
    config = {"plugins": {"enabled": enabled}}
    if extra_config:
        config.update(extra_config)
    (home / "config.yaml").write_text(yaml.safe_dump(config))
    return dest


def test_remove_deletes_dir_and_disables(tmp_path):
    home = tmp_path / "hermes"
    _install_fixture(
        home, other_enabled=["other"], extra_config={"gateway": {"port": 8080}}
    )
    rc = install.main(["remove", "--hermes-home", str(home)])
    assert rc == 0
    assert not (home / "plugins" / NAME).exists()
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert NAME not in config["plugins"]["enabled"]
    assert "other" in config["plugins"]["enabled"]
    assert config["gateway"] == {"port": 8080}


def test_remove_is_idempotent_when_not_installed(tmp_path):
    home = tmp_path / "hermes"
    rc = install.main(["remove", "--hermes-home", str(home)])
    assert rc == 0
    assert not (home / "plugins" / NAME).exists()


def test_remove_version_mismatch_blocks_and_reports(tmp_path, capsys):
    home = tmp_path / "hermes"
    _install_fixture(home, version="0.2.0")
    rc = install.main(["remove", "--version", "9.9.9", "--hermes-home", str(home)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "0.2.0" in err and "9.9.9" in err
    # Nothing was deleted.
    assert (home / "plugins" / NAME / "plugin.yaml").is_file()
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert NAME in config["plugins"]["enabled"]


@pytest.mark.parametrize("requested", ["0.2.0", "v0.2.0"])
def test_remove_version_match_removes(tmp_path, requested):
    home = tmp_path / "hermes"
    _install_fixture(home, version="0.2.0")
    rc = install.main(["remove", "--version", requested, "--hermes-home", str(home)])
    assert rc == 0
    assert not (home / "plugins" / NAME).exists()
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert NAME not in config["plugins"]["enabled"]


def test_remove_version_without_install_errors(tmp_path):
    home = tmp_path / "hermes"
    rc = install.main(["remove", "--version", "0.2.0", "--hermes-home", str(home)])
    assert rc != 0


def test_remove_no_enable_keeps_config(tmp_path):
    home = tmp_path / "hermes"
    _install_fixture(home)
    rc = install.main(["remove", "--no-enable", "--hermes-home", str(home)])
    assert rc == 0
    assert not (home / "plugins" / NAME).exists()
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert NAME in config["plugins"]["enabled"]


def test_remove_dry_run_before_subcommand_deletes_nothing(tmp_path):
    # Regression: `--dry-run` given before the `remove` subcommand must remain a
    # dry run and delete nothing (a SUPPRESS-default clobber once reset it).
    home = tmp_path / "hermes"
    _install_fixture(home)
    rc = install.main(["--dry-run", "remove", "--hermes-home", str(home)])
    assert rc == 0
    assert (home / "plugins" / NAME / "plugin.yaml").is_file()
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert NAME in config["plugins"]["enabled"]


def test_install_local_missing_path_errors_cleanly(tmp_path, capsys):
    # A mistyped --local path exits non-zero with a readable InstallerError
    # message (not an uncaught FileNotFoundError traceback).
    home = tmp_path / "hermes"
    rc = install.main(["--local", str(tmp_path / "nope"), "--hermes-home", str(home)])
    assert rc != 0
    assert "--local" in capsys.readouterr().err
    assert not (home / "plugins" / NAME).exists()


def test_enable_plugin_creates_config_when_absent(tmp_path):
    config = tmp_path / "config.yaml"
    install.enable_plugin(config, NAME)
    data = yaml.safe_load(config.read_text())
    assert data["plugins"]["enabled"] == [NAME]


def test_enable_plugin_preserves_existing_content(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {"gateway": {"port": 8080}, "plugins": {"enabled": ["other-plugin"]}}
        )
    )
    install.enable_plugin(config, NAME)
    data = yaml.safe_load(config.read_text())
    assert data["gateway"] == {"port": 8080}
    assert data["plugins"]["enabled"] == ["other-plugin", NAME]


def test_enable_plugin_is_idempotent(tmp_path):
    config = tmp_path / "config.yaml"
    install.enable_plugin(config, NAME)
    install.enable_plugin(config, NAME)
    data = yaml.safe_load(config.read_text())
    assert data["plugins"]["enabled"].count(NAME) == 1


def test_install_plugin_dir_copies_and_overwrites(tmp_path):
    hermes_home = tmp_path / "hermes"
    dest = install.install_plugin_dir(install.PLUGIN_SRC, hermes_home, NAME)
    assert (dest / "plugin.yaml").exists()
    assert (dest / "hooks" / "footer_hook.py").exists()
    # Re-running overwrites in place without nesting or error.
    dest_again = install.install_plugin_dir(install.PLUGIN_SRC, hermes_home, NAME)
    assert dest_again == dest
    assert (dest_again / "plugin.yaml").exists()
    assert not (dest_again / "plugin").exists()


def test_install_plugin_dir_replaces_prior_symlink(tmp_path):
    # A prior manual symlink install (per the README) must be unlinked, not
    # recursed into, before copying — otherwise shutil.rmtree would fail.
    hermes_home = tmp_path / "hermes"
    plugins = hermes_home / "plugins"
    plugins.mkdir(parents=True)
    (plugins / NAME).symlink_to(install.PLUGIN_SRC, target_is_directory=True)
    dest = install.install_plugin_dir(install.PLUGIN_SRC, hermes_home, NAME)
    assert dest.is_dir() and not dest.is_symlink()
    assert (dest / "plugin.yaml").exists()
