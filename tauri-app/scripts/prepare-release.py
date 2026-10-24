"""Stage desktop release assets, rejecting missing or ambiguous downloads."""

import argparse
import json
from pathlib import Path
import shutil


REQUIRED_INSTALLERS = {
    "RefChecker-macos-arm64.dmg": "RefChecker_*_aarch64.dmg",
    "RefChecker-windows-x64.msi": "RefChecker_*_x64_en-US.msi",
    "RefChecker-linux-x64.AppImage": "RefChecker_*_amd64.AppImage",
    "RefChecker-linux-x64.deb": "RefChecker_*_amd64.deb",
}
OPTIONAL_INSTALLERS = {
    "RefChecker-windows-x64-setup.exe": "RefChecker_*_x64-setup.exe",
}


def stage_release(artifacts: Path, manifest: Path, output: Path) -> None:
    sources = {}
    for source in sorted(artifacts.rglob("*")):
        if not source.is_file():
            continue
        if source.name in sources:
            raise ValueError(f"Duplicate release asset: {source.name}")
        sources[source.name] = source

    aliases = {}
    for alias, pattern in {**REQUIRED_INSTALLERS, **OPTIONAL_INSTALLERS}.items():
        matches = [source for source in sources.values() if source.match(pattern)]
        if not matches and alias in OPTIONAL_INSTALLERS:
            continue
        if len(matches) != 1:
            raise ValueError(f"Expected one installer matching {pattern}, found {len(matches)}")
        if matches[0].stat().st_size == 0:
            raise ValueError(f"Empty installer: {matches[0]}")
        aliases[alias] = matches[0]

    json.loads(manifest.read_text(encoding="utf-8"))
    output.mkdir(parents=True)
    for name, source in {**sources, **aliases}.items():
        shutil.copy2(source, output / name)
    shutil.copy2(manifest, output / "latest.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    stage_release(args.artifacts, args.manifest, args.output)
