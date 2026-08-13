import collections
import gzip
import io
import json
import logging
import sqlite3
import tarfile

import pytest

from refchecker.checkers.local_semantic_scholar import (
    FULL_SNAPSHOT_MIN_ROWS,
    LocalNonArxivReferenceChecker,
)
from refchecker.database import local_database_updater as updater
from refchecker.database.download_semantic_scholar_db import (
    MAX_MALFORMED_LINE_LOGS,
    SemanticScholarAuthError,
    SemanticScholarDiskSpaceError,
    SemanticScholarDownloader,
)
from refchecker.database.local_database_updater import (
    build_acl_database_from_tarball,
    build_dblp_database_from_xml_gz,
    build_openalex_database_from_snapshot_files,
    repair_local_database_schema,
    update_crossref_database,
)
from refchecker.utils.text_utils import normalize_paper_title


def test_build_dblp_database_from_xml_gz(tmp_path):
    xml_gz_path = tmp_path / 'dblp.xml.gz'
    db_path = tmp_path / 'dblp.db'

    xml_text = '''<?xml version="1.0" encoding="UTF-8"?>
<dblp>
  <inproceedings key="conf/nips/VaswaniSPUJGKP17">
    <author>Ashish Vaswani</author>
    <author>Noam Shazeer</author>
    <title>Attention is All you Need.</title>
    <booktitle>Advances in Neural Information Processing Systems</booktitle>
    <year>2017</year>
    <ee>https://doi.org/10.5555/3295222.3295349</ee>
    <ee>https://arxiv.org/abs/1706.03762</ee>
  </inproceedings>
</dblp>
'''
    with gzip.open(xml_gz_path, 'wt', encoding='utf-8') as handle:
        handle.write(xml_text)

    inserted = build_dblp_database_from_xml_gz(str(db_path), str(xml_gz_path))

    assert inserted == 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            'SELECT * FROM papers WHERE paperId = ?',
            ('dblp:conf/nips/VaswaniSPUJGKP17',),
        ).fetchone()
        assert row is not None
        assert row['title'] == 'Attention is All you Need.'
        assert row['venue'] == 'Advances in Neural Information Processing Systems'
        assert row['year'] == 2017
        assert row['externalIds_DOI'] == '10.5555/3295222.3295349'
        assert row['externalIds_ArXiv'] == '1706.03762'
        assert row['source_url'] == 'https://dblp.org/rec/conf/nips/VaswaniSPUJGKP17'
        assert json.loads(row['authors']) == ['Ashish Vaswani', 'Noam Shazeer']
    finally:
        conn.close()


def test_build_openalex_database_from_snapshot_files(tmp_path):
    snapshot_path = tmp_path / 'part_000.gz'
    db_path = tmp_path / 'openalex.db'

    records = [
        {
            'id': 'https://openalex.org/W2741809807',
            'display_name': 'Attention is All you Need',
            'type': 'article',
            'publication_year': 2017,
            'doi': 'https://doi.org/10.5555/3295222.3295349',
            'authorships': [
                {'author': {'display_name': 'Ashish Vaswani'}},
                {'author': {'display_name': 'Noam Shazeer'}},
            ],
            'primary_location': {
                'landing_page_url': 'https://arxiv.org/abs/1706.03762',
                'source': {'display_name': 'Advances in Neural Information Processing Systems'},
            },
            'locations': [
                {'landing_page_url': 'https://arxiv.org/abs/1706.03762'},
            ],
        },
        {
            'id': 'https://openalex.org/W2',
            'display_name': 'Dataset Record',
            'type': 'dataset',
            'publication_year': 2024,
            'authorships': [],
        },
    ]
    with gzip.open(snapshot_path, 'wt', encoding='utf-8') as handle:
        for record in records:
            handle.write(json.dumps(record) + '\n')

    inserted = build_openalex_database_from_snapshot_files(
        str(db_path),
        [str(snapshot_path)],
        min_year=2010,
        last_sync_date='2025-01-15',
    )

    assert inserted == 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            'SELECT * FROM papers WHERE paperId = ?',
            ('openalex:2741809807',),
        ).fetchone()
        assert row is not None
        assert row['title'] == 'Attention is All you Need'
        assert row['venue'] == 'Advances in Neural Information Processing Systems'
        assert row['year'] == 2017
        assert row['externalIds_DOI'] == '10.5555/3295222.3295349'
        assert row['externalIds_ArXiv'] == '1706.03762'
        assert row['source_url'] == 'https://openalex.org/W2741809807'

        last_sync = conn.execute(
            'SELECT value FROM metadata WHERE key = ?',
            ('last_sync_date',),
        ).fetchone()
        assert last_sync is not None
        assert last_sync[0] == '2025-01-15'
    finally:
        conn.close()


def test_update_openalex_database_checkpoints_completed_partitions(tmp_path, monkeypatch):
    db_path = tmp_path / 'openalex.db'

    monkeypatch.setattr(
        updater,
        'list_openalex_date_partitions',
        lambda session: [('2025-01-01', 'prefix-1'), ('2025-01-02', 'prefix-2')],
    )

    def fake_partition_files(session, prefix):
        if prefix == 'prefix-2':
            raise RuntimeError('simulated interruption')
        return []

    monkeypatch.setattr(updater, 'list_openalex_partition_files', fake_partition_files)

    with pytest.raises(RuntimeError, match='simulated interruption'):
        updater.update_openalex_database(str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            'SELECT value FROM metadata WHERE key = ?',
            ('last_sync_date',),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0] == '2025-01-01'


def test_build_acl_database_from_tarball(tmp_path):
        tarball_path = tmp_path / 'acl-anthology.tar.gz'
        db_path = tmp_path / 'acl_anthology.db'

        xml_text = '''<?xml version="1.0" encoding="UTF-8"?>
<collection id="2024.acl">
    <volume id="long" type="proceedings">
        <meta>
            <booktitle>Proceedings of <fixed-case>ACL</fixed-case> 2024</booktitle>
            <year>2024</year>
        </meta>
        <paper id="0">
            <title>Proceedings of ACL 2024</title>
            <url>2024.acl-long.0</url>
        </paper>
        <paper id="1">
            <title>Attention Patterns in <fixed-case>BERT</fixed-case> Models</title>
            <author><first>Alice</first><last>Smith</last></author>
            <author><first>Bob</first><last>Jones</last></author>
            <doi>10.18653/v1/2024.acl-long.1</doi>
            <url>2024.acl-long.1</url>
        </paper>
    </volume>
</collection>
'''

        with tarfile.open(tarball_path, 'w:gz') as archive:
                data = xml_text.encode('utf-8')
                member = tarfile.TarInfo('acl-org-acl-anthology-main/data/xml/2024.acl.xml')
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))

        inserted = build_acl_database_from_tarball(str(db_path), str(tarball_path))

        assert inserted == 1

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
                row = conn.execute(
                        'SELECT * FROM papers WHERE paperId = ?',
                        ('acl:2024.acl-long.1',),
                ).fetchone()
                assert row is not None
                assert row['title'] == 'Attention Patterns in BERT Models'
                assert row['venue'] == 'Proceedings of ACL 2024'
                assert row['year'] == 2024
                assert row['externalIds_DOI'] == '10.18653/v1/2024.acl-long.1'
                assert row['source_url'] == 'https://aclanthology.org/2024.acl-long.1'
                assert json.loads(row['authors']) == ['Alice Smith', 'Bob Jones']
        finally:
                conn.close()


def test_build_dblp_database_handles_named_entities(tmp_path):
    xml_gz_path = tmp_path / 'dblp.xml.gz'
    db_path = tmp_path / 'dblp.db'

    xml_text = '''<?xml version="1.0" encoding="UTF-8"?>
<dblp>
  <article key="journals/test/Mueller24">
    <author>J&ouml;rg M&uuml;ller</author>
    <title>F&auml;higkeit &amp; Logic.</title>
    <journal>Test Journal</journal>
    <year>2024</year>
    <ee>https://doi.org/10.1000/example-doi</ee>
  </article>
</dblp>
'''
    with gzip.open(xml_gz_path, 'wt', encoding='utf-8') as handle:
        handle.write(xml_text)

    inserted = build_dblp_database_from_xml_gz(str(db_path), str(xml_gz_path))

    assert inserted == 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            'SELECT * FROM papers WHERE paperId = ?',
            ('dblp:journals/test/Mueller24',),
        ).fetchone()
        assert row is not None
        assert row['title'] == 'Fähigkeit & Logic.'
        assert json.loads(row['authors']) == ['Jörg Müller']
        assert row['externalIds_DOI'] == '10.1000/example-doi'
    finally:
        conn.close()


def test_update_crossref_database_seeds_from_local_s2_db(tmp_path):
    s2_db_path = tmp_path / 'semantic_scholar.db'
    crossref_db_path = tmp_path / 'crossref.db'

    conn = sqlite3.connect(s2_db_path)
    try:
        conn.execute(
            '''
            CREATE TABLE papers (
                paperId TEXT PRIMARY KEY,
                title TEXT,
                normalized_paper_title TEXT,
                year INTEGER,
                authors TEXT,
                venue TEXT,
                externalIds_DOI TEXT,
                externalIds_ArXiv TEXT
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        conn.execute(
            '''
            INSERT INTO papers (
                paperId,
                title,
                normalized_paper_title,
                year,
                authors,
                venue,
                externalIds_DOI,
                externalIds_ArXiv
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                'S2-123',
                'Example DOI Paper',
                normalize_paper_title('Example DOI Paper'),
                2024,
                json.dumps(['Jane Example'], ensure_ascii=True),
                'Example Venue',
                '10.1000/example-doi',
                None,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    outcome = update_crossref_database(str(crossref_db_path))

    assert outcome.updated is True
    assert 'Seeded CrossRef database' in outcome.message

    conn = sqlite3.connect(crossref_db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            'SELECT * FROM papers WHERE paperId = ?',
            ('crossref:10.1000/example-doi',),
        ).fetchone()
        assert row is not None
        assert row['title'] == 'Example DOI Paper'
        assert row['externalIds_DOI'] == '10.1000/example-doi'
        assert row['source_url'] == 'https://doi.org/10.1000/example-doi'
        assert json.loads(row['authors']) == ['Jane Example']
    finally:
        conn.close()

    second_outcome = update_crossref_database(str(crossref_db_path))
    assert second_outcome.skipped is True
    assert second_outcome.message == 'CrossRef database already up to date'


def test_repair_local_database_schema_adds_missing_lookup_indexes_and_source_url(tmp_path):
    db_path = tmp_path / 'legacy.db'

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            '''
            CREATE TABLE papers (
                paperId TEXT PRIMARY KEY,
                title TEXT,
                normalized_paper_title TEXT,
                venue TEXT,
                year INTEGER,
                externalIds_DOI TEXT,
                externalIds_ArXiv TEXT,
                authors TEXT
            )
            '''
        )
        conn.execute(
            '''
            INSERT INTO papers (
                paperId,
                title,
                normalized_paper_title,
                venue,
                year,
                externalIds_DOI,
                externalIds_ArXiv,
                authors
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                'openalex:1',
                'Legacy Record',
                'legacyrecord',
                'LegacyConf',
                2024,
                '10.1000/legacy',
                '2401.00001',
                json.dumps(['Legacy Author'], ensure_ascii=True),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    report = repair_local_database_schema(str(db_path))

    assert report['added_columns'] == ['source_url']
    assert set(report['added_indexes']) == {
        'idx_papers_arxiv',
        'idx_papers_doi',
        'idx_papers_normalized_title',
    }
    assert report['missing_columns'] == []
    assert report['missing_indexes'] == []

    conn = sqlite3.connect(db_path)
    try:
        columns = {
            row[1]
            for row in conn.execute('PRAGMA table_info(papers)').fetchall()
        }
        indexes = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
    finally:
        conn.close()

    assert 'source_url' in columns
    assert {
        'idx_papers_arxiv',
        'idx_papers_doi',
        'idx_papers_normalized_title',
    }.issubset(indexes)


def test_local_checker_repairs_legacy_lookup_schema_on_open(tmp_path):
    db_path = tmp_path / 'legacy-openalex.db'

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            '''
            CREATE TABLE papers (
                paperId TEXT PRIMARY KEY,
                title TEXT,
                normalized_paper_title TEXT,
                venue TEXT,
                year INTEGER,
                externalIds_DOI TEXT,
                externalIds_ArXiv TEXT,
                authors TEXT
            )
            '''
        )
        conn.execute(
            '''
            INSERT INTO papers (
                paperId,
                title,
                normalized_paper_title,
                venue,
                year,
                externalIds_DOI,
                externalIds_ArXiv,
                authors
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                'openalex:2',
                'Checker Repair Record',
                'checkerrepairrecord',
                'RepairConf',
                2025,
                '10.1000/checker',
                '2501.00002',
                json.dumps(['Repair Author'], ensure_ascii=True),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    checker = LocalNonArxivReferenceChecker(
        db_path=str(db_path),
        database_label='OpenAlex',
        database_key='local_openalex',
    )
    checker.close()

    conn = sqlite3.connect(db_path)
    try:
        indexes = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
    finally:
        conn.close()

    assert {
        'idx_papers_arxiv',
        'idx_papers_doi',
        'idx_papers_normalized_title',
    }.issubset(indexes)


def test_semantic_scholar_downloader_stores_source_url(tmp_path):
    db_path = tmp_path / 'semantic_scholar.db'
    downloader = SemanticScholarDownloader(output_dir=str(tmp_path), db_path=str(db_path))
    try:
        downloader.store_papers_batch([
            {
                'paperId': 'S2-1',
                'title': 'Semantic Scholar URL Record',
                'authors': [{'name': 'Author One'}],
                'year': 2024,
                'externalIds': {'DOI': '10.1000/s2-url'},
                'url': 'https://www.semanticscholar.org/paper/S2-1',
            }
        ])
    finally:
        downloader.close()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            'SELECT source_url FROM papers WHERE paperId = ?',
            ('S2-1',),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row['source_url'] == 'https://www.semanticscholar.org/paper/S2-1'


def test_local_checker_prefers_source_url(tmp_path):
    xml_gz_path = tmp_path / 'dblp.xml.gz'
    db_path = tmp_path / 'dblp.db'

    xml_text = '''<?xml version="1.0" encoding="UTF-8"?>
<dblp>
  <inproceedings key="conf/nips/VaswaniSPUJGKP17">
    <author>Ashish Vaswani</author>
    <author>Noam Shazeer</author>
    <title>Attention is All you Need.</title>
    <booktitle>Advances in Neural Information Processing Systems</booktitle>
    <year>2017</year>
  </inproceedings>
</dblp>
'''
    with gzip.open(xml_gz_path, 'wt', encoding='utf-8') as handle:
        handle.write(xml_text)

    build_dblp_database_from_xml_gz(str(db_path), str(xml_gz_path))

    checker = LocalNonArxivReferenceChecker(
        db_path=str(db_path),
        database_label='DBLP',
        database_key='local_dblp',
    )
    try:
        verified, _errors, url = checker.verify_reference(
            {
                'title': 'Attention is All you Need',
                'authors': ['Ashish Vaswani', 'Noam Shazeer'],
                'year': 2017,
                'venue': 'Advances in Neural Information Processing Systems',
            }
        )
    finally:
        checker.close()

    assert verified is not None
    assert url == 'https://dblp.org/rec/conf/nips/VaswaniSPUJGKP17'


def test_local_checker_queries_acl_database(tmp_path):
        tarball_path = tmp_path / 'acl-anthology.tar.gz'
        db_path = tmp_path / 'acl_anthology.db'

        xml_text = '''<?xml version="1.0" encoding="UTF-8"?>
<collection id="2023.emnlp">
    <volume id="main" type="proceedings">
        <meta>
            <booktitle>Proceedings of EMNLP 2023</booktitle>
            <year>2023</year>
        </meta>
        <paper id="7">
            <title>Reliable Local ACL Matching</title>
            <author><first>Jane</first><last>Example</last></author>
            <author><first>John</first><last>Example</last></author>
            <doi>10.18653/v1/2023.emnlp-main.7</doi>
            <url>2023.emnlp-main.7</url>
        </paper>
    </volume>
</collection>
'''

        with tarfile.open(tarball_path, 'w:gz') as archive:
                data = xml_text.encode('utf-8')
                member = tarfile.TarInfo('acl-org-acl-anthology-main/data/xml/2023.emnlp.xml')
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))

        build_acl_database_from_tarball(str(db_path), str(tarball_path))

        checker = LocalNonArxivReferenceChecker(
                db_path=str(db_path),
                database_label='ACL Anthology',
                database_key='local_acl',
        )
        try:
                verified, _errors, url = checker.verify_reference(
                        {
                                'title': 'Reliable Local ACL Matching',
                                'authors': ['Jane Example', 'John Example'],
                                'year': 2023,
                                'venue': 'Proceedings of EMNLP 2023',
                        }
                )
        finally:
                checker.close()

        assert verified is not None
        assert verified['_matched_database'] == 'ACL Anthology'


def test_dblp_checker_does_not_flag_missing_arxiv_id_as_error(tmp_path):
    """When DBLP has no arXiv ID for a paper, citing an arXiv URL is NOT an error."""
    xml_gz_path = tmp_path / 'dblp.xml.gz'
    db_path = tmp_path / 'dblp.db'

    xml_text = '''<?xml version="1.0" encoding="UTF-8"?>
<dblp>
  <inproceedings key="conf/nips/ChengYFGYK0L24">
    <author>An-Chieh Cheng</author>
    <author>Hongxu Yin</author>
    <title>SpatialRGPT: Grounded Spatial Reasoning in Vision-Language Models.</title>
    <booktitle>NeurIPS</booktitle>
    <year>2024</year>
  </inproceedings>
</dblp>
'''
    with gzip.open(xml_gz_path, 'wt', encoding='utf-8') as handle:
        handle.write(xml_text)

    build_dblp_database_from_xml_gz(str(db_path), str(xml_gz_path))

    checker = LocalNonArxivReferenceChecker(
        db_path=str(db_path),
        database_label='DBLP',
        database_key='local_dblp',
    )
    try:
        verified, errors, url = checker.verify_reference(
            {
                'title': 'SpatialRGPT: Grounded spatial reasoning in vision language models',
                'authors': ['An-Chieh Cheng', 'Hongxu Yin'],
                'year': 2024,
                'venue': 'arXiv preprint',
                'url': 'https://arxiv.org/abs/2406.01584',
            }
        )
    finally:
        checker.close()

    assert verified is not None

    # No errors should contain an arXiv ID complaint
    arxiv_errors = [e for e in errors if e.get('error_type') == 'arxiv_id']
    assert arxiv_errors == [], f"Should NOT flag missing arXiv ID as error: {arxiv_errors}"

    # Venue should NOT be flagged as mismatch (arXiv preprint → NeurIPS)
    venue_errors = [
        e for e in errors
        if e.get('error_type') == 'venue' and 'mismatch' in e.get('error_details', '').lower()
    ]
    assert venue_errors == [], f"Should NOT flag arXiv → NeurIPS as venue mismatch: {venue_errors}"


def test_corr_venue_skipped_in_venue_missing_check(tmp_path):
    """CoRR (arXiv's formal name) should not trigger 'Venue missing' errors."""
    xml_gz_path = tmp_path / 'dblp.xml.gz'
    db_path = tmp_path / 'dblp.db'

    xml_text = '''<?xml version="1.0" encoding="UTF-8"?>
<dblp>
  <article key="journals/corr/abs-2312-11805">
    <author>Gemini Team</author>
    <title>Gemini: A Family of Highly Capable Multimodal Models.</title>
    <journal>CoRR</journal>
    <year>2023</year>
  </article>
</dblp>
'''
    with gzip.open(xml_gz_path, 'wt', encoding='utf-8') as handle:
        handle.write(xml_text)

    build_dblp_database_from_xml_gz(str(db_path), str(xml_gz_path))

    checker = LocalNonArxivReferenceChecker(
        db_path=str(db_path),
        database_label='DBLP',
        database_key='local_dblp',
    )
    try:
        verified, errors, url = checker.verify_reference(
            {
                'title': 'Gemini: A family of highly capable multimodal models',
                'authors': ['Gemini Team'],
                'year': 2023,
                'url': 'https://arxiv.org/abs/2312.11805',
            }
        )
    finally:
        checker.close()

    assert verified is not None

    venue_errors = [e for e in errors if e.get('error_type') == 'venue']
    assert venue_errors == [], f"CoRR should NOT trigger venue missing error: {venue_errors}"

def _make_papers_archive(path, paper_id, title):
    """Write a one-record gzipped S2 papers shard."""
    record = {
        'corpusid': 1,
        'paperId': paper_id,
        'title': title,
        'authors': [{'name': 'Author One'}],
        'year': 2024,
        'externalIds': {'DOI': f'10.1000/{paper_id}'},
        'venue': 'Test Venue',
    }
    with gzip.open(path, 'wt', encoding='utf-8') as handle:
        handle.write(json.dumps(record) + '\n')


def test_bootstrap_deletes_each_archive_after_ingest(tmp_path, monkeypatch):
    """Archives must not accumulate: the dataset plus the DB does not fit on a
    disk sized for the DB, which is what stalls a server bootstrap."""
    db_path = tmp_path / 'semantic_scholar.db'
    downloader = SemanticScholarDownloader(output_dir=str(tmp_path), db_path=str(db_path))
    try:
        files = [{'path': f'papers-{i}.gz', 'url': f'https://example/{i}', 'size': 10} for i in range(3)]
        monkeypatch.setattr(downloader, 'get_latest_release_id', lambda: '2026-01-01')
        monkeypatch.setattr(downloader, 'list_files', lambda release, dataset='papers': files)

        def _fake_download(file_meta):
            target = tmp_path / file_meta['path']
            _make_papers_archive(target, file_meta['path'], f"Paper {file_meta['path']}")
            return file_meta['path'], True

        monkeypatch.setattr(downloader, 'download_file', _fake_download)

        assert downloader.download_dataset_files() is True

        assert list(tmp_path.glob('*.gz')) == []
        count = downloader.conn.execute('SELECT COUNT(*) FROM papers').fetchone()[0]
        assert count == 3
        assert downloader.get_last_release_id() == '2026-01-01'
    finally:
        downloader.close()


def test_bootstrap_keeps_archives_when_opted_in(tmp_path, monkeypatch):
    monkeypatch.setenv('REFCHECKER_S2_KEEP_ARCHIVES', 'true')
    db_path = tmp_path / 'semantic_scholar.db'
    downloader = SemanticScholarDownloader(output_dir=str(tmp_path), db_path=str(db_path))
    try:
        files = [{'path': 'papers-0.gz', 'url': 'https://example/0', 'size': 10}]
        monkeypatch.setattr(downloader, 'get_latest_release_id', lambda: '2026-01-01')
        monkeypatch.setattr(downloader, 'list_files', lambda release, dataset='papers': files)

        def _fake_download(file_meta):
            _make_papers_archive(tmp_path / file_meta['path'], file_meta['path'], 'Kept')
            return file_meta['path'], True

        monkeypatch.setattr(downloader, 'download_file', _fake_download)
        assert downloader.download_dataset_files() is True
        assert (tmp_path / 'papers-0.gz').exists()
    finally:
        downloader.close()


def test_bootstrap_stops_before_filling_the_disk(tmp_path, monkeypatch):
    """Running the volume to zero corrupts SQLite; stop while there is room."""
    db_path = tmp_path / 'semantic_scholar.db'
    downloader = SemanticScholarDownloader(output_dir=str(tmp_path), db_path=str(db_path))
    try:
        files = [{'path': f'papers-{i}.gz', 'url': f'https://example/{i}', 'size': 10} for i in range(3)]
        monkeypatch.setattr(downloader, 'get_latest_release_id', lambda: '2026-01-01')
        monkeypatch.setattr(downloader, 'list_files', lambda release, dataset='papers': files)

        downloaded = []

        def _fake_download(file_meta):
            downloaded.append(file_meta['path'])
            _make_papers_archive(tmp_path / file_meta['path'], file_meta['path'], 'X')
            return file_meta['path'], True

        monkeypatch.setattr(downloader, 'download_file', _fake_download)

        usage = collections.namedtuple('usage', 'total used free')
        monkeypatch.setattr(
            'refchecker.database.download_semantic_scholar_db.shutil.disk_usage',
            lambda path: usage(100, 100, 0),
        )

        assert downloader.download_dataset_files() is False
        assert downloaded == []
    finally:
        downloader.close()


def _make_minimal_s2_db(path, release_id=None):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE papers (
                paperId TEXT PRIMARY KEY,
                title TEXT,
                normalized_paper_title TEXT,
                venue TEXT,
                year INTEGER,
                externalIds_DOI TEXT,
                externalIds_ArXiv TEXT,
                authors TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        if release_id is not None:
            conn.execute(
                "INSERT INTO metadata (key, value) VALUES ('last_release_id', ?)",
                (release_id,),
            )
        conn.commit()
    finally:
        conn.close()


def test_partial_database_does_not_claim_complete_coverage(tmp_path):
    """A DB still being built must not be trusted to disprove a reference."""
    db_path = tmp_path / 'partial.db'
    _make_minimal_s2_db(db_path)
    checker = LocalNonArxivReferenceChecker(db_path=str(db_path))
    try:
        assert checker.has_complete_coverage() is False
    finally:
        checker.close()


def test_finished_database_claims_complete_coverage(tmp_path):
    db_path = tmp_path / 'complete.db'
    _make_minimal_s2_db(db_path, release_id='2026-08-05')
    checker = LocalNonArxivReferenceChecker(db_path=str(db_path))
    try:
        assert checker.has_complete_coverage() is True
    finally:
        checker.close()


def test_interrupted_bootstrap_resumes_without_redownloading(tmp_path, monkeypatch):
    """Resuming must skip shards already ingested and only then mark complete."""
    db_path = tmp_path / 'semantic_scholar.db'
    files = [{'path': f'papers-{i}.gz', 'url': f'https://example/{i}', 'size': 10} for i in range(3)]
    downloaded = []

    def _install(downloader, fail_after=None):
        monkeypatch.setattr(downloader, 'get_latest_release_id', lambda: '2026-01-01')
        monkeypatch.setattr(downloader, 'list_files', lambda release, dataset='papers': files)

        def _fake_download(file_meta):
            if fail_after is not None and len(downloaded) >= fail_after:
                raise RuntimeError('connection reset')
            downloaded.append(file_meta['path'])
            _make_papers_archive(tmp_path / file_meta['path'], file_meta['path'], 'X')
            return file_meta['path'], True

        monkeypatch.setattr(downloader, 'download_file', _fake_download)

    first = SemanticScholarDownloader(output_dir=str(tmp_path), db_path=str(db_path))
    try:
        _install(first, fail_after=2)
        first.download_dataset_files()
        # Partial ingest must not advertise a finished snapshot.
        assert first.get_last_release_id() is None
    finally:
        first.close()

    assert downloaded == ['papers-0.gz', 'papers-1.gz']

    second = SemanticScholarDownloader(output_dir=str(tmp_path), db_path=str(db_path))
    try:
        _install(second)
        assert second.download_dataset_files() is True
        assert second.get_last_release_id() == '2026-01-01'
    finally:
        second.close()

    # Only the shard that was missing is fetched on the retry.
    assert downloaded == ['papers-0.gz', 'papers-1.gz', 'papers-2.gz']


def _make_repaired_s2_db(path):
    """A database with the full expected schema, as a finished build leaves it."""
    _make_minimal_s2_db(path, release_id='2026-08-05')
    report = repair_local_database_schema(str(path))
    assert not report['missing_columns'], report
    assert not report['missing_indexes'], report


def test_opening_healthy_database_performs_no_writes(tmp_path, monkeypatch):
    """Every check opens this file; writing on open serializes concurrent checks
    against each other on a database that can be ~90GB."""
    db_path = tmp_path / 'healthy.db'
    _make_repaired_s2_db(db_path)

    def _fail_on_repair(*args, **kwargs):
        raise AssertionError('schema repair ran against an already-healthy database')

    monkeypatch.setattr(
        'refchecker.checkers.local_semantic_scholar.repair_local_database_schema',
        _fail_on_repair,
    )

    before = db_path.stat().st_mtime_ns
    checker = LocalNonArxivReferenceChecker(db_path=str(db_path))
    try:
        assert checker.conn.execute('PRAGMA busy_timeout').fetchone()[0] > 0
    finally:
        checker.close()
    assert db_path.stat().st_mtime_ns == before


def test_opening_damaged_database_still_repairs(tmp_path):
    """A genuinely missing index must still be created."""
    db_path = tmp_path / 'damaged.db'
    _make_repaired_s2_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute('DROP INDEX idx_papers_doi')
    conn.commit()
    conn.close()

    checker = LocalNonArxivReferenceChecker(db_path=str(db_path))
    try:
        indexes = {
            row[0]
            for row in checker.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_papers_%'"
            ).fetchall()
        }
    finally:
        checker.close()
    assert 'idx_papers_doi' in indexes


def test_legacy_full_database_without_marker_reports_complete(tmp_path):
    """A database built before the completion marker existed must not be treated
    as a partial bootstrap, which would keep the S2 API in the hot path."""
    db_path = tmp_path / 'legacy-full.db'
    _make_repaired_s2_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM metadata WHERE key='last_release_id'")
    conn.execute(
        "INSERT INTO papers (rowid, title) VALUES (?, ?)",
        (FULL_SNAPSHOT_MIN_ROWS, 'a paper deep into a full snapshot'),
    )
    conn.commit()
    conn.close()

    checker = LocalNonArxivReferenceChecker(db_path=str(db_path))
    try:
        assert checker.has_complete_coverage() is True
    finally:
        checker.close()


def test_small_database_without_marker_reports_incomplete(tmp_path):
    db_path = tmp_path / 'partial.db'
    _make_repaired_s2_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM metadata WHERE key='last_release_id'")
    conn.commit()
    conn.close()

    checker = LocalNonArxivReferenceChecker(db_path=str(db_path))
    try:
        assert checker.has_complete_coverage() is False
    finally:
        checker.close()

def _http_error(status):
    import requests
    response = requests.Response()
    response.status_code = status
    response.url = 'https://api.semanticscholar.org/datasets/v1/release/latest'
    error = requests.exceptions.HTTPError(f'{status} Client Error', response=response)
    return error


def test_unauthorized_release_lookup_raises_auth_error(tmp_path):
    """A 401 from the datasets API must be distinguishable from a transient
    failure: it means SEMANTIC_SCHOLAR_API_KEY is missing or invalid and every
    future refresh will fail identically until an operator fixes it."""
    downloader = SemanticScholarDownloader(
        output_dir=str(tmp_path), db_path=str(tmp_path / 's2.db')
    )
    try:
        class _Session:
            def get(self, *args, **kwargs):
                raise _http_error(401)

            def close(self):
                pass

        downloader.session = _Session()
        with pytest.raises(SemanticScholarAuthError):
            downloader.get_latest_release_id()
    finally:
        downloader.close()


def test_unauthorized_file_listing_raises_instead_of_reporting_no_files(tmp_path):
    """list_files() previously swallowed the 401 and returned [], which the
    caller reported as 'no files found for the latest release'."""
    downloader = SemanticScholarDownloader(
        output_dir=str(tmp_path), db_path=str(tmp_path / 's2.db')
    )
    try:
        class _Session:
            def get(self, *args, **kwargs):
                raise _http_error(403)

            def close(self):
                pass

        downloader.session = _Session()
        with pytest.raises(SemanticScholarAuthError):
            downloader.list_files('2026-08-05')
    finally:
        downloader.close()


def test_refresh_reports_missing_api_key_instead_of_generic_failure(tmp_path, monkeypatch):
    """The deployed message was 'Semantic Scholar refresh failed', which gave an
    operator nothing to act on while the snapshot silently aged five months."""
    db_path = tmp_path / 's2.db'
    _make_minimal_s2_db(db_path, release_id='2026-03-10')

    class _AuthFailingDownloader:
        def __init__(self, *args, **kwargs):
            pass

        def refresh_database(self, *args, **kwargs):
            raise SemanticScholarAuthError('401 Unauthorized')

        def close(self):
            pass

    monkeypatch.setattr(updater, 'SemanticScholarDownloader', _AuthFailingDownloader)

    outcome = updater._prepare_s2_database(str(db_path), api_key=None)

    assert outcome.updated is False
    assert 'SEMANTIC_SCHOLAR_API_KEY' in outcome.message


def _gzipped_jsonl(records):
    """The datasets API serves gzipped JSONL from S3 with no Content-Encoding."""
    body = "\n".join(json.dumps(r) for r in records).encode("utf-8")
    return gzip.compress(body)


class _FakeRawStream:
    """Stands in for urllib3's raw response: read-only, not rewindable."""

    def __init__(self, payload):
        self._buffer = io.BytesIO(payload)
        self.decode_content = False

    def read(self, size=-1):
        return self._buffer.read(size)


class _FakeResponse:
    def __init__(self, payload):
        self.raw = _FakeRawStream(payload)
        self.status_code = 200
        self.headers = {}

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=False):
        raise AssertionError(
            "incremental ingest must decompress the archive, not read it as text"
        )


def _incremental_downloader(tmp_path, payload, monkeypatch):
    db_path = tmp_path / 'semantic_scholar.db'
    downloader = SemanticScholarDownloader(output_dir=str(tmp_path), db_path=str(db_path))

    class _Session:
        def get(self, *args, **kwargs):
            return _FakeResponse(payload)

        def close(self):
            pass

    monkeypatch.setattr(downloader, 'session', _Session())
    return downloader


def test_incremental_update_decompresses_gzipped_diff(tmp_path, monkeypatch):
    """The diff files are gzip; reading them as text yielded binary garbage on
    every line, so no update ever applied while the run still reported success."""
    payload = _gzipped_jsonl([
        {'paperId': 'S2-INC-1', 'title': 'Incrementally Updated Paper', 'year': 2026},
        {'paperId': 'S2-INC-2', 'title': 'Another Updated Paper', 'year': 2026},
    ])
    downloader = _incremental_downloader(tmp_path, payload, monkeypatch)
    try:
        processed = downloader._process_incremental_file('https://example/diff.gz', 'update')

        assert processed == 2
        titles = {
            row[0]
            for row in downloader.conn.execute('SELECT title FROM papers').fetchall()
        }
        assert 'Incrementally Updated Paper' in titles
    finally:
        downloader.close()


def test_incremental_update_still_reads_uncompressed_diff(tmp_path, monkeypatch):
    """Plain JSONL must keep working: the format is sniffed, not assumed."""
    payload = b'{"paperId": "S2-PLAIN", "title": "Uncompressed Diff", "year": 2026}\n'
    downloader = _incremental_downloader(tmp_path, payload, monkeypatch)
    try:
        assert downloader._process_incremental_file('https://example/diff', 'update') == 1
    finally:
        downloader.close()


def test_unreadable_incremental_file_aborts_instead_of_logging_every_line(tmp_path, monkeypatch):
    """An undecodable payload produced one log line per record and filled the
    production data disk with a multi-gigabyte log, taking the DB offline."""
    payload = b"\n".join(b"\x83\x95\xbe not json" for _ in range(5000))
    downloader = _incremental_downloader(tmp_path, payload, monkeypatch)

    class _Collector(logging.Handler):
        def __init__(self):
            super().__init__()
            self.messages = []

        def emit(self, record):
            self.messages.append(record.getMessage())

    collector = _Collector()
    module_logger = logging.getLogger(
        'refchecker.database.download_semantic_scholar_db'
    )
    module_logger.addHandler(collector)
    try:
        with pytest.raises(Exception):
            downloader._process_incremental_file('https://example/diff', 'update')

        per_line = [m for m in collector.messages if 'Malformed line' in m]
        assert len(per_line) <= MAX_MALFORMED_LINE_LOGS
    finally:
        module_logger.removeHandler(collector)
        downloader.close()


def test_failed_incremental_file_does_not_advance_recorded_release(tmp_path, monkeypatch):
    """Advancing the release marker past diffs we could not apply would skip
    them forever, which is how the snapshot silently stayed months out of date."""
    db_path = tmp_path / 'semantic_scholar.db'
    _make_minimal_s2_db(db_path, release_id='2026-03-10')
    downloader = SemanticScholarDownloader(output_dir=str(tmp_path), db_path=str(db_path))
    try:
        monkeypatch.setattr(downloader, 'get_latest_release_id', lambda: '2026-08-05')

        def _boom(file_url, operation_type):
            raise RuntimeError('unreadable diff')

        monkeypatch.setattr(downloader, '_process_incremental_file', _boom)

        result = downloader.download_incremental_updates([
            {'update_files': ['https://example/diff.gz'], 'delete_files': []}
        ])

        assert result is False
        assert downloader.get_last_release_id() == '2026-03-10'
    finally:
        downloader.close()


def test_interrupted_download_leaves_no_partial_archive(tmp_path, monkeypatch):
    """A download that dies part-way (dropped connection, full disk) used to
    leave a truncated .gz behind that nothing cleaned up."""
    db_path = tmp_path / 'semantic_scholar.db'
    downloader = SemanticScholarDownloader(output_dir=str(tmp_path), db_path=str(db_path))
    try:
        class _Response:
            status_code = 200
            headers = {'Content-Length': '100'}

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                yield b'partial data'
                raise OSError(28, 'No space left on device')

        class _Session:
            def get(self, *args, **kwargs):
                return _Response()

            def close(self):
                pass

        monkeypatch.setattr(downloader, 'session', _Session())

        with pytest.raises(OSError):
            downloader.download_file({'path': 'papers-0.gz', 'url': 'https://example/0', 'size': 100})

        leftovers = sorted(p.name for p in tmp_path.iterdir() if '.gz' in p.name)
        assert leftovers == []
    finally:
        downloader.close()


def test_incremental_ingest_stops_before_filling_the_disk(tmp_path, monkeypatch):
    """An incremental catch-up writes rows straight into the DB, so it can
    exhaust the volume without downloading anything -- which is what left the
    87GB production database raising "disk I/O error" on every lookup."""
    payload = _gzipped_jsonl([{'paperId': 'S2-1', 'title': 'Paper', 'year': 2026}])
    downloader = _incremental_downloader(tmp_path, payload, monkeypatch)
    try:
        monkeypatch.setattr(
            'refchecker.database.download_semantic_scholar_db.shutil.disk_usage',
            lambda path: collections.namedtuple('u', 'total used free')(100, 100, 1024),
        )

        with pytest.raises(RuntimeError, match='refusing to continue'):
            downloader._process_incremental_file('https://example/diff.gz', 'update')
    finally:
        downloader.close()


def test_disk_exhaustion_stops_the_catch_up_on_the_first_file(tmp_path, monkeypatch):
    """A full disk stops the whole run, not one file at a time.

    Every remaining diff hits the same wall, so continuing merely logged 1002
    identical errors across 499 files. The first failure has to end the run.
    """
    payload = _gzipped_jsonl([{'paperId': 'S2-1', 'title': 'Paper', 'year': 2026}])
    downloader = _incremental_downloader(tmp_path, payload, monkeypatch)
    try:
        monkeypatch.setattr(
            'refchecker.database.download_semantic_scholar_db.shutil.disk_usage',
            lambda path: collections.namedtuple('u', 'total used free')(100, 100, 1024),
        )
        diffs = [{
            'update_files': [f'https://example/diff-{i}.gz' for i in range(20)],
            'delete_files': [],
        }]

        with pytest.raises(SemanticScholarDiskSpaceError):
            downloader.download_incremental_updates(diffs)
    finally:
        downloader.close()


def test_disk_exhaustion_does_not_escalate_to_a_full_download(tmp_path, monkeypatch):
    """A full re-download needs far more room than the catch-up that just ran
    out, so escalating is guaranteed to fail and buries the real cause."""
    db_path = tmp_path / 'semantic_scholar.db'
    _make_minimal_s2_db(db_path, release_id='2026-03-10')
    downloader = SemanticScholarDownloader(output_dir=str(tmp_path), db_path=str(db_path))
    try:
        monkeypatch.setattr(
            downloader, 'check_for_updates',
            lambda: {
                'has_updates': True,
                'message': 'updates available',
                'incremental_updates': [{'update_files': ['u'], 'delete_files': []}],
            },
        )

        def _boom(_diffs):
            raise SemanticScholarDiskSpaceError('Only 4.9 GB free on /data')

        monkeypatch.setattr(downloader, 'download_incremental_updates', _boom)

        called = []
        monkeypatch.setattr(
            downloader, 'download_dataset_files',
            lambda *a, **k: called.append(True) or True,
        )

        downloader.refresh_database()

        assert called == [], 'must not fall back to a full dataset download'
    finally:
        downloader.close()


def test_completed_diffs_are_recorded_before_a_later_one_fails(tmp_path, monkeypatch):
    """A five-month catch-up that dies on the last diff used to discard every
    diff already applied, so the next run started over from the beginning."""
    db_path = tmp_path / 'semantic_scholar.db'
    _make_minimal_s2_db(db_path, release_id='2026-03-10')
    downloader = SemanticScholarDownloader(output_dir=str(tmp_path), db_path=str(db_path))
    try:
        monkeypatch.setattr(downloader, 'get_latest_release_id', lambda: '2026-08-05')

        def _process(file_url, operation_type):
            if file_url == 'bad':
                raise RuntimeError('unreadable diff')
            return 1

        monkeypatch.setattr(downloader, '_process_incremental_file', _process)

        result = downloader.download_incremental_updates([
            {'to_release': '2026-03-17', 'update_files': ['ok'], 'delete_files': []},
            {'to_release': '2026-04-07', 'update_files': ['ok'], 'delete_files': []},
            {'to_release': '2026-05-05', 'update_files': ['bad'], 'delete_files': []},
        ])

        assert result is False
        assert downloader.get_last_release_id() == '2026-04-07'
    finally:
        downloader.close()


def test_checkpoint_stops_at_the_first_failed_diff(tmp_path, monkeypatch):
    """The release marker is a watermark, so moving it past a diff that failed
    would skip those records permanently even though later diffs applied."""
    db_path = tmp_path / 'semantic_scholar.db'
    _make_minimal_s2_db(db_path, release_id='2026-03-10')
    downloader = SemanticScholarDownloader(output_dir=str(tmp_path), db_path=str(db_path))
    try:
        monkeypatch.setattr(downloader, 'get_latest_release_id', lambda: '2026-08-05')

        def _process(file_url, operation_type):
            if file_url == 'bad':
                raise RuntimeError('unreadable diff')
            return 1

        monkeypatch.setattr(downloader, '_process_incremental_file', _process)

        downloader.download_incremental_updates([
            {'to_release': '2026-03-17', 'update_files': ['bad'], 'delete_files': []},
            {'to_release': '2026-04-07', 'update_files': ['ok'], 'delete_files': []},
        ])

        assert downloader.get_last_release_id() == '2026-03-10'
    finally:
        downloader.close()


def test_disk_exhaustion_keeps_the_diffs_that_already_landed(tmp_path, monkeypatch):
    """Running out of room mid-catch-up must not cost the completed diffs; the
    rerun after a resize should pick up where it stopped."""
    db_path = tmp_path / 'semantic_scholar.db'
    _make_minimal_s2_db(db_path, release_id='2026-03-10')
    downloader = SemanticScholarDownloader(output_dir=str(tmp_path), db_path=str(db_path))
    try:
        monkeypatch.setattr(downloader, 'get_latest_release_id', lambda: '2026-08-05')

        def _process(file_url, operation_type):
            if file_url == 'full':
                raise SemanticScholarDiskSpaceError('Only 4.9 GB free on /data')
            return 1

        monkeypatch.setattr(downloader, '_process_incremental_file', _process)

        with pytest.raises(SemanticScholarDiskSpaceError):
            downloader.download_incremental_updates([
                {'to_release': '2026-03-17', 'update_files': ['ok'], 'delete_files': []},
                {'to_release': '2026-04-07', 'update_files': ['full'], 'delete_files': []},
            ])

        assert downloader.get_last_release_id() == '2026-03-17'
    finally:
        downloader.close()


def test_disk_check_at_a_commit_point_is_not_counted_as_a_bad_record(tmp_path, monkeypatch):
    """The periodic headroom check runs inside the per-line try block. Letting
    the generic handler swallow it hid a full disk and kept writing rows."""
    records = [{'paperId': f'S2-{i}', 'title': f'Paper {i}', 'year': 2026}
               for i in range(10001)]
    payload = _gzipped_jsonl(records)
    downloader = _incremental_downloader(tmp_path, payload, monkeypatch)
    try:
        usage = collections.namedtuple('u', 'total used free')
        calls = {'n': 0}

        def _disk_usage(path):
            # Roomy at the start so ingest begins, empty by the first commit.
            calls['n'] += 1
            free = 50 * 1024 ** 3 if calls['n'] == 1 else 1024
            return usage(100, 100, free)

        monkeypatch.setattr(
            'refchecker.database.download_semantic_scholar_db.shutil.disk_usage',
            _disk_usage,
        )

        with pytest.raises(SemanticScholarDiskSpaceError):
            downloader._process_incremental_file('https://example/diff.gz', 'update')
    finally:
        downloader.close()


def _rate_limited_downloader(tmp_path, monkeypatch, responses):
    db_path = tmp_path / 'semantic_scholar.db'
    _make_minimal_s2_db(db_path, release_id='2026-03-10')
    downloader = SemanticScholarDownloader(output_dir=str(tmp_path), db_path=str(db_path))

    class _Resp:
        def __init__(self, status, payload=None):
            self.status_code = status
            self._payload = payload or {}
            self.headers = {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    queue = list(responses)

    class _Session:
        def get(self, *args, **kwargs):
            return _Resp(*queue.pop(0))

        def close(self):
            pass

    monkeypatch.setattr(downloader, 'session', _Session())
    monkeypatch.setattr(
        'refchecker.database.download_semantic_scholar_db.time.sleep', lambda s: None
    )
    return downloader


def test_rate_limited_diff_request_is_retried(tmp_path, monkeypatch):
    """A 429 is transient and says nothing about whether updates exist."""
    diffs = {'diffs': [{'update_files': ['https://example/u.gz'], 'delete_files': []}]}
    downloader = _rate_limited_downloader(
        tmp_path, monkeypatch, [(429, None), (429, None), (200, diffs)]
    )
    try:
        monkeypatch.setattr(downloader, 'get_latest_release_id', lambda: '2026-08-05')

        result = downloader.check_incremental_updates('2026-03-10')

        assert result == diffs['diffs']
    finally:
        downloader.close()


def test_persistent_rate_limit_does_not_trigger_full_redownload(tmp_path, monkeypatch):
    """Treating a throttle as "no incremental updates" made refresh fall through
    to re-downloading the whole ~90GB dataset, which cannot fit beside the DB."""
    downloader = _rate_limited_downloader(
        tmp_path, monkeypatch, [(429, None)] * 10
    )
    try:
        monkeypatch.setattr(downloader, 'get_latest_release_id', lambda: '2026-08-05')

        def _must_not_run(*args, **kwargs):
            raise AssertionError('rate limiting must not trigger a full dataset download')

        monkeypatch.setattr(downloader, 'download_dataset_files', _must_not_run)

        assert downloader.refresh_database() is False
        assert downloader.get_last_release_id() == '2026-03-10'
    finally:
        downloader.close()


def test_rate_limited_release_lookup_is_retried(tmp_path, monkeypatch):
    """Every datasets endpoint throttles, not just diffs; a 429 on the release
    lookup previously aborted the refresh and escalated to a full download."""
    downloader = _rate_limited_downloader(
        tmp_path, monkeypatch, [(429, None), (200, {'release_id': '2026-08-05'})]
    )
    try:
        assert downloader.get_latest_release_id() == '2026-08-05'
    finally:
        downloader.close()


def test_rate_limited_file_listing_is_retried(tmp_path, monkeypatch):
    downloader = _rate_limited_downloader(
        tmp_path,
        monkeypatch,
        [(429, None), (200, {'files': ['https://example/papers-0.gz?token=x']})],
    )
    try:
        files = downloader.list_files('2026-08-05', dataset='papers')

        assert len(files) == 1
    finally:
        downloader.close()


def test_signed_dataset_urls_are_not_written_to_logs(tmp_path, monkeypatch):
    """Dataset links carry AWSAccessKeyId, Signature and x-amz-security-token;
    those must not be recorded in a log file that operators read and share."""
    signed = (
        'https://ai2-s2ag.s3.amazonaws.com/updates/papers/shard.gz'
        '?AWSAccessKeyId=ASIASECRET&Signature=abc%3D&x-amz-security-token=TOKEN'
    )
    downloader = _incremental_downloader(tmp_path, b'not json\n', monkeypatch)

    class _Collector(logging.Handler):
        def __init__(self):
            super().__init__()
            self.messages = []

        def emit(self, record):
            self.messages.append(record.getMessage())

    collector = _Collector()
    module_logger = logging.getLogger(
        'refchecker.database.download_semantic_scholar_db'
    )
    module_logger.setLevel(logging.DEBUG)
    module_logger.addHandler(collector)
    try:
        downloader._process_incremental_file(signed, 'update')

        blob = ' '.join(collector.messages)
        assert 'ASIASECRET' not in blob
        assert 'x-amz-security-token' not in blob
        assert 'shard.gz' in blob
    finally:
        module_logger.removeHandler(collector)
        downloader.close()
