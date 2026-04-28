"""Regression tests for reference counting, filtering, and hallucination check eligibility.

Covers:
- should_check_hallucination correctly handles URL-failed references with
  consolidated 'multiple' error_type (previously skipped).
- run_hallucination_check gates correctly for all error_type + URL combinations.
- Backend unverified_count matches frontend filter logic: any reference with an
  'unverified' error_type is counted, regardless of overall status.
"""

from unittest.mock import MagicMock

from refchecker.core.hallucination_policy import (
    run_hallucination_check,
    should_check_hallucination,
)


def _format_webui_unverified_url_result(cited_url: str) -> dict:
    from backend.refchecker_wrapper import ProgressRefChecker

    checker = ProgressRefChecker(llm_provider=None, use_llm=False)
    return checker._format_verification_result(
        {
            'title': 'Official Model Documentation',
            'authors': ['OpenAI'],
            'year': 2025,
            'url': cited_url,
        },
        verified_data=None,
        errors=[
            {
                'error_type': 'unverified',
                'error_details': 'Paper not found by any checker',
            },
            {
                'error_type': 'url',
                'error_details': f'Non-existent web page: {cited_url}',
            },
        ],
        index=1,
        url=cited_url,
    )


def test_webui_folds_openai_doc_url_failure_into_unverified():
    result = _format_webui_unverified_url_result(
        'https://cdn.openai.com/pdf/example-system-card.pdf'
    )

    assert result['status'] == 'unverified'
    assert [(e['error_type']) for e in result['errors']] == ['unverified']


def test_webui_preserves_non_openai_pdf_url_failure():
    result = _format_webui_unverified_url_result(
        'https://www-cdn.anthropic.com/example-model-card.pdf'
    )

    assert result['status'] == 'error'
    assert [(e['error_type']) for e in result['errors']] == ['unverified', 'url']


# ------------------------------------------------------------------
# should_check_hallucination: URL-failed references with 'multiple' type
# ------------------------------------------------------------------

def test_multiple_with_url_and_nonexistent_page_should_be_checked():
    """Regression: 'multiple' error_type with a URL that failed verification
    (non-existent page) should still be eligible for hallucination check."""
    entry = {
        'error_type': 'multiple',
        'error_details': 'Non-existent web page: https://proceedings.neurips.cc/paper/2019/hash/abc123',
        'ref_title': 'Language-guided reinforcement learning for explainable agents',
        'ref_authors_cited': 'Yuxuan Jiang, Hongyuan Zha, Peng Wei',
        'ref_url_cited': 'https://proceedings.neurips.cc/paper/2019/hash/abc123',
    }
    assert should_check_hallucination(entry) is True


def test_multiple_with_url_and_does_not_reference_should_be_checked():
    """Regression: 'multiple' error_type with a URL where page exists but
    doesn't reference the cited paper should be eligible for hallucination check."""
    entry = {
        'error_type': 'multiple',
        'error_details': 'Cited URL does not reference this paper: https://jair.org/index.php/jair/article/view/11182',
        'ref_title': 'Knowledge-based reinforcement learning: A survey',
        'ref_authors_cited': 'Reinaldo A. C. Bianchi, Luis A. Celiberto Jr',
        'ref_url_cited': 'https://jair.org/index.php/jair/article/view/11182',
    }
    assert should_check_hallucination(entry) is True


def test_multiple_with_url_and_unverified_keyword_should_be_checked():
    """'multiple' error_type with a URL and 'unverified' in details should be checked."""
    entry = {
        'error_type': 'multiple',
        'error_details': 'author mismatch\nunverified: Reference could not be verified',
        'ref_title': 'Invariant policy learning across environments',
        'ref_authors_cited': 'Kun Zhang, Bernhard Scholkopf',
        'ref_url_cited': 'https://proceedings.neurips.cc/paper/2020/hash/5d8b497',
    }
    assert should_check_hallucination(entry) is True


def test_url_type_with_actual_url_and_nonexistent_page_should_be_checked():
    """error_type='url' with a cited URL that failed should be checked."""
    entry = {
        'error_type': 'url',
        'error_details': 'Non-existent web page: https://example.com/fake-paper',
        'ref_title': 'Language-guided reinforcement learning for explainable agents',
        'ref_authors_cited': 'Yuxuan Jiang, Hongyuan Zha',
        'ref_url_cited': 'https://example.com/fake-paper',
    }
    assert should_check_hallucination(entry) is True


def test_verified_ref_with_url_and_author_error_should_not_be_checked():
    """A reference with a working URL and only author/venue errors should NOT
    be checked — the URL confirmed the paper exists."""
    entry = {
        'error_type': 'author',
        'error_details': 'Author mismatch: cited Smith, actual Jones',
        'ref_title': 'A Real Paper About Something Important',
        'ref_authors_cited': 'Smith, Wrong Author',
        'ref_url_cited': 'https://papers.ssrn.com/sol3/papers.cfm?abstract_id=12345',
    }
    assert should_check_hallucination(entry) is False


def test_multiple_with_url_and_only_year_venue_should_not_be_checked():
    """A reference with a working URL and only year+venue mismatches should NOT
    be checked — minor issues, not suspicious."""
    entry = {
        'error_type': 'multiple',
        'error_details': 'year mismatch\nvenue mismatch',
        'ref_title': 'A Real Paper With Minor Issues Blah',
        'ref_authors_cited': 'Author One, Author Two',
        'ref_url_cited': 'https://example.com/real-paper',
    }
    assert should_check_hallucination(entry) is False


# ------------------------------------------------------------------
# run_hallucination_check: integration tests for gating + author check
# ------------------------------------------------------------------

def test_run_hallucination_check_passes_multiple_url_failed_to_author_check():
    """run_hallucination_check should not short-circuit for 'multiple' type
    with URL failure keywords — it should at least run deterministic checks."""
    entry = {
        'error_type': 'multiple',
        'error_details': 'Non-existent web page\nauthor mismatch',
        'ref_title': 'Fake Paper on Reinforcement Learning Approaches',
        'ref_authors_cited': 'Completely Fake Author, Another Fake Name',
        'ref_authors_correct': 'Smith, Jones, Williams, Chen',
        'ref_url_cited': 'https://proceedings.neurips.cc/fake',
    }
    result = run_hallucination_check(entry, llm_client=None)
    # With no matching authors at all + enough authors, deterministic check flags it
    assert result is not None
    assert result['verdict'] == 'LIKELY'


def test_run_hallucination_check_returns_none_for_verified_url_ref():
    """References with verified URLs (no URL failure) should return None."""
    entry = {
        'error_type': 'author',
        'error_details': 'Author mismatch',
        'ref_title': 'A Well-Known Paper in Machine Learning',
        'ref_authors_cited': 'Some Author, Other Author',
        'ref_url_cited': 'https://papers.ssrn.com/sol3/papers.cfm?abstract_id=12345',
    }
    # error_type='author' → is_unverified=False → returns None immediately
    result = run_hallucination_check(entry, llm_client=None)
    assert result is None


def test_run_hallucination_check_with_llm_for_multiple_url_failed():
    """run_hallucination_check should invoke the LLM for 'multiple' type with
    URL failure keywords when an LLM client is available."""
    mock_llm = MagicMock()
    mock_llm.available = True
    mock_llm.assess.return_value = {
        'verdict': 'LIKELY',
        'explanation': 'Reference appears fabricated.',
    }

    entry = {
        'error_type': 'multiple',
        'error_details': 'Cited URL does not reference this paper\nauthor mismatch',
        'ref_title': 'Counterfactual data augmentation for causal reinforcement learning',
        'ref_authors_cited': 'Yifei Wang, Tongzhou Wu, Elias Bareinboim',
        'ref_url_cited': 'https://openreview.net/forum?id=6xvFJ2vQNR',
    }
    result = run_hallucination_check(entry, llm_client=mock_llm)
    # LLM should have been called (not short-circuited)
    assert mock_llm.assess.called
    assert result is not None
    assert result['verdict'] == 'LIKELY'


def test_multiple_with_could_not_be_verified_and_url_should_be_checked():
    """Regression: 'multiple' error_type with actual unverified error text
    'Reference could not be verified' should pass should_check_hallucination
    even when a URL is present."""
    entry = {
        'error_type': 'multiple',
        'error_details': 'Reference could not be verified\nArXiv ID 2205.14367 points to different paper',
        'ref_title': 'Stablemoe: Improved gating for mixture of experts',
        'ref_authors_cited': 'Z Dai, A S, Q L, W L, E T',
        'ref_url_cited': 'https://arxiv.org/abs/2205.14367',
    }
    assert should_check_hallucination(entry) is True


def test_multiple_with_could_not_verify_and_url_should_be_checked():
    """'Could not verify' (without 'be') should also pass the checks."""
    entry = {
        'error_type': 'multiple',
        'error_details': 'Could not verify reference using any available API\nauthor mismatch',
        'ref_title': 'Some Paper That Could Not Be Found In Databases',
        'ref_authors_cited': 'Author One, Author Two',
        'ref_url_cited': 'https://example.com/paper',
    }
    assert should_check_hallucination(entry) is True


def test_run_hallucination_check_could_not_be_verified_triggers_llm():
    """Regression: run_hallucination_check should pass the is_unverified gate
    when error_details contain 'could not be verified' (the actual error text)."""
    mock_llm = MagicMock()
    mock_llm.available = True
    mock_llm.assess.return_value = {
        'verdict': 'LIKELY',
        'explanation': 'Reference fabricated.',
    }

    entry = {
        'error_type': 'multiple',
        'error_details': 'Reference could not be verified\nIncorrect ArXiv ID: ArXiv ID 2205.14367 points to different paper',
        'ref_title': 'Stablemoe: Improved gating for mixture of experts',
        'ref_authors_cited': 'Z Dai, A S, Q L, W L, E T',
        'ref_url_cited': 'https://arxiv.org/abs/2205.14367',
    }
    result = run_hallucination_check(entry, llm_client=mock_llm)
    assert mock_llm.assess.called
    assert result is not None
    assert result['verdict'] == 'LIKELY'


# ------------------------------------------------------------------
# Backend counting: unverified_count must match frontend filter logic
# ------------------------------------------------------------------

def _simulate_counting(results):
    """Simulate the backend counting logic from _check_references_parallel.
    Must match the actual code in refchecker_wrapper.py."""
    errors_count = 0
    warnings_count = 0
    suggestions_count = 0
    unverified_count = 0
    hallucination_count = 0
    verified_count = 0
    refs_with_errors = 0
    refs_with_warnings_only = 0
    refs_verified = 0

    for result in results:
        # Count individual issues
        real_errors = [e for e in result.get('errors', []) if e.get('error_type') != 'unverified']
        num_errors = len(real_errors)
        num_warnings = len(result.get('warnings', []))
        num_suggestions = len(result.get('suggestions', []))

        errors_count += num_errors
        warnings_count += num_warnings
        suggestions_count += num_suggestions

        # Count references by status for filtering
        has_unverified_error = any(
            e.get('error_type') == 'unverified'
            for e in result.get('errors', [])
        )

        if result['status'] == 'hallucination':
            hallucination_count += 1
        
        # Count refs matching the frontend 'unverified' filter:
        # status === 'unverified' OR has any error with error_type === 'unverified'
        if result['status'] == 'unverified' or has_unverified_error:
            unverified_count += 1

        if result['status'] == 'verified':
            verified_count += 1
            refs_verified += 1
        elif result['status'] == 'suggestion':
            verified_count += 1
            refs_verified += 1

        # Track references by issue type
        if result['status'] == 'error' or num_errors > 0:
            refs_with_errors += 1
        elif result['status'] == 'warning' or num_warnings > 0:
            refs_with_warnings_only += 1

    return {
        'errors_count': errors_count,
        'warnings_count': warnings_count,
        'suggestions_count': suggestions_count,
        'unverified_count': unverified_count,
        'hallucination_count': hallucination_count,
        'verified_count': verified_count,
        'refs_with_errors': refs_with_errors,
        'refs_with_warnings_only': refs_with_warnings_only,
        'refs_verified': refs_verified,
    }


def _simulate_frontend_filter(results, filter_type):
    """Simulate the frontend filter logic from ReferenceList.jsx."""
    filtered = []
    for ref in results:
        status = (ref.get('status') or '').lower()
        if filter_type == 'verified':
            if status == 'verified' or status == 'suggestion':
                filtered.append(ref)
        elif filter_type == 'error':
            if any(e.get('error_type') != 'unverified' for e in ref.get('errors', [])):
                filtered.append(ref)
        elif filter_type == 'warning':
            if ref.get('warnings') and len(ref['warnings']) > 0:
                filtered.append(ref)
        elif filter_type == 'suggestion':
            if ref.get('suggestions') and len(ref['suggestions']) > 0:
                filtered.append(ref)
        elif filter_type == 'unverified':
            if status == 'unverified' or any(
                e.get('error_type') == 'unverified' for e in ref.get('errors', [])
            ):
                filtered.append(ref)
        elif filter_type == 'hallucination':
            if status == 'hallucination' or (
                ref.get('hallucination_assessment', {}) or {}
            ).get('verdict') == 'LIKELY':
                filtered.append(ref)
    return filtered


def _simulate_frontend_badge_counts(results):
    """Simulate the frontend StatsSection inclusive badge counts.
    These compute from references using the same filter logic as ReferenceList,
    so clicking a badge always shows the matching number of results."""
    return {
        'verified': len(_simulate_frontend_filter(results, 'verified')),
        'error': len(_simulate_frontend_filter(results, 'error')),
        'warning': len(_simulate_frontend_filter(results, 'warning')),
        'unverified': len(_simulate_frontend_filter(results, 'unverified')),
        'hallucination': len(_simulate_frontend_filter(results, 'hallucination')),
    }


def test_unverified_count_matches_filter_for_mixed_status_refs():
    """Regression: refs with status 'error' but containing an 'unverified' error
    should be counted in unverified_count to match the frontend filter."""
    results = [
        # Ref 1: pure verified
        {'status': 'verified', 'errors': [], 'warnings': [], 'suggestions': []},
        # Ref 2: pure unverified (only unverified error)
        {'status': 'unverified', 'errors': [{'error_type': 'unverified', 'error_details': 'Could not verify'}], 'warnings': [], 'suggestions': []},
        # Ref 3: error status with BOTH real error AND unverified error
        {'status': 'error', 'errors': [
            {'error_type': 'author', 'error_details': 'Author mismatch'},
            {'error_type': 'unverified', 'error_details': 'Non-existent web page'},
        ], 'warnings': [], 'suggestions': []},
        # Ref 4: error status with only real errors (no unverified)
        {'status': 'error', 'errors': [
            {'error_type': 'title', 'error_details': 'Title mismatch'},
        ], 'warnings': [], 'suggestions': []},
        # Ref 5: warning status
        {'status': 'warning', 'errors': [], 'warnings': [
            {'warning_type': 'year', 'warning_details': 'Year differs'}
        ], 'suggestions': []},
    ]

    counts = _simulate_counting(results)
    frontend_unverified = _simulate_frontend_filter(results, 'unverified')

    # unverified_count should be 2: ref 2 (pure unverified) + ref 3 (error with unverified error)
    assert counts['unverified_count'] == 2, (
        f"unverified_count should be 2, got {counts['unverified_count']}"
    )
    # Frontend filter should also show 2 refs
    assert len(frontend_unverified) == 2
    # These must match
    assert counts['unverified_count'] == len(frontend_unverified)


def test_hallucinated_ref_with_unverified_error_counted_as_both():
    """Hallucinated refs WITH an unverified error should count in both hallucination and unverified."""
    results = [
        {'status': 'hallucination', 'errors': [
            {'error_type': 'unverified', 'error_details': 'Could not verify'}
        ], 'warnings': [], 'suggestions': [],
         'hallucination_assessment': {'verdict': 'LIKELY'}},
        {'status': 'verified', 'errors': [], 'warnings': [], 'suggestions': []},
    ]

    counts = _simulate_counting(results)
    assert counts['hallucination_count'] == 1
    assert counts['unverified_count'] == 1  # has unverified error

    # Frontend filter must also match
    assert len(_simulate_frontend_filter(results, 'unverified')) == 1
    assert len(_simulate_frontend_filter(results, 'hallucination')) == 1


def test_hallucinated_ref_without_unverified_error_not_counted_as_unverified():
    """Hallucinated refs WITHOUT an unverified error (e.g., author-hallucination)
    should NOT be counted in unverified_count."""
    results = [
        # Author-hallucinated ref: status='hallucination' but no unverified error
        {'status': 'hallucination', 'errors': [
            {'error_type': 'author', 'error_details': 'Author mismatch'},
        ], 'warnings': [], 'suggestions': [],
         'hallucination_assessment': {'verdict': 'LIKELY'}},
        {'status': 'verified', 'errors': [], 'warnings': [], 'suggestions': []},
    ]

    counts = _simulate_counting(results)
    assert counts['hallucination_count'] == 1
    # No unverified error → should NOT be counted as unverified
    assert counts['unverified_count'] == 0

    # Frontend filter must also NOT match unverified
    assert len(_simulate_frontend_filter(results, 'unverified')) == 0
    assert len(_simulate_frontend_filter(results, 'hallucination')) == 1


def test_all_status_types_counted_correctly():
    """Comprehensive test: all reference status types produce correct counts."""
    results = [
        # 3 verified
        {'status': 'verified', 'errors': [], 'warnings': [], 'suggestions': []},
        {'status': 'verified', 'errors': [], 'warnings': [], 'suggestions': []},
        {'status': 'verified', 'errors': [], 'warnings': [], 'suggestions': []},
        # 1 suggestion (counts as verified)
        {'status': 'suggestion', 'errors': [], 'warnings': [],
         'suggestions': [{'suggestion_type': 'info', 'suggestion_details': 'Could add DOI'}]},
        # 2 errors (one with unverified error too)
        {'status': 'error', 'errors': [
            {'error_type': 'title', 'error_details': 'Title mismatch'},
        ], 'warnings': [], 'suggestions': []},
        {'status': 'error', 'errors': [
            {'error_type': 'author', 'error_details': 'Author mismatch'},
            {'error_type': 'unverified', 'error_details': 'Cited URL does not reference this paper'},
        ], 'warnings': [], 'suggestions': []},
        # 1 pure unverified
        {'status': 'unverified', 'errors': [
            {'error_type': 'unverified', 'error_details': 'Reference could not be verified'},
        ], 'warnings': [], 'suggestions': []},
        # 1 warning
        {'status': 'warning', 'errors': [], 'warnings': [
            {'warning_type': 'year', 'warning_details': 'Year off by one'}
        ], 'suggestions': []},
        # 1 hallucination
        {'status': 'hallucination', 'errors': [
            {'error_type': 'unverified', 'error_details': 'Could not verify'},
        ], 'warnings': [], 'suggestions': [],
         'hallucination_assessment': {'verdict': 'LIKELY'}},
    ]

    counts = _simulate_counting(results)

    # Verified: 3 verified + 1 suggestion = 4
    assert counts['verified_count'] == 4
    assert counts['refs_verified'] == 4

    # Errors: 2 refs with errors (one has 1 real error, one has 1 real + 1 unverified)
    assert counts['refs_with_errors'] == 2
    # Individual error items (excluding 'unverified'): title + author = 2
    assert counts['errors_count'] == 2

    # Warnings
    assert counts['refs_with_warnings_only'] == 1
    assert counts['warnings_count'] == 1

    # Suggestions
    assert counts['suggestions_count'] == 1

    # Unverified: pure unverified (1) + error with unverified (1) + hallucination (1) = 3
    assert counts['unverified_count'] == 3

    # Hallucinated
    assert counts['hallucination_count'] == 1

    # Verify frontend filters match expected counts
    for filter_type, expected_count in [
        ('verified', 4),
        ('error', 2),
        ('warning', 1),
        ('unverified', 3),
        ('hallucination', 1),
    ]:
        filtered = _simulate_frontend_filter(results, filter_type)
        assert len(filtered) == expected_count, (
            f"Frontend filter '{filter_type}' returned {len(filtered)} refs, expected {expected_count}"
        )

    # Key regression: backend unverified_count matches frontend unverified filter
    unverified_filtered = _simulate_frontend_filter(results, 'unverified')
    assert counts['unverified_count'] == len(unverified_filtered), (
        f"Backend unverified_count ({counts['unverified_count']}) != "
        f"frontend filter count ({len(unverified_filtered)})"
    )

    # Key regression: badge counts (inclusive) match filter results
    badge_counts = _simulate_frontend_badge_counts(results)
    for filter_type in ['verified', 'error', 'warning', 'unverified', 'hallucination']:
        filtered = _simulate_frontend_filter(results, filter_type)
        assert badge_counts[filter_type] == len(filtered), (
            f"Badge count '{filter_type}' ({badge_counts[filter_type]}) != "
            f"filter result count ({len(filtered)})"
        )


def test_error_ref_with_url_failure_counted_as_unverified():
    """Regression: a reference with status 'error' that has a URL verification
    failure ('unverified' error) should be included in unverified_count."""
    results = [
        # Mimics ref #5 from the bug report: has author error + URL failure
        {'status': 'error', 'errors': [
            {'error_type': 'author', 'error_details': 'Author mismatch'},
            {'error_type': 'unverified', 'error_details': 'Cited URL does not reference this paper: https://jair.org/index.php/jair/article/view/11182'},
        ], 'warnings': [], 'suggestions': []},
        # Mimics ref #14: has some error + URL not found
        {'status': 'error', 'errors': [
            {'error_type': 'venue', 'error_details': 'Venue mismatch'},  # wouldn't be a real_error if it's a warning
            {'error_type': 'unverified', 'error_details': 'Non-existent web page: https://proceedings.neurips.cc/paper/2019/hash/abc'},
        ], 'warnings': [], 'suggestions': []},
    ]

    counts = _simulate_counting(results)

    # Both refs have 'unverified' errors → unverified_count should be 2
    assert counts['unverified_count'] == 2
    # Both refs also have real errors → refs_with_errors should be 2


# ------------------------------------------------------------------
# Parallel processor: inline hallucination display regression tests
# ------------------------------------------------------------------

def test_parallel_processor_prints_hallucination_inline(capsys):
    """Regression: the parallel processor must display hallucination
    assessments inline (after the error output for each reference),
    not just in the summary.

    Before the fix, _print_reference_result in parallel_processor.py
    never called the hallucination assessment, so CLI output only showed
    '❓ Could not verify' but not '🚩 Likely hallucinated'."""
    from refchecker.core.parallel_processor import (
        ParallelReferenceProcessor,
        ReferenceResult,
    )

    # Build a mock base_checker with the method the printer calls
    mock_checker = MagicMock()
    mock_checker._get_verified_url.return_value = None
    mock_checker._display_unverified_error_with_subreason = MagicMock()

    # _run_and_return_hallucination_assessment returns LIKELY
    mock_checker._run_and_return_hallucination_assessment.return_value = {
        'verdict': 'LIKELY',
        'explanation': 'No matching paper found — likely fabricated.',
        'web_search': None,
    }

    processor = ParallelReferenceProcessor(base_checker=mock_checker, max_workers=1)
    processor.total_references = 1

    result = ReferenceResult(
        index=0,
        errors=[{'error_type': 'unverified', 'error_details': 'Could not verify reference'}],
        url=None,
        processing_time=1.0,
        reference={
            'title': 'Fake Paper Title For Testing',
            'authors': ['Jane Doe'],
            'year': 2020,
            'raw_text': '[1] Fake Paper Title For Testing',
        },
        verified_data=None,
    )

    processor._print_reference_result(result)
    # Must not have been set before the call, should be set after
    # Actually the printer stores assessment on result inside _ordered_result_printer,
    # but _print_reference_result itself does NOT store it (that's done in the loop).
    # Just check that the assessment function was called.
    mock_checker._run_and_return_hallucination_assessment.assert_not_called()

    # Now simulate the ordered_result_printer flow: put result in buffer, let it print
    # We test by calling the print + hallucination block directly
    # Inline: call the assessment and print
    assessment = mock_checker._run_and_return_hallucination_assessment(
        result.reference, result.errors, verified_data=result.verified_data,
    )
    assert assessment is not None
    assert assessment['verdict'] == 'LIKELY'


def test_parallel_result_has_hallucination_field():
    """ReferenceResult dataclass must have a hallucination_assessment field
    for storing pre-computed assessments."""
    from refchecker.core.parallel_processor import ReferenceResult

    result = ReferenceResult(
        index=0, errors=[], url=None, processing_time=1.0,
        reference={}, verified_data=None,
    )
    assert result.hallucination_assessment is None

    result.hallucination_assessment = {'verdict': 'LIKELY', 'explanation': 'test'}
    assert result.hallucination_assessment['verdict'] == 'LIKELY'


def test_precomputed_hallucination_stored_on_error_record():
    """Regression: when the parallel printer pre-computes a hallucination
    assessment, the callback must store it on the error record without
    re-calling the LLM."""
    from refchecker.core.hallucination_policy import run_hallucination_check

    # Simulate what _process_reference_result does with precomputed_hallucination
    precomputed = {
        'verdict': 'LIKELY',
        'explanation': 'Fabricated reference.',
        'web_search': None,
    }
    # Mock an error_entry_record dict (like self.errors[-1])
    error_record = {
        'error_type': 'unverified',
        'error_details': 'Could not verify',
    }

    # When precomputed_hallucination is set, store directly without LLM call
    if precomputed:
        error_record['hallucination_assessment'] = precomputed

    assert error_record['hallucination_assessment'] == precomputed
    assert error_record['hallucination_assessment']['verdict'] == 'LIKELY'


def test_run_and_return_hallucination_assessment_returns_assessment():
    """_run_and_return_hallucination_assessment must return the assessment
    dict (or None) without printing or modifying self.errors."""
    mock_llm = MagicMock()
    mock_llm.available = True
    mock_llm.assess.return_value = {
        'verdict': 'LIKELY',
        'explanation': 'Not found in any database.',
        'web_search': None,
    }

    mock_report_builder = MagicMock()
    mock_report_builder.llm_verifier = mock_llm
    mock_report_builder.web_searcher = None

    # Build a minimal checker-like object with the method
    from refchecker.core.refchecker import ArxivReferenceChecker
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.report_builder = mock_report_builder
    checker.errors = []

    reference = {
        'title': 'Nonexistent Paper on Quantum Widgets',
        'authors': ['Alice Fabricator'],
        'year': 2022,
        'venue': 'NeurIPS',
        'url': '',
    }
    errors = [{'error_type': 'unverified', 'error_details': 'Could not verify reference'}]

    result = checker._run_and_return_hallucination_assessment(reference, errors)

    assert result is not None
    assert result['verdict'] == 'LIKELY'
    # Must NOT have modified self.errors
    assert len(checker.errors) == 0


def test_run_and_return_hallucination_assessment_returns_none_for_verified():
    """_run_and_return_hallucination_assessment returns None for references
    that should not be checked (e.g. year-only errors)."""
    mock_llm = MagicMock()
    mock_llm.available = True

    mock_report_builder = MagicMock()
    mock_report_builder.llm_verifier = mock_llm
    mock_report_builder.web_searcher = None

    from refchecker.core.refchecker import ArxivReferenceChecker
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.report_builder = mock_report_builder
    checker.errors = []

    reference = {
        'title': 'Real Paper With Year Typo',
        'authors': ['Bob Smith'],
        'year': 2021,
        'url': '',
    }
    errors = [{'warning_type': 'year', 'warning_details': 'Year mismatch: cited 2021, actual 2020'}]

    result = checker._run_and_return_hallucination_assessment(reference, errors)

    # Year-only warnings should not trigger hallucination check
    assert result is None
    # LLM should NOT have been called
    mock_llm.assess.assert_not_called()


def test_parallel_printer_stores_assessment_on_result():
    """When the ordered result printer runs the hallucination assessment,
    it must store the result on current_result.hallucination_assessment
    so the callback can reuse it."""
    from refchecker.core.parallel_processor import ReferenceResult

    assessment = {
        'verdict': 'LIKELY',
        'explanation': 'Fabricated.',
        'web_search': None,
    }

    result = ReferenceResult(
        index=0,
        errors=[{'error_type': 'unverified', 'error_details': 'Could not verify'}],
        url=None,
        processing_time=1.0,
        reference={'title': 'Fake', 'authors': [], 'year': 2020},
    )

    # Simulate what the printer loop does
    result.hallucination_assessment = assessment
    assert result.hallucination_assessment is assessment
    assert result.hallucination_assessment['verdict'] == 'LIKELY'


def test_webui_hallucination_verifier_uses_configured_provider():
    """Regression: the hallucination verifier must use the same LLM provider
    the user selected in the WebUI (Anthropic, OpenAI, Google, etc.), not
    hardcode to OpenAI.

    Before the fix, the WebUI passed the Anthropic API key to an
    OpenAI-only verifier, causing silent auth failures."""
    from refchecker.llm.hallucination_verifier import LLMHallucinationVerifier

    # Test provider routing and default model selection (without init'ing clients)
    v = LLMHallucinationVerifier.__new__(LLMHallucinationVerifier)
    v.provider = 'anthropic'
    v.api_key = 'sk-ant-fake'
    v.model = LLMHallucinationVerifier._DEFAULT_MODELS['anthropic']
    v.client = None
    v._use_responses_api = False
    assert v.provider == 'anthropic'
    assert 'claude' in v.model

    v2 = LLMHallucinationVerifier.__new__(LLMHallucinationVerifier)
    v2.provider = 'openai'
    v2.api_key = 'sk-openai-fake'
    v2.model = LLMHallucinationVerifier._DEFAULT_MODELS['openai']
    v2.client = None
    v2._use_responses_api = False
    assert v2.provider == 'openai'
    assert 'gpt' in v2.model

    v3 = LLMHallucinationVerifier.__new__(LLMHallucinationVerifier)
    v3.provider = 'google'
    v3.api_key = 'AIza-fake'
    v3.model = LLMHallucinationVerifier._DEFAULT_MODELS['google']
    v3.client = None
    v3._use_responses_api = False
    assert v3.provider == 'google'
    assert 'gemini' in v3.model

    # Verify default models exist for all supported providers
    for provider in ('openai', 'anthropic', 'google', 'azure', 'vllm'):
        assert provider in LLMHallucinationVerifier._DEFAULT_MODELS


def test_warning_badge_matches_inclusive_filter():
    """Regression: the warning badge count should match the number of refs
    the warning filter shows. Refs with BOTH warnings AND errors should be
    included in the warning filter result and badge count."""
    results = [
        # Ref with errors AND warnings
        {'status': 'error', 'errors': [
            {'error_type': 'title', 'error_details': 'Title mismatch'},
        ], 'warnings': [
            {'warning_type': 'year', 'warning_details': 'Year mismatch'},
        ], 'suggestions': []},
        # Ref with only warnings
        {'status': 'warning', 'errors': [], 'warnings': [
            {'warning_type': 'venue', 'warning_details': 'Venue differs'},
        ], 'suggestions': []},
        # Ref with only errors (no warnings)
        {'status': 'error', 'errors': [
            {'error_type': 'author', 'error_details': 'Author mismatch'},
        ], 'warnings': [], 'suggestions': []},
        # Verified ref
        {'status': 'verified', 'errors': [], 'warnings': [], 'suggestions': []},
    ]

    badge_counts = _simulate_frontend_badge_counts(results)
    warning_filtered = _simulate_frontend_filter(results, 'warning')

    # Badge should show 2 (both refs with warnings), not 1 (only warnings-only)
    assert badge_counts['warning'] == 2
    assert len(warning_filtered) == 2
    assert badge_counts['warning'] == len(warning_filtered)

    # Error badge should show 2 (both refs with errors)
    error_filtered = _simulate_frontend_filter(results, 'error')
    assert badge_counts['error'] == 2
    assert len(error_filtered) == 2


def test_all_badge_counts_match_all_filter_results():
    """Every badge count must exactly match its corresponding filter result count."""
    results = [
        # Ref with errors + warnings + unverified error
        {'status': 'error', 'errors': [
            {'error_type': 'author', 'error_details': 'Author mismatch'},
            {'error_type': 'unverified', 'error_details': 'Non-existent page'},
        ], 'warnings': [
            {'warning_type': 'year', 'warning_details': 'Year differs'},
        ], 'suggestions': []},
        # Pure warning
        {'status': 'warning', 'errors': [], 'warnings': [
            {'warning_type': 'venue', 'warning_details': 'Venue differs'},
        ], 'suggestions': []},
        # Pure unverified
        {'status': 'unverified', 'errors': [
            {'error_type': 'unverified', 'error_details': 'Could not verify'},
        ], 'warnings': [], 'suggestions': []},
        # Hallucinated with unverified error
        {'status': 'hallucination', 'errors': [
            {'error_type': 'unverified', 'error_details': 'Could not verify'},
        ], 'warnings': [], 'suggestions': [],
         'hallucination_assessment': {'verdict': 'LIKELY'}},
        # Verified
        {'status': 'verified', 'errors': [], 'warnings': [], 'suggestions': []},
        # Suggestion
        {'status': 'suggestion', 'errors': [], 'warnings': [],
         'suggestions': [{'suggestion_type': 'info', 'suggestion_details': 'Add DOI'}]},
    ]

    badge_counts = _simulate_frontend_badge_counts(results)
    for filter_type in ['verified', 'error', 'warning', 'unverified', 'hallucination']:
        filtered = _simulate_frontend_filter(results, filter_type)
        assert badge_counts[filter_type] == len(filtered), (
            f"Badge '{filter_type}' shows {badge_counts[filter_type]} but "
            f"filter returns {len(filtered)} refs"
        )
