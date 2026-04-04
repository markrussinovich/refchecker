"""
Tests for venue matching in local_semantic_scholar.py verify_reference().

Ensures the local DB checker produces venue warnings/errors matching
the behavior of the online Semantic Scholar checker.
"""

import json
import sqlite3
import tempfile
import os
import pytest

from refchecker.checkers.local_semantic_scholar import LocalNonArxivReferenceChecker


def _create_test_db(papers):
    """
    Create a temporary SQLite DB with the slim schema and insert papers.

    Args:
        papers: list of dicts with keys matching the papers table columns.
            Required: paperId, title.  Optional: normalized_paper_title,
            year, authors (list of dicts or JSON string), venue, url,
            externalIds_DOI, externalIds_ArXiv.

    Returns:
        (db_path, tmp_dir)  – caller must clean up tmp_dir.
    """
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
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
    """)
    conn.execute("""
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX idx_papers_normalized_title ON papers(normalized_paper_title)")
    conn.execute("CREATE INDEX idx_papers_doi ON papers(externalIds_DOI)")
    conn.execute("CREATE INDEX idx_papers_arxiv ON papers(externalIds_ArXiv)")

    import re
    for p in papers:
        title = p.get("title", "")
        norm = re.sub(r'[^a-z0-9]', '', title.lower())
        authors = p.get("authors", [])
        if isinstance(authors, list):
            # Compact format: store as ["name1", "name2"]
            if authors and isinstance(authors[0], dict):
                authors = json.dumps([a.get("name", "") for a in authors])
            else:
                authors = json.dumps(authors)
        conn.execute(
            "INSERT INTO papers VALUES (?,?,?,?,?,?,?,?)",
            (
                p.get("paperId", "1"),
                title,
                p.get("normalized_paper_title", norm),
                p.get("year"),
                authors,
                p.get("venue", ""),
                p.get("externalIds_DOI"),
                p.get("externalIds_ArXiv"),
            ),
        )
    conn.commit()
    conn.close()
    return db_path, tmp_dir


@pytest.fixture
def _make_checker():
    """Factory fixture that creates a checker backed by a temp DB."""
    checkers = []
    tmp_dirs = []

    def _factory(papers):
        db_path, tmp_dir = _create_test_db(papers)
        tmp_dirs.append(tmp_dir)
        checker = LocalNonArxivReferenceChecker(db_path=db_path)
        checkers.append(checker)
        return checker

    yield _factory

    for c in checkers:
        c.close()
    import shutil
    for d in tmp_dirs:
        shutil.rmtree(d, ignore_errors=True)


# ── Venue mismatch ──────────────────────────────────────────────────

def test_venue_mismatch_produces_warning(_make_checker):
    """When cited venue differs from DB venue, a venue warning is produced."""
    checker = _make_checker([{
        "paperId": "100",
        "title": "Attention Is All You Need",
        "year": 2017,
        "authors": [{"authorId": "1", "name": "A. Vaswani"}],
        "venue": "Neural Information Processing Systems",
        "externalIds_DOI": "10.5555/3295222.3295349",
    }])

    reference = {
        "title": "Attention Is All You Need",
        "authors": ["A. Vaswani"],
        "year": 2017,
        "venue": "ICML",
        "doi": "10.5555/3295222.3295349",
    }

    verified_data, errors, url = checker.verify_reference(reference)
    assert verified_data is not None
    venue_issues = [e for e in errors if e.get("warning_type") == "venue" or e.get("error_type") == "venue"]
    assert len(venue_issues) >= 1, f"Expected venue warning/error, got: {errors}"


def test_venue_match_no_warning(_make_checker):
    """When cited venue matches DB venue, no venue warning is produced."""
    checker = _make_checker([{
        "paperId": "100",
        "title": "Attention Is All You Need",
        "year": 2017,
        "authors": [{"authorId": "1", "name": "A. Vaswani"}],
        "venue": "Neural Information Processing Systems",
        "externalIds_DOI": "10.5555/3295222.3295349",
    }])

    reference = {
        "title": "Attention Is All You Need",
        "authors": ["A. Vaswani"],
        "year": 2017,
        "venue": "Neural Information Processing Systems",
        "doi": "10.5555/3295222.3295349",
    }

    verified_data, errors, url = checker.verify_reference(reference)
    assert verified_data is not None
    venue_issues = [e for e in errors if e.get("warning_type") == "venue" or e.get("error_type") == "venue"]
    assert len(venue_issues) == 0, f"Unexpected venue issue: {venue_issues}"


# ── Missing venue ───────────────────────────────────────────────────

def test_missing_venue_produces_error(_make_checker):
    """When reference has no venue but DB has a real venue, an error is produced."""
    checker = _make_checker([{
        "paperId": "200",
        "title": "Deep Residual Learning",
        "year": 2016,
        "authors": [{"authorId": "2", "name": "K. He"}],
        "venue": "Computer Vision and Pattern Recognition",
        "externalIds_DOI": "10.1109/CVPR.2016.90",
    }])

    reference = {
        "title": "Deep Residual Learning",
        "authors": ["K. He"],
        "year": 2016,
        "doi": "10.1109/CVPR.2016.90",
        # No venue field
    }

    verified_data, errors, url = checker.verify_reference(reference)
    assert verified_data is not None
    venue_errors = [e for e in errors if e.get("error_type") == "venue"]
    assert len(venue_errors) >= 1, f"Expected venue error for missing venue, got: {errors}"
    assert "missing" in venue_errors[0]["error_details"].lower() or "should include" in venue_errors[0]["error_details"].lower()


def test_missing_venue_skips_arxiv_venue(_make_checker):
    """When DB venue is 'ArXiv' (generic), no missing-venue error is produced."""
    checker = _make_checker([{
        "paperId": "300",
        "title": "Some ArXiv Paper",
        "year": 2023,
        "authors": [{"authorId": "3", "name": "J. Doe"}],
        "venue": "ArXiv",
        "externalIds_DOI": "10.1234/test",
    }])

    reference = {
        "title": "Some ArXiv Paper",
        "authors": ["J. Doe"],
        "year": 2023,
        "doi": "10.1234/test",
    }

    verified_data, errors, url = checker.verify_reference(reference)
    assert verified_data is not None
    venue_errors = [e for e in errors if e.get("error_type") == "venue"]
    assert len(venue_errors) == 0, f"Should not flag generic ArXiv as missing venue: {venue_errors}"


# ── Venue via journal field ─────────────────────────────────────────

def test_venue_check_uses_journal_field(_make_checker):
    """The checker reads cited venue from 'journal' if 'venue' is absent."""
    checker = _make_checker([{
        "paperId": "400",
        "title": "A Study of Transformers",
        "year": 2020,
        "authors": [{"authorId": "4", "name": "X. Author"}],
        "venue": "Nature",
        "externalIds_DOI": "10.1038/test",
    }])

    reference = {
        "title": "A Study of Transformers",
        "authors": ["X. Author"],
        "year": 2020,
        "journal": "Science",  # Different from "Nature"
        "doi": "10.1038/test",
    }

    verified_data, errors, url = checker.verify_reference(reference)
    assert verified_data is not None
    venue_issues = [e for e in errors if e.get("warning_type") == "venue" or e.get("error_type") == "venue"]
    assert len(venue_issues) >= 1, f"Expected venue mismatch for Science vs Nature: {venue_issues}"


# ── Title mismatch ──────────────────────────────────────────────────

def test_title_mismatch_produces_error(_make_checker):
    """When paper is found by DOI but titles differ significantly, a title error is produced."""
    checker = _make_checker([{
        "paperId": "500",
        "title": "Actual Paper Title That Is Different",
        "year": 2021,
        "authors": [{"authorId": "5", "name": "A. Author"}],
        "venue": "",
        "externalIds_DOI": "10.9999/unique-doi",
    }])

    reference = {
        "title": "Completely Wrong Title Not Matching At All",
        "authors": ["A. Author"],
        "year": 2021,
        "doi": "10.9999/unique-doi",
    }

    verified_data, errors, url = checker.verify_reference(reference)
    assert verified_data is not None
    title_errors = [e for e in errors if e.get("error_type") == "title"]
    assert len(title_errors) >= 1, f"Expected title error, got: {errors}"


# ── ArXiv URL suggestion ───────────────────────────────────────────

def test_arxiv_url_suggestion(_make_checker):
    """When paper has ArXiv ID but reference lacks arXiv URL, an info is produced."""
    checker = _make_checker([{
        "paperId": "600",
        "title": "Neural Scaling Laws",
        "year": 2020,
        "authors": [{"authorId": "6", "name": "J. Kaplan"}],
        "venue": "",
        "externalIds_DOI": "10.1234/scaling",
        "externalIds_ArXiv": "2001.08361",
    }])

    reference = {
        "title": "Neural Scaling Laws",
        "authors": ["J. Kaplan"],
        "year": 2020,
        "doi": "10.1234/scaling",
        "url": "https://example.com/paper",
    }

    verified_data, errors, url = checker.verify_reference(reference)
    assert verified_data is not None
    url_infos = [e for e in errors if e.get("info_type") == "url"]
    assert len(url_infos) >= 1, f"Expected arXiv URL suggestion, got: {errors}"
    assert "2001.08361" in url_infos[0]["info_details"]


def test_arxiv_url_suggestion_not_when_present(_make_checker):
    """When reference already has the arXiv URL, no suggestion is produced."""
    checker = _make_checker([{
        "paperId": "700",
        "title": "Neural Scaling Laws",
        "year": 2020,
        "authors": [{"authorId": "7", "name": "J. Kaplan"}],
        "venue": "",
        "externalIds_ArXiv": "2001.08361",
    }])

    reference = {
        "title": "Neural Scaling Laws",
        "authors": ["J. Kaplan"],
        "year": 2020,
        "url": "https://arxiv.org/abs/2001.08361",
    }

    verified_data, errors, url = checker.verify_reference(reference)
    assert verified_data is not None
    url_infos = [e for e in errors if e.get("info_type") == "url"]
    assert len(url_infos) == 0, f"Should not suggest arXiv URL when already present: {url_infos}"


# ── ArXiv URL mismatch (wrong arXiv URL, real paper) ──────────────

def test_wrong_arxiv_url_detected_when_paper_found_by_title(_make_checker):
    """
    Regression: a reference with an incorrect arXiv URL but a real paper
    title must flag an arxiv_id error — the wrong URL should NOT be silently
    accepted as the desired citation.
    """
    # DB contains two papers: the "correct" one (Paper A) with its own ArXiv ID,
    # and a different paper (Paper B) at the ArXiv ID that the reference cites.
    checker = _make_checker([
        {
            "paperId": "A1",
            "title": "Attention Is All You Need",
            "year": 2017,
            "authors": [{"authorId": "1", "name": "A. Vaswani"}],
            "venue": "NeurIPS",
            "externalIds_ArXiv": "1706.03762",
        },
        {
            "paperId": "B2",
            "title": "Completely Different Paper",
            "year": 2019,
            "authors": [{"authorId": "2", "name": "B. Smith"}],
            "venue": "",
            "externalIds_ArXiv": "1901.99999",
        },
    ])

    reference = {
        "title": "Attention Is All You Need",
        "authors": ["A. Vaswani"],
        "year": 2017,
        # Wrong arXiv URL — points to Paper B
        "url": "https://arxiv.org/abs/1901.99999",
    }

    verified_data, errors, url = checker.verify_reference(reference)
    # Should still resolve the correct paper by title
    assert verified_data is not None
    assert verified_data["title"] == "Attention Is All You Need"

    # Must flag the wrong arXiv ID
    arxiv_errors = [e for e in errors if e.get("error_type") == "arxiv_id"]
    assert len(arxiv_errors) >= 1, f"Expected arxiv_id error, got: {errors}"
    assert "1706.03762" in arxiv_errors[0].get("ref_url_correct", "") or \
           "1706.03762" in arxiv_errors[0].get("error_details", "")


def test_wrong_arxiv_url_paper_has_no_arxiv_id(_make_checker):
    """
    When the reference cites an arXiv URL but the matched paper has NO ArXiv ID,
    the arXiv URL should be flagged as incorrect.
    """
    checker = _make_checker([
        {
            "paperId": "C3",
            "title": "Some Conference Paper",
            "year": 2020,
            "authors": [{"authorId": "3", "name": "C. Author"}],
            "venue": "ICML",
            "externalIds_DOI": "10.1234/conf2020",
            # No ArXiv ID
        },
    ])

    reference = {
        "title": "Some Conference Paper",
        "authors": ["C. Author"],
        "year": 2020,
        "url": "https://arxiv.org/abs/2005.12345",
    }

    verified_data, errors, url = checker.verify_reference(reference)
    assert verified_data is not None
    arxiv_errors = [e for e in errors if e.get("error_type") == "arxiv_id"]
    assert len(arxiv_errors) >= 1, f"Expected arxiv_id error for spurious arXiv URL, got: {errors}"


def test_correct_arxiv_url_no_error(_make_checker):
    """
    When the arXiv URL in the reference matches the paper's ArXiv ID,
    no arxiv_id error should be produced.
    """
    checker = _make_checker([
        {
            "paperId": "D4",
            "title": "Attention Is All You Need",
            "year": 2017,
            "authors": [{"authorId": "1", "name": "A. Vaswani"}],
            "venue": "NeurIPS",
            "externalIds_ArXiv": "1706.03762",
        },
    ])

    reference = {
        "title": "Attention Is All You Need",
        "authors": ["A. Vaswani"],
        "year": 2017,
        "url": "https://arxiv.org/abs/1706.03762",
    }

    verified_data, errors, url = checker.verify_reference(reference)
    assert verified_data is not None
    arxiv_errors = [e for e in errors if e.get("error_type") == "arxiv_id"]
    assert len(arxiv_errors) == 0, f"No arxiv_id error expected for correct URL, got: {errors}"
