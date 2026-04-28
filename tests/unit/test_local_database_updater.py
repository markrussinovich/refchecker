import gzip
import io
import json
import sqlite3
import tarfile

import pytest

from refchecker.checkers.local_semantic_scholar import LocalNonArxivReferenceChecker
from refchecker.database import local_database_updater as updater
from refchecker.database.download_semantic_scholar_db import SemanticScholarDownloader
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