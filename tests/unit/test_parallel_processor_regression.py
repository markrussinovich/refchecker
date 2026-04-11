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