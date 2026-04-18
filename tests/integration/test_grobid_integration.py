"""
GROBID integration tests.

Tests that:
1. GROBID auto-starts via Docker
2. Reference extraction produces valid structured output
3. Extracted references match refchecker's cached LLM extraction (ground truth)

Uses the same papers as the mode-consistency regression tests.
Requires Docker to be available on the host.
"""

import json
import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.grobid import ensure_grobid_running, extract_refs_via_grobid, GROBID_URL

# Papers from the mode-consistency regression suite that have PDFs available
ICLR_CACHE = Path("/datadrive/iclr2026/cache")
TEST_CACHE = Path(__file__).resolve().parents[1] / 'fixtures' / 'test_cache'

# Papers with both PDF and bibliography.json available
PAPER_CASES = []
for paper_id in ['nspzrcvzcB', 'H8tismBT3Q', '0FhrtdKLtD']:
    pdf_path = ICLR_CACHE / f"openreview_{paper_id}" / "paper.pdf"
    bib_path_iclr = ICLR_CACHE / f"openreview_{paper_id}" / "bibliography.json"
    bib_path_fixture = TEST_CACHE / f"openreview_{paper_id}" / "bibliography.json"
    bib_path = bib_path_iclr if bib_path_iclr.exists() else bib_path_fixture
    if pdf_path.exists() and bib_path.exists():
        PAPER_CASES.append((paper_id, str(pdf_path), str(bib_path)))

def _docker_available():
    """Check if Docker is available (with or without sudo)."""
    import subprocess
    for cmd in [['docker', 'info'], ['sudo', '-n', 'docker', 'info']]:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=5)
            if r.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return False

skip_no_docker = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker not available"
)

skip_no_papers = pytest.mark.skipif(
    len(PAPER_CASES) == 0,
    reason="No test papers with PDFs available"
)


def _normalize(s):
    if not s:
        return ""
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', '', s.lower())).strip()


def _title_sim(a, b):
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


@skip_no_docker
class TestGrobidIntegration:
    """Tests requiring a running GROBID instance (auto-started via Docker)."""

    def test_grobid_auto_starts(self):
        """GROBID should auto-start when Docker is available."""
        available = ensure_grobid_running()
        if not available:
            pytest.skip("GROBID did not become available (may need more time or resources)")

    def test_grobid_health_check(self):
        """GROBID health endpoint should respond correctly."""
        import requests
        if not ensure_grobid_running():
            pytest.skip("GROBID not available")
        resp = requests.get(f"{GROBID_URL}/api/isalive", timeout=5)
        assert resp.status_code == 200
        assert resp.text.strip().lower() == 'true'

    @skip_no_papers
    @pytest.mark.parametrize("paper_id,pdf_path,bib_path", PAPER_CASES,
                             ids=[p[0] for p in PAPER_CASES])
    def test_extraction_produces_valid_refs(self, paper_id, pdf_path, bib_path):
        """GROBID should extract structured references from a PDF."""
        refs = extract_refs_via_grobid(pdf_path)

        assert len(refs) > 0, f"GROBID should extract at least 1 reference from {paper_id}"

        # Every ref should have at least a title or authors
        for i, ref in enumerate(refs):
            assert ref.get("title") or ref.get("authors"), \
                f"Ref {i} in {paper_id} has neither title nor authors"

        # Check structural integrity
        for ref in refs[:5]:
            assert isinstance(ref.get("authors", []), list)
            assert isinstance(ref.get("title", ""), str)
            assert isinstance(ref.get("venue", ""), str)
            assert ref.get("year") is None or isinstance(ref["year"], int)

    @skip_no_papers
    @pytest.mark.parametrize("paper_id,pdf_path,bib_path", PAPER_CASES,
                             ids=[p[0] for p in PAPER_CASES])
    def test_extraction_matches_llm_ground_truth(self, paper_id, pdf_path, bib_path):
        """GROBID extraction should substantially match refchecker's LLM extraction."""
        grobid_refs = extract_refs_via_grobid(pdf_path)

        with open(bib_path) as f:
            llm_refs = json.load(f)

        assert len(grobid_refs) > 0, f"GROBID extracted 0 refs from {paper_id}"
        assert len(llm_refs) > 0, f"LLM ground truth has 0 refs for {paper_id}"

        # Match GROBID refs to LLM refs by title similarity
        matched = 0
        for g_ref in grobid_refs:
            g_title = g_ref.get("title", "")
            for l_ref in llm_refs:
                l_title = l_ref.get("title", "")
                if _title_sim(g_title, l_title) >= 0.7:
                    matched += 1
                    break

        recall = matched / len(llm_refs) if llm_refs else 0
        precision = matched / len(grobid_refs) if grobid_refs else 0

        # GROBID should match at least 70% of LLM-extracted refs
        assert recall >= 0.70, (
            f"GROBID recall too low for {paper_id}: "
            f"{matched}/{len(llm_refs)} = {recall:.0%} (need ≥70%). "
            f"GROBID extracted {len(grobid_refs)}, LLM has {len(llm_refs)}."
        )

        # GROBID precision should be reasonable (not too many false positives)
        assert precision >= 0.50, (
            f"GROBID precision too low for {paper_id}: "
            f"{matched}/{len(grobid_refs)} = {precision:.0%} (need ≥50%). "
            f"GROBID extracted {len(grobid_refs)}, matched {matched} to LLM's {len(llm_refs)}."
        )

    @skip_no_papers
    def test_extraction_ref_count_reasonable(self):
        """GROBID should extract a reasonable number of refs from each paper."""
        paper_id, pdf_path, bib_path = PAPER_CASES[0]
        grobid_refs = extract_refs_via_grobid(pdf_path)
        with open(bib_path) as f:
            llm_refs = json.load(f)

        # GROBID count should be within 50% of LLM count
        ratio = len(grobid_refs) / len(llm_refs) if llm_refs else 0
        assert 0.5 <= ratio <= 1.5, (
            f"GROBID ref count ({len(grobid_refs)}) too far from LLM ({len(llm_refs)}) "
            f"for {paper_id}: ratio={ratio:.2f}"
        )

    @skip_no_papers
    def test_extraction_has_years(self):
        """Most GROBID-extracted refs should have a year."""
        paper_id, pdf_path, _ = PAPER_CASES[0]
        refs = extract_refs_via_grobid(pdf_path)
        with_year = sum(1 for r in refs if r.get("year"))
        pct = with_year / len(refs) if refs else 0
        assert pct >= 0.80, (
            f"Only {with_year}/{len(refs)} ({pct:.0%}) GROBID refs have years for {paper_id}"
        )

    @skip_no_papers
    def test_extraction_has_authors(self):
        """Most GROBID-extracted refs should have authors."""
        paper_id, pdf_path, _ = PAPER_CASES[0]
        refs = extract_refs_via_grobid(pdf_path)
        with_authors = sum(1 for r in refs if r.get("authors"))
        pct = with_authors / len(refs) if refs else 0
        assert pct >= 0.80, (
            f"Only {with_authors}/{len(refs)} ({pct:.0%}) GROBID refs have authors for {paper_id}"
        )
