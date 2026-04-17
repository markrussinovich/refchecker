from refchecker.utils.database_config import resolve_database_paths


def test_resolve_database_paths_from_directory(tmp_path):
    db_dir = tmp_path / "dbs"
    db_dir.mkdir()
    s2 = db_dir / "semantic_scholar.db"
    s2.write_text("", encoding="utf-8")
    oa = db_dir / "openalex.db"
    oa.write_text("", encoding="utf-8")

    resolved = resolve_database_paths(database_directory=str(db_dir))

    assert resolved["s2"] == str(s2)
    assert resolved["openalex"] == str(oa)


def test_explicit_database_path_wins_over_directory(tmp_path):
    db_dir = tmp_path / "dbs"
    db_dir.mkdir()
    (db_dir / "semantic_scholar.db").write_text("", encoding="utf-8")
    explicit = tmp_path / "custom_s2.db"
    explicit.write_text("", encoding="utf-8")

    resolved = resolve_database_paths(
        explicit_paths={"s2": str(explicit)},
        database_directory=str(db_dir),
    )

    assert resolved["s2"] == str(explicit)
