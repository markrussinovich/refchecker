from types import MethodType

from refchecker.core.refchecker import ArxivReferenceChecker


def test_openreview_source_download_failure_sets_fatal_error():
    checker = ArxivReferenceChecker(llm_config={'disabled': True})

    def fake_resolve(self, url):
        return {
            'id': 'TNqbfqSPoD',
            'source_url': 'https://openreview.net/forum?id=TNqbfqSPoD',
        }

    def fake_download(self, paper):
        self.last_download_error = '403 Client Error: Forbidden'
        return None

    checker._resolve_url_paper_metadata = MethodType(fake_resolve, checker)
    checker.download_pdf = MethodType(fake_download, checker)

    paper = checker._create_local_file_paper('https://openreview.net/pdf?id=TNqbfqSPoD')
    references = checker.extract_bibliography(paper, debug_mode=True)

    assert references == []
    assert checker.fatal_error is True
    assert 'OpenReview blocked automated access' in checker.fatal_error_message
    assert 'TNqbfqSPoD' in checker.fatal_error_message
    assert '403 Client Error: Forbidden' in checker.fatal_error_message


def test_write_structured_report_skips_after_fatal_error(tmp_path):
    checker = ArxivReferenceChecker(
        llm_config={'disabled': True},
        report_file=str(tmp_path / 'fatal-report.json'),
        report_format='json',
    )
    checker.fatal_error = True

    checker.write_structured_report(
        payload={
            'summary': {'records_written': 0},
            'papers': [],
            'records': [],
        }
    )

    assert not (tmp_path / 'fatal-report.json').exists()