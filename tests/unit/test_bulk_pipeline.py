from types import SimpleNamespace

from refchecker.core.bulk_pipeline import BulkHallucinationBatcher, BulkLLMExtractionBatcher, BulkProgressReporter


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

    assert results == [
        {'verdict': 'LIKELY', 'explanation': 'No evidence found.', 'web_search': None},
        {'verdict': 'UNLIKELY', 'explanation': 'Paper exists.', 'web_search': None},
    ]


def test_bulk_progress_reporter_prints_timestamped_completion(capsys):
    reporter = BulkProgressReporter(total_papers=3)

    reporter.report(
        SimpleNamespace(
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
    assert 'Example Paper' in output
    assert 'refs=10' in output
    assert 'errors=2' in output
    assert 'Totals: refs=10' in output
    assert 'https://example.com/paper-1' in output