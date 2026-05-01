from types import SimpleNamespace

from refchecker.core.parallel_processor import ParallelReferenceProcessor, ReferenceResult


def test_parallel_printer_does_not_rerun_hallucination_assessment(capsys):
    base_checker = SimpleNamespace(
        _get_verified_url=lambda verified_data, url, errors: url,
        _print_reference_header=lambda ref, index, total: print(f"[{index+1}/{total}] {ref.get('title', '')}"),
        _print_verified_urls=lambda ref, vd, url, errors: None,
        _display_non_unverified_errors=lambda errors, debug_mode, print_output: None,
        _display_unverified_error_with_subreason=lambda *args, **kwargs: None,
        _run_and_display_hallucination_assessment=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError('parallel printer should not rerun hallucination assessment')
        ),
    )

    processor = ParallelReferenceProcessor(base_checker=base_checker, max_workers=2)
    processor.total_references = 1

    result = ReferenceResult(
        index=0,
        errors=[{'error_type': 'unverified', 'error_details': 'Reference could not be verified'}],
        url='https://example.com/paper',
        processing_time=0.25,
        reference={
            'title': 'Synthetic Reference',
            'authors': ['Author One'],
            'year': 2025,
            'venue': 'TestConf',
            'url': 'https://example.com/paper',
            'raw_text': '[1] Synthetic Reference',
        },
        verified_data=None,
    )

    processor._print_reference_result(result)

    captured = capsys.readouterr()
    assert 'Synthetic Reference' in captured.out


def test_parallel_printer_labels_llm_verified_source(capsys):
    base_checker = SimpleNamespace(
        _print_reference_header=lambda ref, index, total: print(
            f"[{index+1}/{total}] {ref.get('title', '')}"
        ),
        _print_verified_urls=lambda ref, vd, url, errors: print(''),
        _display_non_unverified_errors=lambda errors, debug_mode, print_output: None,
        _display_unverified_error_with_subreason=lambda *args, **kwargs: None,
    )

    processor = ParallelReferenceProcessor(base_checker=base_checker, max_workers=2)
    processor.total_references = 1

    result = ReferenceResult(
        index=0,
        errors=[],
        url='https://doi.org/10.1007/978-3-030-10973-8',
        processing_time=0.25,
        reference={
            'title': 'Potential explanations for why people are missed in the us census',
            'authors': ["William P O'Hare", "William P O'Hare"],
            'year': 2019,
            'venue': 'Differential Undercounts in the US Census: Who is Missed?',
            'raw_text': (
                '[68] Potential explanations for why people are missed in the us census'
            ),
        },
        verified_data=None,
        hallucination_assessment={
            'verdict': 'UNLIKELY',
            'link': 'https://doi.org/10.1007/978-3-030-10973-8',
            'explanation': 'The cited work is a real book chapter.',
        },
    )

    processor._print_reference_result(result)

    output = capsys.readouterr().out
    assert '       Matched Database: LLM search' in output
    assert '       Verified URL: https://doi.org/10.1007/978-3-030-10973-8' in output
    assert output.index('       Matched Database: LLM search') < output.index('       Verified URL:')
    assert '\n\n       Matched Database: LLM search' in output
    assert '\n\n\n       Matched Database: LLM search' not in output


def test_parallel_printer_does_not_duplicate_llm_verified_url(capsys):
    def print_verified_urls(ref, verified_data, url_from_verifier, errors):
        print('')
        if url_from_verifier:
            print(f'       Verified URL: {url_from_verifier}')

    base_checker = SimpleNamespace(
        _print_reference_header=lambda ref, index, total: print(
            f"[{index+1}/{total}] {ref.get('title', '')}"
        ),
        _print_verified_urls=print_verified_urls,
        _display_non_unverified_errors=lambda errors, debug_mode, print_output: None,
        _display_unverified_error_with_subreason=lambda *args, **kwargs: None,
    )

    processor = ParallelReferenceProcessor(base_checker=base_checker, max_workers=2)
    processor.total_references = 1

    result = ReferenceResult(
        index=0,
        errors=[{'error_type': 'author', 'error_details': 'Author count mismatch'}],
        url='https://zenodo.org/doi/10.5281/zenodo.14751899',
        processing_time=0.25,
        reference={
            'title': 'Marlowe: Stanford’s gpu-based computational instrument',
            'authors': ['Craig Kapfer', 'Kurt Stine'],
            'year': 2025,
            'url': 'https://zenodo.org/doi/10.5281/zenodo.14751899',
            'raw_text': '[43] Marlowe',
        },
        verified_data=None,
        hallucination_assessment={
            'verdict': 'UNLIKELY',
            'link': 'https://zenodo.org/doi/10.5281/zenodo.14751899',
            'explanation': 'The cited work is real.',
        },
    )

    processor._print_reference_result(result)

    output = capsys.readouterr().out
    assert output.count('       Verified URL: https://zenodo.org/doi/10.5281/zenodo.14751899') == 1
    assert '       Matched Database: LLM search' in output
