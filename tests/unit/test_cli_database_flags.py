from pathlib import Path


def test_cli_exposes_multi_database_flags():
    src = Path("src/refchecker/core/refchecker.py").read_text(encoding="utf-8")

    for flag in (
        "--database-dir",
        "--s2-db",
        "--openalex-db",
        "--crossref-db",
        "--dblp-db",
        "--acl-db",
        "--update-databases",
        "--openalex-since",
        "--openalex-min-year",
    ):
        assert flag in src


def test_webui_cli_exposes_multi_database_flags():
    src = Path("backend/cli.py").read_text(encoding="utf-8")

    for flag in (
        "--database-dir",
        "--s2-db",
        "--openalex-db",
        "--crossref-db",
        "--dblp-db",
        "--acl-db",
    ):
        assert flag in src
