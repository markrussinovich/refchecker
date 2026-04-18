#!/usr/bin/env python3
"""Helpers for configuring local checker databases."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Mapping, Optional

DATABASE_FILE_ALIASES = {
    "s2": ("semantic_scholar.db", "s2.db"),
    "openalex": ("openalex.db",),
    "crossref": ("crossref.db",),
    "dblp": ("dblp.db",),
    "acl": ("acl_anthology.db",),
}

DATABASE_LABELS = {
    "s2": "Semantic Scholar",
    "openalex": "OpenAlex",
    "crossref": "CrossRef",
    "dblp": "DBLP",
    "acl": "ACL Anthology",
}

DATABASE_LOOKUP_ORDER = (
    "s2",
    "openalex",
    "crossref",
    "dblp",
    "acl",
)

DATABASE_UPDATE_ORDER = (
    "s2",
    "dblp",
    "acl",
    "openalex",
    "crossref",
)

DATABASE_BUILD_DEPENDENCIES = {
    "crossref": ("s2", "dblp", "openalex", "acl"),
}


def _resolve_named_db_file(db_name: str, directory: Path) -> Optional[str]:
    """Resolve a named DB inside a directory using its canonical filenames."""
    for filename in DATABASE_FILE_ALIASES.get(db_name, ()): 
        db_file = directory / filename
        if db_file.is_file():
            return str(db_file)
    return None


def resolve_db_file(path_value: Optional[str], db_name: Optional[str] = None) -> Optional[str]:
    """Resolve a DB path (file or directory) to a concrete SQLite file path."""
    if not path_value:
        return None

    candidate = Path(path_value).expanduser()
    if candidate.is_dir():
        if db_name:
            return _resolve_named_db_file(db_name, candidate)
        db_files = sorted(candidate.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        if db_files:
            return str(db_files[0])
        return None
    return str(candidate)


def resolve_database_paths(
    explicit_paths: Optional[Mapping[str, Optional[str]]] = None,
    database_directory: Optional[str] = None,
) -> Dict[str, str]:
    """Resolve per-database paths from explicit flags and/or a shared directory."""
    resolved: Dict[str, str] = {}
    explicit_paths = explicit_paths or {}

    for db_name in DATABASE_FILE_ALIASES:
        direct = resolve_db_file(explicit_paths.get(db_name), db_name=db_name)
        if direct:
            resolved[db_name] = direct

    if database_directory:
        db_dir = Path(database_directory).expanduser()
        if db_dir.is_dir():
            for db_name, aliases in DATABASE_FILE_ALIASES.items():
                if db_name in resolved:
                    continue
                for filename in aliases:
                    db_file = db_dir / filename
                    if db_file.is_file():
                        resolved[db_name] = str(db_file)
                        break

    return resolved


def resolve_database_update_paths(
    explicit_paths: Optional[Mapping[str, Optional[str]]] = None,
    database_directory: Optional[str] = None,
) -> Dict[str, str]:
    """Resolve per-database paths for update/build operations.

    Unlike ``resolve_database_paths()``, this helper also plans default file
    locations for databases that do not exist yet when ``database_directory`` is
    configured.
    """
    resolved = resolve_database_paths(
        explicit_paths=explicit_paths,
        database_directory=database_directory,
    )

    explicit_paths = explicit_paths or {}

    for db_name, aliases in DATABASE_FILE_ALIASES.items():
        if db_name in resolved:
            continue
        candidate = explicit_paths.get(db_name)
        if not candidate:
            continue
        db_dir = Path(candidate).expanduser()
        if db_dir.is_dir():
            resolved[db_name] = str(db_dir / aliases[0])

    if not database_directory:
        return resolved

    db_dir = Path(database_directory).expanduser()
    for db_name, aliases in DATABASE_FILE_ALIASES.items():
        if db_name in resolved:
            continue
        resolved[db_name] = str(db_dir / aliases[0])

    return resolved
