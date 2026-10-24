"""Advertised desktop downloads must exist before any release is published."""

import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[2]
stage_release = runpy.run_path(
    str(ROOT / "tauri-app" / "scripts" / "prepare-release.py")
)["stage_release"]
INSTALLERS = [
    ("macos-arm64", "RefChecker_1.2.3_aarch64.dmg"),
    ("windows", "RefChecker_1.2.3_x64_en-US.msi"),
    ("linux", "RefChecker_1.2.3_amd64.AppImage"),
    ("linux", "RefChecker_1.2.3_amd64.deb"),
]


@pytest.fixture
def release_files(tmp_path):
    artifacts = tmp_path / "artifacts"
    for platform, name in INSTALLERS:
        directory = artifacts / f"refchecker-desktop-{platform}"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(name.encode())
    manifest = tmp_path / "latest.json"
    manifest.write_text(json.dumps({"version": "1.2.3", "platforms": {}}))
    return artifacts, manifest, tmp_path / "release-files"


def test_staged_release_serves_every_readme_download_and_updater(release_files):
    artifacts, manifest, output = release_files
    signature = artifacts / "refchecker-desktop-windows" / f"{INSTALLERS[1][1]}.sig"
    signature.write_text("updater signature")
    stage_release(artifacts, manifest, output)

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    urls = re.findall(r'https://github.com/[^"\s<>]+/RefChecker-[^"\s<>]+', readme)
    assert len(urls) == 4
    for url in urls:
        assert "/releases/download/desktop-latest/" in url
        assert (output / url.rsplit("/", 1)[1]).read_bytes().startswith(b"RefChecker_1.2.3_")
    config = json.loads((ROOT / "tauri-app" / "src-tauri" / "tauri.conf.json").read_text())
    endpoint = config["plugins"]["updater"]["endpoints"][0]
    assert "/releases/download/desktop-latest/" in endpoint
    assert (output / endpoint.rsplit("/", 1)[1]).read_bytes() == manifest.read_bytes()
    assert (output / signature.name).read_text() == "updater signature"
    for _, name in INSTALLERS:
        assert (output / name).read_bytes() == name.encode()


@pytest.mark.parametrize("platform,name", INSTALLERS)
@pytest.mark.parametrize("empty", [False, True], ids=["missing", "empty"])
def test_missing_or_empty_advertised_installer_blocks_release(release_files, platform, name, empty):
    artifacts, manifest, output = release_files
    installer = artifacts / f"refchecker-desktop-{platform}" / name
    if empty:
        installer.write_bytes(b"")
    else:
        installer.unlink()
    with pytest.raises(ValueError, match="Empty installer|Expected one installer"):
        stage_release(artifacts, manifest, output)
    assert not output.exists()


def test_ambiguous_versions_cannot_silently_choose_an_installer(release_files):
    artifacts, manifest, output = release_files
    (artifacts / "refchecker-desktop-windows" / "RefChecker_1.2.2_x64_en-US.msi").write_bytes(b"old")
    with pytest.raises(ValueError, match="Expected one installer"):
        stage_release(artifacts, manifest, output)
    assert not output.exists()


def test_duplicate_asset_names_cannot_overwrite_each_other(release_files):
    artifacts, manifest, output = release_files
    duplicate = artifacts / "duplicate"
    duplicate.mkdir()
    (duplicate / INSTALLERS[0][1]).write_bytes(b"another build")
    with pytest.raises(ValueError, match="Duplicate release asset"):
        stage_release(artifacts, manifest, output)
    assert not output.exists()


@pytest.mark.parametrize("current", ["", "1.2.2", "1.2.3", "1.3.0"])
@pytest.mark.parametrize("upload_fails", [False, True])
def test_channel_publication_creates_updates_and_preserves_newer_releases(
    release_files, current, upload_fails,
):
    git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
    bash = str(git_bash) if os.name == "nt" and git_bash.is_file() else shutil.which("bash")
    if not bash:
        pytest.skip("Bash is required to execute the release workflow")

    artifacts, manifest, output = release_files
    stage_release(artifacts, manifest, output)
    workflow = (ROOT / ".github" / "workflows" / "desktop-release.yml").read_text(encoding="utf-8")
    step = workflow.split("      - name: Update desktop download channel\n", 1)[1]
    script = textwrap.dedent(step.split("        run: |\n", 1)[1])
    fake_commands = r"""
        gh() {
          printf '%s\n' "$*" >> gh-commands.log
          if [ "$1 $2" = "release view" ]; then
            [ -n "$CURRENT_RELEASE" ] || return 1
            printf 'RefChecker Desktop %s\n' "$CURRENT_RELEASE"
          elif [ "$1 $2" = "release upload" ]; then
            [ "$UPLOAD_FAILS" = "false" ] || return 1
            shift 3
            for asset in "$@"; do
              [ "$asset" = "--clobber" ] || [ -s "$asset" ] || return 1
            done
          fi
        }
        git() { printf 'test-source-commit\n'; }
    """
    result = subprocess.run(
        [bash, "--noprofile", "--norc"],
        input=textwrap.dedent(fake_commands) + "\n" + script,
        text=True, capture_output=True, cwd=artifacts.parent,
        env={
            **os.environ,
            "GH_REPO": "markrussinovich/refchecker",
            "VERSION": "1.2.3",
            "CURRENT_RELEASE": current,
            "UPLOAD_FAILS": str(upload_fails).lower(),
        },
    )
    commands = (artifacts.parent / "gh-commands.log").read_text().splitlines()
    if current == "1.3.0":
        assert result.returncode == 0, result.stderr
        assert len(commands) == 1
        assert "leaving the download channel unchanged" in result.stdout
        return

    assert result.returncode == (1 if upload_fails else 0), result.stderr
    if current:
        assert any("api --method PATCH" in command and "sha=test-source-commit" in command
                   for command in commands)
        assert not any("release create" in command for command in commands)
    else:
        assert "--draft --latest=false" in commands[1]
        assert "--target test-source-commit" in commands[1]
    assert "release upload desktop-latest" in commands[2]
    assert "RefChecker-windows-x64.msi" in commands[2]
    assert "release-files/latest.json --clobber" in commands[2]
    if upload_fails:
        assert not any("release edit" in command for command in commands)
    else:
        assert "--draft=false --prerelease=false --latest=false" in commands[-1]
