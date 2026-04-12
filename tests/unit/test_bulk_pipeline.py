from types import SimpleNamespace

from refchecker.core.bulk_pipeline import BulkHallucinationBatcher, BulkLLMExtractionBatcher, BulkProgressReporter, BulkVerificationCache


class _FakeExtractionProvider:
    def _call_llm(self, prompt):
        assert 'ITEM 0' in prompt
        assert 'ITEM 1' in prompt
        return (
            '[\n'
            '  {"index": 0, "references": ["A One#Paper One#Venue One#2024#https://one"]},\n'
            '  {"index": 1, "references": ["B Two#Paper Two#Venue Two#2025#https://two"]}\n'
            ']'
        )


class _FakeExtractionChecker:
    def __init__(self):
        self.llm_extractor = SimpleNamespace(llm_provider=_FakeExtractionProvider())

    def _process_llm_extracted_references(self, references):
        return [{'raw': reference} for reference in references]


class _FakeHallucinationVerifier:
    available = True

    def _call(self, system_prompt, user_prompt):
        assert 'ITEM 0' in user_prompt
        assert 'ITEM 1' in user_prompt
        return (
            '[\n'
            '  {"index": 0, "verdict": "LIKELY", "explanation": "No evidence found."},\n'
            '  {"index": 1, "verdict": "UNLIKELY", "explanation": "Paper exists."}\n'
            ']',
            [],
        )


def test_bulk_llm_extraction_batcher_processes_multiple_items():
    batcher = BulkLLMExtractionBatcher(enabled=False)
    checker = _FakeExtractionChecker()

    results = batcher._process_batch([
        SimpleNamespace(checker=checker, bibliography_text='refs one'),
        SimpleNamespace(checker=checker, bibliography_text='refs two'),
    ])

    assert results == [
        [{'raw': 'A One#Paper One#Venue One#2024#https://one'}],
        [{'raw': 'B Two#Paper Two#Venue Two#2025#https://two'}],
    ]


def test_bulk_hallucination_batcher_processes_multiple_items():
    """_process_batch delegates to _process_single per item for mode consistency.

    Each item goes through run_hallucination_check → pre_screen_hallucination.
    With minimal error entries (no real errors), pre_screen returns 'skip'
    and run_hallucination_check returns None for each item.
    """
    batcher = BulkHallucinationBatcher(enabled=False)

    results = batcher._process_batch([
        SimpleNamespace(
            error_entry={'ref_title': 'Paper One', 'ref_authors_cited': 'A One', 'error_type': 'unverified', 'error_details': 'could not verify'},
            llm_verifier=_FakeHallucinationVerifier(),
            web_searcher=None,
        ),
        SimpleNamespace(
            error_entry={'ref_title': 'Paper Two', 'ref_authors_cited': 'B Two', 'error_type': 'unverified', 'error_details': 'could not verify'},
            llm_verifier=_FakeHallucinationVerifier(),
            web_searcher=None,
        ),
    ])

    # Individual processing: pre_screen returns 'skip' (no real errors beyond
    # 'unverified'), so run_hallucination_check returns None for each item.
    assert results == [None, None]


def test_bulk_progress_reporter_prints_timestamped_completion(capsys):
    reporter = BulkProgressReporter(total_papers=3)

    reporter.report(
        SimpleNamespace(
            index=0,
            title='Example Paper',
            paper_id='paper-1',
            input_spec='paper-1',
            source_url='https://example.com/paper-1',
            elapsed_seconds=42.5,
            references_processed=10,
            total_errors_found=2,
            total_warnings_found=1,
            total_info_found=0,
            total_unverified_refs=3,
            errors=[],
        )
    )

    output = capsys.readouterr().out.strip()
    assert '1/3' in output
    assert 'paper-1' in output
    assert 'refs=10' in output
    assert 'errors=2' in output
    assert 'Totals: refs=10' in output


def test_verification_cache_hit_and_miss():
    cache = BulkVerificationCache()

    ref_a = {'title': 'Attention Is All You Need', 'authors': ['Ashish Vaswani'], 'year': '2017'}
    ref_b = {'title': 'Deep Residual Learning for Image Recognition', 'authors': ['Kaiming He'], 'year': '2016'}

    # First lookup is a miss
    assert cache.get(ref_a) is None
    assert cache.misses == 1
    assert cache.hits == 0

    # Store result
    result_a = ([{'error_type': 'year', 'error_details': 'off by one'}], 'https://arxiv.org/abs/1706.03762', {'title': 'Attention Is All You Need'})
    cache.put(ref_a, result_a)
    assert cache.size == 1

    # Second lookup is a hit
    cached = cache.get(ref_a)
    assert cached is result_a
    assert cache.hits == 1
    assert cache.misses == 1

    # Different reference is a miss
    assert cache.get(ref_b) is None


def test_bulk_hallucination_batcher_process_single_uses_run_hallucination_check():
    """Regression: bulk_pipeline must import run_hallucination_check so _process_single works."""
    from unittest.mock import patch, MagicMock

    batcher = BulkHallucinationBatcher(enabled=False)

    payload = SimpleNamespace(
        error_entry={'ref_title': 'Test', 'ref_authors_cited': 'A', 'error_type': 'unverified', 'error_details': 'n/a'},
        llm_verifier=MagicMock(),
        web_searcher=None,
    )

    with patch('refchecker.core.bulk_pipeline.run_hallucination_check', return_value={'verdict': 'LIKELY', 'explanation': 'fake'}) as mock_fn:
        result = batcher._process_single(payload)
        mock_fn.assert_called_once_with(
            payload.error_entry,
            llm_client=payload.llm_verifier,
            web_searcher=payload.web_searcher,
        )
        assert result == {'verdict': 'LIKELY', 'explanation': 'fake'}


def test_verification_cache_variant_lookups():
    cache = BulkVerificationCache()

    ref_a = {'title': 'Attention Is All You Need', 'authors': ['Ashish Vaswani'], 'year': '2017'}
    result_a = ([{'error_type': 'year', 'error_details': 'off by one'}], 'https://arxiv.org/abs/1706.03762', {'title': 'Attention Is All You Need'})
    cache.put(ref_a, result_a)

    # Same title from different paper (slightly different author format) still hits
    # because last name 'Vaswani' normalizes the same way
    ref_a_variant = {'title': 'Attention Is All You Need', 'authors': ['A. Vaswani'], 'year': '2017'}
    assert cache.get(ref_a_variant) is result_a

    # Truly different first author last name is a miss
    ref_a_diff_author = {'title': 'Attention Is All You Need', 'authors': ['Noam Shazeer'], 'year': '2017'}
    assert cache.get(ref_a_diff_author) is None

    # But exact same normalized key hits
    ref_a_exact = {'title': '  attention is all you need  ', 'authors': ['Ashish Vaswani'], 'year': '2017'}
    assert cache.get(ref_a_exact) is result_a


def test_verification_cache_skips_short_titles():
    cache = BulkVerificationCache()
    ref = {'title': 'Short', 'authors': ['A'], 'year': '2020'}
    cache.put(ref, 'should_not_store')
    assert cache.size == 0
    assert cache.get(ref) is None