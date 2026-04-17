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
}

DATABASE_LABELS = {
    "s2": "S2",
    "openalex": "OpenAlex",
    "crossref": "CrossRef",
    "dblp": "DBLP",
}


def resolve_db_file(path_value: Optional[str]) -> Optional[str]:
    """Resolve a DB path (file or directory) to a concrete SQLite file path."""
    if not path_value:
        return None

    candidate = Path(path_value).expanduser()
    if candidate.is_dir():
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
        direct = resolve_db_file(explicit_paths.get(db_name))
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
