from pathlib import Path


def test_cli_exposes_multi_database_flags():
    src = Path("src/refchecker/core/refchecker.py").read_text(encoding="utf-8")

    for flag in ("--database-dir", "--s2-db", "--openalex-db", "--crossref-db", "--dblp-db", "--update-databases"):
        assert flag in src
