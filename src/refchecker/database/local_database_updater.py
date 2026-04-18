#!/usr/bin/env python3
"""Build and refresh local checker databases used by RefChecker."""

from __future__ import annotations

import argparse
import gzip
import io
import json
import logging
import os
import re
import sqlite3
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.entities import name2codepoint
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

import requests

from refchecker.database.download_semantic_scholar_db import SemanticScholarDownloader
from refchecker.utils.database_config import DATABASE_FILE_ALIASES, DATABASE_LABELS
from refchecker.utils.doi_utils import normalize_doi
from refchecker.utils.text_utils import normalize_paper_title
from refchecker.utils.url_utils import extract_arxiv_id_from_url

logger = logging.getLogger(__name__)

LOCAL_DB_SCHEMA_VERSION = 'refchecker-local-v1'
LOCAL_DB_REQUIRED_COLUMNS = {
    'paperId',
    'title',
    'normalized_paper_title',
    'venue',
    'year',
    'externalIds_DOI',
    'externalIds_ArXiv',
    'authors',
    'source_url',
}
LOCAL_DB_REQUIRED_INDEXES = {
    'idx_papers_normalized_title',
    'idx_papers_doi',
    'idx_papers_arxiv',
}
DBLP_DUMP_URL = 'https://dblp.uni-trier.de/xml/dblp.xml.gz'
ACL_ANTHOLOGY_TARBALL_URL = 'https://api.github.com/repos/acl-org/acl-anthology/tarball'
ACL_ANTHOLOGY_COMMITS_URL = 'https://api.github.com/repos/acl-org/acl-anthology/commits'
OPENALEX_BUCKET_URL = 'https://openalex.s3.us-east-1.amazonaws.com'
OPENALEX_ALLOWED_TYPES = {
    'article',
    'book-chapter',
    'preprint',
    'review',
    'dissertation',
}
DBLP_PUBLICATION_TAGS = {
    'article',
    'inproceedings',
    'proceedings',
    'book',
    'incollection',
    'phdthesis',
    'mastersthesis',
}
DBLP_ENTITY_RE = re.compile(r'&([A-Za-z][A-Za-z0-9]+);')
XML_PREDEFINED_ENTITIES = {'amp', 'lt', 'gt', 'apos', 'quot'}
CROSSREF_SEED_DATABASES = ('s2', 'dblp', 'openalex', 'acl')
ACL_OLD_PREFIX_MAP = {
    'A': 'ACL',
    'C': 'COLING',
    'D': 'EMNLP',
    'E': 'EACL',
    'H': 'HLT',
    'I': 'IJCNLP',
    'J': 'Computational Linguistics',
    'K': 'CoNLL',
    'L': 'LREC',
    'M': 'MUC',
    'N': 'NAACL',
    'P': 'ACL',
    'Q': 'TACL',
    'R': 'RANLP',
    'S': 'SemEval',
    'T': 'Theoretical Linguistics',
    'W': 'Workshop',
    'X': 'ANLP',
    'Y': 'PACLIC',
}


@dataclass
class DatabaseUpdateOutcome:
    updated: bool
    skipped: bool
    message: str


def _configure_logging() -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
    )


def _connect_sqlite(db_path: str) -> sqlite3.Connection:
    db_parent = os.path.dirname(os.path.abspath(db_path))
    if db_parent:
        os.makedirs(db_parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA cache_size=-64000')
    conn.execute('PRAGMA temp_store=MEMORY')
    return conn


def _ensure_common_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS papers (
            paperId TEXT PRIMARY KEY,
            title TEXT,
            normalized_paper_title TEXT,
            venue TEXT,
            year INTEGER,
            externalIds_DOI TEXT,
            externalIds_ArXiv TEXT,
            authors TEXT,
            source_url TEXT
        )
        '''
    )
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

    columns = {
        row[1]
        for row in conn.execute('PRAGMA table_info(papers)').fetchall()
    }
    if 'source_url' not in columns:
        conn.execute('ALTER TABLE papers ADD COLUMN source_url TEXT')

    conn.commit()


def _ensure_common_indexes(conn: sqlite3.Connection) -> None:
    conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_normalized_title ON papers(normalized_paper_title)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(externalIds_DOI)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_arxiv ON papers(externalIds_ArXiv)')
    conn.commit()


def _get_papers_columns(conn: sqlite3.Connection) -> set[str]:
    return {
        row[1]
        for row in conn.execute('PRAGMA table_info(papers)').fetchall()
    }


def _get_lookup_indexes(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_papers_%'"
        ).fetchall()
        if row[0]
    }


def repair_local_database_schema(
    db_path: str,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, object]:
    """Best-effort repair for shared local DB columns and lookup indexes."""
    owns_connection = conn is None
    connection = conn or _connect_sqlite(db_path)

    try:
        has_papers_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='papers'"
        ).fetchone()
        if has_papers_table is None:
            raise ValueError(f"Database at {db_path} is missing the required 'papers' table")

        before_columns = _get_papers_columns(connection)
        before_indexes = _get_lookup_indexes(connection)

        _ensure_common_schema(connection)
        _ensure_common_indexes(connection)

        after_columns = _get_papers_columns(connection)
        after_indexes = _get_lookup_indexes(connection)

        try:
            connection.execute('PRAGMA optimize')
        except sqlite3.Error:
            pass

        return {
            'columns': after_columns,
            'indexes': after_indexes,
            'added_columns': sorted(after_columns - before_columns),
            'added_indexes': sorted(after_indexes - before_indexes),
            'missing_columns': sorted(LOCAL_DB_REQUIRED_COLUMNS - after_columns),
            'missing_indexes': sorted(LOCAL_DB_REQUIRED_INDEXES - after_indexes),
        }
    finally:
        if owns_connection:
            try:
                connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            except sqlite3.Error:
                pass
            connection.close()


def _write_metadata(conn: sqlite3.Connection, metadata: Dict[str, Optional[str]]) -> None:
    rows = [
        (key, value)
        for key, value in metadata.items()
        if value is not None
    ]
    if not rows:
        return
    conn.executemany(
        '''
        INSERT OR REPLACE INTO metadata (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ''',
        rows,
    )
    conn.commit()


def _read_metadata_value(db_path: str, key: str) -> Optional[str]:
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                'SELECT value FROM metadata WHERE key = ?',
                (key,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def _count_papers(conn: sqlite3.Connection) -> int:
    row = conn.execute('SELECT COUNT(*) FROM papers').fetchone()
    return int(row[0]) if row else 0


def _sanitize_non_xml_named_entities(text: str) -> str:
    def replace_entity(match: re.Match[str]) -> str:
        entity_name = match.group(1)
        if entity_name in XML_PREDEFINED_ENTITIES:
            return match.group(0)

        codepoint = name2codepoint.get(entity_name)
        if codepoint is None:
            return match.group(0)
        return chr(codepoint)

    return DBLP_ENTITY_RE.sub(replace_entity, text)


def _normalize_inline_xml_text(element: Optional[ET.Element]) -> str:
    if element is None:
        return ''
    return re.sub(r'\s+', ' ', ''.join(element.itertext())).strip()


def _parse_acl_anthology_id(anthology_id: str) -> Tuple[Optional[int], Optional[str]]:
    new_fmt = re.match(r'^(\d{4})\.([^.-]+)', anthology_id)
    if new_fmt:
        return int(new_fmt.group(1)), new_fmt.group(2).upper()

    old_fmt = re.match(r'^([A-Za-z])(\d{2})-', anthology_id)
    if old_fmt:
        prefix = old_fmt.group(1).upper()
        year_suffix = int(old_fmt.group(2))
        year = 2000 + year_suffix if year_suffix < 50 else 1900 + year_suffix
        return year, ACL_OLD_PREFIX_MAP.get(prefix, prefix)

    return None, None


def _build_acl_anthology_id(
    collection_id: str,
    volume_id: str,
    paper_id: str,
    explicit_url: str,
) -> str:
    if explicit_url:
        return explicit_url.strip().strip('/')
    if collection_id and '.' in collection_id and volume_id:
        return f'{collection_id}-{volume_id}.{paper_id}'
    if collection_id and volume_id.isdigit() and paper_id.isdigit():
        return f'{collection_id}-{volume_id}{int(paper_id):03d}'
    if collection_id and volume_id:
        return f'{collection_id}-{volume_id}.{paper_id}'
    if collection_id and paper_id:
        return f'{collection_id}-{paper_id}'
    return paper_id


def _iter_acl_rows_from_xml_stream(xml_stream: object) -> Iterator[Tuple[str, str, str, str, Optional[int], Optional[str], Optional[str], str, Optional[str]]]:
    tree = ET.parse(xml_stream)
    root = tree.getroot()
    collection_id = (root.attrib.get('id') or '').strip()

    for volume in root.findall('volume'):
        volume_id = (volume.attrib.get('id') or '').strip()
        volume_meta = volume.find('meta')
        volume_venue = ''
        volume_year: Optional[int] = None
        if volume_meta is not None:
            for venue_tag in ('booktitle', 'journal-title', 'journal', 'title'):
                volume_venue = _normalize_inline_xml_text(volume_meta.find(venue_tag))
                if volume_venue:
                    break

            volume_year_text = _normalize_inline_xml_text(volume_meta.find('year'))
            if volume_year_text.isdigit():
                volume_year = int(volume_year_text)

        for paper in volume.findall('paper'):
            paper_id = (paper.attrib.get('id') or '').strip()
            if paper_id == '0':
                continue

            title = _normalize_inline_xml_text(paper.find('title'))
            if not title:
                continue

            authors: List[str] = []
            for contributor_tag in ('author', 'editor'):
                for contributor in paper.findall(contributor_tag):
                    first_name = _normalize_inline_xml_text(contributor.find('first'))
                    last_name = _normalize_inline_xml_text(contributor.find('last'))
                    if first_name or last_name:
                        author_name = f'{first_name} {last_name}'.strip()
                    else:
                        author_name = _normalize_inline_xml_text(contributor)
                    if author_name:
                        authors.append(author_name)

            doi = normalize_doi(_normalize_inline_xml_text(paper.find('doi'))) or None
            anthology_id = _build_acl_anthology_id(
                collection_id,
                volume_id,
                paper_id,
                _normalize_inline_xml_text(paper.find('url')),
            )
            if not anthology_id:
                continue

            parsed_year, parsed_venue = _parse_acl_anthology_id(anthology_id)
            venue = volume_venue or parsed_venue or ''
            year = volume_year if volume_year is not None else parsed_year
            source_url = f'https://aclanthology.org/{anthology_id}'

            yield (
                f'acl:{anthology_id}',
                title,
                normalize_paper_title(title),
                venue,
                year,
                doi,
                None,
                json.dumps(authors, ensure_ascii=True),
                source_url,
            )


def _iter_acl_rows_from_tarball(tarball_path: str) -> Iterator[Tuple[str, str, str, str, Optional[int], Optional[str], Optional[str], str, Optional[str]]]:
    with tarfile.open(tarball_path, 'r:gz') as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            member_name = member.name.replace('\\', '/')
            if '/data/xml/' not in member_name or not member_name.endswith('.xml'):
                continue
            xml_handle = archive.extractfile(member)
            if xml_handle is None:
                continue
            try:
                yield from _iter_acl_rows_from_xml_stream(xml_handle)
            except ET.ParseError as exc:
                logger.warning('Skipping ACL Anthology file %s: %s', member_name, exc)
            finally:
                xml_handle.close()


def _fetch_latest_acl_commit_sha(session: requests.Session) -> Optional[str]:
    response = session.get(
        ACL_ANTHOLOGY_COMMITS_URL,
        params={'per_page': '1'},
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or not payload:
        return None
    latest_commit = payload[0]
    if not isinstance(latest_commit, dict):
        return None
    sha = latest_commit.get('sha')
    return sha.strip() if isinstance(sha, str) and sha.strip() else None


def _prepare_s2_database(db_path: str, api_key: Optional[str] = None) -> DatabaseUpdateOutcome:
    downloader = SemanticScholarDownloader(
        output_dir=os.path.dirname(os.path.abspath(db_path)) or '.',
        api_key=api_key,
        db_path=db_path,
    )
    try:
        if not downloader.refresh_database():
            return DatabaseUpdateOutcome(
                updated=False,
                skipped=False,
                message='Semantic Scholar refresh failed',
            )
        return DatabaseUpdateOutcome(
            updated=True,
            skipped=False,
            message='Updated S2 database',
        )
    finally:
        downloader.close()


def _iter_dblp_rows_from_xml_gz(xml_gz_path: str) -> Iterator[Tuple[str, str, str, str, Optional[int], Optional[str], Optional[str], str, Optional[str]]]:
    parser = ET.XMLPullParser(events=('start', 'end'))
    root: Optional[ET.Element] = None

    with gzip.open(xml_gz_path, 'rt', encoding='utf-8', errors='replace') as handle:
        for raw_line in handle:
            parser.feed(_sanitize_non_xml_named_entities(raw_line))

            for event, elem in parser.read_events():
                tag = elem.tag.rsplit('}', 1)[-1] if isinstance(elem.tag, str) else ''

                if event == 'start':
                    if root is None and tag == 'dblp':
                        root = elem
                    continue

                if tag not in DBLP_PUBLICATION_TAGS:
                    continue

                key = (elem.attrib.get('key') or '').strip()
                title_elem = elem.find('title')
                title = ''.join(title_elem.itertext()).strip() if title_elem is not None else ''
                if not title:
                    elem.clear()
                    continue

                authors = [
                    ''.join(author.itertext()).strip()
                    for author in elem.findall('author')
                    if ''.join(author.itertext()).strip()
                ]
                if not authors:
                    authors = [
                        ''.join(editor.itertext()).strip()
                        for editor in elem.findall('editor')
                        if ''.join(editor.itertext()).strip()
                    ]

                year_text = (elem.findtext('year') or '').strip()
                year = int(year_text) if year_text.isdigit() else None

                venue = ''
                for venue_tag in ('journal', 'booktitle', 'school', 'publisher'):
                    venue = (elem.findtext(venue_tag) or '').strip()
                    if venue:
                        break

                doi = (elem.findtext('doi') or '').strip() or None
                arxiv_id = None
                for ee in elem.findall('ee'):
                    ee_text = ''.join(ee.itertext()).strip()
                    if not doi and 'doi.org/' in ee_text:
                        doi = normalize_doi(ee_text)
                    if not arxiv_id:
                        arxiv_id = extract_arxiv_id_from_url(ee_text)

                if doi:
                    doi = normalize_doi(doi)

                source_url = f'https://dblp.org/rec/{key}' if key else None
                paper_id = f'dblp:{key}' if key else f'dblp:{normalize_paper_title(title)}:{year or 0}'

                yield (
                    paper_id,
                    title,
                    normalize_paper_title(title),
                    venue,
                    year,
                    doi,
                    arxiv_id,
                    json.dumps(authors, ensure_ascii=True),
                    source_url,
                )

                elem.clear()
                if root is not None and len(root) >= 512:
                    root.clear()

    parser.close()


def _insert_paper_rows(conn: sqlite3.Connection, rows: Iterable[Tuple[str, str, str, str, Optional[int], Optional[str], Optional[str], str, Optional[str]]]) -> int:
    total = 0
    batch: List[Tuple[str, str, str, str, Optional[int], Optional[str], Optional[str], str, Optional[str]]] = []

    for row in rows:
        batch.append(row)
        if len(batch) >= 2000:
            conn.executemany(
                '''
                INSERT OR REPLACE INTO papers (
                    paperId,
                    title,
                    normalized_paper_title,
                    venue,
                    year,
                    externalIds_DOI,
                    externalIds_ArXiv,
                    authors,
                    source_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                batch,
            )
            total += len(batch)
            batch.clear()

    if batch:
        conn.executemany(
            '''
            INSERT OR REPLACE INTO papers (
                paperId,
                title,
                normalized_paper_title,
                venue,
                year,
                externalIds_DOI,
                externalIds_ArXiv,
                authors,
                source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            batch,
        )
        total += len(batch)

    conn.commit()
    return total


def build_dblp_database_from_xml_gz(db_path: str, xml_gz_path: str) -> int:
    conn = _connect_sqlite(db_path)
    try:
        _ensure_common_schema(conn)
        inserted = _insert_paper_rows(conn, _iter_dblp_rows_from_xml_gz(xml_gz_path))
        _ensure_common_indexes(conn)
        _write_metadata(
            conn,
            {
                'schema_version': LOCAL_DB_SCHEMA_VERSION,
                'database': 'dblp',
                'last_updated': str(int(time.time())),
                'publication_count': str(_count_papers(conn)),
            },
        )
        return inserted
    finally:
        conn.close()


def build_acl_database_from_tarball(db_path: str, tarball_path: str) -> int:
    conn = _connect_sqlite(db_path)
    try:
        _ensure_common_schema(conn)
        inserted = _insert_paper_rows(conn, _iter_acl_rows_from_tarball(tarball_path))
        _ensure_common_indexes(conn)
        _write_metadata(
            conn,
            {
                'schema_version': LOCAL_DB_SCHEMA_VERSION,
                'database': 'acl',
                'last_updated': str(int(time.time())),
                'publication_count': str(_count_papers(conn)),
            },
        )
        return inserted
    finally:
        conn.close()


def update_acl_database(
    db_path: str,
    source_file: Optional[str] = None,
) -> DatabaseUpdateOutcome:
    db_parent = os.path.dirname(os.path.abspath(db_path)) or '.'
    os.makedirs(db_parent, exist_ok=True)

    if source_file:
        publication_count = build_acl_database_from_tarball(db_path, source_file)
        if publication_count == 0:
            return DatabaseUpdateOutcome(
                updated=False,
                skipped=False,
                message='ACL Anthology build produced no paper records',
            )
        return DatabaseUpdateOutcome(
            updated=True,
            skipped=False,
            message=f'Built ACL Anthology database from {source_file}',
        )

    session = requests.Session()
    session.headers.update({
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'RefChecker/1.0.0 (https://github.com/markrussinovich/refchecker)',
    })

    latest_commit_sha = None
    try:
        latest_commit_sha = _fetch_latest_acl_commit_sha(session)
    except Exception as exc:
        logger.warning('Failed to fetch latest ACL Anthology commit SHA: %s', exc)

    stored_commit_sha = _read_metadata_value(db_path, 'commit_sha')
    if latest_commit_sha and stored_commit_sha == latest_commit_sha:
        return DatabaseUpdateOutcome(
            updated=False,
            skipped=True,
            message='ACL Anthology database already up to date',
        )

    response = session.get(
        ACL_ANTHOLOGY_TARBALL_URL,
        stream=True,
        timeout=(30, 600),
    )
    response.raise_for_status()

    with tempfile.TemporaryDirectory(dir=db_parent) as tmp_dir:
        tarball_path = os.path.join(tmp_dir, 'acl-anthology.tar.gz')
        with open(tarball_path, 'wb') as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        response.close()

        temp_db_path = os.path.join(tmp_dir, 'acl_anthology.db')
        publication_count = build_acl_database_from_tarball(temp_db_path, tarball_path)

        if publication_count == 0:
            return DatabaseUpdateOutcome(
                updated=False,
                skipped=False,
                message='ACL Anthology build produced no paper records',
            )

        conn = _connect_sqlite(temp_db_path)
        try:
            _write_metadata(
                conn,
                {
                    'commit_sha': latest_commit_sha,
                },
            )
        finally:
            conn.close()

        os.replace(temp_db_path, db_path)

    return DatabaseUpdateOutcome(
        updated=True,
        skipped=False,
        message=f'Updated {DATABASE_LABELS["acl"]} database',
    )


def update_dblp_database(db_path: str, source_file: Optional[str] = None) -> DatabaseUpdateOutcome:
    db_parent = os.path.dirname(os.path.abspath(db_path)) or '.'
    os.makedirs(db_parent, exist_ok=True)

    stored_etag = _read_metadata_value(db_path, 'etag')
    stored_last_modified = _read_metadata_value(db_path, 'last_modified')

    if source_file:
        inserted = build_dblp_database_from_xml_gz(db_path, source_file)
        return DatabaseUpdateOutcome(
            updated=bool(inserted),
            skipped=False,
            message=f'Built DBLP database from {source_file}',
        )

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'RefChecker/1.0.0 (https://github.com/markrussinovich/refchecker)',
    })

    headers = {}
    if stored_etag:
        headers['If-None-Match'] = stored_etag
    if stored_last_modified:
        headers['If-Modified-Since'] = stored_last_modified

    response = session.get(DBLP_DUMP_URL, headers=headers, stream=True, timeout=(30, 600))
    if response.status_code == 304:
        response.close()
        return DatabaseUpdateOutcome(
            updated=False,
            skipped=True,
            message='DBLP database already up to date',
        )
    response.raise_for_status()

    new_etag = response.headers.get('etag')
    new_last_modified = response.headers.get('last-modified')

    with tempfile.TemporaryDirectory(dir=db_parent) as tmp_dir:
        xml_gz_path = os.path.join(tmp_dir, 'dblp.xml.gz')
        with open(xml_gz_path, 'wb') as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        response.close()

        temp_db_path = os.path.join(tmp_dir, 'dblp.db')
        inserted = build_dblp_database_from_xml_gz(temp_db_path, xml_gz_path)

        conn = _connect_sqlite(temp_db_path)
        try:
            _write_metadata(
                conn,
                {
                    'etag': new_etag,
                    'last_modified': new_last_modified,
                },
            )
        finally:
            conn.close()

        os.replace(temp_db_path, db_path)

    return DatabaseUpdateOutcome(
        updated=bool(inserted),
        skipped=False,
        message='Updated DBLP database',
    )


def _openalex_best_source_url(work: Dict[str, object]) -> Optional[str]:
    work_id = work.get('id')
    if isinstance(work_id, str) and work_id:
        return work_id

    primary_location = work.get('primary_location')
    if isinstance(primary_location, dict):
        landing_page = primary_location.get('landing_page_url')
        if isinstance(landing_page, str) and landing_page:
            return landing_page

    doi = work.get('doi')
    if isinstance(doi, str) and doi:
        normalized = normalize_doi(doi)
        if normalized:
            return f'https://doi.org/{normalized}'

    return None


def _extract_openalex_arxiv_id(work: Dict[str, object]) -> Optional[str]:
    ids = work.get('ids')
    if isinstance(ids, dict):
        arxiv_candidate = ids.get('arxiv')
        if isinstance(arxiv_candidate, str):
            arxiv_id = extract_arxiv_id_from_url(arxiv_candidate)
            if arxiv_id:
                return arxiv_id

    candidate_urls: List[str] = []
    primary_location = work.get('primary_location')
    if isinstance(primary_location, dict):
        for key in ('landing_page_url', 'pdf_url'):
            value = primary_location.get(key)
            if isinstance(value, str) and value:
                candidate_urls.append(value)

    locations = work.get('locations')
    if isinstance(locations, list):
        for location in locations:
            if not isinstance(location, dict):
                continue
            for key in ('landing_page_url', 'pdf_url'):
                value = location.get(key)
                if isinstance(value, str) and value:
                    candidate_urls.append(value)

    for candidate_url in candidate_urls:
        arxiv_id = extract_arxiv_id_from_url(candidate_url)
        if arxiv_id:
            return arxiv_id

    return None


def parse_openalex_work_json(line: str, min_year: Optional[int] = None) -> Optional[Tuple[str, str, str, str, Optional[int], Optional[str], Optional[str], str, Optional[str]]]:
    work = json.loads(line)
    work_type = work.get('type')
    if work_type not in OPENALEX_ALLOWED_TYPES:
        return None

    publication_year = work.get('publication_year')
    if min_year is not None:
        if not isinstance(publication_year, int) or publication_year < min_year:
            return None

    title = work.get('display_name') or work.get('title')
    if not isinstance(title, str) or not title.strip():
        return None
    title = title.strip()

    work_id = work.get('id')
    if not isinstance(work_id, str) or not work_id:
        return None
    work_id_value = work_id.rsplit('/', 1)[-1]
    if work_id_value.startswith('W'):
        work_id_value = work_id_value[1:]

    authors: List[str] = []
    authorships = work.get('authorships')
    if isinstance(authorships, list):
        for authorship in authorships:
            if not isinstance(authorship, dict):
                continue
            author = authorship.get('author')
            if not isinstance(author, dict):
                continue
            display_name = author.get('display_name')
            if isinstance(display_name, str) and display_name:
                authors.append(display_name)

    venue = ''
    primary_location = work.get('primary_location')
    if isinstance(primary_location, dict):
        source = primary_location.get('source')
        if isinstance(source, dict):
            source_name = source.get('display_name')
            if isinstance(source_name, str) and source_name:
                venue = source_name

    doi = work.get('doi')
    if isinstance(doi, str) and doi:
        doi = normalize_doi(doi)
    else:
        doi = None

    return (
        f'openalex:{work_id_value}',
        title,
        normalize_paper_title(title),
        venue,
        publication_year if isinstance(publication_year, int) else None,
        doi,
        _extract_openalex_arxiv_id(work),
        json.dumps(authors, ensure_ascii=True),
        _openalex_best_source_url(work),
    )


def _iter_openalex_bucket_page(session: requests.Session, params: Dict[str, str]) -> ET.Element:
    response = session.get(f'{OPENALEX_BUCKET_URL}/', params=params, timeout=120)
    response.raise_for_status()
    return ET.fromstring(response.text)


def _xml_text(elem: Optional[ET.Element]) -> Optional[str]:
    if elem is None or elem.text is None:
        return None
    text = elem.text.strip()
    return text or None


def list_openalex_date_partitions(session: requests.Session) -> List[Tuple[str, str]]:
    partitions: List[Tuple[str, str]] = []
    continuation_token: Optional[str] = None

    while True:
        params = {
            'list-type': '2',
            'prefix': 'data/works/',
            'delimiter': '/',
        }
        if continuation_token:
            params['continuation-token'] = continuation_token

        root = _iter_openalex_bucket_page(session, params)
        for prefix_elem in root.findall('.//{*}CommonPrefixes/{*}Prefix'):
            prefix = _xml_text(prefix_elem)
            if not prefix:
                continue
            partition_date = prefix.rstrip('/').rsplit('=', 1)[-1]
            if len(partition_date) == 10:
                partitions.append((partition_date, prefix))

        continuation_token = _xml_text(root.find('.//{*}NextContinuationToken'))
        if not continuation_token:
            break

    partitions.sort(key=lambda item: item[0])
    return partitions


def list_openalex_partition_files(session: requests.Session, prefix: str) -> List[Tuple[str, int]]:
    files: List[Tuple[str, int]] = []
    continuation_token: Optional[str] = None

    while True:
        params = {
            'list-type': '2',
            'prefix': prefix,
        }
        if continuation_token:
            params['continuation-token'] = continuation_token

        root = _iter_openalex_bucket_page(session, params)
        for content in root.findall('.//{*}Contents'):
            key = _xml_text(content.find('{*}Key'))
            if not key or not key.endswith('.gz'):
                continue
            size_text = _xml_text(content.find('{*}Size')) or '0'
            files.append((key, int(size_text)))

        continuation_token = _xml_text(root.find('.//{*}NextContinuationToken'))
        if not continuation_token:
            break

    return files


def _ingest_openalex_text_stream(conn: sqlite3.Connection, text_stream: Iterable[str], min_year: Optional[int] = None) -> int:
    rows: List[Tuple[str, str, str, str, Optional[int], Optional[str], Optional[str], str, Optional[str]]] = []
    inserted = 0

    for raw_line in text_stream:
        line = raw_line.strip()
        if not line:
            continue
        parsed = parse_openalex_work_json(line, min_year=min_year)
        if not parsed:
            continue
        rows.append(parsed)
        if len(rows) >= 2000:
            inserted += _insert_paper_rows(conn, rows)
            rows.clear()

    if rows:
        inserted += _insert_paper_rows(conn, rows)

    return inserted


def build_openalex_database_from_snapshot_files(
    db_path: str,
    snapshot_files: Sequence[str],
    min_year: Optional[int] = None,
    last_sync_date: Optional[str] = None,
) -> int:
    conn = _connect_sqlite(db_path)
    try:
        _ensure_common_schema(conn)
        inserted = 0
        for snapshot_file in snapshot_files:
            with gzip.open(snapshot_file, 'rt', encoding='utf-8') as handle:
                inserted += _ingest_openalex_text_stream(conn, handle, min_year=min_year)
        _ensure_common_indexes(conn)
        _write_metadata(
            conn,
            {
                'schema_version': LOCAL_DB_SCHEMA_VERSION,
                'database': 'openalex',
                'last_updated': str(int(time.time())),
                'last_sync_date': last_sync_date,
                'openalex_min_year': str(min_year) if min_year is not None else None,
                'publication_count': str(_count_papers(conn)),
            },
        )
        return inserted
    finally:
        conn.close()


def update_openalex_database(
    db_path: str,
    since: Optional[str] = None,
    min_year: Optional[int] = None,
) -> DatabaseUpdateOutcome:
    since = since or os.environ.get('REFCHECKER_OPENALEX_SINCE') or _read_metadata_value(db_path, 'last_sync_date')

    if min_year is None:
        env_min_year = os.environ.get('REFCHECKER_OPENALEX_MIN_YEAR')
        if env_min_year and env_min_year.isdigit():
            min_year = int(env_min_year)

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'RefChecker/1.0.0 (https://github.com/markrussinovich/refchecker)',
    })

    partitions = list_openalex_date_partitions(session)
    if since:
        partitions = [partition for partition in partitions if partition[0] > since]

    if not partitions:
        return DatabaseUpdateOutcome(
            updated=False,
            skipped=True,
            message='OpenAlex database already up to date',
        )

    conn = _connect_sqlite(db_path)
    try:
        _ensure_common_schema(conn)
        inserted = 0
        newest_date = since or ''

        for partition_date, prefix in partitions:
            files = list_openalex_partition_files(session, prefix)
            logger.info('Processing OpenAlex partition %s (%d files)', partition_date, len(files))
            for key, _ in files:
                response = session.get(
                    f'{OPENALEX_BUCKET_URL}/{key}',
                    stream=True,
                    timeout=(30, 600),
                )
                try:
                    response.raise_for_status()
                    response.raw.decode_content = False
                    with gzip.GzipFile(fileobj=response.raw) as gz_handle:
                        with io.TextIOWrapper(gz_handle, encoding='utf-8') as text_handle:
                            inserted += _ingest_openalex_text_stream(
                                conn,
                                text_handle,
                                min_year=min_year,
                            )
                except Exception as exc:
                    logger.warning('Skipping OpenAlex file %s: %s', key, exc)
                finally:
                    response.close()
            newest_date = partition_date

        _ensure_common_indexes(conn)
        _write_metadata(
            conn,
            {
                'schema_version': LOCAL_DB_SCHEMA_VERSION,
                'database': 'openalex',
                'last_updated': str(int(time.time())),
                'last_sync_date': newest_date,
                'openalex_min_year': str(min_year) if min_year is not None else None,
                'publication_count': str(_count_papers(conn)),
            },
        )
    finally:
        conn.close()

    if inserted == 0:
        return DatabaseUpdateOutcome(
            updated=False,
            skipped=True,
            message='OpenAlex partitions contained no new matching works',
        )

    return DatabaseUpdateOutcome(
        updated=True,
        skipped=False,
        message='Updated OpenAlex database',
    )


def _paper_table_has_column(db_path: str, column_name: str) -> bool:
    if not os.path.exists(db_path):
        return False

    conn = sqlite3.connect(db_path)
    try:
        columns = {
            row[1]
            for row in conn.execute('PRAGMA table_info(papers)').fetchall()
        }
    finally:
        conn.close()
    return column_name in columns


def _discover_crossref_seed_paths(db_path: str) -> Dict[str, str]:
    db_dir = Path(db_path).expanduser().resolve().parent
    source_paths: Dict[str, str] = {}

    for db_name in CROSSREF_SEED_DATABASES:
        for filename in DATABASE_FILE_ALIASES.get(db_name, ()): 
            candidate = db_dir / filename
            if candidate.is_file():
                source_paths[db_name] = str(candidate)
                break

    return source_paths


def _crossref_seed_fingerprint(source_paths: Mapping[str, str]) -> str:
    fingerprint = {
        db_name: {
            'path': os.path.abspath(db_file),
            'mtime_ns': os.stat(db_file).st_mtime_ns,
            'size': os.stat(db_file).st_size,
        }
        for db_name, db_file in source_paths.items()
        if os.path.exists(db_file)
    }
    return json.dumps(fingerprint, sort_keys=True, separators=(',', ':'))


def _seed_crossref_from_source_database(
    conn: sqlite3.Connection,
    *,
    source_name: str,
    source_path: str,
) -> int:
    alias = f'seed_{source_name}'
    has_source_url = _paper_table_has_column(source_path, 'source_url')
    source_url_expr = 'source_url' if has_source_url else 'NULL'
    before_changes = conn.total_changes

    conn.execute(f"ATTACH DATABASE ? AS {alias}", (source_path,))
    try:
        conn.execute(
            f'''
            INSERT OR REPLACE INTO papers (
                paperId,
                title,
                normalized_paper_title,
                venue,
                year,
                externalIds_DOI,
                externalIds_ArXiv,
                authors,
                source_url
            )
            SELECT
                'crossref:' || LOWER(TRIM(externalIds_DOI)),
                title,
                normalized_paper_title,
                venue,
                year,
                LOWER(TRIM(externalIds_DOI)),
                externalIds_ArXiv,
                authors,
                CASE
                    WHEN externalIds_DOI IS NOT NULL AND TRIM(externalIds_DOI) <> ''
                        THEN 'https://doi.org/' || LOWER(TRIM(externalIds_DOI))
                    WHEN {source_url_expr} IS NOT NULL AND TRIM({source_url_expr}) <> ''
                        THEN {source_url_expr}
                    ELSE NULL
                END
            FROM {alias}.papers
            WHERE externalIds_DOI IS NOT NULL
              AND TRIM(externalIds_DOI) <> ''
              AND title IS NOT NULL
              AND TRIM(title) <> ''
            '''
        )
        conn.commit()
    finally:
        conn.execute(f'DETACH DATABASE {alias}')

    return conn.total_changes - before_changes


def build_crossref_database_from_local_sources(
    db_path: str,
    source_paths: Mapping[str, str],
) -> int:
    conn = _connect_sqlite(db_path)
    try:
        _ensure_common_schema(conn)
        conn.execute('DELETE FROM papers')
        conn.commit()

        for db_name in CROSSREF_SEED_DATABASES:
            source_path = source_paths.get(db_name)
            if not source_path:
                continue
            _seed_crossref_from_source_database(
                conn,
                source_name=db_name,
                source_path=source_path,
            )

        _ensure_common_indexes(conn)
        return _count_papers(conn)
    finally:
        conn.close()


def update_crossref_database(
    db_path: str,
    source_paths: Optional[Mapping[str, str]] = None,
) -> DatabaseUpdateOutcome:
    source_paths = dict(source_paths or _discover_crossref_seed_paths(db_path))
    if not source_paths:
        return DatabaseUpdateOutcome(
            updated=False,
            skipped=True,
            message='No local DOI-bearing source databases were available to seed CrossRef database',
        )

    seed_fingerprint = _crossref_seed_fingerprint(source_paths)
    if os.path.exists(db_path) and _read_metadata_value(db_path, 'seed_fingerprint') == seed_fingerprint:
        return DatabaseUpdateOutcome(
            updated=False,
            skipped=True,
            message='CrossRef database already up to date',
        )

    db_parent = os.path.dirname(os.path.abspath(db_path)) or '.'
    os.makedirs(db_parent, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=db_parent) as tmp_dir:
        temp_db_path = os.path.join(tmp_dir, 'crossref.db')
        publication_count = build_crossref_database_from_local_sources(temp_db_path, source_paths)

        conn = _connect_sqlite(temp_db_path)
        try:
            _write_metadata(
                conn,
                {
                    'schema_version': LOCAL_DB_SCHEMA_VERSION,
                    'database': 'crossref',
                    'last_updated': str(int(time.time())),
                    'publication_count': str(publication_count),
                    'seed_fingerprint': seed_fingerprint,
                    'seed_sources': json.dumps(list(source_paths), ensure_ascii=True),
                    'seed_strategy': 'local-doi-bootstrap',
                },
            )
        finally:
            conn.close()

        os.replace(temp_db_path, db_path)

    if publication_count == 0:
        return DatabaseUpdateOutcome(
            updated=False,
            skipped=True,
            message='CrossRef seed sources contained no DOI-bearing records',
        )

    return DatabaseUpdateOutcome(
        updated=True,
        skipped=False,
        message=f'Seeded CrossRef database from local DOI metadata ({publication_count} papers)',
    )


def update_local_database(
    db_name: str,
    db_path: str,
    *,
    api_key: Optional[str] = None,
    openalex_since: Optional[str] = None,
    openalex_min_year: Optional[int] = None,
    dblp_source_file: Optional[str] = None,
    acl_source_file: Optional[str] = None,
) -> DatabaseUpdateOutcome:
    if db_name == 's2':
        return _prepare_s2_database(db_path, api_key=api_key)
    if db_name == 'dblp':
        return update_dblp_database(db_path, source_file=dblp_source_file)
    if db_name == 'acl':
        return update_acl_database(db_path, source_file=acl_source_file)
    if db_name == 'openalex':
        return update_openalex_database(db_path, since=openalex_since, min_year=openalex_min_year)
    if db_name == 'crossref':
        return update_crossref_database(db_path)
    raise ValueError(f'Unsupported database: {db_name}')


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_logging()

    parser = argparse.ArgumentParser(description='Build or refresh a local RefChecker database')
    parser.add_argument('--database', required=True, choices=sorted(DATABASE_LABELS))
    parser.add_argument('--db-path', required=True, help='SQLite database path to build or refresh')
    parser.add_argument('--api-key', help='Semantic Scholar API key for S2 refreshes')
    parser.add_argument('--openalex-since', help='Only ingest OpenAlex partitions newer than YYYY-MM-DD')
    parser.add_argument('--openalex-min-year', type=int, help='Only ingest OpenAlex works published in this year or later')
    parser.add_argument('--dblp-source-file', help='Local dblp.xml.gz file to import instead of downloading')
    parser.add_argument('--acl-source-file', help='Local acl-anthology tarball to import instead of downloading')
    args = parser.parse_args(argv)

    outcome = update_local_database(
        args.database,
        args.db_path,
        api_key=args.api_key,
        openalex_since=args.openalex_since,
        openalex_min_year=args.openalex_min_year,
        dblp_source_file=args.dblp_source_file,
        acl_source_file=args.acl_source_file,
    )
    logger.info('%s: %s', DATABASE_LABELS.get(args.database, args.database), outcome.message)
    return 0 if outcome.skipped or outcome.updated else 1


if __name__ == '__main__':
    raise SystemExit(main())